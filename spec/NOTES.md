# Sortyard domain model — frozen JSON Schemas (Phase 0)

These schemas freeze the domain model of the Sortyard design draft, §3 ("Domain model — the
logical objects"), as the contract for the API work that follows (Phase 0 item 2; definitions
in git per §5.1). One file per domain object; `common.schema.json` holds the shared
definitions (ids, references, timestamps, content hashes, the tenancy base shapes).

## Conventions

- Dialect: JSON Schema Draft 2020-12. `$id` is `https://sortyard.ai/spec/<file>`; cross-file
  `$ref`s are relative to that base.
- Objects are closed (`unevaluatedProperties: false` / `additionalProperties: false`): a field
  not in the contract is refused. The only open shapes are noted below.
- Every workspace-scoped object carries `workspace_id` from day one (§3.1). Exceptions:
  Installation, Workspace itself, DeploymentConfig (installation-wide), and ResourceEnvelope
  (an embedded value object of ExecutionBinding).
- `x-sortyard-store` annotates the authoritative home of each object, following §5.1:
  `definition` (git, materialised into the DB as immutable content-hashed versions — carries
  `version`), `state` (DB), `config` (live-tunable admin config: Admin UI with audit), and
  `read-model` (recomputable, stores nothing authoritative). `x-sortyard-design-ref` names
  the draft section. Both are annotations; validators ignore them.
- Durations are integer seconds with a `_seconds` suffix; timestamps are RFC 3339
  `date-time`.
- Every schema carries at least one `examples` instance; the test validates each one.

## Object → file

| §3 object | File |
|---|---|
| Installation | installation.schema.json |
| Workspace / Organisation | workspace.schema.json |
| Project | project.schema.json |
| Archetype | archetype.schema.json |
| Repo | repo.schema.json |
| Task | task.schema.json |
| Milestone | milestone.schema.json |
| Decision | decision.schema.json |
| Chain / Run | chain.schema.json |
| StageRun | stage-run.schema.json |
| Escalation | escalation.schema.json |
| Sequence (recorded as SequenceChange) | sequence-change.schema.json; the `sequence` property on Task/Milestone, stage order in Workflow |
| SequencingPolicy | sequencing-policy.schema.json |
| Workflow (and its stages) | workflow.schema.json |
| Role / Persona | role.schema.json |
| Lane | lane.schema.json |
| Conductor configuration | conductor-config.schema.json |
| PrioritizationPolicy | prioritization-policy.schema.json |
| GroomingPass | grooming-pass.schema.json |
| Policy (all 11 kinds) | policy.schema.json |
| Agent / Worker | agent.schema.json |
| ContextRecipe | context-recipe.schema.json |
| ExecutionBinding | execution-binding.schema.json |
| ResourceEnvelope | resource-envelope.schema.json |
| Integrator | integrator.schema.json |
| CredentialCustody | credential-custody.schema.json |
| Mirror | mirror.schema.json |
| Extension (Skill / Integration / Sensor / packs) | extension.schema.json |
| Secret (reference only) | secret.schema.json |
| Eval | eval.schema.json |
| EvalRun | eval-run.schema.json |
| Scorecard Battery | scorecard-battery.schema.json |
| ThroughputWindow | throughput-window.schema.json |
| Event Ledger (one Event) | event.schema.json |
| DecisionLog (one entry) | decision-log.schema.json |
| Self-heal | self-heal.schema.json |
| Alert / Finding | alert.schema.json |
| Operator | operator.schema.json |
| RoleBinding | role-binding.schema.json |
| AuditLog (one entry) | audit-log.schema.json |
| DeploymentConfig | deployment-config.schema.json |

Not modelled as separate objects, on purpose: the Conductor itself (a service — its
configuration is the object, §3.4), Tuning (§3.9 calls it the live-editable *subset* of
Policy/Lane config — a view, not a store), Context Assembly and the Auth Broker (services;
their data is ContextRecipe/StageRun packet hashes and CredentialCustody respectively), the
Extension Registry (a location, carried as `registry` on Extension), and Observability export
(a projection of the Event Ledger, configured in DeploymentConfig `otel`).

## Ambiguities in the draft (recorded, not silently resolved)

1. **Draft version.** The task names draft v5 (`~/workspace/harness-reboot/HARNESS-REBOOT-DRAFT-v5.md`),
   which is not reachable from this run. The schemas were transcribed from §3 of the copy in
   meta-harness `projects/sortyard/DESIGN.md`, which is v6 = "v5 plus the tech-stack decision
   (§4a)". §3 should therefore be identical to v5, but that was not diffed.
2. **Project lifecycle.** §3.2 gives `discovery → active → maintain → archived`, then says the
   source's states are `discovery / active / maintain / project-definition` and that `archived`
   does not exist in `repos.yaml`. The enum carries the union
   (`discovery, project-definition, active, maintain, archived`); which ones survive is open.
3. **Repo role casing.** The draft writes "product / GTM / infra"; the enum is lowercase
   `product | gtm | infra`.
4. **Urgent: flag or tier?** §3.5 has both an `urgent_flag` prioritization key and a priority
   tier `urgent`. Task.priority carries both (`tier` and boolean `urgent`); whether the
   `urgent` tier implies the flag is not stated.
