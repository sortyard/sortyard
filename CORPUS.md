# Sortyard — Milestone Corpus (planning record)

> Historical architecture/planning record. The governing scope is
> [SY-DEC-005](DECISIONS.md#sy-dec-005) (2026-11-23 amendment): the workflow kernel plus the
> tracker view, Postgres only. The [ecosystem requirements baseline](docs/requirements/README.md)
> is reference. Read this record for provenance; it does not override either or current Plane
> execution state.

- **Source:** frontier-model design pass, 2026-11-07 — devised against the Sortyard design draft v6 (DESIGN.md in this folder) and the filed Phase 0 / Phase 1 items. Working copy: ~/workspace/harness-reboot/MILESTONE-CORPUS-FRONTIER.md.
- **Status:** planning record — filings reconcile to this; later phases are groomed here and filed in milestone tranches, not dumped.
- **Filed so far:** Phase 0 (HARNESS-286..289) and Phase 1 (HARNESS-310..315 plus the reconciliation additions HARNESS-316..321, filed 2026-11-07). Everything from Phase 2 onward lives in this document until its tranche is released (rule R2 in §4 of the corpus below).
- **Map:** MILESTONES.md in this folder is the phase-level view of this corpus.

---

# Sortyard Milestone Corpus — Frontier Design

**Purpose:** answer Joe's question — "do we have a corpus of groomed tasks by milestone?" — with a corpus that is more than §8's phase sketches transcribed into titles. This document tests the phase structure, breaks every phase after Phase 0 into lane-buildable tasks in real dependency order, judges Juno's Phase 1 six, and names the risks the corpus has to respect.

**Status:** design document for Joe's reaction. Nothing here is filed. Juno reconciles and files from it.

**Size signals:** S = one focused change / one PR-sized unit. M = several coordinated changes, still one coherent task. L = a multi-part task that is legitimate as a milestone task only because its parts share one outcome; if a worker cannot describe its internal order in one pass, split it before filing. Sizes are relative work signals, not calendar estimates — on a single HARNESS lane, elapsed time is dominated by review, merge, deploy and soak windows, not by these signals.

---

## 1. Verdict on the phase structure itself

**The §8 spine is right; the phase boundaries are not.** Keep the strangler shape, shadow-before-authority, milestone-boundary cutovers, and one-project-at-a-time. Those follow directly from the design's own principles: advance only on observed state (§1.1), pipeline purity (§1.4), bound execution (§1.11), and the never-empty-queue rule (§3.5). But four structural corrections are needed before this becomes a corpus:

1. **Phase 1 is two milestones wearing one coat.** "Core skeleton" bundles platform foundations (repo, schema, ledger, API) with the shadow-conductor truth experiment. The foundations are ordinary build work; the shadow comparison is an *evidence* milestone whose exit is a verdict, not a feature. Split into **Phase 1A (Foundation)** and **Phase 1B (Shadow truth)** under one Phase 1 exit, so the queue can show which kind of work is actually blocking.

2. **Phase 3 as written is dangerously underspecified.** §8 gives it one paragraph — "smallest project cutover" — but real claiming requires the entire execution core the paragraph never lists: definitions sync, context assembly, the binding resolver, mirrors, the worker launcher / chain advancer, credential custody, the fenced integrator, the eval runner, self-heal. A cutover task filed against §8's paragraph would hand back or improvise. Split Phase 3 into **Phase 3A (Bound execution core)** and **Phase 3B (HARNESS authority cutover)**. 3A is the largest build in the programme; pretending it is part of a "cutover" hides that.

3. **Phase 4 must not be one milestone.** It contains a repeatable cutover kit, three product cutovers, evidence/baseline migration, sensor/cron retirement, dispatcher absorption, two legacy retirements, and the experiment-rig split. Split into **Phase 4A (Cutover factory + parity machinery)**, **Phase 4B (one milestone gate per product — Rove, then Loopmentum, then Cortexplane)**, and **Phase 4C (Legacy retirement)**. Each product cutover is its own boundary with its own rollback snapshot; a shared "Phase 4 done" state would blur exactly the per-project authority question the phase exists to answer.

4. **Three things §8 leaves to Phase 5/6 must be pulled forward, or they will arrive too late to shape anything:**
   - The **contributor ContextRecipe and one-command local replica** (§11) belong in Phase 1A. They are not launch polish; they are how every later task — including ones built by other people's agents — gets executed. §11 itself says the goldfish install is a release gate, not documentation.
   - The **extension registry core** belongs in Phase 3A, because the Execution Binding must resolve exact skill/workflow/eval-pack versions. A registry that appears in Phase 5 cannot be retrofitted under the binding without reopening it.
   - The **fork-PR verification lane** (§11) belongs in Phase 5, *before* the Phase 6 launch invites strangers' code. Building it in Phase 6 means the invitation and the safety mechanism race each other.

   Conversely, **Phase 5's full definitions migration stays late** — but its *seed* (a loader plus the default definitions the new system needs to run at all) belongs in Phase 1A. Phase 5 is then honestly renamed: not "definitions into git-mode" from nothing, but the conformance pass and completion of a migration whose foundation was laid in Phase 1.

5. **Phase 2 is correctly placed but must stay narrow.** Read-only glass over shadow data is the right second phase — Joe steering from the new surface while the old system runs the trains is the strangler pattern working as intended. The trap is scope: §6 lists thirteen views. Phase 2 is five of them (Board, task-detail-is-its-chain, Pickup Preview, DecisionLog, Eval grid/dashboards) plus a console shell. Policies/Lanes/Extensions/Secrets/Admin *write* surfaces belong with the phases whose machinery they operate (3A and 5), not in a read-only phase.

6. **Phase 6 splits into a release-candidate milestone and a launch action.** "OSS readiness" mixes buildable work (docs, examples, upgrade suite, security pass) with decisions only Joe can make (licence confirmation, trademark) and an operational act (publish). Keep them visibly separate, or the buildable work will appear blocked by decisions it does not depend on — the exact invisibility defect HARNESS-238 exists to fix.

**Net structure:** Phase 0 (filed) → 1A Foundation → 1B Shadow truth → 2 Read-only glass → 3A Bound execution core → 3B HARNESS cutover → 4A Cutover factory → 4B Product cutovers (×3, separately gated) → 4C Legacy retirement → 5 Definitions conformance + extension platform → 6A Release candidate → 6B Launch.

---

## 2. The corpus by milestone

### Phase 1A — Foundation (repo, data, contract)

**M1.1 — Repository and local-replica foundation.**
The `sortyard` repo becomes buildable by a zero-context agent: Python package layout with the six services as entry points (per §4a), locked dependencies, strict typing/lint/test configuration, container images, an `AGENTS.md` contributor brief with an architecture map, and a one-command local replica (Compose or kind) that boots Postgres and a stub API in the deployment's shape. This is §11's contributor ContextRecipe in its first, load-bearing form — every later task in every phase assumes it exists.
*Depends on:* Phase 0 complete (HARNESS-287 schemas, HARNESS-288 OpenAPI, HARNESS-289 repo). *Size:* M.

**M1.2 — Definitions loader and seed corpus.**
Default definitions — the built-in workflows, lane shapes, policy set, archetype skeletons and context recipes the system needs to run at all — are bundled as versioned definition files, validated against the Phase 0 schemas, and materialised into the database as immutable, content-hashed versions by a loader that also implements §5.1's controller-down behaviour (`definitions: stale`, keep running on last materialised versions, refuse new edits). Phase 5 migrates the *full* corpus; this task lays the mechanism and the seed it cannot start without.
*Depends on:* M1.1, HARNESS-287. *Size:* M.

**M1.3 — Postgres schema and schema-generated models.**
The §3 domain objects become the Postgres schema — tasks, milestones, decisions, chains/stage runs, lanes, policies, extensions, mirrors, secrets-as-references, operators/role bindings — with migrations run as Jobs, and the Python data models generated from the Phase 0 JSON Schemas with a drift check that fails the build if generated code and schema disagree. This is the §4a "schema is the contract" decision made mechanical; hand-written parallel DTOs are explicitly out.
*Depends on:* M1.1, HARNESS-287 (M1.2 may land in parallel; the schema must not wait for the seed content). *Size:* L.

**M1.4 — Event ledger and DecisionLog kernel.**
An append-only event store on Postgres: every object transition records `{ts, actor, object, transition, facts, refs}`; conductor decisions additionally record their inputs (policy versions, queue-snapshot hash, reason codes) as the DecisionLog stream. The kernel provides idempotent append, per-object history queries, snapshot hashing for later comparison work, and the OpenTelemetry export seam (§3.8) as a projection, not a second record.
*Depends on:* M1.3. *Size:* M.

**M1.5 — Identity, service accounts, and the permission matrix.**
Operators (OIDC) and scoped service accounts exist as first-class objects, and §7's permission matrix is enforced in code, including its sharpest rule: token issuance *refuses* any scope set that both creates tasks and claims them. Build-worker, sensor, grooming, conductor and operator scopes are distinct credentials from the start, and every mutation writes an audit record — retrofitting identity under a working conductor is the kind of change this phase exists to avoid.
*Depends on:* M1.3, M1.4. *Size:* M.

**M1.6 — Helm chart: minimal real install.**
One chart installs the all-in-one profile (API + conductor entry points, Postgres, optional object store) on a fresh cluster, with `values.yaml` mapped to the DeploymentConfig object, migrations as Jobs, GitOps-compatible rendering — and the control-plane protection §3.7b admits the current system lacks: PriorityClass and reserved requests for the control plane, a LimitRange bounding worker Jobs. The chart scopes itself to the harness cluster; everything outside it stays an integration (§4).
*Depends on:* M1.1, M1.3 (an API stub is enough to prove the chart; the chart must not wait for the full API). *Size:* M.

**M1.7 — Core state API: the first vertical slice.**
The API service implements the core objects end-to-end — Project, Task (with its §3.3 state machine, including `blocked` and `handed_back` as reason-carrying transitions), Milestone/Sequence, Decision (default + `decide_by` resolution), Lane and Policy reads — through the one door §4 demands: the conductor, the console and agents all use this API, and no component gets a private path. The OpenAPI document is generated from the implementation and checked against HARNESS-288's spec.
*Depends on:* M1.4, M1.5, HARNESS-288. *Size:* L.

**M1.8 — MCP server and CLI parity for the core slice.**
The core slice is reachable the way agents and scripts will actually reach it: an MCP server exposing the §7 tool set for the implemented objects, and `harnessctl` as a thin client in which every command is an API call. Both run under M1.5's scoped accounts, so the permission matrix is exercised by real callers in Phase 1 rather than discovered by the console in Phase 2.
*Depends on:* M1.7. *Size:* M.

**M1.15 — Legacy evidence preservation snapshot.** *(numbered out of order deliberately: it is a Phase 1 obligation discovered late in this design pass, and keeping its number honest is cheaper than renumbering the milestone)*
Before any legacy component is modified or retired, the current system's evidence is frozen read-only with hashes: the control-plane ledger (`index.jsonl`), the scorecard battery's corpus and baselines, and a Plane board snapshot. §3.8 is blunt that a lone delivery is unscored without a comparable baseline corpus; Phase 4's importer can only import what still exists. This snapshot is the insurance policy for every later phase.
*Depends on:* M1.4. *Size:* S.

### Phase 1B — Shadow truth (the conductor, observed before it is trusted)

**M1.9 — Legacy input adapters (read-only).**
The three real input paths — `task_ready` gating output, `plane_sync`'s register view, and drive.py's board view — are replicated as read-only adapters that produce canonical, timestamped queue snapshots in Sortyard's model. Adapters never write to Plane, the registers, or the board; NonceLogic's legacy surfaces are migration inputs, isolated here so they never leak into the core domain as assumptions (§1.9).
*Depends on:* M1.3, M1.4 (snapshots persist through the ledger kernel). *Size:* L.

**M1.10 — Eligibility, sequencing and binding evaluator (shadow form).**
Given a queue snapshot, the evaluator computes — without claiming anything — each task's eligibility, its position under the lexicographic PrioritizationPolicy and the five sequencing orders of §3.3a, and the completeness of its would-be Execution Binding, emitting §3.7b's specific reason codes (`unbound: mirror stale`, `held: dependency X not done`, `slot held: merging`, …). This is the derivability principle (§1.2) as a component: the Pickup Preview in Phase 2 and the real conductor in Phase 3 are both clients of this evaluator, not reimplementations of it.
*Depends on:* M1.2, M1.7, M1.9. *Size:* L.

**M1.11 — Shadow conductor claim loop.**
A leader-elected loop runs the evaluator on the live cadence, applies lane caps and slot-occupancy rules against the shadow state, and logs every would-claim, would-skip and would-hand-back to the DecisionLog with the snapshot hash and policy versions it computed from. It holds no credentials that could mutate the real board; its entire output is evidence.
*Depends on:* M1.10, M1.4. *Size:* M.

**M1.12 — Claim comparator and divergence ledger.**
Shadow decisions are aligned with real drive.py claims over matching time windows and every divergence is classified and stored as data: input difference (the two systems saw different boards), policy mismatch (a rule exists in one and not the other), implementation defect (same inputs, same policy, different answer), or real-world side effect (a merge, park or requeue the shadow cannot honestly simulate — §8's reason for comparing claims only). The output is a divergence report per window and a burn-down list that feeds design corrections back into the evaluator, not a prose summary.
*Depends on:* M1.11. *Size:* M.

**M1.13 — The one-loop question, answered with measurement.**
§4's open question — can one conductor loop carry both claim cadence (~5-minute, board-facing) and chain-advancement (continuous, Job-facing, including self-repair that can restart the control plane itself)? — is answered by instrumenting the shadow loop's claim latency and running a prototype chain-advancer load model against it, ending in a recorded Decision (merged loop with separated responsibilities, or two loops) with the measurements attached. Phase 3A's conductor is built to this decision; nothing else in Phase 1 or 2 waits for it.
*Depends on:* M1.11. *Size:* M.

**M1.14 — Goldfish install and shadow smoke.**
A zero-context agent, given only the repo, installs the chart on a fresh cluster, loads the seed definitions, connects the legacy adapters, and produces a shadow decision — filing every point of friction as a finding against the repo, the docs, or the chart. This is §1.9's "install in an afternoon" bar and §11's agent-legibility gate applied to our own Phase 1 output before Phase 2 builds glass on top of it.
*Depends on:* M1.6, M1.8, M1.12. *Size:* M.

> **Phase 1 exit is an operation, not a task:** the 1–2 week shadow soak runs M1.11/M1.12 against the live board, and its divergences are dispositioned (fixed, or accepted with reasons) into a shadow-readiness Decision. Phase 2 may build against early soak data; Phase 3B may not proceed without that Decision. Do not file the soak as a build task — a calendar window is not lane work, and pretending otherwise is how it becomes invisible.

### Phase 2 — Read-only glass over shadow data

**M2.1 — Console shell, design system, session auth.**
The TypeScript + React console exists as a static app served by the API service: routing, the brand design system (palette, type, dark-first), OIDC session handling under M1.5's operator accounts, and an empty-but-real frame for the Phase 2 views. Every console data path goes through the public API — the console gets no private endpoints (§6's rule).
*Depends on:* M1.7, M1.5. *Size:* M.

**M2.2 — Read-model projections for board and pipeline.**
Query-optimised projections over the ledger and shadow snapshots serve the console's shapes: board state by milestone/sequence, per-task unified timelines (binding, stages, jobs, traces, PR, checks, merge, deploy verdict, evals, cost — §6.0's one record, not two linked ones), and chain/run summaries imported from the legacy adapters. Projections are labelled as projections everywhere they appear; the ledger remains the truth (§1.3).
*Depends on:* M1.4, M1.7, M1.9. *Size:* L.

