# 11 — Coherence: how the pieces fit, and what to change in the existing design

Part A states the six things that make this one product: who owns each fact, where the
interface boundaries are, how identity works, what gets deployed, how it is extended, and how it
is observed. Part B lists what in DESIGN v6 and CORPUS contradicts that, is missing, or
over-reaches, with the change recommended and the evidence. Findings are numbered **CF-nn** and
referenced from the requirement files. Part C records what the owner's two directions of
2026-11-12 — a divergence must be demonstrably better, and plan for the best outcome — changed
in this specification.

---

# Part A — One coherent install

## A1. Data model and ownership

One rule: **Postgres owns every fact Sortyard is the authority for. Everything from outside is an
observation with a time. Everything computed is a projection that can be dropped and rebuilt.**

| Fact | Authority | Written by | Sortyard's copy is |
|---|---|---|---|
| Tasks, relations, order, notes, decisions, needs | Sortyard (Postgres) | Operators and agents through the API; the controller through domain commands | the record |
| Chains, stage attempts, bindings, verdicts, park and hand-back reasons | Sortyard | The controller; workers submit results through the API | the record |
| Definitions (policies, lanes, project config, workflows, packet templates, profiles, checklists) | Sortyard, as immutable versions | `apply`, UI, API, or the pull from a locked Git source | the record; files are a transport (DEF-002, DEF-003) |
| Ledger (events, decisions, audit) | Sortyard, append-only | Every domain command, in the same transaction as the change | the record |
| Identity: users, bindings, service accounts, token hashes | Sortyard | Admins | the record |
| Packets, logs, traces, receipts | Sortyard blob store, addressed by content hash | Controller, workers | the record, subject to retention |
| Code, branches, change requests, check runs, protection rules | The Git host | The integrator requests changes; the host decides | an observation with `observed_at` |
| Jobs and pods | Kubernetes | The controller requests; the cluster decides | an observation |
| Secret values | A Kubernetes Secret or an external store | The operator | a reference only |
| Subscription credential files | The agent CLI (it refreshes and writes back) | The CLI; one keeper | a custody record and a health state |
| Mirrors | Derived from the Git host | The mirror mechanism | a cache with a freshness fact |
| Queue census, Pickup Preview, metrics, dashboards | Computed | Nobody | a projection labelled with `as_of` |
| A mirrored external board (during migration) | The external tracker | Nobody in Sortyard | a read-only import; observe mode only |

Consequences that the requirements enforce:

- **One writer path.** Every change is a domain command that validates, changes state and appends its event in one transaction (API-002, OBS-001). The API and the controller call the same commands.
- **No bidirectional sync, anywhere.** Not with Plane (MIG-004 is read-only; OD-4), not with a definitions repository (a locked installation pulls one way, DEF-003), not with the Git host (observations only).
- **Concurrency is explicit.** Objects have revisions; stale writes are refused (API-004); chains have epochs; stale side effects are refused (REC-020).
- **History is free.** Any object's past is its events (OBS-002); metrics are folds over the ledger (OBS-003).

The physical model already in the repository (one table per object, a `doc` JSONB column with
generated columns, append-only streams) fits this. Three additions are needed: a `revision` on
every mutable row; a `schema_version` in every stored document so that migrations can transform
documents; and one sequence across events, decisions and audit entries so that a task's timeline
has a total order.

## A2. Boundaries between UI, API, MCP and CLI

```
  operator ── console (SPA) ─┐
  scripts ─── sortyardctl ───┼──► REST /v1 ──► authenticate → authorise → validate ─┐
  agents ──── MCP (/mcp) ────┘        ▲                                              ▼
  workers ─── stage token ────────────┘                                   domain commands
                                                                           (state machines,
  controller ──────────── in-process ────────────────────────────────────►  invariants,
  integrator ──────────── in-process ────────────────────────────────────►  ledger append)
                                                                                     ▼
                                                                                 Postgres
```

