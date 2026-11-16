# Sortyard — Milestone Map

> Historical architecture/planning record. The current requirements and dependency order
> are in the [ecosystem requirements baseline](docs/requirements/README.md). Read this record for provenance;
> it does not override the consolidated baseline or current Plane execution state.

Current substrate planning: [SY-DEC-004](docs/decisions/appwrite-substrate.md) selects
Appwrite persistence and human auth as the preferred target. Qualify transactions and immutable
history, implement the native adapter/schema, integrate Auth/Teams, then rehearse a one-writer
migration. Read-only console work can proceed alongside qualification. Existing SQL code and
deployments remain current until that implementation ships. Work state is read from Plane;
phase descriptions below are historical planning, not current task-state evidence.

The corpus of groomed work, by milestone. The full task corpus is `CORPUS.md` in this folder (frontier design pass, 2026-11-07); this map is its phase-level view. Tracking is on the Sortyard Plane project (identifier `SORTYARD`,
https://plane.ts.noncelogic.com/noncelogic/projects/10d493fb-4cef-4ef1-ab70-a0aefca87d59/issues/),
which has tasks:off and no plan file, so each filed task below is a SORTYARD board item created directly (the item is the filing). Sortyard was migrated off the HARNESS board on 2026-11-09; the identifiers below are SORTYARD board items. Design record: `DESIGN.md` in this folder (draft v6; working copy `~/workspace/harness-reboot/HARNESS-REBOOT-DRAFT-v6.md`), §8 for the original phase definitions. Decisions: `DECISIONS.md` in this folder. Charter: `README.md`.

Phase structure per the corpus reconciliation (2026-11-07): the draft's Phase 1 splits into 1A Foundation / 1B Shadow truth, Phase 3 into 3A Bound execution core / 3B HARNESS cutover, Phase 4 into 4A Cutover factory / 4B one gate per product / 4C Legacy retirement, and Phase 6 into 6A Release candidate / 6B Launch.

Later phases are named, not groomed into board items yet — filed per tranche as each milestone approaches (corpus R2 rule): under description-level dependencies, a task filed early is a task that can be claimed early, so the corpus files late and grooms early.

## Phase 0 — Freeze the model (filed 2026-11-06)

The design becomes a schema + OpenAPI spec. No code moves yet.

- **SORTYARD-1** — Sortyard Phase 0: verify conductor fix-round semantics from product-factory source (high). Status at 2026-11-07: built — PR #244 is in review (tracked as HARNESS-290); the item itself is Todo + self-heal (a later claim handed back: the worker's environment lacked the source/draft — see the item's comments). Completion waits on the PR.
- **SORTYARD-2** — Sortyard Phase 0: freeze the domain model — JSON Schemas for the §3 objects (high). Status: STALE-STATUS-A — the design draft was not present in the worker environment; schemas not yet written). Next in the Phase 0 chain.
- **SORTYARD-3** — Sortyard Phase 0: OpenAPI spec for the Sortyard API, incl. the MCP permission matrix (medium; depends on SORTYARD-2). Status: Todo + self-heal, waiting on 287.
- **SORTYARD-4** — Sortyard Phase 0: create github.com/sortyard/sortyard (private) and seed it from projects/sortyard (medium; depends on SORTYARD-2 + SORTYARD-3). Status: Todo + self-heal by design (operator-side GitHub writes — a lane claiming it hands back, correctly).

## Phase 1A — Foundation (groomed + filed 2026-11-07)

Repo, data, contract — corpus M1.1–M1.8 + M1.15 in `CORPUS.md`. All build work happens in github.com/sortyard/sortyard, so every item is dependency-held behind SORTYARD-4 plus its internal predecessors — filed visible, held by the description-level dependency convention, by design. Items marked *(added 2026-11-07)* are the reconciliation additions from the frontier corpus; the rest are Juno's original six, which stay as filed.

