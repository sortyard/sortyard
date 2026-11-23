-- 0001 — the §3 domain objects and the event ledger (design draft §3, §4: "Postgres for
-- state + ledger, JSONB for facts").
--
-- One table per §3 object schema in spec/ (ResourceEnvelope is embedded in ExecutionBinding
-- and has no table). Every row's `doc` is the object exactly as its JSON Schema defines it;
-- the Python models in sortyard.models are generated from the same schemas, so `doc` is what
-- Model.to_dict() writes and Model.from_dict() reads. Every other column is a GENERATED
-- projection of `doc` (id, tenancy, version, the fields queries filter on): it cannot
-- disagree with the document, so the table and the contract cannot drift.
--
-- Keys follow the store each schema declares (x-sortyard-store, §5.1):
--   definition            (id, version); rows are immutable versions — a change is a new row.
--   state, config, read-model   id; the row is the object's current state.
-- Workspace-scoped objects reference sortyard.workspace (§3.1: workspace_id from day one).
--
-- Streams that only grow — the event ledger, the DecisionLog and the AuditLog — refuse
-- UPDATE, DELETE and TRUNCATE.
--
-- Applied by migrate.sh (the chart's migration Job) inside one transaction, together with
-- its sortyard.schema_migration row. Released migrations are never edited: change the
-- schema with a new numbered file.

CREATE SCHEMA IF NOT EXISTS sortyard;

-- Statement-level guard: raises for whatever operation the trigger is attached to.
CREATE FUNCTION sortyard.refuse() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'sortyard.% %: % refused', TG_TABLE_NAME, TG_ARGV[0], TG_OP
        USING ERRCODE = 'feature_not_supported';
END
$$;

-- Installation (§3.1; store: config).
CREATE TABLE sortyard.installation (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.installation (name);

-- Workspace (§3.1; store: state).
CREATE TABLE sortyard.workspace (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    installation_id text GENERATED ALWAYS AS (doc ->> 'installation_id') STORED NOT NULL
        REFERENCES sortyard.installation (id),
    slug text GENERATED ALWAYS AS (doc ->> 'slug') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.workspace (installation_id);
CREATE INDEX ON sortyard.workspace (slug);

-- Agent (§3.7; store: definition).
CREATE TABLE sortyard.agent (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.agent (workspace_id);
CREATE INDEX ON sortyard.agent (name);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.agent
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- Alert (§3.8; store: state).
CREATE TABLE sortyard.alert (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    kind text GENERATED ALWAYS AS (doc ->> 'kind') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    task_id text GENERATED ALWAYS AS (doc ->> 'task_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.alert (workspace_id);
CREATE INDEX ON sortyard.alert (kind);
CREATE INDEX ON sortyard.alert (state);
CREATE INDEX ON sortyard.alert (task_id);

-- Archetype (§3.2; store: definition).
CREATE TABLE sortyard.archetype (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    status text GENERATED ALWAYS AS (doc ->> 'status') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.archetype (workspace_id);
CREATE INDEX ON sortyard.archetype (name);
CREATE INDEX ON sortyard.archetype (status);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.archetype
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- AuditLogEntry (§3.9; store: state).
CREATE TABLE sortyard.audit_log (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    action text GENERATED ALWAYS AS (doc ->> 'action') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.audit_log (workspace_id);
CREATE INDEX ON sortyard.audit_log (action);
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON sortyard.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('is append-only');

-- Chain (§3.3, §5.1; store: state).
CREATE TABLE sortyard.chain (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    task_id text GENERATED ALWAYS AS (doc ->> 'task_id') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    lane_id text GENERATED ALWAYS AS (doc ->> 'lane_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.chain (workspace_id);
CREATE INDEX ON sortyard.chain (task_id);
CREATE INDEX ON sortyard.chain (state);
CREATE INDEX ON sortyard.chain (lane_id);

-- ConductorConfig (§3.4, §3.7b; store: config).
CREATE TABLE sortyard.conductor_config (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.conductor_config (workspace_id);

-- ContextRecipe (§3.7a, §3.7b; store: definition).
CREATE TABLE sortyard.context_recipe (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    project_id text GENERATED ALWAYS AS (doc ->> 'project_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.context_recipe (workspace_id);
CREATE INDEX ON sortyard.context_recipe (project_id);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.context_recipe
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- CredentialCustody (§3.7a; store: config).
CREATE TABLE sortyard.credential_custody (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    credential text GENERATED ALWAYS AS (doc ->> 'credential') STORED,
    custody text GENERATED ALWAYS AS (doc ->> 'custody') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.credential_custody (workspace_id);
CREATE INDEX ON sortyard.credential_custody (credential);
CREATE INDEX ON sortyard.credential_custody (custody);

-- Decision (§3.3; store: state).
CREATE TABLE sortyard.decision (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    project_id text GENERATED ALWAYS AS (doc ->> 'project_id') STORED,
    task_id text GENERATED ALWAYS AS (doc ->> 'task_id') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.decision (workspace_id);
CREATE INDEX ON sortyard.decision (project_id);
CREATE INDEX ON sortyard.decision (task_id);
CREATE INDEX ON sortyard.decision (state);

-- DecisionLogEntry (§3.8, §3.5, §3.7b; store: state).
CREATE TABLE sortyard.decision_log (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    decision text GENERATED ALWAYS AS (doc ->> 'decision') STORED,
    task_id text GENERATED ALWAYS AS (doc ->> 'task_id') STORED,
    conductor_pass_id text GENERATED ALWAYS AS (doc ->> 'conductor_pass_id') STORED,
    event_id text GENERATED ALWAYS AS (doc ->> 'event_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.decision_log (workspace_id);
CREATE INDEX ON sortyard.decision_log (decision);
CREATE INDEX ON sortyard.decision_log (task_id);
CREATE INDEX ON sortyard.decision_log (conductor_pass_id);
CREATE INDEX ON sortyard.decision_log (event_id);
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON sortyard.decision_log
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('is append-only');

-- DeploymentConfig (§3.9, §5.1; store: config).
CREATE TABLE sortyard.deployment_config (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    installation_id text GENERATED ALWAYS AS (doc ->> 'installation_id') STORED NOT NULL
        REFERENCES sortyard.installation (id),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.deployment_config (installation_id);

-- Escalation (§3.3; store: state).
CREATE TABLE sortyard.escalation (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    chain_id text GENERATED ALWAYS AS (doc ->> 'chain_id') STORED,
    task_id text GENERATED ALWAYS AS (doc ->> 'task_id') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.escalation (workspace_id);
CREATE INDEX ON sortyard.escalation (chain_id);
CREATE INDEX ON sortyard.escalation (task_id);
CREATE INDEX ON sortyard.escalation (state);

-- Eval (§3.8; store: definition).
CREATE TABLE sortyard.eval (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.eval (workspace_id);
CREATE INDEX ON sortyard.eval (name);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.eval
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- EvalRun (§3.8; store: state).
CREATE TABLE sortyard.eval_run (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    subject_ref text GENERATED ALWAYS AS (doc ->> 'subject_ref') STORED,
    verdict text GENERATED ALWAYS AS (doc ->> 'verdict') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.eval_run (workspace_id);
CREATE INDEX ON sortyard.eval_run (subject_ref);
CREATE INDEX ON sortyard.eval_run (verdict);

-- ExecutionBinding (§3.7b; store: state).
CREATE TABLE sortyard.execution_binding (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    task_id text GENERATED ALWAYS AS (doc ->> 'task_id') STORED,
    stage text GENERATED ALWAYS AS (doc ->> 'stage') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.execution_binding (workspace_id);
CREATE INDEX ON sortyard.execution_binding (task_id);
CREATE INDEX ON sortyard.execution_binding (stage);
CREATE INDEX ON sortyard.execution_binding (state);

-- Extension (§3.7a, §3.7b; store: definition).
CREATE TABLE sortyard.extension (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    kind text GENERATED ALWAYS AS (doc ->> 'kind') STORED,
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.extension (workspace_id);
CREATE INDEX ON sortyard.extension (kind);
CREATE INDEX ON sortyard.extension (name);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.extension
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- GroomingPass (§3.5; store: state).
CREATE TABLE sortyard.grooming_pass (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    project_id text GENERATED ALWAYS AS (doc ->> 'project_id') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.grooming_pass (workspace_id);
CREATE INDEX ON sortyard.grooming_pass (project_id);
CREATE INDEX ON sortyard.grooming_pass (state);

-- Integrator (§3.7a; store: config).
CREATE TABLE sortyard.integrator (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.integrator (workspace_id);
CREATE INDEX ON sortyard.integrator (name);

-- Lane (§3.4, §3.7b; store: config).
CREATE TABLE sortyard.lane (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    scope text GENERATED ALWAYS AS (doc ->> 'scope') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.lane (workspace_id);
CREATE INDEX ON sortyard.lane (name);
CREATE INDEX ON sortyard.lane (scope);

-- Milestone (§3.3, §3.3a; store: state).
CREATE TABLE sortyard.milestone (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    project_id text GENERATED ALWAYS AS (doc ->> 'project_id') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.milestone (workspace_id);
CREATE INDEX ON sortyard.milestone (project_id);
CREATE INDEX ON sortyard.milestone (state);

-- Mirror (§3.7; store: state).
CREATE TABLE sortyard.mirror (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    repo_id text GENERATED ALWAYS AS (doc ->> 'repo_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.mirror (workspace_id);
CREATE INDEX ON sortyard.mirror (repo_id);

-- Operator (§3.9; store: state).
CREATE TABLE sortyard.operator (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    subject text GENERATED ALWAYS AS (doc ->> 'subject') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.operator (workspace_id);
CREATE INDEX ON sortyard.operator (subject);
CREATE INDEX ON sortyard.operator (state);

-- Policy (§3.6; store: definition).
CREATE TABLE sortyard.policy (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    kind text GENERATED ALWAYS AS (doc ->> 'kind') STORED,
    scope text GENERATED ALWAYS AS (doc ->> 'scope') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.policy (workspace_id);
CREATE INDEX ON sortyard.policy (kind);
CREATE INDEX ON sortyard.policy (scope);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.policy
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- PrioritizationPolicy (§3.5; store: definition).
CREATE TABLE sortyard.prioritization_policy (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    scope text GENERATED ALWAYS AS (doc ->> 'scope') STORED,
    project_id text GENERATED ALWAYS AS (doc ->> 'project_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.prioritization_policy (workspace_id);
CREATE INDEX ON sortyard.prioritization_policy (scope);
CREATE INDEX ON sortyard.prioritization_policy (project_id);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.prioritization_policy
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- Project (§3.2; store: state).
CREATE TABLE sortyard.project (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.project (workspace_id);
CREATE INDEX ON sortyard.project (name);
CREATE INDEX ON sortyard.project (state);

-- Repo (§3.2; store: state).
CREATE TABLE sortyard.repo (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    project_id text GENERATED ALWAYS AS (doc ->> 'project_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.repo (workspace_id);
CREATE INDEX ON sortyard.repo (project_id);

-- Role (§3.4; store: definition).
CREATE TABLE sortyard.role (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    kind text GENERATED ALWAYS AS (doc ->> 'kind') STORED,
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.role (workspace_id);
CREATE INDEX ON sortyard.role (kind);
CREATE INDEX ON sortyard.role (name);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.role
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- RoleBinding (§3.9; store: config).
CREATE TABLE sortyard.role_binding (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    role text GENERATED ALWAYS AS (doc ->> 'role') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.role_binding (workspace_id);
CREATE INDEX ON sortyard.role_binding (role);

-- ScorecardBattery (§3.8; store: definition).
CREATE TABLE sortyard.scorecard_battery (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.scorecard_battery (workspace_id);
CREATE INDEX ON sortyard.scorecard_battery (name);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.scorecard_battery
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- Secret (§3.7a; store: config).
CREATE TABLE sortyard.secret (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    backend text GENERATED ALWAYS AS (doc ->> 'backend') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.secret (workspace_id);
CREATE INDEX ON sortyard.secret (name);
CREATE INDEX ON sortyard.secret (backend);

-- SelfHeal (§3.8; store: state).
CREATE TABLE sortyard.self_heal (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    task_id text GENERATED ALWAYS AS (doc ->> 'task_id') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.self_heal (workspace_id);
CREATE INDEX ON sortyard.self_heal (task_id);
CREATE INDEX ON sortyard.self_heal (state);

-- SequenceChange (§3.3a; store: state).
CREATE TABLE sortyard.sequence_change (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    subject_kind text GENERATED ALWAYS AS (doc ->> 'subject_kind') STORED,
    subject_id text GENERATED ALWAYS AS (doc ->> 'subject_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.sequence_change (workspace_id);
CREATE INDEX ON sortyard.sequence_change (subject_kind);
CREATE INDEX ON sortyard.sequence_change (subject_id);

-- SequencingPolicy (§3.3a; store: definition).
CREATE TABLE sortyard.sequencing_policy (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    scope text GENERATED ALWAYS AS (doc ->> 'scope') STORED,
    lane_id text GENERATED ALWAYS AS (doc ->> 'lane_id') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.sequencing_policy (workspace_id);
CREATE INDEX ON sortyard.sequencing_policy (scope);
CREATE INDEX ON sortyard.sequencing_policy (lane_id);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.sequencing_policy
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');

-- StageRun (§3.3, §3.7b; store: state).
CREATE TABLE sortyard.stage_run (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    chain_id text GENERATED ALWAYS AS (doc ->> 'chain_id') STORED,
    stage text GENERATED ALWAYS AS (doc ->> 'stage') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.stage_run (workspace_id);
CREATE INDEX ON sortyard.stage_run (chain_id);
CREATE INDEX ON sortyard.stage_run (stage);
CREATE INDEX ON sortyard.stage_run (state);

-- Task (§3.3; store: state).
CREATE TABLE sortyard.task (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    project_id text GENERATED ALWAYS AS (doc ->> 'project_id') STORED,
    milestone_id text GENERATED ALWAYS AS (doc ->> 'milestone_id') STORED,
    lane_id text GENERATED ALWAYS AS (doc ->> 'lane_id') STORED,
    chain_id text GENERATED ALWAYS AS (doc ->> 'chain_id') STORED,
    state text GENERATED ALWAYS AS (doc ->> 'state') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.task (workspace_id);
CREATE INDEX ON sortyard.task (project_id);
CREATE INDEX ON sortyard.task (milestone_id);
CREATE INDEX ON sortyard.task (lane_id);
CREATE INDEX ON sortyard.task (chain_id);
CREATE INDEX ON sortyard.task (state);

-- ThroughputWindow (§3.8, §0.1; store: read-model).
CREATE TABLE sortyard.throughput_window (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    granularity text GENERATED ALWAYS AS (doc ->> 'granularity') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE INDEX ON sortyard.throughput_window (workspace_id);
CREATE INDEX ON sortyard.throughput_window (granularity);

-- Workflow (§3.4, §3.3a; store: definition).
CREATE TABLE sortyard.workflow (
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    version text GENERATED ALWAYS AS (doc ->> 'version') STORED NOT NULL,
    content_hash text GENERATED ALWAYS AS (doc ->> 'content_hash') STORED,
    name text GENERATED ALWAYS AS (doc ->> 'name') STORED,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);
CREATE INDEX ON sortyard.workflow (workspace_id);
CREATE INDEX ON sortyard.workflow (name);
CREATE TRIGGER immutable BEFORE UPDATE ON sortyard.workflow
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('rows are immutable definition versions');


-- The event ledger (§3.8): the append-only spine. Every transition, decision, eval verdict,
-- merge and deploy observation is one Event {ts, actor, object, transition, facts, refs}.
-- `seq` is the ledger position, assigned here and never by the writer; it is monotonic, not
-- gapless (an aborted append consumes a number), and positions are assigned at insert, so a
-- reader tailing the ledger must not assume a lower seq is always visible first.
CREATE TABLE sortyard.event (
    seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
    id text GENERATED ALWAYS AS (doc ->> 'id') STORED NOT NULL UNIQUE,
    workspace_id text GENERATED ALWAYS AS (doc ->> 'workspace_id') STORED NOT NULL
        REFERENCES sortyard.workspace (id),
    object_kind text GENERATED ALWAYS AS (doc -> 'object' ->> 'kind') STORED NOT NULL,
    object_id text GENERATED ALWAYS AS (doc -> 'object' ->> 'id') STORED NOT NULL,
    transition text GENERATED ALWAYS AS (doc -> 'transition' ->> 'name') STORED NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON sortyard.event (workspace_id);
CREATE INDEX ON sortyard.event (object_kind, object_id, seq);
CREATE TRIGGER append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON sortyard.event
    FOR EACH STATEMENT EXECUTE FUNCTION sortyard.refuse('is append-only');

-- Stamp the assigned position into the document, so `doc` is a complete Event.
CREATE FUNCTION sortyard.event_position() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.doc ? 'seq' THEN
        RAISE EXCEPTION 'sortyard.event: the ledger assigns seq; an appended event must not carry one'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    NEW.doc := NEW.doc || jsonb_build_object('seq', NEW.seq);
    RETURN NEW;
END
$$;
CREATE TRIGGER event_position BEFORE INSERT ON sortyard.event
    FOR EACH ROW EXECUTE FUNCTION sortyard.event_position();

-- Idempotent append: returns the event's ledger position. Appending the same event (same id,
-- same content) again returns the original position and records nothing; reusing an id for
-- different content is refused.
CREATE FUNCTION sortyard.append_event(event jsonb) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    assigned bigint;
    existing jsonb;
BEGIN
    INSERT INTO sortyard.event (doc) VALUES (event)
        ON CONFLICT (id) DO NOTHING
        RETURNING seq INTO assigned;
    IF assigned IS NULL THEN
        SELECT e.seq, e.doc - 'seq' INTO assigned, existing
            FROM sortyard.event AS e WHERE e.id = event ->> 'id';
        IF existing IS DISTINCT FROM event THEN
            RAISE EXCEPTION 'sortyard.event: % was already appended with different content',
                event ->> 'id'
                USING ERRCODE = 'unique_violation';
        END IF;
    END IF;
    RETURN assigned;
END
$$;

-- One object's history: its events in ledger order.
CREATE FUNCTION sortyard.object_history(of_kind text, of_id text) RETURNS SETOF jsonb
LANGUAGE sql STABLE AS $$
    SELECT doc FROM sortyard.event
    WHERE object_kind = of_kind AND object_id = of_id
    ORDER BY seq
$$;
