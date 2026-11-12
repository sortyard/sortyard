# 07 — Interfaces: API, MCP, CLI, identity and permissions

Areas: **API**, **MCP**, **CLI**, **IAM**. The rule that organises them: there is one domain
layer in which every state change is a named command that enforces the state machines and writes
its ledger event. The REST API exposes those commands one-to-one. The console, the CLI and the
MCP server are clients of the REST API and have no other path. The controller and the integrator
call the same domain layer in-process. Nothing a person or an agent can do is hidden from the
API, and nothing only the controller may do is offered by it.

This differs from DESIGN §4 ("the conductor is a client of [the API]") and from the prototype
clients (one MCP tool and one CLI command per operation). Reasons are in
[11-coherence.md](11-coherence.md) CF-07 and CF-08.

---

## API

### API-001 — One versioned REST API with a served OpenAPI document
**MS1** · WP1.2 · MUST · KEEP

The API lives under `/v1`, is described by an OpenAPI 3.1 document served at
`/v1/openapi.json`, and CI fails if the implementation and the document disagree. Resource shapes
come from the JSON Schemas in `spec/`, from which the Python models are generated.

- AC1: A contract test calls every operation in the document against a running server and validates each response against its schema.
- AC2: `python -m sortyard.models.codegen --check` and the OpenAPI drift check gate every PR; the `spec` job is no longer `continue-on-error`.
- AC3: Surface parity, measured at every merge to `main`: the share of the commands a person or an agent may perform that are REST operations, and the share of REST operations that have a CLI path, MCP reach and, when operator-facing, a console control. Target: 100% on all four at every merge, with no exemption. Floor: 100% for REST, CLI and MCP at every merge; console exemptions are dated and empty at each milestone exit (UI-002).

Source: spec NOTES "API conventions"; `.github/workflows/ci.yml` (the `spec` job currently fails on main and does not gate); goldfish GF1-02, GF1-09.

### API-002 — Commands live in the domain layer; the API adds no rules
**MS1** · WP1.2 · MUST · FIX

State machines, invariants and ledger writes are enforced in the domain layer (and by database
constraints where possible). HTTP handlers authenticate, authorise, validate shape and call a
command.