**M2.3 — Board and milestone/sequence view (read-only).**
Tasks by state, milestone and explicit sequence position, with filters and saved views (Plane's proven concepts, §5.2 option C), hand-back and block reasons inline, and drag *disabled* — in a read-only phase a drag would be a lie; reordering arrives with the write surfaces that can honour §3.3a's SequenceChange audit.
*Depends on:* M2.1, M2.2. *Size:* M.

**M2.4 — Task detail is its chain, plus the trace viewer.**
One page per task: the §6.0 timeline from claim to deploy verdict, stage-by-stage facts and costs, and the trace viewer carried over from the current UI (invocation/result/prose filtering, shell-read flagging). This view is the console's centre and the reason the phase exists; it is built against shadow and imported data so its shape is proven before real chains depend on it.
*Depends on:* M2.2, M2.3. *Size:* L.

**M2.5 — Pickup Preview over shadow decisions.**
The derivability view: current queue, computed order, next-10-claims simulation, and per-item reason codes served by M1.10's evaluator — including binding failures by name. When Joe asks "why wasn't X picked up?", this view is the answer, and Phase 3B's cutover decision leans on it having been right during the soak.
*Depends on:* M1.10, M2.1, M2.2. *Size:* M.

**M2.6 — DecisionLog and audit explorer.**
Conductor decisions are searchable by object, reason code, policy version and snapshot, with replay of a single pass's inputs; operator audit history (M1.5) is visible alongside. This is §3.8's promise — "why wasn't X picked up?" as a query, not an investigation — delivered while the decisions are still shadow decisions and cheap to be wrong about.
*Depends on:* M1.4, M2.1. *Size:* S.

**M2.7 — Eval grid and throughput dashboards.**
Eval runs × checks with absent-states rendered as their own state (never as failures, §1.6), and the §3.8 ThroughputWindows as dashboards: claims, completions, merges, lead/dwell distributions, lane utilisation, hand-back and stall counts, and the God-Agent scoreboard (oldest unowned work, oldest logjam, merges/day, owner-pointed-out count). All aggregates are recomputed from the ledger; nothing here stores a second truth.
*Depends on:* M1.4, M2.2. *Size:* M.

**M2.8 — Decision inbox and shadow what-if steering.**
The operator can answer Decision objects and explore sequence changes against the *shadow* system — answers and drags are recorded, audited SequenceChanges in Sortyard's store, visibly labelled non-authoritative while the legacy system still runs the trains. This gives Joe real steering practice on the new glass (§8 Phase 2's intent) without a second system of record ever existing.
*Depends on:* M1.7, M2.3, M2.5. *Size:* M.