1. **SORTYARD-5** — Sortyard Phase 1: repo + chart skeleton — Python package (services as entry points), CI, Helm chart deploying API + Postgres (high). Depends: SORTYARD-4. (Corpus M1.1 + M1.6, filed combined.)
2. **SORTYARD-6** — Sortyard Phase 1: Postgres schema + event ledger from the §3 JSON Schemas (models generated from schemas, migrations as Jobs) (high). Depends: SORTYARD-5, SORTYARD-2. (Corpus M1.3 + M1.4, filed combined.)
3. **SORTYARD-14** — Sortyard Phase 1: permission matrix as its own surface — service-account scopes incl. the create+claim refusal, issued and audited as data (medium). Depends: SORTYARD-6. (Corpus M1.5 — *(added 2026-11-07)*, split out of SORTYARD-7.)
4. **SORTYARD-7** — Sortyard Phase 1: API service — REST surface per the OpenAPI spec, service accounts + §7 permission matrix enforced (medium). Depends: SORTYARD-6, SORTYARD-3. (Corpus M1.7. Scope narrowed at reconciliation to *enforcement of* the matrix SORTYARD-14 defines — recorded by comment on the item, not a silent edit.)
5. **SORTYARD-12** — Sortyard Phase 1: definitions loader + seed corpus — definitions-in-git loaded, versioned, pinned; the installation's own definitions seeded (medium). Depends: SORTYARD-6. (Corpus M1.2 — *(added 2026-11-07)*.)
6. **SORTYARD-13** — Sortyard Phase 1: contributor foundation — one-command local replica of the deployment topology + repo brief (AGENTS.md) a zero-context agent can build from (medium). Depends: SORTYARD-5. (The §11 piece of corpus M1.1, pulled forward from launch polish — *(added 2026-11-07)*.)
7. **SORTYARD-15** — Sortyard Phase 1: MCP server + CLI parity — every API operation reachable as MCP tools and via the sortyardctl CLI, no back doors (medium). Depends: SORTYARD-7. (Corpus M1.8 — *(added 2026-11-07)*.)
8. **SORTYARD-11** — Sortyard Phase 1: legacy evidence preservation — freeze the current ledger history + battery baseline corpus before any phase modifies the estate they describe (high). Depends: none — and it must land before any Phase 3/4 work. (Corpus M1.15 — *(added 2026-11-07)*. Time-critical: the only corpus item that becomes impossible later.)
9. **SORTYARD-16** — Sortyard Phase 1: goldfish install + smoke — a zero-context agent installs the chart on a clean cluster and runs the demo workflow, unaided; the report is the deliverable (medium). Depends: SORTYARD-5, SORTYARD-7. (Corpus M1.14, install + smoke scope — *(added 2026-11-07)*.)

## Phase 1B — Shadow truth (groomed + filed 2026-11-07)

The conductor, observed before it is trusted — corpus M1.9–M1.13.

1. **SORTYARD-8** — Sortyard Phase 1: shadow conductor — replicate the real input path read-only, log would-claim decisions to the DecisionLog (high). Depends: SORTYARD-6. (Corpus M1.9 + M1.10 + M1.11, filed combined.)
2. **SORTYARD-9** — Sortyard Phase 1: claim-comparison harness — diff shadow vs real drive.py claim decisions, divergence report + eval (medium). Depends: SORTYARD-8. (Corpus M1.12 — its real product is a classified divergence ledger stored as data, not a diff.)
3. **SORTYARD-10** — Sortyard Phase 1: one-loop latency answer — measure whether one conductor loop can carry claim + chain-advancement; record as a decision (medium). Depends: SORTYARD-8. (Corpus M1.13; the answer lands as SY-DEC-002 in `DECISIONS.md`.)

**Phase 1 exit is an operation, not a task:** the 1–2 week shadow soak runs SORTYARD-8/314 against the live board, and its divergences are dispositioned (fixed, or accepted with reasons) into a shadow-readiness Decision. Phase 2 may build against early soak data; Phase 3B may not proceed without that Decision. The soak is never filed as a build task — a calendar window is not lane work.

## Phase 2 — Read-only glass over shadow data (sketch — not yet groomed)