- **REST is the product's surface.** It exposes every command a person or agent may perform, one to one (API-001, API-006).
- **The console has no private path** (UI-001) and must cover every operator-facing operation (UI-002).
- **The CLI and MCP are thin** over REST (CLI-003, MCP-003) with a designed layer on top: task-level commands (CLI-002) and curated tools per role (MCP-002).
- **The controller and integrator do not use HTTP.** They share the domain layer. What only they may do — claim, advance, land — is not offered by the API at all (API-017). See CF-07.
- **Workers use two operations** and nothing else (MCP-005).

## A3. Identity and permissions

Three kinds of principal: **people** (local account, OIDC, or an authenticating proxy;
IAM-002), **service accounts** with scoped, expiring tokens (IAM-005, IAM-006), and **system
actors** (`system:controller`, `system:integrator`), which never authenticate over the API and
appear only as actors in the ledger. Stage tokens are minted per attempt and die with it
(IAM-007).

Authorisation is one default-deny function over a matrix declared in the OpenAPI document, with
object scope applied in the data layer (IAM-009), and tested cell by cell (IAM-010). The
security invariant is stated for what it protects against (IAM-008): nothing driven by a model
can make its own work run.

## A4. Deployment topology, upgrades, migrations

```
 namespace sortyard                               namespace sortyard-work (or the same)
 ┌───────────┐  ┌─────────────┐  ┌────────────┐   ┌──────────────────────────────┐
 │ api ×1..2 │  │ controller  │  │ integrator │   │ worker Jobs (one per stage)  │
 │ console   │  │ (1 leader)  │  │ (1 leader) │   │ sensor Jobs (scheduled)      │
 │ REST, MCP │  │ sched, adv, │  │ holds the  │   │ stage token + model cred     │
 │ no K8s,   │  │ mirrors,    │  │ Git write  │   │ no K8s token, no Git write   │
 │ no Git    │  │ health;     │  │ credential │   └──────────────────────────────┘
 │ creds     │  │ creates Jobs│  │ only       │
 └─────┬─────┘  └──────┬──────┘  └──────┬─────┘     Postgres (bundled or external)
       └───────────────┴────────────────┴────────►  blob store (PVC or S3)
```

Three workloads because there are three sets of privileges that should not share a pod: the API
faces users and holds no cluster or Git credentials; the controller can create Jobs and holds no
Git write credential; the integrator holds the Git write credential and can create nothing
(DEP-001, MRG-001, CRD-007). Workers hold neither.

No CRDs and no cluster-scoped objects are needed (DEP-002). Stateful dependencies are Postgres
and one blob location (DEP-003).

Upgrades are a chart version bump with no downtime as the target: a pre-upgrade migration Job
(DEP-007), expand-then-contract schema changes so that adjacent versions run side by side and
nothing pauses for skew (REC-015), a surge rollout of the API and leaders that hand over on
shutdown (DEP-010, REC-014), running Jobs that survive and are collected
afterwards (DEP-009), and a tested path from every earlier minor (DEP-008). The legacy system's
release guarantees — exact-commit builds, digest pinning, no cluster credential in CI, an older
release cannot replace a newer one, the running revision is visible — are kept by standard means
(QLT-023, QLT-024, DEP-020, API-014) instead of a bespoke release controller.

## A5. Extensibility

Three extension points, none of which loads foreign code into the control plane (EXT-001):

1. **Definitions** — workflows, packet templates, policies, checklists, profiles, applied as bundles from files or a pinned Git ref (DEF-002, EXT-005).
2. **Containers under a contract** — harness images (EXT-002) and sensors (EXT-004). Any language.
3. **HTTP** — REST, MCP, the event stream, signed webhooks (API-008, API-009), and adapter interfaces for Git hosts, CI and tracker import that live in-tree (EXT-003, CIH-013, EXT-006).

A new idea therefore has a home that needs nobody's permission (a bundle, an image, a webhook
consumer), and the core's attack surface does not grow with the ecosystem.

## A6. Observability

One ledger feeds everything (OBS-001): the task timeline, the decision log, audit, metrics,
dashboards, the daily record. Dashboards live in the console and need nothing beyond Postgres
(UI-015). System health has a registry of mechanisms with freshness windows, checked by something
independent of what it watches (REC-017), and a four-state health that never hides the unknown
(REC-019). For people who already run an observability stack there is a Prometheus endpoint and
optional OTLP export (OBS-010, OBS-012). Notifications go to a person only for what only that
person can do (OBS-013).