**M2.9 — Console quality walk in the replica.**
The Phase 2 console is walked causally in the deployment-shaped replica (Playwright, per the zero-difference doctrine): navigation and information-architecture coherence, every view against seeded shadow data, API behaviour behind each screen. Findings file as tasks against Phase 2 or later phases; the walk is a task with findings as its output, not a gate bolted onto other tasks.
*Depends on:* M2.3–M2.8. *Size:* M.

### Phase 3A — Bound execution core

**M3.1 — Definitions sync controller (git mode).**
The §5.1 division becomes operational: a controller watches the definitions repo, materialises new definition versions into the DB, enforces pinning (a running chain keeps its starting workflow version to completion), surfaces `definitions: stale` when it cannot sync, and supports the DB-only mode flag for small installs with one-way `harness export` back to git. M1.2 built the loader; this is the live, watched, failure-honest version of it.
*Depends on:* M1.2, M1.7. *Size:* L.

**M3.2 — Extension registry core (git-backed).**
Skills, workflow packs, eval packs, archetype packs and sensors are registered, versioned, and enabled per project, with exact-version resolution the binding can rely on. The registry is git-backed in v1 (§8 non-goals respected — no marketplace), but its data model is the registry model from day one, so Phase 5's SDK and Phase 6's community extensions are clients of it, not a replacement for it.
*Depends on:* M3.1. *Size:* L.

