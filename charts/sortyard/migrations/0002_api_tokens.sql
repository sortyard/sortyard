-- 0002 — API bearer tokens (design §7: service accounts with scoped tokens).
--
-- Not a §3 object: the credential store behind the API's bearer authentication. A token is
-- issued for a RoleBinding (§3.9) and is stored only as its SHA-256; the token itself is shown
-- once, at issuance, and never stored.
--
-- - Service-account tokens (role = an agent role) are issued by issueServiceAccountToken for
--   an `agent-service-account` binding. A build-worker token is confined to one stage run, a
--   sensor or grooming token to one project.
-- - Operator tokens (role = admin/operator/viewer) are the interim operator credential until
--   OIDC sessions land; the effective role is always the binding's current role.
--
-- `capabilities` is the token's column of the §7 matrix at issuance. No token may hold both
-- task.create and task.claim — the queue-poisoning pair is refused by the API at issuance and,
-- whatever wrote the row, by this table.
CREATE TABLE sortyard.api_token (
    id text PRIMARY KEY,
    token_sha256 text NOT NULL UNIQUE,
    workspace_id text NOT NULL REFERENCES sortyard.workspace (id),
    role_binding_id text NOT NULL REFERENCES sortyard.role_binding (id) ON DELETE CASCADE,
    principal jsonb NOT NULL,
    role text NOT NULL CHECK (role IN (
        'admin', 'operator', 'viewer', 'conductor', 'build-worker', 'sensor', 'grooming-agent'
    )),
    capabilities text[] NOT NULL,
    project_id text,
    stage_run_id text,
    issued_by jsonb,
    issued_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CONSTRAINT no_create_and_claim
        CHECK (NOT (capabilities @> ARRAY['task.create', 'task.claim']::text[])),
    CONSTRAINT build_worker_is_confined_to_a_stage_run
        CHECK (role <> 'build-worker' OR stage_run_id IS NOT NULL),
    CONSTRAINT sensor_is_confined_to_a_project
        CHECK (role <> 'sensor' OR project_id IS NOT NULL)
);
CREATE INDEX ON sortyard.api_token (role_binding_id);
CREATE INDEX ON sortyard.api_token ((principal ->> 'id'));