---

# Part B — Findings against DESIGN v6 and CORPUS

Each finding: what the record says, why it does not hold, the change. Severity: **structural**
(changes the plan), **scope** (changes what is built), **correction** (a fact or a gap).

Each finding ends with a **Divergence** line. Where the change alters what the estate's system
does today, the line names the entry in [18-divergences.md](18-divergences.md) that carries
the legacy baseline, the dimensions on which the change is better and its demonstration. Where
the change is to the plan only — DESIGN v6 or CORPUS proposed something the estate never ran —
the line says so.

## CF-01 — Two programmes are planned as one · structural

**Record.** CORPUS interleaves building the product with migrating the estate: Phase 1B (shadow
the legacy conductor), Phase 2 (read-only glass over shadow data), Phase 3B/4 (cutovers),
Phase 5 (migrate meta-harness), Phase 6 (make it public).

**Problem.** On that path the product is first usable on a fresh cluster in Phase 6. Phases 1B
and 2 produce increments that mean nothing outside the owner's estate. The Phase 1 goldfish
report was blocked for exactly this reason: no REST surface, no seed definitions, no demo
workflow.

**Change.** Two tracks. The **product track** (MS1–MS6, MS8) delivers increments a stranger can
install and use. The **migration track** (parts of MS0 and MS2, all of MS7) consumes product
releases. Shadow data stops being the console's subject.

**Divergence.** None. A change to the plan; no behaviour of the estate's system changes.

## CF-02 — The first end-to-end run is 35 items away · structural

**Record.** Real execution arrives in Phase 3A (11 large tasks) and the first real chain in
Phase 3B (SORTYARD-39).

**Problem.** Nothing verifies the whole loop until most of the system exists. The estate's own
doctrine demands a replica with fake providers.

**Change.** MS3 delivers a hermetic end-to-end chain: scripted harness (EXE-012), plain-git
adapter with Sortyard-run checks (MRG-011, EXE-017), on a kind cluster, as the quickstart demo
and as the test rig for everything after.

**Divergence.** None. A change to the order of the plan.

## CF-03 — The board is treated as commodity and its write side comes last · structural

**Record.** DESIGN §5.2: "the board is comparatively commodity UI". CORPUS Phase 2 ships a
read-only board; lanes, policies, secrets and admin screens are one task in Phase 5 (M5.6),
after every cutover.

**Problem.** The operator steers from the board every day (order, Backlog, priority, decisions).
Under CORPUS, the estate would run on Sortyard for the whole cutover period with tuning
available only by API. That contradicts "UI for everything" and "without losing any … tunability".

**Change.** The tracker is writable in MS1. Every capability ships with its screen in the same
milestone (UI-002 makes this mechanical). There is no late write-surfaces task.

**Divergence.** DIV-01. The board becomes native where the estate steers on Plane.

## CF-04 — The built-in workflows and review rules are stale · scope

**Record.** DESIGN §3.4 carries "today's real set": feature as Frame → Judge → Shape → Build →
Verify, plus incident, release, support, infrastructure change/drift/incident, job, design-first;
§3.6 defines three review regimes (one review; two reviewers on design records; dual review on
chains). The seed bundle has nine workflows and three `merge_gate` policies.

**Evidence.** The owner's "Delivery lanes" (2026-10-25) "wins over any project workflow, role,
contract, register, task contract or issue body that asks for more": one review per pull
request; defects take the short lane with "no frame, triage or shape stage". `drive.py`'s build
packet tells the worker that its rules "replace any process the task text asks for, such as
dispatch commands, frame/triage/shape stages, design records, custody or extra proofs". Since
then the gate became: code review + test-determinism review + design review for UI changes.

**Change.** Ship `change` and `job` (FLW-002, FLW-003) with the review policy that runs
(FLW-005 to FLW-009). Other workflows are definitions someone may add (FLW-017).

**Divergence.** DIV-30. Not a divergence: the shipped workflow is the one the conductor runs.

## CF-05 — Context recipes, skills and a six-kind extension registry over-reach · scope