**M3.3 — Context Assembler and packet store.**
ContextRecipes become executable: per project/worktype/role allowlists assemble packets with token budgets, `derived_from` provenance and drift checks (stale provenance warns on the task, never silently poisons it), content-hashed packet storage in the object store, and the goldfish property as a checkable artefact — every StageRun records the exact packet hash it ran. This is `dispatch`'s successor, carrying its allowlist lesson (retrieval over a vault put 36% dead material in packets) as a design constraint.
*Depends on:* M3.1, M3.2. *Size:* L.

**M3.4 — Execution Binding resolver.**
For any (task, stage) pair, the resolver produces the §3.7b binding — pinned workflow version, role/persona, assembled packet hash, exact skill versions confirmed installed, lane/place/worker image, model and per-key budget, credential-custody refs, materialised dependency artifacts, and the ResourceEnvelope — or fails with the specific `unbound: …` reason. The shadow evaluator (M1.10) becomes a thin client of this resolver, so the pre-claim gate Joe sees in the Pickup Preview and the gate the real conductor enforces are the same code.
*Depends on:* M3.2, M3.3, M1.10. *Size:* L.

**M3.5 — Mirror service and dependency materialisation.**
Repo mirrors are first-class objects (source, last-refresh, freshness) refreshed by a service; worker clones come only from mirrors; a stale mirror is a named binding failure, never a surprise mid-job. Dependency outputs from `depends_on` tasks are materialised into the isolated workdir by reference before the agent starts, as mh attachments do today — dependencies are inputs, not links (§3.7b).
*Depends on:* M3.4 (interfaces), M1.3. *Size:* L.

**M3.6 — Worker launcher and Chain Advancer.**
Stages execute as Kubernetes Jobs — one stage per pod, isolated workdir, hermetic prepare/reseed before agent start — and observed facts (exit, checks, artefacts) advance the chain through the workflow's declared stage sequence. Stall detection and Escalations implement §3.3's rules in full: four-round revision cap, stall classes, self-repair bounded at two attempts per distinct defect (one when the repair concludes "not dispatcher-side"), and the 15-minute repaired-code-not-running terminal condition. Whether this shares a loop with the conductor follows M1.13's Decision, not this task's preference.
*Depends on:* M3.4, M3.5. *Size:* L.

