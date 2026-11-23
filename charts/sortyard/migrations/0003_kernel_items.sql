-- 0003 — the kernel's projection: items, runs and links (company/HARNESS-V3.md section 3.2,
-- SY-V3-LEDGER-AND-VIEW).
--
-- The item workflow owns item state. Every transition it makes is written here by one call,
-- sortyard.record_item_transition, which updates the item row, closes and opens the run rows
-- and appends the ledger Event together: a function call is one statement, so all of it lands
-- or none of it does. The tracker reads these tables and nothing writes item state any other
-- way: a direct UPDATE of an item's state columns is refused.
--
-- Unlike the section 3 objects of 0001, these are typed columns, not a JSON document: this is
-- a read model the kernel defines, with no schema in spec/ to stay in step with.
--
-- The tenant identifier is workspace_id, as on every table since 0001. It is NOT NULL and
-- leads every key here.

CREATE TABLE sortyard.item (
    workspace_id text NOT NULL REFERENCES sortyard.workspace (id),
    id text NOT NULL CHECK (id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$'),
    project_id text NOT NULL,
    -- A grouping and a preferred shipping order. It never orders the queue: links do.
    milestone_id text,
    title text NOT NULL,
    risk_tier text NOT NULL,
    -- Creation order: the tie-break between items that no link orders.
    position bigint GENERATED ALWAYS AS IDENTITY,
    -- Where the workflow says the item is. NULL until its first transition is recorded.
    state text,
    -- What kind of state it is, from the state table: queue, work, need, decision, terminal.
    state_kind text,
    owner text,
    limit_text text,
    reason text,
    entered_at timestamptz,
    -- The number of transitions recorded; the next one must carry sequence + 1.
    sequence integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, id)
);
CREATE INDEX ON sortyard.item (workspace_id, project_id);

-- One row per stay of an item in a state: who owned it, under what limit, how it was entered
-- and how it was left.
CREATE TABLE sortyard.item_run (
    workspace_id text NOT NULL,
    item_id text NOT NULL,
    sequence integer NOT NULL CHECK (sequence >= 1),
    state text NOT NULL,
    state_kind text NOT NULL,
    owner text,
    limit_text text,
    reason text NOT NULL,
    from_state text,
    cause text NOT NULL,
    entered_at timestamptz NOT NULL,
    left_at timestamptz,
    -- The ledger Event of the transition into this run. Not a foreign key: the same call writes
    -- both, and a reference would change how the ledger refuses TRUNCATE.
    event_id text NOT NULL,
    PRIMARY KEY (workspace_id, item_id, sequence),
    FOREIGN KEY (workspace_id, item_id) REFERENCES sortyard.item (workspace_id, id)
);

-- blocked_by links: the only ordering of the queue.
CREATE TABLE sortyard.item_link (
    workspace_id text NOT NULL,
    item_id text NOT NULL,
    blocked_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, item_id, blocked_by),
    FOREIGN KEY (workspace_id, item_id) REFERENCES sortyard.item (workspace_id, id),
    FOREIGN KEY (workspace_id, blocked_by) REFERENCES sortyard.item (workspace_id, id),
    CHECK (item_id <> blocked_by)
);
CREATE INDEX ON sortyard.item_link (workspace_id, blocked_by);

-- Item state is written by record_item_transition and by nothing else.
CREATE FUNCTION sortyard.item_state_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.workspace_id, NEW.id, NEW.project_id) IS DISTINCT FROM
       (OLD.workspace_id, OLD.id, OLD.project_id) THEN
        RAISE EXCEPTION 'sortyard.item: an item keeps its workspace, id and project'
            USING ERRCODE = 'feature_not_supported';
    END IF;
    IF current_setting('sortyard.recording_transition', true) IS DISTINCT FROM 'on' AND (
        (NEW.state, NEW.state_kind, NEW.owner, NEW.limit_text, NEW.reason, NEW.entered_at,
         NEW.sequence)
        IS DISTINCT FROM
        (OLD.state, OLD.state_kind, OLD.owner, OLD.limit_text, OLD.reason, OLD.entered_at,
         OLD.sequence)
    ) THEN
        RAISE EXCEPTION 'sortyard.item: state is written by the item workflow only; send the workflow a request'
            USING ERRCODE = 'feature_not_supported';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER state_guard BEFORE UPDATE ON sortyard.item
    FOR EACH ROW EXECUTE FUNCTION sortyard.item_state_guard();

CREATE FUNCTION sortyard.item_starts_stateless() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.sequence <> 0 OR (NEW.state, NEW.state_kind, NEW.owner, NEW.limit_text, NEW.reason,
                             NEW.entered_at) IS DISTINCT FROM (NULL, NULL, NULL, NULL, NULL, NULL)
    THEN
        RAISE EXCEPTION 'sortyard.item: a new item has no state; the item workflow records its first transition'
            USING ERRCODE = 'feature_not_supported';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER starts_stateless BEFORE INSERT ON sortyard.item
    FOR EACH ROW EXECUTE FUNCTION sortyard.item_starts_stateless();

CREATE TRIGGER append_only BEFORE DELETE OR TRUNCATE ON sortyard.item_run
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are history');

-- Run rows are written by record_item_transition and by nothing else: it inserts one and
-- stamps left_at on the one before.
CREATE FUNCTION sortyard.item_run_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('sortyard.recording_transition', true) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'sortyard.item_run: runs are written by the item workflow only'
            USING ERRCODE = 'feature_not_supported';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER run_guard BEFORE INSERT OR UPDATE ON sortyard.item_run
    FOR EACH ROW EXECUTE FUNCTION sortyard.item_run_guard();

-- Record one transition: the item row, its run rows and the ledger Event, together.
--
--   transition  {item, sequence, state, state_kind, owner, limit, reason, from_state, cause,
--                entered_at}
--   event       the ledger Event for it (workspace_id is the tenant; the ledger assigns seq)
--
-- Returns the Event's ledger position. The call is idempotent: the workflow's record step may
-- be delivered more than once, and a transition already recorded returns its position and
-- writes nothing. Anything else is refused and writes nothing: a sequence below 1, one that
-- skips a number, an Event that is not about this item, and a second, different Event for a
-- transition already recorded.
CREATE FUNCTION sortyard.record_item_transition(transition jsonb, event jsonb) RETURNS bigint
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
         from_state, cause, entered_at, event_id)
    VALUES
        (tenant, the_item, next_sequence, transition ->> 'state', transition ->> 'state_kind',
         transition ->> 'owner',
         transition ->> 'limit', transition ->> 'reason', transition ->> 'from_state',
         transition ->> 'cause', entered, event ->> 'id');
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