**Record.** DESIGN §3.7: ContextRecipe (allowlists, token budgets, provenance drift), an
Extension Registry of skills, integrations, sensors, archetype/workflow/eval packs with an SDK,
a conformance kit and an RFC path for a new kind; the binding verifies exact skill versions.
CORPUS: M3.2, M3.3 (large), M5.2–M5.4, M5.7.

**Evidence.** What a worker receives today is a fixed packet template plus the task text,
findings, CI excerpts and a checklist, and the instruction to read the repository's own
`AGENTS.md`. No skill is injected by the conductor. The "36% dead material" problem that
recipes were meant to fix belonged to the retired dispatch path.

**Change.** Packet templates and checklists as versioned definitions (EXE-015); a binding made
of the checks that exist (EXE-001); extension through definitions, containers and HTTP
(EXT-001). No registry, SDK, archetypes, roles-as-objects or skill objects in 1.0. Skill files
keep reaching workers as they do today, through the worker image and the repository, and the
binding records both (EXE-001). This removes four large CORPUS tasks and most of Phase 5.

**Divergence.** DIV-23 for how new behaviour is added; DIV-29 and DIV-31 for the objects that are not built, which the estate never had.

## CF-06 — Two homes for definitions recreates the drift it is meant to end · scope

**Record.** DESIGN §5.1: git is the system of record for definitions, the database for state; a
sync controller materialises versions; the UI proposes changes as pull requests in git mode or
writes directly in DB-only mode, with one-way export; controller-down is a named absent state.

**Problem.** That is a second source of truth with a synchroniser, a degraded mode and two edit
paths — the pattern the design sets out to delete for tasks.

**Change.** The database is authoritative for definitions too. Files are a transport: `apply`
and `export` (DEF-002). An installation that wants git review locks definitions to a Git
source, and Sortyard pulls them from it one way, as the legacy conductor reads `repos.yaml`
on every pass (DEF-003). The standing default "definition edits via git PRs" becomes that
lock on the owner's installation (OD-5). The two-way synchroniser is still not built.

**Divergence.** DIV-09. Reshaped on 2026-11-12: a locked installation pulls from Git, as the legacy conductor does.

## CF-07 — "The conductor is a client of the API" · scope

**Record.** DESIGN §4: "if the conductor needs a private path, the API is incomplete". The spec
therefore has conductor-only operations (`claimTask`, `advanceTask`, `handBackTask`,
`instructIntegrator`) and a rule that no token may hold both create and claim.

**Problem.** (1) A claim must be atomic across several rows and an event; REST is the wrong tool.
(2) It couples the scheduler's availability to the API's: on 2026-11-12 every drive pass was
skipped for about 32 minutes because the API pod held an old bundle. (3) Those operations are attack
surface with no external user. (4) The create-and-claim rule is new, not kept: today the sync
files urgent triage items and the driver claims them with one key.

**Change.** One domain layer; the API exposes it for people and agents; the controller calls it
in-process; controller-only commands are not public (API-017); the security rule is restated as
IAM-008.

**Divergence.** DIV-10.

## CF-08 — One MCP tool and one CLI command per operation · scope

**Record.** The prototype clients generate 194 tools and 194 commands (`get-task`,
`create-task` with `--body JSON`).

**Problem.** It satisfies parity and nothing else. An operator-side agent facing 194 tools
performs worse than one facing 15 designed ones; the legacy MCP server deliberately exposes a
curated read-only set. A person will not type `sortyardctl update-task --body @file`.

**Change.** Curated tools per role plus three generic tools for full reach (MCP-002, MCP-003);
task-level CLI commands plus `api <operationId>` (CLI-002, CLI-003); MCP served over HTTP by the
API, not only stdio (MCP-001).

**Divergence.** DIV-16 for how agents operate the system. The prototype's one tool for each operation is plan-only.

## CF-09 — Sign-in assumes an identity provider · correction

**Record.** DESIGN §3.1: "auth provider (OIDC)"; CORPUS M2.1: "OIDC session handling".

**Problem.** A stranger's afternoon install has no identity provider; the estate itself uses a
proxy header that the console team found forgeable from inside the cluster.