**M3.7 — Credential custody, auth broker, and the pool.**
CredentialCustody is implemented per credential class (§3.7a): secrets-store references, CLI-owned 0600 files for subscription auth (the broker's interactive device-flow / setup-token grants, human-approved in their own browser), and operator-side custody for the GitHub write credential — whose default location does **not** move into the cluster under this task or any other without Joe's explicit decision. Pool selection implements least-burned picking, 5-hour cooldowns and the 3-requeue cap as failure isolation; concurrency remains the caps' job alone. Jobs receive only the secret refs their binding declares.
*Depends on:* M3.4, M3.6. *Size:* L.

**M3.8 — Real conductor: claims, leases, hand-backs.**
The deterministic conductor claims for real: leader election, explicit claim leases (leader death → lease expiry → item returns to eligible), slot occupancy held through `merging`, urgent bypass that never preempts a running job, policies read at decision time, and every decision in the DecisionLog with its inputs. Hand-back is a first-class transition requiring reason + evidence. There is no LLM anywhere in this component (§1.2).
*Depends on:* M3.4, M3.6, M1.13 (the loop-shape Decision). *Size:* L.

**M3.9 — Integrator: the fenced shipping leg.**
The `ship.py` successor is the only component that lands code: it requires a `passed` proof receipt for the exact (base, candidate) pair, verify approval of the exact head, and a tree-identity assertion, then lands byte-exact signed commits via the Git Data API with a register checkpoint recording both heads. It runs under the installation's configured credential custody (M3.7) and takes instructions only from the conductor's service account (§7).
*Depends on:* M3.6, M3.7. *Size:* L.

**M3.10 — Eval Runner as its own deployment.**
Deterministic and agent-judge evals run in a deployment topologically separate from the pipeline (§1.4): mandatory absent-states on every eval, posture advisory-by-default, the one-heavy-eval-per-host rule *enforced here* (today it is prose, §3.7b's honesty note), and the scorecard battery carried over as an eval pack — advisory never gating, taste never machine-graded, source-excluded grading supported (§3.8).
*Depends on:* M3.2, M3.6. *Size:* L.

**M3.11 — Self-heal and escalation operations.**
Handed-back work is owned, not parked: it loses conductor eligibility, gains a self-heal assignment carrying the worker's account and evidence, re-alerts at 24h dwell, and returns to eligibility only through a recorded repair. The process is imported from the current self-heal contract's *behaviour* — its document is known-stale (HARNESS-248) and is not imported as truth.
*Depends on:* M3.8. *Size:* M.

### Phase 3B — HARNESS authority cutover (the pilot)

**M3.12 — HARNESS import and Plane projection.**
Open HARNESS work — tasks, decisions, states, hand-back records — imports into the Sortyard DB from a frozen snapshot, and Plane becomes a one-way projection of Sortyard state, labelled as a projection everywhere it appears. The register snapshot is retained as the rollback artefact. This is the §8 Phase 3 mechanism, built only after the execution core exists to be switched *to*.
*Depends on:* M3.1, M3.8. *Size:* L.

**M3.13 — Pilot rehearsal in the replica.**
The HARNESS corpus is cloned into the replica and run end-to-end under Sortyard authority — bound claims, worker stages, integrator landings against a scratch remote, hand-backs, a rollback to the frozen snapshot and back — with divergence between rehearsal behaviour and live behaviour recorded as findings. The rehearsal uses the deployment-shaped environment, not a mocked pipeline, per the zero-difference doctrine.
*Depends on:* M3.2–M3.12. *Size:* L.

**M3.14 — HARNESS authority cutover and hypercare verdict.**
At a milestone boundary, authority switches: Sortyard's conductor claims HARNESS work for real, the legacy conductor stops claiming it, Plane is projection-only, and a hypercare window produces a written verdict — claims correct, landings fenced, hand-backs owned, rollback still possible until the window closes. This is an operational task gated by the Phase 1 shadow-readiness Decision and M3.13's findings; it is not ordinary lane work and must carry a Decision reference when filed.
*Depends on:* M3.13, Phase 1 exit Decision. *Size:* L.

### Phase 4A — Cutover factory and parity machinery

**M4.1 — Repeatable cutover kit.**
The pilot's import/projection/reconciliation/rollback steps generalise into a per-project kit that runs dry first: object-class difference reports (tasks, decisions, chains, evidence), a frozen snapshot, a projection check, and a rollback rehearsal — so each product cutover is the kit executed, not a new invention. Divergences found by the pilot are kit features, not tribal knowledge.
*Depends on:* M3.14. *Size:* L.

**M4.2 — Evidence and baseline import.**
From M1.15's preserved snapshot: ledger history, write-back projections and the battery's baseline corpus import with provenance intact, and gaps are recorded as unscored regions rather than silently zeroed — the battery's comparability (§3.8) survives the migration or visibly doesn't.
*Depends on:* M1.15, M4.1, M3.10. *Size:* L.

**M4.3 — Sensor and grooming parity.**
Juno's watches become system objects before any of them retire: registry-stall and stillness watches, the daily pipeline record, deploy-down detection, and GroomingPasses (frontier-only judgment, enforced as policy on the pass) run as Sensors inside Sortyard in dual-run against the existing crons, with output differences reconciled. A cron retires per project only after its Sensor has matched it — the dual-running period is planned, per §8, not accidental.
*Depends on:* M4.1. *Size:* L.

**M4.4 — Experiment-rig disposition.**
The rig that shares today's control plane (corpus/treatments, request landing) gets an explicit fate: an inventory of its data and consumers, a recorded Decision (separate deployment on the same chart, or retirement), and the split or retirement executed with its data migrated or archived — never silently carried into the product and never silently dropped (§8 Phase 4's conscious-split requirement).
*Depends on:* M4.1 (for its migration machinery). *Size:* L.

### Phase 4B — Product cutovers (each its own milestone gate)

**M4.5 — Rove cutover.**
Rove switches authority at a milestone boundary via the M4.1 kit: import, shadow check, authority switch, Plane projection, rollback snapshot retained, hypercare verdict recorded. Rove first because the standing rollout rule is smallest/safest first and its lane behaviour is the best understood.
*Depends on:* M4.1, M4.2, M4.3. *Size:* L.

**M4.6 — Loopmentum cutover.**
Same kit, same gate, executed only after Rove's verdict is recorded — one project at a time is a rule, not a scheduling preference, and Loopmentum's cutover inherits Rove's kit corrections rather than running in parallel with them.
*Depends on:* M4.5. *Size:* L.

**M4.7 — Cortexplane cutover.**
The largest and most entangled project cuts over last, with its integration settings and trajectory/project structures imported as first-class objects, and the same verdict discipline. By this point the kit has been corrected by two live cutovers; Cortexplane is where that investment pays out.
*Depends on:* M4.6. *Size:* L.

### Phase 4C — Legacy retirement

**M4.8 — Dispatcher absorption.**
All chain advancement routes through Sortyard's Chain Advancer; mh.py's dispatcher stops launching jobs, its remaining state is reconciled into the ledger, and the control plane's dual-scheduler era (§0's finding) ends with one scheduler of record.
*Depends on:* M4.5, M4.6, M4.7, M3.6. *Size:* L.

**M4.9 — drive.py and plane_sync retirement.**
The legacy conductor stops claiming and syncing; Plane's last authority remnants are removed (it remains only as the optional projection/integration of §5.2 option C); exports of both systems' final states are archived read-only. Nothing is deleted that M1.15 and the per-project snapshots don't already preserve.
*Depends on:* M4.8. *Size:* M.

**M4.10 — One-source-of-truth audit and decommission.**
A conformance sweep over the whole estate: every domain object has exactly one authoritative store, every projection is labelled, dual-running configurations are removed, and old stores are archived or deleted per the retention policy. The sweep's output is a defect list, and the phase is not done while it is non-empty — this is §1.3 verified, not asserted.
*Depends on:* M4.4, M4.9. *Size:* M.

### Phase 5 — Definitions conformance and the extension platform