5. **Sequence as an object.** §3.3 lists "Sequence / Sequencing" but says it is "not a
   container object; a property of Tasks, Milestones, Workflows and Chains". The recorded
   object is the auditable **SequenceChange** (§3.3a); `sequence` is an integer property on
   Task and Milestone; workflow stage order is array order. Chains are not given a separate
   sequence field (their order is the pinned workflow's).
6. **Lane `scope` values.** §3.4 requires an explicit scope distinguishing conductor slots from
   dispatcher lanes but names no values; the enum is `conductor | dispatcher`.
7. **Where the stacked admission caps live.** §3.7b names three levels — lane caps, per-project
   heavy caps, and a cluster heavy cap with a reserved rush slot. Lane carries
   `max_concurrent_chains` and `heavy_job_cap`; the per-project and cluster caps plus the rush
   slot are placed in ConductorConfig `admission`. The draft does not say which object owns them.
   The cluster heavy cap value is deployment-specific (1 / 2 / 4) and has no frozen default.
8. **"Claim lease duration".** §3.4 lists it as conductor config while v3 says "lease"
   terminology was killed (for the credential pool). Kept as `claim_lease_duration_seconds`
   because §3.4 still uses the term; rename is open.
9. **Merge-gate fix rounds.** The post-k3s-harness-#199 fix-round count is marked
   **unverified** in §3.6/§10 (Phase 0 item 1 verifies it). `merge_gate.parameters.fix_rounds`
   exists with no default and no fixed value. Review counts per regime are frozen: conductor
   product PR = 1, design record = 2, mh design chain = 2 (separate sessions, correctness +
   usability).
10. **Policy kinds with unspecified parameters.** `retention`, `handback`, `stall` and
    `escalation` are named in §3.6 without parameters. Their parameter objects carry the
    values the draft states elsewhere (§3.3 revision cap 4, two repair attempts per defect,
    one attempt for "not dispatcher-side", 15-minute redeploy deadline; §3.8 24h self-heal
    re-alert) and are left **open** (extra properties allowed) until defined. All other kinds
    are closed.
11. **Grooming's frontier-only rule as a Policy.** §3.5 says it is "recorded as a Policy on the
    pass", but §3.6's kind list has no grooming kind. It is expressed as a `model_budget` policy
    with `stage_models.<stage>.require_frontier: true`, referenced by GroomingPass
    `frontier_policy_ref`. A dedicated kind may be preferable.
12. **Escalation stall classes.** §3.3 describes them in prose; the enum names are derived:
    `repeated_blocker_no_change`, `infrastructure_failed_twice`, `declared_checks_failed`,
    `illegal_dispatch`, plus the terminal conditions `revision_cap_reached`, `redeploy_failed`,
    `repaired_code_not_running`.
13. **Unbound reason codes.** §3.7b gives examples (`unbound: no approved design_ref`,
    `skill <x>@<v> not installed`, `mirror stale`, `credential pool empty`,
    `dependency <task> has no artifact`). ExecutionBinding freezes them as snake_case codes plus
    a `subject`, and adds codes for the other binding questions the draft lists
    (`dependency_not_done`, `parent_in_backlog`, `need_not_discharged`,
    `secret_ref_unresolvable`, `estate_precondition_missing`, `context_packet_failed`).
    DecisionLog `reason_codes` stay free-text strings because the draft's preview codes
    (`slot held: merging`, `throttled: heavy cap full`, …) are display strings.
14. **Integrator: component or record?** §3.7a describes a component and its fence. The
    schema freezes the component's configuration (fence, landing method, custody, where it
    runs); a per-landing record (proof receipt, both heads) is expected to be an Event, not a
    separate object.
15. **Eval `human` method vs no human gates.** §3.8 allows method `human`; §3.4 forbids a
    `human-gate` executor. Both are transcribed as written; a human eval is evidence, never a
    blocking stage.
16. **Chain, StageRun, Decision, Mirror, Alert, Self-heal, GroomingPass, Operator state
    machines.** Only Task and Project have state machines spelled out in the draft. The state
    enums on the other objects are minimal derivations from the prose and are the most likely
    fields to change.
17. **Archetype status.** "shipped" vs "candidate" is from the prose (§3.2), not a named field.
18. **RoleBinding scope.** §3.9 names the roles but no scope; `workspace | project` is assumed.

## API-defined request fields (`openapi.json`)

A request-body field that is not a §3 schema property is marked `x-sortyard-api-defined: true`
in `openapi.json` and explained here (held by `spec/test_openapi.py`).

- `agent_role` (`issueServiceAccountToken`): the §7 agent role (`conductor`, `build-worker`,
  `sensor`, `grooming-agent`) the issued service-account token carries. It is a property of the
  token, not of a §3 object: the RoleBinding's `role` names human roles only, and agent roles
  exist as service accounts (§7). Issuance refuses any token set that could both create and
  claim tasks.
- `stage_run_id` (`issueServiceAccountToken`): the StageRun a `build-worker` token is confined
  to, so a worker can claim only its own context packet and submit only its own stage result.
  It scopes the token; no §3 object carries it as a field of the same name on this request.