**Change.** First-run bootstrap, local accounts, OIDC, and a proxy-header mode that refuses to
start unless the backend is locked down (IAM-001, IAM-002).

**Divergence.** DIV-16.

## CF-10 — Six services is three too many · scope

**Record.** DESIGN §4 and the repository: API, conductor, context assembler, eval runner, sensor
runner, integrator, each an entry point with a stub.

**Problem.** The context assembler is a function called at binding time. Eval and sensor runners
are schedules that launch Jobs — which the controller already does. Each extra workload is
another thing to roll, watch and grant; the estate's last stall came from adding one Kubernetes
object.

**Change.** Three workloads split by privilege (A4; DEP-001). Pipeline purity is kept by where
Jobs run and what they can reach, not by a separate long-lived deployment.

**Divergence.** DIV-19 for the estate's own moving parts; the three stub services are plan-only (DIV-31).

## CF-11 — Storage assumptions that do not travel · correction

**Record.** DESIGN §4 requires an S3-compatible object store and says workers clone from mirrors
"on a shared volume"; SY-DEC-001 says Postgres is the only database.

**Problem.** A required object store is a second stateful dependency (Plane needs MinIO; this is
a place to be lighter). A volume shared by the control plane and every Job needs
`ReadWriteMany` storage or a single node.

**Change.** A blob store with a volume backend by default and S3 optional (DEP-003); mirrors and
stage output over the cluster network (EXE-009).

**Divergence.** DIV-04 and DIV-11.

## CF-12 — SY-DEC-002 measures the old architecture · correction

**Record.** "One conductor loop, or two loops in one service?" — to be decided by replaying a
week of five-minute claim passes and 500 chain events through a merged loop.

**Problem.** The question exists because the legacy system polls in batch passes. A controller
that reconciles each item on events with a periodic resync has no pass to merge or split; what
matters is latency and isolation.

**Change.** Close SY-DEC-002 as superseded by requirements: a claim on the event when a slot
frees (SCH-006), hand-offs on events (FLW-019), per-item failure isolation (SCH-014), restart
recovery (REC-014). The instrument is
retired with the other prototypes (MIG-015).

**Divergence.** DIV-05.

## CF-13 — A live soak is the wrong truth instrument, and it gates the wrong thing · structural

**Record.** "Phase 1 exit is an operation": a one-to-two-week soak comparing shadow claims with
`drive.py`'s, required before the first cutover.

**Problems.** (1) It compares only claim order — four sort keys — while the hard-won behaviour is
in the step machine, which no shadow can observe. (2) The shadow's evaluator
(`shadow/evaluate.py`, 125 lines) is a throwaway replica of `drive.py`, not the product's
evaluator. (3) The baseline moves: the local checkout was 59 commits behind in days. (4) Weeks of
calendar time buy one sample.

**Change.** Record the legacy conductor's inputs now (MIG-002) and replay them through the real
evaluator offline, repeatedly, in CI (MIG-005). Prove the step machine with a parity suite
derived from the legacy behaviours and a chaos suite (REC-025). The soak that matters is the
pilot's hypercare (MIG-009).

**Divergence.** None. A change of instrument, and the one that makes the comparisons possible: replay and the parity suite are two of the demonstration methods.

## CF-14 — Estate-specific code is in the core · correction

**Record.** DESIGN §1.9: "no NonceLogic-specific assumptions in the core".

**Evidence.** `src/sortyard/shadow/` reads Plane, `products.json` and the `task_ready` gating
output; the chart ships a shadow-conductor Deployment with those values; the README carries
internal hosts and board links (goldfish GF1-04).

**Change.** A `migration/` tree outside the package, with gates that keep it out (MIG-006).

**Divergence.** None. Repository hygiene.

## CF-15 — The cutover plan names four projects; nine are driven · correction

**Record.** Pilot on HARNESS, then Rove, Loopmentum, Cortexplane.

**Evidence.** `repos.yaml` has driver blocks for CRANK, CPV2, HARNESS, NONCE, CLOSER, LOOP,
ROVE, SORTYARD and WALWARDEN; a DEVOPS board receives estate-red items and mechanism alarms.