**M5.1 — Definitions inventory and conformance ledger.**
Every meta-harness artefact — templates, skills, workflows, roles, contracts, and every enforceable prose rule in AGENTS.md-class documents — is enumerated and mapped to its target: a definition object, a Policy, an extension, or a conscious retirement with a minute. The ledger is the worklist for the rest of the phase; an unmapped artefact is shaping debt, surfaced as such (§3.3a's discipline applied to definitions).
*Depends on:* M3.1, M3.2. *Size:* L.

**M5.2 — Archetype pack migration.**
The `saas-product` and `infrastructure` archetypes become versioned packs with project pinning and diff/accept inheritance — including repairing the infrastructure template's broken emit/validate path (§3.2's grounded finding) rather than migrating the breakage. Candidate archetypes (inception, opportunity-portfolio) migrate as candidates, not as silently-promoted defaults.
*Depends on:* M5.1. *Size:* L.

**M5.3 — Workflow and role pack migration.**
The built-in workflows (feature with its Frame → Judge → Shape → Build → Verify stages, incident, release, support, infrastructure change/drift/incident, job, design-first) and the template roles/personas become versioned workflow/role definitions, each pinning the review regime its policy requires (§3.6's three regimes, scoped — never flattened).
*Depends on:* M5.1, M3.2. *Size:* L.

**M5.4 — Skills migration into the registry.**
The skill corpus migrates with its frontmatter contracts (kind, required, depends_on) intact: required skills resolved eagerly, situational skills lazy, versions pinned per project, enable/disable from the console. The migration builds the import tooling and lands the corpus through it, so future skill imports — including community ones — use the same path.
*Depends on:* M5.1, M3.2. *Size:* L.

**M5.5 — Policy conformance migration.**
Each prose rule completes its journey to a Policy object with scope, enforcement, absent-state behaviour and audit history — or is retired in the M5.1 ledger with a reason. The policy simulator ("would this policy have refused workflow X?") and the git export round-trip (`harness export` → PR → re-import is a no-op, §5.1) are part of this task, because a policy that cannot be simulated or exported is only half-migrated.
*Depends on:* M5.1, M3.1. *Size:* L.

**M5.6 — Operator write surfaces.**
The console grows its remaining views on the now-real machinery: Policies (edit with form-enforced absent-state/enforcement fields, version diffs, simulate), Lanes & Tuning (live edit, audit), Extensions (install, pin, enable per project), Secrets (references, scopes, rotation state — values never transit), and Admin (users/roles, DeploymentConfig reflection, audit log, backup/restore). Rule unchanged: if it is in the UI, it is in the API.
*Depends on:* M5.2–M5.5, M2.1. *Size:* L.

**M5.7 — Extension SDK, scaffold, and conformance kit.**
A third party — or their agent — can create an extension without reading Sortyard's source: scaffold/templates for each extension kind, a conformance test kit that runs locally in the replica, a published API-stability and versioning commitment, and install-from-git working end-to-end. This is §11's "installable without our permission" made real; the registry core (M3.2) is its runtime, this is its developer surface.
*Depends on:* M3.2, M5.4. *Size:* L.

**M5.8 — Proposals: ideation's front door.**
The Proposal task type exists with its lifecycle — problem, proposed shape, smallest experiment — groomed like all work: duplicates merged, promising proposals converted to spikes, refusals recorded with reasons. The public roadmap is a projection of the real board, and a workflow or recipe built inside Sortyard can be published back to the registry in one action, with attribution (§11.4).
*Depends on:* M1.7, M5.6. *Size:* M.

**M5.9 — Definitions-repo cutover.**
Meta-harness completes its transformation into our installation's definitions repo (or is archived once empty, per the M5.1 ledger's final state): redirects from old paths, old register formats frozen read-only, and the export/import round-trip proven on the real corpus. The register-as-markdown era (§5.1) ends here, with its history preserved in git where git is good at history.
*Depends on:* M5.2–M5.8. *Size:* L.

**M5.10 — Fork-PR verification lane.**
External contributions get a verification path that never touches estate runners: ephemeral, resource-enveloped, credential-free sandboxes run fork code; DCO sign-off is checked mechanically; the merge contract (tests, review, adversary review ownership) is enforced by the lane, and every external change is bound and verified like any other execution (§11.3). This lands *before* the public launch invites the contributions it exists to make safe.
*Depends on:* M5.7, M3.7, M3.10. *Size:* L.

### Phase 6A — Release candidate

**M6.1 — Public docs, quickstart, and worked examples.**
Documentation a stranger's agent can execute from: install on API-key credentials alone (the Auth Broker is optional first-run setup, per §8's acknowledged threat to the afternoon-install bar), the first-sort demo, concepts (binding, lanes, sequencing, policies), examples for each extension kind, and troubleshooting written around absent states — what the system says when something cannot run, and what to do about it.
*Depends on:* M5.7, M5.8. *Size:* L.

**M6.2 — Security and supply-chain release pass.**
The release is hardened as a whole: threat model over the token matrix and credential custody classes, image signing and build provenance, dependency scanning running in the M5.10-style isolated lane (never on estate runners), and an adversarial review of the binding path — the component whose failure mode is "an agent ran unbounded," which is the failure this product exists to prevent.
*Depends on:* M5.10, and the Phase 3A core complete. *Size:* L.

**M6.3 — Upgrade and compatibility suite.**
Upgrading is proven before anyone is asked to do it: chart upgrade from the previous release candidate with live state, DB migrations under load-shaped data, definitions export/import round-trip, API backward-compatibility checks against the published OpenAPI, and extension version-policy enforcement. An install that cannot upgrade is a trap, and §1.9's afternoon bar applies to the second install too.
*Depends on:* M5.9, M6.1. *Size:* L.

**M6.4 — Fresh-cluster release-candidate gauntlet.**
Independent zero-context agents (and at least one human who is not Juno) install the release candidate on vanilla clusters from public docs only, run the demo workflow, land a sample extension through the SDK, and file every friction point; findings are dispositioned as launch blockers or post-launch work, in the open. This is M1.14's goldfish test at release scale — a gate the release passes, not a ceremony it attends.
*Depends on:* M6.1, M6.2, M6.3. *Size:* L.

**M6.5 — First external contribution rehearsal.**
Before the broad invitation, a controlled external contribution — ideally from an agent whose operator we don't know — travels the whole path: proposal or fork PR, sandboxed verification, bound execution, review, landing, attribution. The rehearsal's friction list is the final input to the launch decision; ideation infrastructure that has never carried a stranger's work is a hypothesis, not a feature (§11).
*Depends on:* M5.10, M6.4. *Size:* M.

