# 01 — Product definition

## 1. What Sortyard is

Sortyard is a self-hosted control system that takes software tasks from a board to merged
changes using coding agents on your own Kubernetes cluster, and shows you exactly what is
happening and why.

One install gives you a task tracker that agents can file into, a deterministic scheduler that
decides what runs next and can always explain itself, bounded execution of agent stages as
Kubernetes Jobs, review and merge handling that never bypasses your repository's own gates,
unattended recovery when things go wrong, and one console over all of it. Everything the console
can do is available through a REST API, an MCP server and a CLI.

It replaces, for its owner, a patchwork: a self-hosted Plane board, a Python conductor and
dispatcher, a sync job that projects one onto the other, a markdown control plane, and a set of
metrics scripts, dashboards, watches, crons and runbooks.

## 2. Who it is for

| User | What they need from it | How they reach it |
|---|---|---|
| **The operator** — the person steering delivery (today: the owner) | Set order and priority; defer work; answer the few decisions only they can make; tune capacity; see what is running, what is stuck and why; act (requeue, cancel) without `kubectl`; trust that it runs unattended | Console; notifications only for what needs them |
| **Agents** | *Workers* (inside a stage): receive a packet, return a result — nothing else. *Intake and grooming agents*: file and shape tasks, and know at once whether pickup can see them. *Operator-side agents* (monitoring, self-heal, a developer's own assistant): query state, ask "why", run jobs, resolve hand-backs. *Sensors*: file findings and heartbeats | MCP and REST with scoped tokens; CLI |
| **Outside self-hosters** — a team that wants this for its own repositories | Install in minutes on a cluster they already have; connect a repository and a model credential; watch a first task become a merged change; upgrade without fear; extend without forking | Helm chart, docs, the same console/API/CLI |

The operator and the agents exist today and their needs are evidenced in the estate's records.
The outside self-hoster is the reason the product must stand on its own: every milestone is
judged on a fresh cluster with nothing from the owner's estate.

## 3. The problems it solves

Each is a recorded failure of the current estate (DESIGN §0, task-pickup, the driver log).

1. **State in five places that drift.** The board, the conductor's `state.json`, the dispatcher's database, the Git host and an operator's memory disagree. A Todo item with a live conductor record was skipped every pass and nothing showed it (HARNESS-256). → One store; everything else is an observation with a time, or a labelled projection.
2. **Scheduling you have to investigate.** "Why wasn't X picked up?" took a hand derivation from board comments (task-pickup §8). → The scheduler's reasoning is a query and a screen.
3. **Rules in prose, constants in code.** Lane caps lived in three files with three values; changing one needed a commit and a manual release (HARNESS-246). → Every threshold is live, audited configuration.
4. **Filings that nothing can see.** Tasks were filed and never became eligible because a label or a registration was missing (HARNESS-608, the 2026-11-09 Sortyard stall). → A filing returns a verdict; an invisible filing is a failed filing.
5. **Stalls that hold capacity.** A merge that never fired held two lanes for nine hours; a missing base burned ten builds. → Every wait has a bound and an exit; every stall class has a recovery.
6. **Silence.** A release stalled for 32 minutes because a role lacked one name, and the only sign was a log line. → Every recurring mechanism has a freshness window; going quiet raises an owned item.
7. **No install story.** Standing this up elsewhere means six repositories, a jump box, a private network and tribal knowledge. → One chart, one image, Postgres.
8. **Two tools, no connection.** The board knows tickets; the dashboard knows runs. → A task's page *is* its pipeline.

## 4. Principles kept

From the owner's intended-use statement and the design record, unchanged:

- **Advance only on observed state, never on a self-report.**
- **No unbound agents.** A stage runs only through a recorded binding and inside a resource envelope.
- **One source of truth per object.** Everything else is a projection and says so.
- **The scheduler is a state machine**, derivable from recorded state.
- **The pipeline depends on nothing live.** Fakes in the pipeline; live checks outside it.
- **The owner is never a step inside delivery.**
- **Nothing fails silently.**
- **Boring technology.** Python, Postgres, Kubernetes Jobs, a React single-page app.

One principle is added by this specification:

- **Every milestone is a product someone outside could use.** If an increment only makes sense inside the owner's estate, it belongs to the migration track, not to the product plan.

## 5. Absorbed, replaced, dropped

"Absorbed" means the behaviour is a requirement here. "Replaced" means the need is met in a
different way. "Dropped" means it is not in 1.0, with the reason. Nothing in the estate is left
unmentioned; behaviour-level detail is in [16-legacy-parity.md](16-legacy-parity.md).

### 5.1 Plane (commercial edition v3.3.3, used as the task board)

| Plane feature | Disposition | Reason / where |
|---|---|---|
| Work items with title, description, state, priority | **Absorbed** | TRK-002, TRK-004, TRK-008 |
| Sub-items (parent/child) | **Absorbed** | TRK-005 — load-bearing: a Backlog parent holds its children |
| "Blocked by" relations | **Absorbed** | TRK-006 — the dependency graph the scheduler reads |
| Manual ordering on the board | **Absorbed and fixed** | TRK-007 — Plane's API cannot write the order; Sortyard's can |
| Labels | **Absorbed for people; replaced for control** | TRK-009 — control labels become typed fields |
| Comments | **Absorbed** as notes on one timeline | TRK-010 |
| Due date | **Absorbed** for decisions (`decide_by`) | TRK-011 |
| Project identifiers and sequence ids | **Absorbed** | TRK-001 |
| Board and list views, filters | **Absorbed** | TRK-014 |
| Saved views | **Absorbed, later** | TRK-015 |
| Modules (used for a "Health" grouping) | **Replaced** | System items are a kind with their own views (TRK-003, TRK-014) |
| States Backlog / Todo / In Progress / In Review / Done / Cancelled | **Absorbed** | TRK-004 |
| Cycles (time-boxed iterations) | **Dropped** | The owner removed time-boxed planning from the design (DESIGN §0.1); order is sequencing, not calendar |
| Pages / wiki | **Dropped** | Docs live in repositories; not a delivery concern |
| Estimates, time tracking | **Dropped** | Not used by the estate; cost is measured from stage usage (OBS-006) |
| Intake as a separate module | **Replaced** | Filing with a verdict (TRK-012, TRK-013) |
| Public "deploy boards" | **Dropped** | No use in the estate; a public roadmap is project governance (QLT-042) |
| Plane AI and assignable agents | **Dropped, by principle** | An agent assigned to a ticket is unbound (DESIGN §3.7b) |
| Importers, Slack/GitHub integrations | **Dropped** | Sortyard talks to the Git host directly; notifications by webhook (OBS-013) |
| Multi-workspace, guests, teams | **Dropped for 1.0** | One workspace (API-018) |
| Custom properties and work-item types | **Replaced** | A closed set of task kinds with typed fields (TRK-003) |
| Notifications inbox | **Replaced** | The owner list and attention list (UI-007, OBS-014) |
| Attachments | **Dropped for 1.0** | TRK-019 |
| Plane as a place Sortyard writes to after cutover | **Dropped** | Recommended: archive and link, no outbound projection (OD-4) |

### 5.2 The dashboards and the existing console

| Item | Disposition | Reason / where |
|---|---|---|
| Harness console (Overview, Requests, Chains, Delivery, Runs, Credentials, Settings) | **Absorbed** — its code is the starting point of the console | [08-console.md](08-console.md) |
| Factory dashboard read model (bounded projections, `as_of`, coverage, redaction) | **Absorbed** | API-011, API-012, OBS-003, OBS-004 |
| Journeys J1–J5 and J8, accessibility and keyboard specs, bundle budget | **Absorbed** | UI-009 to UI-021 |
| Trace viewer | **Absorbed** | UI-011, EXE-019 |
| Credential sign-in flows | **Absorbed** | CRD-005, UI-012 |
| Needs-attention insights | **Absorbed** | OBS-014 |
| Read-only MCP server over harness state | **Absorbed and widened** | MCP-002 |
| Concierge (embedded chat agent with approval cards) | **Dropped for 1.0** | The operator's own agent reaches the same data through MCP; avoids embedding model spend and a prompt-injection surface in the control plane (UI-026, OD-3) |
| Eval grid, Compare, "Lab" views of the experiment rig | **Dropped** | The rig is not part of the product (MIG-013) |
| Dashboards in an external observability stack | **Replaced** | Dashboards are in the console; OTLP and Prometheus export are optional (OBS-010, OBS-012) |

### 5.3 The conductor (`drive.py` and its modules)

| Behaviour | Disposition | Where |
|---|---|---|
| Pickup eligibility and order, lanes, the rush lane | **Absorbed** | SCH-001 to SCH-005 |
| The item state machine (build, land, review, fix, merge, confirm) | **Absorbed** | FLW-002, FLW-004 |
| Code review, test-determinism review, design review | **Absorbed** | FLW-005 to FLW-009 |
| Fix rounds, conflict rounds, review tripwire | **Absorbed** | FLW-010 to FLW-012 |
| Auto-merge on the exact head; no direct merge | **Absorbed** | MRG-003 |
| Admin-merge past a quarantined job | **Absorbed as an off-by-default policy** | MRG-004, OD-9 |
| Red-main triage, causal proof, confirming, lock-in | **Absorbed** | CIH-001 to CIH-006 |
| Infra retries, parking, hand-back, blocking causes, self-heal drain | **Absorbed** | REC-002 to REC-010 |
| Ad-hoc jobs | **Absorbed** | FLW-003 |
| Outside-PR adoption, landing sweep, stranded builds | **Absorbed** | FLW-014 to FLW-016 |
| Grooming process step | **Absorbed** | GRM-001 to GRM-006 |
| Release verification with shield, revert, re-groom | **Absorbed as an optional integration** | DLV-003 |
| Running-system delivery (Done means deployed and run) | **Absorbed** | DLV-001, DLV-002 |
| Three-minute polling passes; one exception aborts a pass | **Replaced** | Per-item reconciliation with latency bounds (SCH-006, SCH-014) |
| `state.json`, `grooming.json` and other files on a volume | **Replaced** | The database and the ledger |
| Text marks in descriptions and comments (`Triage:`, `Select:`, `Blocking-cause:` …) | **Replaced** | Typed fields (TRK-010) |

### 5.4 plane-sync

| Behaviour | Disposition | Where |
|---|---|---|
| Release ready tasks once; parent close; decision defaults; needs routing | **Absorbed** | RDY-003, RDY-004, RDY-007, RDY-015, TRK-005 |
| Preflight and the filing sweep | **Absorbed** | RDY-005, RDY-006, TRK-013 |
| Red-main sensing and classification (infra, estate, zero jobs, unrunnable) | **Absorbed** | CIH-001 to CIH-004 |
| Delivery-cost item | **Absorbed** as a metric | OBS-006 |
| Projecting pull requests and issues onto the board as items | **Replaced** | A change request is part of its task's timeline; outside ones become `review` tasks (FLW-014) |
| Health summary item | **Replaced** | Overview and dashboards |
| Drift consolidation between plan, board, STATUS.md and registers | **Dropped** | Those copies cease to exist; an internal consistency sweep remains (GRM-007) |
| The sync itself | **Dropped** | There is nothing to sync |

### 5.5 The dispatcher and control plane (`mh.py`, `auth.py`, `ship.py`, …)

| Behaviour | Disposition | Where |
|---|---|---|
| Stage Jobs with envelopes, deadlines, isolated workdirs | **Absorbed** | EXE-002 to EXE-004 |
| Admission caps with a reserved rush slot | **Absorbed** | SCH-007 |
| Result protocol and validation | **Absorbed** | EXE-006, EXE-007 |
| Mirrors, freshness, seeding | **Absorbed**, transport made portable | EXE-008, EXE-009 |
| Subscription pool, probes, broker, sync, keeper | **Absorbed** | CRD-003 to CRD-006 |
| Model fallback and task-level selection | **Absorbed** | EXE-013, CRD-009 |
| CLI soak window | **Absorbed** | EXE-014 |
| The fenced shipping integrator | **Absorbed** | MRG-001, MRG-011 |
| Work-volume retention under pressure | **Absorbed** | REC-022 |
| Design chains (design → dual review → approval → build → verify) | **Dropped as built-in** | The conductor path does not use them; the engine can express them (FLW-017) |
| Chain self-repair that edits and redeploys the control plane | **Dropped** | A control plane that rewrites itself is not something to ship to strangers; Sortyard changes go through Sortyard and a release |
| Scorecard battery | **Dropped** | Experiment-era instrument, advisory only (MIG-013) |
| Request decomposition ("new request": sentence → tasks), landing | **Replaced** | Intake agents file through the API (TRK-012) |
| SQLite store, JSONL ledgers | **Replaced** | Postgres |
| Bespoke pull-based release controller, bundle size cap, `deploy.sh` | **Replaced** | Helm chart, signed images, the operator's GitOps tool; guarantees kept (QLT-023, QLT-024, DEP-020, REC-015) |

### 5.6 meta-harness (the markdown control plane)

| Content | Disposition | Where |
|---|---|---|
| `repos.yaml` driver blocks | **Absorbed** as project configuration | DEF-009 |
| Ready rules, sizing rules, preflight list | **Absorbed** | RDY-001 to RDY-006 |
| "Delivery lanes" doctrine | **Absorbed** as the shipped workflow and review policy | FLW-002, FLW-005 |
| Testing model | **Absorbed** as Sortyard's own test standard | QLT-010 |
| Review checklists (test determinism, design review) | **Absorbed** as checklist definitions | FLW-007, FLW-008 |
| Premise policy (intended use, reference clones, access citations) | **Absorbed** as an optional policy pack | RDY-009 |
| Self-heal contract | **Absorbed** | REC-009 |
| Template workflows (Frame → Judge → Shape → Build → Verify, incident, release, support), template roles, 26 template skills, archetypes | **Dropped from the product** | The live doctrine overrides them ("This section wins over any project workflow, role, contract …", AGENTS.md); they remain the estate's own definitions if it wants them |
| `dispatch`, `validate`, `drift`, `emit` scripts | **Dropped** | Context is a packet template plus the repository's own agent guide (EXE-015) |
| Task registers, STATUS.md | **Dropped** | Already history since 2026-11-08 |
| Operating runbooks | **Replaced** | The operations guide in the docs, written around reason codes (QLT-001) |

### 5.7 Metrics scripts, watches, crons

| Item | Disposition | Where |
|---|---|---|
| Throughput and delivery-cost analysis scripts | **Absorbed** as the metric catalogue | OBS-004 to OBS-007 |
| Stall watches, stillness watch, queue-stall watch | **Replaced** by self-recovery and conditions | REC-001, REC-010, REC-023 |
| Mechanism registry and health check | **Absorbed** | REC-017 to REC-019 |
| Daily pipeline record | **Absorbed** | OBS-009 |
| Host crons for mirror refresh and credential sync | **Replaced** by in-product mechanisms | EXE-008, CRD-006 |
| Estate watches beyond the pipeline (runners, certificates, backups) | **Out of the product; kept watched** through external heartbeats | REC-018, MIG-012 |
| Slack cards and throughput reports written by an agent | **Replaced** | Notifications (OBS-013) and the daily record |

## 6. Non-goals for 1.0

1. **Being a general project-management tool.** No cycles, wikis, estimates, time tracking, guests or custom fields.
2. **Replacing your CI or your deployment tooling.** Sortyard reads CI and observes deployments; product repositories keep their own pipelines.
3. **Replacing your secrets store.** Sortyard holds references.
4. **Multi-tenant hosting.** One workspace per installation.
5. **A plugin marketplace, registry or SDK.** Extension is by definitions, containers and HTTP (EXT-001).
6. **Running anywhere but Kubernetes.** No Docker Compose install (OD-8).
7. **Git hosts other than GitHub and plain Git.** The adapter interface is there for others.
8. **An embedded assistant.** Bring your own agent over MCP.
9. **Machine-graded quality scores.** Reviews give verdicts on stated criteria; nothing scores taste.
10. **Importing history.** Open work is imported at cutover; the past stays in the frozen snapshot.
11. **Internationalisation.** English, with strings externalised.
12. **High availability beyond a restartable single leader.** Two API replicas and leader hand-over are supported; multi-region is not.