Five of §6's thirteen views — Board, task-detail-is-its-chain (stages, jobs, traces, PR, checks, deploy verdict, evals, cost on one timeline), Pickup Preview, DecisionLog explorer, Eval grid + throughput dashboards — plus the console shell, over shadow data. The operator steers from the new glass while the old system still runs the trains. Policies/Lanes/Extensions/Secrets/Admin *write* surfaces belong with the phases whose machinery they operate (3A, 5), not here. Corpus M2.1–M2.9. Filed per tranche when Phase 1 lands.

## Phase 3A — Bound execution core (sketch — not yet groomed)

The largest build in the programme — the work the draft's Phase 3 paragraph hid inside the word "cutover": definitions sync controller (git mode), extension registry core, context assembler + packet store, Execution Binding resolver, mirror service + dependency materialisation, worker launcher + chain advancer, credential custody + pool, the fenced integrator, eval runner as its own deployment, self-heal operations. Corpus M3.1–M3.11. Filed per tranche when Phase 2 lands.

## Phase 3B — HARNESS authority cutover (sketch — not yet groomed)

One project — the harness's own work (HARNESS items), dogfooding literally — switches authority: import from a frozen snapshot, Plane becomes a one-way projection, replica rehearsal, then the switch at a milestone boundary with a hypercare verdict; the register snapshot is kept as the rollback artefact. The authority switch is premise-class: it files as Decision-gated work carrying a Decision reference and surfaces on the depends-on-Joe list when this phase approaches — never as ordinary lane work. Corpus M3.12–M3.14.

## Phase 4A — Cutover factory + parity machinery (sketch — not yet groomed)

The pilot's steps generalised into a repeatable per-project kit (dry-run difference reports, frozen snapshot, projection check, rollback rehearsal); evidence + baseline import from the Phase 1A preservation snapshot (SORTYARD-11), with gaps recorded as unscored regions; Juno's watches and crons dual-run as Sensors/GroomingPasses and retire per project only after matching; the experiment rig sharing today's control plane gets an explicit fate — separate deployment on the same chart or retirement, by recorded Decision, never silently carried into the product. Corpus M4.1–M4.4.

## Phase 4B — Product cutovers, one milestone gate each (sketch — not yet groomed)

Rove (corpus M4.5) → Loopmentum (M4.6) → Cortexplane (M4.7) — smallest/safest first, one project at a time, each cutover its own milestone boundary with its own rollback snapshot and hypercare verdict, each inheriting the previous one's kit corrections.

## Phase 4C — Legacy retirement (sketch — not yet groomed)

Dispatcher absorption (mh.py stops launching; one scheduler of record), drive.py + plane_sync retirement (Plane remains only as the optional §5.2-option-C projection/integration), and a one-source-of-truth conformance audit whose defect list must be empty for the phase to be done. Corpus M4.8–M4.10.

## Phase 5 — Definitions conformance + extension platform (sketch — not yet groomed)

The conformance pass over every meta-harness artefact: templates → archetype packs, workflows + roles → versioned definitions, skills → the extension registry, prose rules → Policy objects or minuted retirements; operator write surfaces; extension SDK + conformance kit; Proposals as ideation's front door; the definitions-repo cutover; and the fork-PR verification lane — landed *before* the Phase 6 launch invites strangers' code. Corpus M5.1–M5.10.

## Phase 6A — Release candidate (sketch — not yet groomed)

Public docs, quickstart and worked examples a stranger's agent can execute; security + supply-chain release pass (including an adversarial review of the binding path); upgrade + compatibility suite; the fresh-cluster release-candidate gauntlet (zero-context agents install from public docs only — the goldfish test at release scale); first external contribution rehearsal. Corpus M6.1–M6.5.

## Phase 6B — Launch (sketch — not yet groomed)

Kept separate from 6A so buildable work never appears blocked by decisions it does not depend on. M6.6: the licence/trademark/governance gate — Joe's decisions, filed as Decision-gated work (standing default: Apache-2.0 + DCO, no CLA; formal trademark search still owed since the name's adoption). M6.7: the launch act itself — repo + chart published at a pinned first release, docs live, roadmap projection and Proposals front door open, with a named rollback/withdraw path.