### Phase 6B — Launch (decisions and the act, kept separate from buildable work)

**M6.6 — Licence, trademark, and governance gate.**
The non-code launch prerequisites are resolved as records: Joe's licence decision (Apache-2.0 recommended per §11.5, with DCO-not-CLA and no dual-licensing preservation), the formal trademark search the name has owed since adoption, the maintainer model, and the name/logo trademark rules. None of this is lane-buildable in the ordinary sense; it is filed as Decision-gated work so it can never silently block — or silently pass — the launch.
*Depends on:* nothing technical; required by M6.7. *Size:* S (as work) — unbounded (as waiting) if left unstructured, which is the point of filing it.

**M6.7 — Public launch.**
Repo and chart publish at a pinned first release, docs go live, the roadmap projection and Proposals front door open, and first external installs are watched with a named rollback/withdraw path if the gauntlet missed something structural. Launch is an act with an owner and a date, not the tail of a task chain.
*Depends on:* M6.4, M6.5, M6.6. *Size:* M.


---

## 3. Judgment on Juno's Phase 1 six

Juno's six: (1) repo + chart skeleton; (2) Postgres schema + event ledger; (3) API service with the §7 permission matrix; (4) shadow conductor; (5) claim-comparison harness; (6) one-loop latency answer.

**Overall: the right centre of gravity, the wrong granularity.** All six point at real Phase 1 work and none is invented. But two are conflations that will blur inside a lane, one hides the hardest component in the phase inside a single title, and the set omits five things the design itself makes load-bearing. Verdicts individually:

- **(1) Repo + chart skeleton — right work, wrong bundle. SPLIT** into M1.1 (repository + local replica + contributor brief) and M1.6 (Helm chart). The repo foundation is needed by every subsequent task including the schema work; the chart is only provable once there is a schema and a stub API, and forcing them into one task makes the first task on the critical path carry two unrelated failure modes. The split also recovers something Juno's version drops entirely: the **contributor ContextRecipe / local replica** (§11) — a "skeleton" without the replica and the agent brief is a folder layout, not a foundation other agents can build on.

- **(2) Postgres schema + event ledger — right, and correctly paired, but split the seam.** It survives as M1.3 + M1.4. The schema and the ledger share a store but not a design problem: the schema is §3 transcription plus schema-generated models (with the drift check Juno's version implies but doesn't state); the ledger is *semantics* — idempotency, snapshot hashing, decision-input recording — that the comparator and the DecisionLog explorer both depend on. One task would have let the easy half (tables) mask the unfinished half (semantics).

- **(3) API service with permission matrix — right direction, oversized as stated. SPLIT AND NARROW** into M1.5 (identity + permission matrix as its own task, because the create+claim token refusal is a security property that deserves its own review surface) and M1.7 (core state API — a *vertical slice*: Project/Task/Decision/Lane/Policy, not "the API service" full stop). Juno's version also omits **M1.8 (MCP + CLI parity)** — §7 makes agents first-class API citizens, and if the first API consumers are only tests, the console phase will discover the API's agent-facing flaws a phase late.

- **(4) Shadow conductor — the right centrepiece, and the most under-decomposed task in the six.** As stated it hides three distinct builds: the legacy input adapters (M1.9 — unglamorous, failure-prone, and the only part that touches Plane/registers at all), the eligibility/sequencing/binding evaluator (M1.10 — the derivability engine the Pickup Preview and the real conductor will both reuse), and the claim loop itself (M1.11 — comparatively thin once the evaluator exists). Filed as one task, "shadow conductor" would either hand back or silently redefine its scope mid-flight. Split into the three.

- **(5) Claim-comparison harness — right, keep nearly as-is (M1.12).** One sharpening: the comparator's real product is not a diff, it's a *divergence taxonomy stored as data* — input difference / policy mismatch / implementation defect / honest side-effect — because §8's "divergence = design feedback" only works if divergences arrive classified. A diff tool produces arguments; a classified ledger produces fixes.

- **(6) One-loop latency answer — right question, wrong task shape as a build item. KEEP, REFRAMED** as M1.13: a bounded measurement experiment ending in a recorded Decision. It must not be filed as ordinary build work (its deliverable is evidence + a decision, and it needs the shadow loop running to measure), and it must not gate the comparator or Phase 2 — only Phase 3A's conductor build (M3.8) depends on its answer.

**Missing from the six — implied by the design, absent from the list:**

1. **M1.2, definitions loader + seed corpus.** Without it, the evaluator and the API have nothing to evaluate or serve; Juno's six quietly assume definitions exist. §5.1's stale-definitions absent state also has to be built *somewhere* — this is where.
2. **M1.5, identity/permission matrix as a standalone** (above) — the §7 matrix "is the design," per the draft's own words; it should not ride inside an API task.
3. **M1.8, MCP/CLI parity** (above).
4. **M1.14, the goldfish install + shadow smoke.** §1.9 and §11 both make this a gate, and Phase 1 is where it is cheapest. Juno's six end at components; the design demands a phase that ends with a stranger-agent succeeding.
5. **M1.15, legacy evidence preservation.** §8 costs evidence migration in Phase 4, but *preservation* cannot wait for Phase 4 — every phase before it modifies the estate the evidence describes. Nobody's six contained this; it is the easiest task in the corpus to forget and the only one that becomes impossible later.

**What should NOT be in Phase 1:** any console work beyond an API stub (Phase 2); real claims, workers, mirrors, integrator, eval runner (Phase 3A — putting any of them in Phase 1 collapses the shadow discipline that makes the cutover safe); the extension SDK or fork-PR lane (Phases 5 — but note their *foundations*, registry core and custody, are correctly pulled into 3A/1A respectively); product imports; public docs. Phase 1 ends when the shadow has been *believed*, not when the system can *act*.

---

## 4. Cross-phase risks the corpus must respect