**Change.** The pilot is SORTYARD itself: its own board and repository, greenfield, lowest blast
radius, and it makes "Sortyard builds Sortyard" true first. HARNESS is never migrated — its
remaining work is maintenance of the system being retired and it ends with it. Every other
driven project is in the order (OD-7).

**Divergence.** None. A change to the cutover plan.

## CF-16 — Plane as a projection after cutover · scope

**Record.** Standing default: "Plane read-only projection for one milestone"; CORPUS M3.12 builds
a one-way projection.

**Problem.** A projection is a sync to build, watch and explain, kept alive for a system the
operator has just stopped using. The estate's own rule for legacy paths is to shut them down,
not keep them as fallbacks.

**Change.** At cutover a Plane project is frozen with a link to Sortyard, and archived
read-only at the hypercare verdict. Rollback during hypercare replays what changed since the
cutover from a rollback export written by the cutover kit, and is rehearsed (MIG-009). No
outbound sync (OD-4, which stays open).

**Divergence.** DIV-32. Reshaped on 2026-11-12: a rehearsed rollback export replaces the snapshot-only rollback.

## CF-17 — "Done" on the board is not "in the product" · correction

**Evidence.** SORTYARD-9, 10, 11, 12, 14 and 15 are Done; their code is in meta-harness
`projects/sortyard/` (about 5,000 lines), not in `sortyard/sortyard`, which holds four pull
requests. `pytest spec` fails on `main` because the seed omitted `PERMISSIONS.md`. The
operational follow-ups are all Todo: capture the evidence snapshot (SORTYARD-70, 71), run the
soak (72), collect latency data (73), publish the image and install (75, 77), deploy the shadow
(79, 80).

**Change.** MS0 closes this out explicitly (MIG-015), starting with the one item that cannot
wait: the evidence snapshot (MIG-001).

**Divergence.** None. A correction of the record.

## CF-18 — The design's "one unverified fact" is answerable today · correction

**Record.** DESIGN §3.6, §10 Q8, CORPUS R1: post-#199 fix-round semantics are unverified because
"drive.py's source is in no local checkout"; SORTYARD-1 is still Todo; seed policies are marked
provisional.

**Evidence.** `control-plane/conductor/drive.py` on `origin/pilot-dispatcher`: `FIX_ROUNDS = 10`
is "a backstop only: fix_round parks once the same failure comes back"; `CONFLICT_ROUNDS = 5`;
`REVIEW_TRIPWIRE = 5`. The driver log describes the same.

**Change.** Close SORTYARD-1 against FLW-010 to FLW-012; drop the provisional markers.

**Divergence.** None. A correction of the record.

## CF-19 — The design predates a third of what must be preserved · correction

**Evidence.** These exist in the running system and appear nowhere in DESIGN v6 or CORPUS:
the preflight gate; filing verdicts and the filing sweep; blocking causes with automatic return;
the review tripwire; test-determinism and design reviews; the self-heal drain; the
no-silent-failure mechanism registry; the configuration failsafe; release verification with
automatic shield and revert; running-system delivery closure; inherited-red holds; estate-access
and zero-job classification; unrunnable queued jobs; marked vendor inputs; tolerance of API
rollouts.

**Change.** They are requirements here (RDY-005, TRK-013, REC-008, FLW-012, FLW-007, FLW-008,
REC-010, REC-017, RDY-013, DLV-003, DLV-001, CIH-007, CIH-003, EXE-011, REC-016). The legacy
system keeps changing; [16-legacy-parity.md](16-legacy-parity.md) is re-run against it before
each cutover (MIG-010).

**Divergence.** None. These are behaviours the estate has and Sortyard keeps; where one of them changes, its requirement is `FIX` and has its own entry (for example REC-008 in DIV-14).

## CF-20 — The frozen schema is a draft · correction

**Record.** 44 schemas "frozen" in Phase 0, with 18 schema ambiguities and 20 API ambiguities
recorded beside them.

**Problems for the tracker.** Task has no `kind`, `repo` or `acceptance` (the live ready rules
require all three); no notes; control state that today lives in labels has no typed home;
priority is both a tier and a flag; ids are client-assigned; there is no concurrency control;
three separate log stores have no common order.