- AC1: The same command called from an HTTP handler and called in-process (the controller's path) produces identical state and events (shared test).
- AC2: No invariant test depends on going through HTTP.
- AC3: Demonstration (chaos, MS3) — the API is stopped for 10 minutes while chains are in flight. Target: claims, the advancement of finished stages and landing continue throughout, every result produced meanwhile is accepted when the API returns, and zero stages fail. Floor: no evaluation is skipped and no stage fails because the API is down; the legacy conductor skipped every pass while its API was unavailable (BL-25).

Baseline: The legacy conductor is a client of the dispatcher's API. On 2026-11-12 every drive pass was skipped for about 32 minutes while the API pod held an old bundle, and API rollouts have failed reviews, grooming and flake processing (conductor README "API rollouts"; BL-25, BL-08).

Better on: stall-rate, safety, upgrade-effort.

Source: DESIGN §4 ("API service — the only door"); see CF-07 for why the controller does not use HTTP.

### API-003 — Conventions
**MS1** · WP1.2 · MUST · KEEP

Lists use opaque cursors in both directions with `limit` (default 50, max 200), filters and sort
as query parameters, and return a total where it is cheap. Errors are RFC 9457 problem details
with a stable `code`. Status codes: 400 malformed, 401, 403, 404, 409 refused by a state machine
or policy, 412 stale precondition, 422 fails schema validation, 429, 503 dependency unavailable.
Timestamps are RFC 3339 UTC; durations are integer seconds.

- AC1: Every list endpoint passes a shared pagination conformance test (stable order under concurrent inserts, no duplicates or gaps across pages).
- AC2: Every error body validates against the problem schema, for every method on every path.

Source: spec NOTES "API conventions"; harness-console J2 ("server cursors in both directions"), decided D6; goldfish GF1-06 (HTML 501 page).

### API-004 — Optimistic concurrency
**MS1** · WP1.2 · MUST · NEW

Every mutable object has a revision returned as an `ETag`. `PATCH` and action endpoints accept
`If-Match`; a stale revision returns 412. The console always sends it.

- AC1: Two clients editing the same task: the second write fails with 412 and loses nothing.
- AC2: In-process callers (the controller's path) pass through the same revision check.

Source: inference — the frozen API replaces whole documents by merge patch with no precondition, while the operator, agents and the controller all write tasks; Plane writes of a pod on old code overwrote three specs during the 2026-11-08 import.

### API-005 — Idempotency keys
**MS1** · WP1.2 · MUST · KEEP

`POST` operations that create or trigger accept an `Idempotency-Key` header with the semantics
of REC-013; keys are remembered for the retention period (default 24 hours).

- AC1: Contract test: replaying each creating operation with the same key returns the first response.

Source: driver §5 (`client_request_id`).

### API-006 — State changes are named actions
**MS1** · WP1.2 · MUST · KEEP

`PATCH` edits fields and never changes state or queue status. Each transition is its own
endpoint (`POST …/tasks/{id}/release`, `/requeue`, `/cancel`, `/hand-back/resolve`,
`/decisions/{id}/answer`, …) with its own roles and its required reason fields.

- AC1: A `PATCH` containing `state` is rejected with 422 naming the action to use.

Source: spec NOTES "API conventions".

### API-007 — Server-assigned ids, client-supplied external ids
**MS1** · WP1.2 · MUST · KEEP

The server assigns ids and sequence numbers. A client may supply an `external_id` unique within
a project, which makes creates idempotent and lets a file be re-applied.

- AC1: Creating two tasks with the same `external_id` in one project yields one task.
- AC2: No operation requires the client to invent a primary key.

Source: spec NOTES API ambiguity 10 ("`POST` takes the whole object with a client-chosen `id`") — a gap in the frozen spec, not in the estate: Plane assigns ids and sequence numbers today, and `plane_tasks.py file` re-applies a file by task id.

### API-008 — Event stream
**MS1** · WP1.2 · MUST · KEEP

`GET /v1/…/events/stream` is a server-sent-event stream of ledger events, resumable with
`Last-Event-ID` (the ledger sequence), filterable by project, object and kind. Events are also
listable by cursor.

- AC1: A client that disconnects and resumes misses nothing and sees nothing twice.
- AC2: The stream carries only fields the caller may read.

Source: harness-console decided D5 (SSE keyed by a monotonic id, polling fallback); spec NOTES API ambiguity 15.

### API-009 — Outbound webhooks
**MS5** · WP5.8 · SHOULD · NEW

An operator can register webhook endpoints for event kinds. Deliveries are signed (HMAC-SHA256
over the body with a per-endpoint secret, timestamped), retried with backoff, and logged with
their outcome. Destinations are checked against private, loopback and link-local ranges unless
explicitly allowed.

- AC1: A receiver can verify signature and timestamp from the documentation alone.
- AC2: A webhook pointed at a metadata address or a cluster-internal service is refused by default.

Source: DESIGN §7 ("Webhooks/events out"); Plane benchmark (signed webhooks; nine SSRF advisories — see [12-quality-bar.md](12-quality-bar.md)).

### API-010 — Rate limiting
**MS8** · WP8.2 · MUST · NEW

Requests are rate-limited per token and per session; over-limit requests get 429 with
`Retry-After`. Limits are configuration.

- AC1: Default limits never throttle the bundled console or CLI in the scenario suite.

Source: Plane benchmark (API key limit default 60/minute); conductor `causes.tick` polls each parked item at most every 30 minutes "for Plane's rate limit".

### API-011 — Bounded responses and an explicit redaction contract
**MS1** · WP1.2 · MUST · KEEP

No endpoint returns an unbounded collection. Overview and list responses are built from field
allowlists and never include packets, prompts, check commands, free-form worker facts, tokens or
secrets. Detail endpoints that expose sensitive material (a packet, a trace) are separate
operations with their own role.

- AC1: A test enumerates every list and overview schema and asserts none references a sensitive field.
- AC2: Response size for any list call is bounded independently of history size.

Source: FACTORY-DASHBOARD-DESIGN "Decision and boundary" and "Source model and invariants"; harness-console decided D10.

### API-012 — Unknown is not zero
**MS2** · WP2.5 · MUST · KEEP

Every aggregate carries `as_of` and a coverage state. A value whose source is unread, stale or
incomplete is `null` with a `reason`; a ratio with a zero denominator is `null` with
`no_eligible_items`, never a number.

- AC1: Shared helper and a lint: aggregate fields are typed as `value | null + reason`.
- AC2: The UI renders `unknown` for null (UI-024).

Source: FACTORY-DASHBOARD-DESIGN ("They must not be rendered as zero while unconnected"); harness-console J1; factory-measurement-contract "Sources, windows, and missingness".

### API-013 — Stability and deprecation
**MS8** · WP8.3 · MUST · NEW

At 1.0 the `/v1` API is frozen: only additive changes within the major. A deprecation is
announced in the changelog and by a `Deprecation` header and stays for at least two minor
releases or six months, whichever is longer. CI checks every PR for breaking changes against the
last released OpenAPI document.

- AC1: A PR that removes a field or tightens a type fails the compatibility job.
- AC2: Before 1.0, each minor's breaking changes are listed in its upgrade notes.

Source: CORPUS M6.3 ("API backward-compatibility checks against the published OpenAPI"); Plane benchmark (no written deprecation policy found in the repo).

### API-014 — Health and identity endpoints
**MS1** · WP1.2 · MUST · FIX

`/healthz` is liveness. `/readyz` is ready only when the service can authenticate to the
database and the schema version is the one it expects. `/v1/info` returns version, source
commit, image digest, schema version and the health state (REC-019).

- AC1: With a wrong database password `/readyz` returns 503 and the rollout does not go green.
- AC2: The running revision is visible without cluster access.
- AC3: Demonstration (count, MS1) — the facts that answer "what is running, and is it healthy" (version, commit, image digest, schema version, health state) are listed with where each is read. Target: 100% from `/v1/info` in one call. Floor: none needs cluster access; the legacy revision is a cluster annotation (BL-28).

Baseline: The running revision is visible only as a cluster annotation (task-pickup conformance row 7, HARNESS-256; BL-28).

Better on: failure-visibility, operator-actions.

Source: goldfish GF1-07 ("a wrong password installs green"); task-pickup conformance row 7 (running revision visible only as a cluster annotation, HARNESS-256).

### API-015 — Bulk filing
**MS1** · WP1.2 · MUST · KEEP

One operation files a set of tasks with their relations atomically (TRK-012) and returns a
verdict per task.

- AC1: Filing 200 tasks with dependencies in one call on the reference install. Target: under 1 s. Floor: under 5 s.

Source: `plane_tasks.py file`; the 2026-11-08 import (40 new items, 252 relations).

### API-016 — Inbound Git host webhooks are an accelerator, not a dependency
**MS4** · WP4.1 · SHOULD · NEW

Sortyard works by polling the Git host. If inbound webhooks are configured, they only shorten
the time to observe a fact; every fact is still confirmed by reading it. Webhook payloads are
verified by signature.

- AC1: The full scenario suite passes with webhooks disabled.
- AC2: A forged webhook changes nothing.

Source: AGENTS.md "The rule" (observed state); the estate today polls (`drive` every 3 min, `plane_sync` every 5 min) and cannot receive webhooks on a tailnet-only host.

### API-017 — No controller-only public operations
**MS1** · WP1.2 · MUST · KEEP

Claiming a task, advancing a chain, instructing the integrator and applying a decision default
are not API operations. The frozen spec's `claimTask`, `advanceTask`, `handBackTask` and
`instructIntegrator` are removed.

- AC1: The OpenAPI document contains no operation whose only permitted role is the controller.
- AC2: System actors (`system:controller`, `system:integrator`, each with its version) are a separate actor type in the ledger, and no API credential can act as one.

Source: PERMISSIONS.md matrix (conductor-only rows); CF-07. The estate has no public claim operation either: the conductor claims inside its own process.

### API-018 — Workspace addressing
**MS1** · WP1.2 · SHOULD · KEEP

Every object carries `workspace_id`. Paths are `/v1/workspaces/{workspace}/…`; a single-workspace
installation may address its workspace as `default`.

- AC1: A 1.0 installation has exactly one workspace; creating a second is refused with a message that multi-workspace isolation is not supported yet.

Source: DESIGN §3.1 (the field exists from day one; multi-workspace is a v1 non-goal).

---

## MCP

### MCP-001 — MCP over HTTP from the API service, plus a stdio shim
**MS1** · WP1.4 · MUST · NEW

The API service serves MCP over Streamable HTTP at `/mcp`, authenticated by the same tokens as
REST. `sortyardctl mcp` is a stdio shim for clients that only speak stdio. Both expose the same
tools.

- AC1: A remote agent with a URL and a token lists and calls tools with no local install.
- AC2: Redirects are never followed with a token attached.

Source: the prototype is stdio only (`clients/mcp_server.py`); legacy `cp_mcp.py` (HTTP, protocol versions 2025-03-26 to 2025-11-25).

### MCP-002 — Curated, role-scoped tools
**MS1** · WP1.4 · MUST · FIX

Each role sees a small set of tools designed around what it does, at most 25 per role. Named
sets for 1.0: **worker** (`get_packet`, `submit_result`); **intake** (`file_tasks`,
`get_filing_verdict`, `search_tasks`, `get_task`, `add_note`); **groomer** (intake plus
`update_task`, `move_task`, `link_blocker`, `get_queue`); **sensor** (`file_finding`,
`search_findings`, `post_heartbeat`); **operator-agent** (`get_overview`, `get_attention`,
`get_queue`, `why_not_picked`, `get_task`, `get_chain`, `get_stage_outcomes`, `run_job`,
`requeue`, `cancel`, `resolve_hand_back`, `answer_decision`, `set_lanes`, `pause`, `resume`).

- AC1: `tools/list` returns exactly the tool set of the token's role: an `intake` token sees its five tools and nothing else; a worker token sees two (from MS3, MCP-005).
- AC2: The tool list for each role is generated from role annotations on the OpenAPI operations and a curated manifest; a test fails if a manifest tool has no backing operation.
- AC3: Demonstration (benchmark, MS5) — an operator-side agent with only an MCP address and a token performs the legacy operations inventory (BL-20): find why a task waits, requeue, cancel, run a job, resolve a hand-back, answer a decision, change lanes. Target: 100% of the inventory done with at most 25 tools in view, no cluster access and no shell. Floor: every operation the legacy scripts offer is done without cluster access or the shared board key (BL-20, BL-26).

Baseline: Agents operate the legacy system with the scripts of CLI-005, which need a shell in the cluster and the shared board key; its MCP server is read-only with four tools (driver §4 "Tools"; `cp_mcp.py`; BL-20, BL-26).

Better on: safety, operator-actions, install-effort.

Source: PERMISSIONS.md "§7 rules"; legacy `cp_mcp.py` (a curated read-only set: `get_insights`, `get_overview`, `get_request`, `get_stage_outcomes`); the prototype exposes one tool per operation (194).

### MCP-003 — Full reach through three generic tools
**MS1** · WP1.4 · MUST · KEEP

Every API operation the token may call is reachable through `list_operations`,
`describe_operation` and `call_operation`. This is how "APIs for everything, for agents" holds
without hundreds of tools.

- AC1: Parity test: for each role, the operations reachable through MCP equal the role's column of the permission matrix.

Source: DESIGN §7; `clients/README.md` parity rule ("every API operation is exactly one MCP tool").

### MCP-004 — Bounded, honest tool results
**MS1** · WP1.4 · MUST · KEEP

Tool results are capped (default 48,000 characters) with a continuation cursor, say `unknown`
where the API returned null with a reason, and carry MCP annotations (`readOnlyHint`,
`destructiveHint`, `idempotentHint`). A refusal from the API is passed back unchanged.

- AC1: A result over the cap is truncated at a record boundary and names how to continue.

Source: `cp_mcp.py` (`MAX_RESULT_CHARS` 48,000; "A source reported unknown/unavailable is unknown, not zero").

### MCP-005 — Worker tools are the stage contract
**MS3** · WP3.2 · MUST · KEEP

A stage token can do two things: read its own packet and submit its own result. Both are
available as REST operations and as MCP tools.

- AC1: A stage token calling any other operation gets 403; calling another stage's packet gets 404.

Source: DESIGN §7 ("a build worker can read its own context packet and submit its own stage result — nothing else").

---

## CLI

### CLI-001 — `sortyardctl`
**MS1** · WP1.4 · MUST · KEEP

One CLI, installable with `pipx` and shipped in the image. Configuration: API URL and token from
environment, a profile file, or `--token-file`; a token is never accepted as an argument. Exit
codes: 0 success, 1 refused by the API, 2 usage, 3 unreachable.

- AC1: `sortyardctl --help` works offline and lists every command.
- AC2: The process list never shows a token.

Source: `clients/README.md` (`SORTYARD_API_URL`, `SORTYARD_TOKEN`, exit codes).

### CLI-002 — Commands for the things people and agents actually do
**MS1** · WP1.4 · MUST · KEEP

Task-level commands with readable output and `--json`: `task file|add|get|list|edit|move|note`,
`pickup status`, `queue`, `why`, `requeue`, `cancel`, `job run`, `decision list|answer`,
`needs list|discharge`, `lanes get|set`, `pause`, `resume`, `apply`, `export`, `audit`,
`health`, `backup`. Commands arrive with the capability they operate.

- AC1: Each command maps to exactly one documented sequence of API calls.
- AC2: Human output and `--json` output are both covered by snapshot tests.

Source: driver §4 "Tools", §7 "Common operations".

### CLI-003 — Every API operation is reachable
**MS1** · WP1.4 · MUST · KEEP

`sortyardctl api <operationId> [--param k=v] [--body JSON|@file|-]` calls any operation. A parity
test fails if an operation has no CLI path.

- AC1: Unknown operations or arguments send nothing.

Source: `clients/README.md` parity rule; DESIGN §7 ("everything the CLI does is an API call (no back doors)").

### CLI-004 — Dry run
**MS2** · WP2.9 · SHOULD · KEEP

Mutating task-level commands accept `--dry-run` and print what would change, using the server's
own evaluation.

- AC1: `task file --dry-run` returns the verdict each task would get and writes nothing.

Source: `drive.py --dry-run`, `plane_sync.py --dry-run`.

### CLI-005 — Parity with the legacy operator tools
**MS2** · WP2.9 · MUST · KEEP

Each legacy tool has a documented equivalent: `add_item.py` → `task add --release`;
`add_item.py --job` → `job run`; `requeue.py` → `requeue`; `plane_tasks.py file` → `task file`;
`pickup_status.py` → `pickup status` (same verdicts and exit codes); `file_verify.py` → the
verdict returned by `task file`; `queue_audit.py` → `queue audit`; `repos_check.py` → `apply
--validate`; `preflight` → `task preflight`.

- AC1: The migration guide has this table and each row has a test.
- AC2: (WP5.11) Coverage of the legacy operations inventory (BL-20: the tools above, the legacy console's journeys and the steering done on the Plane board), as the share with a documented and tested Sortyard equivalent. Target: 100% by the MS5 gate. Floor: 100% of the operations the usage census (MIG-017) shows in use, before the first cutover.

Source: driver §4 "Tools"; conductor README (tool descriptions).

---

## IAM — identity, authorisation, audit

### IAM-001 — First-run bootstrap
**MS1** · WP1.3 · MUST · NEW

A fresh install has no accounts and no default password. The chart creates a one-time setup
token in a Secret; presenting it once creates the first admin and invalidates the token.

- AC1: The API refuses every other operation until bootstrap completes.
- AC2: The setup token cannot be used twice and expires (default after 24 hours); the docs say how to mint a new one.

Source: inference — DESIGN §3.1 assumes an OIDC provider; a stranger's install has none. Plane benchmark: instance-admin first-run setup.

### IAM-002 — Operator sign-in
**MS1** · WP1.3 · MUST · FIX

Three methods: local accounts (password hashed with argon2id, optional TOTP); OIDC; and a
trusted-proxy header mode for installations behind an authenticating proxy. Local accounts ship
in MS1; OIDC and the proxy mode are complete by MS6.

- AC1: A local account signs in with its password and, when enrolled, a TOTP code; a wrong second factor is refused and the attempt is audited.
- AC2: (WP6.4) The proxy mode is refused at startup unless the API is unreachable except through the proxy (a NetworkPolicy the chart renders, verified by a startup probe).
- AC3: (WP6.4) OIDC maps a claim to roles; a user with no mapping gets no access.
- AC4: Demonstration (chaos, MS6) — a pod inside the cluster sends every mutating operation with a forged identity header, in each sign-in mode. Target: 100% refused and audited, in every mode. Floor: zero forged requests accepted; the legacy backend accepts them until it is locked down (BL-26).

Baseline: The legacy console trusts a `Tailscale-User-Login` header that pods inside the cluster can forge, and its mutation routes accept any same-network POST (harness-console decided D2, D16; VISION; BL-26).

Better on: safety.

Source: harness-console decided D2, D16 (the `Tailscale-User-Login` header is forgeable from in-cluster pods until the backend is locked down); HC02-BACKEND-LOCKDOWN-DESIGN.

### IAM-003 — Session and request hardening
**MS1** · WP1.3 · MUST · KEEP

Cookie sessions are `HttpOnly`, `Secure`, `SameSite=Lax`, with CSRF protection; mutations require
a same-origin request with a JSON body. Token-authenticated requests need no CSRF. The console
ships a strict Content-Security-Policy.

- AC1: A cross-site form post to any mutation is rejected.
- AC2: A security-headers test runs against every route.

Source: harness-console VISION ("mutation routes accept any same-network POST"), decided D2.

### IAM-004 — Human roles
**MS1** · WP1.3 · MUST · KEEP

`admin` (everything, including identity, credentials and integrations), `operator` (steer:
tasks, decisions, lanes, policies, requeue, cancel), `viewer` (read). A role binding is scoped
to the workspace or to one project.

- AC1: The permission matrix is generated from annotations in the OpenAPI document and published in the docs; a test fails if the page and the document disagree.

Source: PERMISSIONS.md; DESIGN §3.9.

### IAM-005 — Service accounts and tokens
**MS1** · WP1.3 · MUST · KEEP

A service account has a role and a scope. Tokens are shown once, stored hashed, expire (default
90 days), can be revoked, and record last use. Issuing, rotating and revoking are audited.

- AC1: A database dump contains no usable token.
- AC2: An expiring token is flagged in the token list ahead of expiry (default 14 days) and, from MS5, raises an attention item (OBS-014).

Source: `identity/README.md` (scopes issued and revoked as data, every mutation audited); the owner's GitHub token expiry is tracked by hand today (driver §5).

### IAM-006 — Agent roles
**MS1** · WP1.3 · MUST · KEEP

Agent roles: `intake` (create tasks and notes in its project), `groomer` (intake plus edit,
order and link in its project), `sensor` (file findings and heartbeats in its project),
`operator-agent` (operator capabilities for unattended agents such as self-heal), and `worker`
(stage tokens only, IAM-007).

- AC1: Each role's allowed operations are a column of the matrix with an allow and a deny test per cell (IAM-010).
- AC2: A sensor can search its own project's findings so that it can de-duplicate.

Source: DESIGN §7; spec NOTES API ambiguity 5 ("a sensor therefore cannot de-duplicate against existing findings"); `SELF-HEAL.md` (an agent with host access works the queue).

### IAM-007 — Stage tokens
**MS3** · WP3.2 · MUST · KEEP

The controller mints one token per stage attempt, confined to that attempt and its chain epoch,
expiring at the stage deadline plus a margin, and revoked when the stage ends.

- AC1: A stage token used after its stage ended is refused.

Source: `identity/README.md` ("a build-worker token, confined to one `stage_run_id`").

### IAM-008 — No agent can make its own work run
**MS1** · WP1.3 · MUST · FIX

The invariant behind the design's "no token may create tasks and claim them": no principal
driven by a model can both introduce work and cause it to execute without passing gates it does
not control. Concretely: claiming is not grantable to anyone (API-017); a worker cannot create
tasks (follow-ups travel as stage output and are filed by the controller); tasks created by
agent principals are released only by the ready, preflight and release rules, which agents cannot
edit; system-created tasks record their origin and the rule that released them.

- AC1: No role's column contains both task creation and any release-rule or policy edit.
- AC2: A worker-token call to create a task is refused.
- AC3: The legacy pattern (the sync creates urgent triage items and the driver claims them, both deterministic) is allowed and attributed to `system:` actors.
- AC4: Demonstration (count, MS1) — every credential is listed with whether it can introduce work and whether it can release or claim it, for the legacy system and for Sortyard. Target: zero credentials hold both, and 100% of the matrix cells are tested. Floor: fewer credentials hold both than in the legacy system, where one shared key does (BL-26).

Baseline: The sync that files urgent triage items and the driver that claims them share one Plane key (DESIGN §7; `plane_sync.queue_triage`); by inference the filing tools use the same one (BL-26).

Better on: safety.

Source: DESIGN §7 (queue-poisoning vector); spec NOTES API ambiguity 6 (who creates `chain` and `eval-finding` tasks?); `plane_sync.queue_triage` and `drive` share one Plane key today.

### IAM-009 — Authorisation is central, default-deny and object-scoped
**MS1** · WP1.3 · MUST · NEW

One authorisation function decides every request from the operation's declared roles and the
caller's bindings. An operation with no declared role is unreachable. Object access is scoped in
the data-access layer: every query is constrained by the caller's workspace and project scope,
so an id from another scope behaves as not found.

- AC1: No handler contains its own role check (lint).
- AC2: A request for an object outside the caller's scope returns 404, never 403 with details and never the object.

Source: Plane benchmark — 57 of 89 published advisories are authorisation flaws (CWE-639, 862, 284, 863); see [12-quality-bar.md](12-quality-bar.md).

### IAM-010 — The authorisation matrix is tested cell by cell
**MS1** · WP1.3 · MUST · NEW

For every operation × role there is an automated test asserting allow or deny, generated from
the matrix; and for every operation that takes an object id, a test that an id from another
project and another workspace is refused.

- AC1: Adding an operation without declaring its roles fails CI.
- AC2: The generated suite runs on every PR in under two minutes.

Source: `test_openapi.py` already checks the matrix document against the spec; this extends the check to the running service.

### IAM-011 — Audit log
**MS1** · WP1.3 · MUST · KEEP

Every mutation records actor, time, target, before and after (redacted), request id, client and
result, in an append-only store. A refused request is logged separately from mutations. The
audit trail of an object is visible on that object.

- AC1: The append-only guarantee is enforced by the database (update, delete and truncate refused), as in the existing migration.
- AC2: The time from a mutating UI action to its entry in the entity's audit trail. Target: 1 s. Floor: 5 s.

Source: harness-console J5 ("an audit entry (actor, time, target, result) is visible on the entity"); migration `0001` (refuse triggers).

### IAM-012 — Approval mode for agent-proposed actions
**MS6** · WP6.6 · SHOULD · KEEP

An operator-agent token, and the embedded concierge (UI-026), can run in approval mode: a
state-changing action becomes a proposal that a person approves, edits or rejects in the console
before it runs. The proposal shows the exact action and its effect; approving runs it as the
approver, audited with the proposer named.

- AC1: A proposal never executes without the approval of a person who holds the role the action needs; an edited proposal runs as edited.
- AC2: The legacy journeys for approving and for editing an approval (J7, J12) pass against Sortyard.
- AC3: A proposal is the stored "check" half of an action endpoint, which already separates check from do; no second execution path exists.

Source: harness-console J7, decided D9; console e2e `j7-approve`, `j12-approval-edit`. Cut reversed on 2026-11-12: the feature is built and in the legacy console, and no measured case showed that removing it is better.
