-- 0004 — what the lane runtime keeps (company/HARNESS-V3.md sections 3.1 and 3.3,
-- SY-V3-LANE-RUNTIME): each item's spec, the stay it is in, lane slots, capability-gap items and
-- probe results.
--
-- Nothing in the kernel service's memory is the only copy of anything: a restart reads all of
-- this back. The tenant identifier is workspace_id, on every row, as since 0001.

-- What an item was admitted with. Written once, by admission, together with the item row and
-- its links; never changed afterwards (admitting the same id again with another spec is
-- refused).
CREATE TABLE sortyard.item_spec (
    workspace_id text NOT NULL,
    item_id text NOT NULL,
    -- The lane the item runs on: the name of a lane capability file.
    lane text NOT NULL,
    -- Where the change goes: owner/name and the base branch.
    repository text NOT NULL,
    base text NOT NULL,
    -- The needs the item lists against its lane's capability file: an array of references.
    needs jsonb NOT NULL CHECK (jsonb_typeof(needs) = 'array'),
    -- The spec as admitted: at least an outcome and one named acceptance test.
    spec jsonb NOT NULL CHECK (jsonb_typeof(spec) = 'object'),
    admitted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, item_id),
    FOREIGN KEY (workspace_id, item_id) REFERENCES sortyard.item (workspace_id, id)
);
CREATE INDEX ON sortyard.item_spec (lane);
CREATE TRIGGER immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON sortyard.item_spec
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are written once, at admission');

-- A lane slot granted to an item: the scheduler's answer "dispatched", made durable so that
-- two answers given at the same moment cannot both take the last slot. The slot is held while
-- the item is neither merged nor waiting on a need (read from the item row); the grant itself
-- is never taken back.
CREATE TABLE sortyard.item_slot (
    workspace_id text NOT NULL,
    item_id text NOT NULL,
    lane text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, item_id),
    FOREIGN KEY (workspace_id, item_id) REFERENCES sortyard.item (workspace_id, id)
);
CREATE INDEX ON sortyard.item_slot (lane);

-- The stay a run row describes, as the owner was called with it: the dispatch number (an
-- outcome reported for a stay carries it, so one for an earlier stay is ignored), the attempt,
-- the action handed to the owner, the detail the item entered with and the stay's deadline.
-- Whoever observes outside work reads the open stays from here, not from a process's memory.
ALTER TABLE sortyard.item_run
    ADD COLUMN dispatch integer,
    ADD COLUMN attempt integer,
    ADD COLUMN action text,
    ADD COLUMN detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN deadline timestamptz;

-- Capability-gap items (section 3.3): one failed need of one lane, for its resolver.
CREATE SEQUENCE sortyard.capability_gap_number;
CREATE TABLE sortyard.capability_gap (
    id text PRIMARY KEY DEFAULT 'gap-' || nextval('sortyard.capability_gap_number'),
    workspace_id text NOT NULL REFERENCES sortyard.workspace (id),
    lane text NOT NULL,
    need text NOT NULL,
    resolver text NOT NULL,
    -- The probe output that opened it.
    output text NOT NULL,
    open boolean NOT NULL DEFAULT true,
    opened_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz
);
-- A need of a lane has at most one open gap item, whoever asks and however many ask at once.
CREATE UNIQUE INDEX capability_gap_one_open
    ON sortyard.capability_gap (workspace_id, lane, need) WHERE open;

-- The work items linked to a gap item, in the order they were linked. `waiting` says the item
-- still waits on it; a closed gap item keeps its rows as the record of what it held up.
CREATE TABLE sortyard.capability_gap_item (
    gap_id text NOT NULL REFERENCES sortyard.capability_gap (id),
    workspace_id text NOT NULL,
    item_id text NOT NULL,
    position bigint GENERATED ALWAYS AS IDENTITY,
    waiting boolean NOT NULL DEFAULT true,
    PRIMARY KEY (gap_id, item_id)
);
CREATE INDEX ON sortyard.capability_gap_item (workspace_id, item_id);

-- Every probe result of every preflight dispatch. A result recorded again (the engine retries
-- a step whose worker died) replaces the one before it.
CREATE TABLE sortyard.probe_result (
    workspace_id text NOT NULL,
    item_id text NOT NULL,
    dispatch integer NOT NULL,
    need text NOT NULL,
    lane text NOT NULL,
    passed boolean NOT NULL,
    output text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, item_id, dispatch, need)
);