**Change.** Treat `spec/` as version 0. Re-cut Task and its neighbours in MS1 (TRK-002 to
TRK-011, API-004, API-007, OBS-001). Schemas are versioned and migrated, and freeze with the API
at 1.0.

**Divergence.** DIV-02.

## CF-21 — "Never `--admin`" and the quarantine merge disagree · correction

**Evidence.** The driver log and the conductor README: "never `--admin`, never a direct merge".
JOB-QUARANTINE.md: with only quarantined jobs failing, "`merging` lands the approved head itself
(`gh pr merge --squash --admin --match-head-commit`), once per head".

**Change.** Make it an explicit policy (MRG-004). The estate bundle keeps it on, as today; new
installations get it off by default (OD-9).

**Divergence.** DIV-33. The legacy behaviour is kept for the estate.

## CF-22 — Project governance filed as product features · scope

**Record.** CORPUS M5.8 (Proposals as a task type, public roadmap as a projection of the board,
publish-back to a registry), M5.10 (a fork-PR verification lane built into Sortyard), M6.5.

**Problem.** These are how the upstream project runs itself, and standard tooling covers them:
the repository's issue tracker and discussions, provider-hosted CI for forks with no secrets, a
DCO check.

**Change.** QLT-013, QLT-040, QLT-042. Sortyard does not need to ship them as features to
launch.

**Divergence.** DIV-31. Plan-only.

## CF-23 — The experiment rig, the scorecard battery and the eval grid · scope

**Record.** DESIGN §3.8 makes Eval, EvalRun and the Scorecard Battery first-class; CORPUS M3.10
builds an eval runner deployment and M4.2 imports battery baselines.

**Evidence.** The battery is advisory and scored only on the legacy chain path; the console
moved the experiment views under "Lab"; the conductor's gates are reviews and required checks.

**Change.** Reviews and checks are the evaluation mechanism of 1.0, each with a declared
absent state (FLW-009). The rig stays outside the product as its own deployment, unless the
usage census shows it is not used (MIG-013).

**Divergence.** DIV-28 for the rig the estate runs, which is kept outside the product; DIV-31 for the eval-runner service, which is plan-only.

## CF-24 — Estate rules that must not leak into the public repository · correction

**Evidence.** The estate forbids provider-hosted CI runners for its own work; the Sortyard
repository's CI correctly uses them. The corpus proposes running dependency scans "never on
estate runners" in a custom lane.

**Change.** State it once so nobody "fixes" it: the public repository uses provider-hosted
runners with no secrets (QLT-013). Estate rules apply to the estate's installation as policy.

**Divergence.** None. A rule for the public repository.

## CF-25 — Credential custody in the design is out of date · correction

**Record.** DESIGN §3.7a: "the cluster deliberately holds no GitHub credential … Moving a
long-lived GitHub write credential into the cluster … requires Joe's explicit approval".

**Evidence.** Since the conductor moved in-cluster (2026-10-27) it reads a cluster Secret that
holds the owner's personal token — "the owner's token, by the owner's choice" — with an expiry
date (driver §5).

**Change.** The decision has in effect been made; make it explicit and better: a GitHub App with
minted, narrow tokens, mounted only in the integrator (CRD-007, OD-6).

**Divergence.** DIV-17.

---

# Part C — What the rules of 2026-11-12 changed

The owner gave two directions on the draft: a divergence from the system in hand must be
demonstrably better, and the plan should aim at the best outcome imaginable and accept a small
miss. The rules are QLT-050 and QLT-051; the register is
[18-divergences.md](18-divergences.md). This part lists what moved.

## C1. Origins now mean "relative to the estate"

The earlier draft tagged a requirement `FIX` when it closed a gap in DESIGN v6 or in the
prototype as well as when it changed what the estate does. Only the second is a divergence.
After re-tagging:

- **`FIX` means the estate does this differently.** Each such requirement carries a `Baseline:`
  line, a `Better on:` line and at least one `Demonstration` criterion with a target and a floor.
- **Moved to `FIX`,** because the estate does something else today: TRK-014, EXE-009, EXE-020,
  REC-008, REC-014, REC-015, IAM-002, UI-004, OBS-001, OBS-006, OBS-009, DEF-003, EXT-001,
  DEP-001, DEP-002, DEP-003.