**R1 — HARNESS-286 is a premise, not a foundation, until it lands.** The post-#199 fix-round semantics are unverified by the design's own admission (§3.6, §10 Q8). Everything that encodes review behaviour inherits the risk: the `merge_gate` policy's conductor regime (M1.2's seed corpus, M5.5's migration), the shadow evaluator's expectations of what the real conductor does after a claim (M1.10–M1.12 — a comparator calibrated against a wrong model of fix rounds will manufacture divergences), and the real conductor's merge handling (M3.8). *Corpus rule:* until HARNESS-286's findings are merged and the draft amended, no task may hard-code a fix-round count; policy fixtures carry the count as a marked-provisional parameter, and M1.12's taxonomy gains a fifth honest class if needed — "real behaviour not yet grounded."

**R2 — Description-level dependencies are not dependencies.** Direct HARNESS items are held in order by their descriptions, not by machine gating; the conductor can claim a successor whose predecessor is merely *described* as blocking it. A corpus of ~60 tasks dumped into Todo at once would therefore not be a sequenced corpus — it would be a raffle with good documentation. *Corpus rule:* file in milestone tranches. At any moment, only the current milestone's head chain is Todo-visible; the rest of the corpus lives in this document and in MILESTONES.md until its tranche is released. Juno's Phase 1 filing, happening in parallel with this document, should be reconciled against §3's splits *before* more than its first task becomes claimable.

**R3 — One HARNESS lane is the programme's real clock.** HARNESS has one conductor slot; slot occupancy holds through review and `merging`. Sixty tasks through one slot, each with review rounds, means the corpus's critical path is measured in review-and-merge cycles, not build effort — and every estate task (jump-box work, RBAC-blocked items like HARNESS-280's history) competes for the same operational attention. *Corpus rules:* keep the eligible head short and always real (never-empty-queue applies to the *head*, not to dumping the backlog); expect L tasks to be split at filing time; and treat hand-backs to self-heal as scheduled events in the plan, not surprises — several tasks above (M3.14, M4.x cutovers, M3.7 custody work) have estate-side components a repo worker by design cannot complete.

**R4 — Decision-gated work must not masquerade as lane work.** At least five corpus points are premise-class or Joe-decision points, and filing them as ordinary tasks would let defaults ratify them silently — the exact failure the premise policy exists to prevent: (a) Phase 3B's authority switch itself; (b) any change to GitHub write-credential custody (§3.7a — the design's default is *no move*, and a task that "simplifies" custody is a security-posture change); (c) the experiment rig's fate (M4.4 — split vs retire is a Decision with an inventory, not an implementer's choice); (d) licence + trademark (M6.6); (e) §10's still-open confirmations that this corpus assumes but does not settle — Plane option C (assumed throughout; §5.2 recommends, §10 asks), definitions-editing default, and first-cutover = HARNESS (assumed in Phase 3B; if Joe picks a product instead, 3B and 4B reorder). Each must surface on the depends-on-Joe list as its own item when its phase approaches.

**R5 — The shadow baseline moves.** drive.py, plane_sync and the board will all change during a 1–2 week soak (they changed during the week this design was drafted). The comparator must version both sides — snapshot hashes and policy versions on every decision (M1.4 exists largely for this) — or the soak will produce a divergence count that measures the legacy system's release cadence instead of the shadow's correctness.

**R6 — Pipeline purity binds the corpus itself.** Tasks that verify Sortyard behaviour must do so in the replica with faked providers (§1.4/§1.5); a task whose verification requires live Plane, live GitHub, or the live cluster is mis-shaped and will stall inside the pipeline exactly the way the doctrine predicts. Live proof belongs to the acceptance lane (sensors, M4.3) and to operational tasks (M3.13/M3.14 rehearsals and cutovers), never inside a build task's definition.

**R7 — Connective tissue is scheduled work or it doesn't happen.** Three cross-cutting obligations have no natural owner in a per-phase corpus and must be carried explicitly: the **evidence thread** (M1.15 preserve → M4.2 import → battery comparability), the **legibility thread** (M1.1 replica/brief → M1.14 goldfish → M5.7 SDK → M6.4 gauntlet — each stage assumes the previous one's findings were fixed, not just filed), and the **custody thread** (M1.5 token matrix → M3.7 custody classes → M5.10 fork lane → M6.2 adversarial pass). If a future grooming pass "tidies" any of these chains by dropping a link, the phase it feeds will discover the gap at the worst moment.

---

## 5. What I'd file first — the eligible head after Phase 0

Assuming Phase 0's outputs are accepted (HARNESS-286's findings merged into the draft, 287's schemas and 288's spec in the seeded repo from 289), and filing under R2's tranche discipline — *one milestone's head, not the whole corpus* — the queue I would leave behind is:

**Eligible immediately (the head, in claim order):**

1. **M1.1 — Repository and local-replica foundation.** The single head item. Everything in Phase 1 imports from, builds in, or is verified inside what this task creates; it is also the task that makes all later tasks executable by agents other than the one writing them. Nothing else should be claimable until it lands — on a one-slot lane, a head of one *is* the never-empty queue, provided the next tranche is groomed and ready (it is: this document).

**Groomed and held for release the moment M1.1 lands (in order):**

2. **M1.3 — Postgres schema and schema-generated models** (the data contract every service writes against; deliberately ahead of M1.2's seed content, because the schema must not be held hostage to definition content).
3. **M1.2 — Definitions loader and seed corpus** (lands into M1.3's schema; carries R1's marked-provisional rule for anything HARNESS-286 touches).
4. **M1.4 — Event ledger and DecisionLog kernel** (unblocks both the API slice and the shadow line).
5. **M1.6 — Helm chart: minimal real install** (can be claimed as soon as M1.3 lands; proves the install story while the API is still a slice).

**Explicitly NOT filed yet:** Juno's (3) and (4) as single items — they enter the queue only in their split forms (M1.5, M1.7, M1.9, M1.10, M1.11), released when M1.4 lands; the comparator (M1.12) and one-loop experiment (M1.13) when the shadow loop exists to feed them; and nothing from Phase 2 onward, however groomed it looks on paper — under description-level dependencies, a task filed early is a task that can be claimed early, and a corpus that respects its own sequencing files late and grooms early.

*— End of corpus. Reconciliation and filing are Juno's, after Joe reacts.*