-- record_item_transition as in 0003, and it now also writes the stay's dispatch, attempt,
-- action, detail and deadline on the run row. Nothing else about it changed.
--
--   transition  {item, sequence, state, state_kind, owner, limit, reason, from_state, cause,
--                entered_at, dispatch, attempt, action, detail, deadline}
CREATE OR REPLACE FUNCTION sortyard.record_item_transition(transition jsonb, event jsonb) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    tenant text := event ->> 'workspace_id';
    the_item text := transition ->> 'item';
    next_sequence integer := (transition ->> 'sequence')::integer;
    entered timestamptz := (transition ->> 'entered_at')::timestamptz;
    existing sortyard.item%ROWTYPE;
    recorded_event text;
    ledger_seq bigint;
BEGIN
    IF tenant IS NULL OR the_item IS NULL OR next_sequence IS NULL OR entered IS NULL THEN
        RAISE EXCEPTION 'sortyard.item: a transition names its tenant, item, sequence and entered_at'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT * INTO existing FROM sortyard.item AS i
        WHERE i.workspace_id = tenant AND i.id = the_item FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'sortyard.item: no item % in workspace %', the_item, tenant
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF next_sequence < 1 THEN
        RAISE EXCEPTION 'sortyard.item: a transition''s sequence starts at 1, not %', next_sequence
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF event -> 'object' ->> 'kind' IS DISTINCT FROM 'item'
       OR event -> 'object' ->> 'id' IS DISTINCT FROM the_item THEN
        RAISE EXCEPTION 'sortyard.item: the event of a transition of % is about that item', the_item
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF next_sequence <= existing.sequence THEN
        -- Already recorded: it must be the same Event again. append_event then returns the
        -- original position, and refuses an Event whose content differs.
        SELECT r.event_id INTO recorded_event FROM sortyard.item_run AS r
            WHERE r.workspace_id = tenant AND r.item_id = the_item AND r.sequence = next_sequence;
        IF recorded_event IS DISTINCT FROM event ->> 'id' THEN
            RAISE EXCEPTION 'sortyard.item: transition % of % is already recorded as event %',
                next_sequence, the_item, recorded_event
                USING ERRCODE = 'unique_violation';
        END IF;
        RETURN sortyard.append_event(event);
    END IF;
    IF next_sequence <> existing.sequence + 1 THEN
        RAISE EXCEPTION 'sortyard.item: % is at transition %, cannot record %',
            the_item, existing.sequence, next_sequence
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    ledger_seq := sortyard.append_event(event);
    PERFORM set_config('sortyard.recording_transition', 'on', true);
    UPDATE sortyard.item_run AS r SET left_at = entered
        WHERE r.workspace_id = tenant AND r.item_id = the_item
          AND r.sequence = existing.sequence;
    INSERT INTO sortyard.item_run
        (workspace_id, item_id, sequence, state, state_kind, owner, limit_text, reason,
         from_state, cause, entered_at, event_id, dispatch, attempt, action, detail, deadline)
    VALUES
        (tenant, the_item, next_sequence, transition ->> 'state', transition ->> 'state_kind',
         transition ->> 'owner',
         transition ->> 'limit', transition ->> 'reason', transition ->> 'from_state',
         transition ->> 'cause', entered, event ->> 'id',
         COALESCE((transition ->> 'dispatch')::integer, next_sequence),
         COALESCE((transition ->> 'attempt')::integer, 1),
         transition ->> 'action',
         COALESCE(NULLIF(transition -> 'detail', 'null'::jsonb), '{}'::jsonb),
         (transition ->> 'deadline')::timestamptz);
    UPDATE sortyard.item AS i SET
        state = transition ->> 'state',
        state_kind = transition ->> 'state_kind',
        owner = transition ->> 'owner',
        limit_text = transition ->> 'limit',
        reason = transition ->> 'reason',
        entered_at = entered,
        sequence = next_sequence
        WHERE i.workspace_id = tenant AND i.id = the_item;
    PERFORM set_config('sortyard.recording_transition', 'off', true);
    RETURN ledger_seq;
END
$$;