- **Moved to `KEEP`,** because the estate already behaves this way and the gap was in the plan:
  API-007, API-017, QLT-012, MRG-004.
- **Moved to `NEW`,** because nothing in the estate occupies the place: DEP-007, DEP-012,
  MIG-006, MIG-015, QLT-002, UI-006, UI-008.

## C2. Divergences that could not show they were better

| What the draft did | What it does now | Reason |
|---|---|---|
| Cut the embedded concierge and approval mode | Requirements in MS6 (UI-026, IAM-012) | The feature is built and shipped; "use your own agent" is a different tool, not a measured gain |
| Locked definitions fed by `apply` from CI, in MS6 | A locked installation pulls from Git itself, in MS3 (DEF-003) | The legacy conductor reads its configuration from Git on every pass; the draft was slower and could fail unseen |
| Archived Plane at cutover; rolled back from the frozen snapshot | Frozen at cutover, archived at the verdict; rollback from an export of what changed (MIG-009) | A snapshot rollback loses the work done since the cutover |
| Switched off merging past a quarantined job everywhere | On in the estate bundle (MRG-004) | It would hold changes that merge today, with nothing measured in return |
| Left the experiment rig's fate to a later decision | Kept as its own deployment unless the census shows no use (MIG-013) | Archiving something in use is a loss |
| Dropped design-first chains, sentence-to-task intake, issue projection, attachments and other Plane features, and the improvement ledger on the inference that they are unused | Each cut is conditional on the usage census (MIG-017) | Use was inferred, not measured |

The cuts of things the estate never had — the extension registry and SDK, skill and recipe
objects, a separate eval-runner service, Proposals, the roadmap projection, the fork lane, a
two-way definitions sync — stand. They are changes to the plan, not to the estate's behaviour,
and each removes parts with no legacy behaviour behind it. The reasoning for each is in
[18-divergences.md](18-divergences.md) §5.

## C3. Designs changed to reach the targets

Where a target needed more than the draft built, the design changed; no target was lowered.

| Target | What the draft built | What changed |
|---|---|---|
| Upgrade with zero downtime | A skew guard that idled the controller until versions agreed; "under 60 seconds and harmless" with one replica | Adjacent versions run side by side (REC-015); a surge rollout of the API with event-stream resume, on the default storage too (DEP-010, now MUST); leaders hand over on shutdown (REC-014) |
| Stalls found and healed in minutes | The legacy thresholds: one flat 4-hour stall bound, causes polled every 30 minutes | Bounds from each phase's own history, a no-progress watchdog, an announced self-heal queue (REC-026); causes re-evaluated on the resolving event (REC-008) |
| The control plane adds almost nothing to a task's time | Event-driven slot reuse only | Every hand-off in a chain happens on its event, and the wait is measured for each chain (FLW-019) |
| Console interaction within 100 ms | Budgets inherited from the legacy console | A local store fed by the event stream, with optimistic updates (UI-018) |
| Install in one command and minutes | "At most 8 commands" and 15 minutes | One command that installs and prints the address and setup token; the old figures became the floor (DEP-005) |
| Every merge running within 10 minutes | Releases from tags only | A development build for every merge to `main` (QLT-024) |
| Zero operator actions | Not measured | `operator.interventions`, `stall.episodes`, `chain.control_wait` and `upgrade.impact` in the metric catalogue (OBS-004), with a scorecard (QLT-051) |

## C4. What the plan gained

- **A baseline-capture work package in MS0** (WP0.4: MIG-016, MIG-017). Without captured legacy
  figures no comparison can be made later, and the legacy system changes weekly.
- **Comparisons in every milestone exit.** Each exit lists the demonstrations due, generated
  from the criteria, and MS5's 72-hour run and MS7's verdicts are judged against the legacy
  stall, recovery, intervention, throughput and cost figures.
- **Two levels in every measured exit,** and a planner rule (rule 12) for filing the gap to
  target as backlog.
- **A validator that enforces all of it** ([tools/gen.py](tools/gen.py)).
