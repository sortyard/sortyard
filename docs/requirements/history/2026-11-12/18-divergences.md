# 18 — Divergences, baselines, targets and floors

Two directions from the owner on 2026-11-12 govern this file, and through it every other file in
the directory:

> "Anywhere sortyard diverges from the cobbled solution we have in hand, the divergence needs to
> evolve into something that's demonstrably better in as many ways possible."

> "Why not plan for the best outcome imaginable and be ready to accept we might miss the mark by
> a little."

Section 1 states the two rules and their vocabulary. Section 2 is the catalogue of legacy
baselines that comparisons are made against. Section 3 is the scorecard: the headline targets,
then every measured criterion in the specification. Section 4 is the register of every place
Sortyard differs from the estate's system, with a verdict for each. Section 5 records the audit
of 2026-11-12: which cuts were reversed, which were reshaped, and which stand and why.

---

## 1. The rules

### 1.1 Divergence (QLT-050)

A **divergence** is anything Sortyard does differently from the system the estate runs today.
Four things count: a requirement whose origin is `FIX`; a row of
[16-legacy-parity.md](16-legacy-parity.md) whose disposition is not `KEEP`; a cut (a legacy
behaviour that is not carried); and a finding in [11-coherence.md](11-coherence.md) that
replaces a mechanism. Each one must state:

1. **the legacy baseline**, with its evidence — a `BL` id from section 2;
2. **the dimensions** on which the new behaviour is better, from the closed list below;
3. **a demonstration** — a measured comparison against the baseline, with a threshold.

"Different but equivalent" does not pass. A divergence either shows it is better or the legacy
behaviour is kept: as the requirement itself, or as the setting the estate bundle ships. A
divergence whose demonstration misses its floor is not shipped to the estate.

Two bundles are meant throughout. The **default bundle** is what a new installation gets
(DEF-008). The **estate bundle** is the estate's own definitions — its workflows, the packs it
switches on, and the legacy value of every policy key — kept in its Git source and pulled by
its installation (DEF-003, MIG-010). Where a legacy behaviour is right for the estate and wrong
as a default for strangers, the estate bundle keeps it and the default bundle does not; that is
a default for new installations, not a divergence.

Differences from DESIGN v6 or CORPUS are not divergences in this sense. Where the plan proposed
something the estate never had, dropping it from the plan keeps the legacy behaviour; such
entries are marked `not a divergence` and say what the estate does instead.

### 1.2 Target and floor (QLT-051)

Every measured criterion has two levels.

- **Target** — the best outcome imaginable for a product of this kind, set from first principles
  and from the best tools in the field, not as a small step past the legacy system. The design
  and the work packages are sized for the target.
- **Floor** — what a gate enforces. Where a legacy baseline exists the floor is "demonstrably
  better than the baseline"; where none exists it is a stated absolute bar.

A cutover, a promotion or a milestone exit needs only the floors. A measured value between
floor and target is recorded and opens one `target-gap` task in Backlog. The gap is backlog, not
failure. A target is never lowered to fit a measurement.

### 1.3 Vocabulary

**Origins** of a requirement, relative to the estate as it runs:

| Origin | Meaning | What the requirement must carry |
|---|---|---|
| `KEEP` | The estate behaves this way and Sortyard preserves it | — |
| `FIX` | The estate does this differently and Sortyard changes it on purpose: a divergence | `Baseline:`, `Better on:`, and at least one `Demonstration` criterion |
| `NEW` | Nothing in the estate occupies this place (install, identity for strangers, public release) | — |

**Dimensions** (`Better on:`): `throughput`, `latency`, `stall-rate`, `recovery-time`,
`operator-actions`, `failure-visibility`, `safety`, `install-effort`, `upgrade-effort`, `cost`,
`simplicity`.

**Methods** of demonstration. A demonstration cannot be due before its method exists; the
validator checks the last column.

| Method | What it is | Exists from |
|---|---|---|
| `replay` | The recorded legacy passes or records, run through Sortyard and compared (MIG-005) | MS2 |
| `parity` | A scenario built from a recorded legacy case, run in the scenario suite (REC-025) | MS2; the full suite at MS5 |
| `ledger` | A metric from Sortyard's ledger against the captured legacy figure (OBS-004) | MS4 on fixtures; MS7 on the pilot |
| `benchmark` | A scripted, timed or step-counted run, on Sortyard and where possible on the legacy tools | MS1 |
| `chaos` | Fault injection, with the recorded legacy outcome of the same fault as the baseline | MS2 |
| `count` | A count of things — stores, workloads, holders, steps, copies — against the legacy count | MS1 |
| `drill` | A rehearsed operation: install, upgrade, restore, rollback | MS3 |
| `usage` | The census of real use of a legacy feature (MIG-017) | MS0 |

**How a criterion is written.** A measured criterion reads
`<what is measured>. Target: <level>. Floor: <level>.` A demonstration reads
`Demonstration (<method>, MSn) — <the comparison>. Target: <level>. Floor: <level> (BL-nn).`,
where MSn is the milestone at whose exit it is due. A quantity that is a shipped policy default
is not a bar; it says "default" and has no levels.

**Verdicts** in the register (section 4):

| Verdict | Meaning | The entry must carry |
|---|---|---|
| `diverge` | Sortyard differs and must show it is better | Baseline, Better on, Demonstration |
| `diverge (reshaped)` | The design was changed on 2026-11-12 so that it can show it is better | The same |
| `conditional on use` | A cut that stands only if the usage census counts no use | The same, plus what happens if it is used |
| `keep legacy` | The estate keeps the behaviour: as a requirement, a setting of the estate bundle, or a thing left running outside the product | Kept by |
| `keep legacy (cut reversed)` | A cut in the earlier draft, now a requirement | Kept by |
| `not a divergence` | A change to the plan, not to what the estate does | Kept by: the legacy behaviour that continues |

---

## 2. Legacy baselines

Each baseline is captured by MIG-016 before anything changes, re-captured for each project
before its cutover, and loaded into Sortyard as a reference series. "Known today" is what the
sources already state; "to capture" means no figure exists yet and none is to be guessed. The
sources are the ones abbreviated in [17-evidence.md](17-evidence.md).

| Id | Baseline | How it is captured | Known today (evidence) |
|---|---|---|---|
| BL-01 | Throughput: merged changes a day, for each lane and project | Git host merge history for the driven repositories, with lanes from `repos.yaml`, over 28 days | 378 items went through review in the seven days to 2026-11-10 on 17 configured lanes, about 3 for each lane a day (CR "Review tripwire"; `repos.yaml`). Merges a day: to capture |
| BL-02 | Task-to-merge time: release to merge, p50 and p90, by project and task kind | Board activity (release time) joined to the merge time on the Git host | Not measured today; `metrics/analyze.py` reports open-to-merge for pull requests only. To capture |
| BL-03 | Control-plane wait in a chain: time spent waiting for the next pass at each hand-off | The recorded passes (MIG-002) and the frozen ledger: gap between the enabling fact and the action | The drive pass runs every 3 minutes and the sync every 5 (TP §3). Inference: a hand-off waits half a pass on average. Per-chain figure: to capture |
| BL-04 | Slot reuse: slot freed to next claim | The recorded passes | One pass at the least, up to 180 s (TP §3) |
| BL-05 | Stall episodes: every recorded case of work or a slot held with nothing acting, with its class, length, how it was found and how it ended | Incident notes, release notes and the frozen ledger | Two slots held about nine hours by a merge that never fired (HARNESS-242); cortexplane #1132 sat 20 hours on a missing check; loopmentum #498 waited 8 hours for a review; ROVE-764 sat two days in Backlog after main went green; eight red-main items handed back for 630 item-hours; a publish blocked about 33 hours by an unrunnable job (CR "Incident notes"; TP conformance row 1) |
| BL-06 | Recovery: time from a blocking cause resolving to the item being back in the queue; age of the self-heal queue | The `causes` records and board activity | Causes are polled at most every 30 minutes; one flat stall threshold of 4 hours; 35 self-heal items open, 21 untouched for 24 hours (CR "Blocking causes", "Self-heal drain"; HARNESS-444) |
| BL-07 | Operator interventions: actions by a person on work in flight, for each week and for each 100 merged changes (requeues, manual state or label changes, fixes applied by hand) | Board activity by human actors and the driver log, over 28 days | Not counted today. To capture |
| BL-08 | Silent failures: cases where a mechanism stopped or went wrong with no alarm, and how long until someone noticed | Release notes and incident notes | Every pass skipped for about 32 minutes on 2026-11-12 with only a log line; six tasks claimed into an unregistered build target on 2026-11-09; a Todo item with a stale record skipped every pass (CR "API rollouts"; HARNESS-256) |
| BL-09 | Answering "why was it not picked": steps and time | Scripted on the legacy tools for the TP §8 case and 20 sampled questions | A hand derivation from board comments and `state.json`; several waiting places are "Not visible" (TP §7, §8). Steps and time: to capture |
| BL-10 | Configuration lead time: from deciding a change to its being in force, for lanes and for caps and thresholds | Commit history of `repos.yaml` and of the files that hold the caps, with release times | Lanes change by a commit read at the next pass; caps are literals in three files and need a release (DRV §1; HARNESS-246). Times: to capture |
| BL-11 | Control-plane release: time from merge to running, people involved, failures | The release controller's records and Git history | Releases were manual (TP conformance row 8); the release of 2026-11-12 was blocked about 32 minutes by a hand-maintained Role. Merge-to-running time: to capture |
| BL-12 | Filing visibility: invisible filings, and the time until each was reported | The cited items and the sweep's cadence | Filings invisible for want of a label (HARNESS-608, HARNESS-615 to 618); the filing sweep reports after 30 minutes (CR "Filing visibility") |
| BL-13 | Install and onboarding effort: what a second installation of the legacy system takes | Counted from the runbooks; it cannot be installed to measure | About six repositories, a jump box and a private network (DESIGN §0); onboarding a project is one `repos.yaml` entry plus settings on each repository (onboarding.md) |
| BL-14 | Moving parts: long-lived workloads, scheduled jobs, host crons and stores of the delivery system | Cluster manifests, `mechanisms.yaml` and host crontabs | 68 registered mechanisms across the estate; stores: `state.json`, `grooming.json`, the dispatcher's SQLite database, JSONL ledgers, a shared work volume, the board's database. Plane's community bundle is 13 services with 4 stateful dependencies ([12-quality-bar.md](12-quality-bar.md) §1); the estate runs the commercial edition, whose count is to capture |
| BL-15 | Review churn: share of items at or over the tripwire, and the share of requests they take | The frozen ledger | 46 of 378 items reached five or more code reviews and took 44% of all requests, 2026-11-03 to 10 (CR "Review tripwire") |
| BL-16 | Delivery cost: agent-minutes and stages for each merged change, by project | Stage usage in the frozen ledger over merges from the Git host | A cost item exists for the current window only (CR `cost_item`). Series: to capture |
| BL-17 | Red main: time main is red, items filed for one outage, item-hours in hand-back | The frozen ledger and CI history | Nine items filed for one outage (CPV2-597 to 624); 630 item-hours handed back (CR `queue_triage`, `estate_access`). Time red: to capture |
| BL-18 | Operator journeys: steps, tools and time to find a task, see the health items, see why a task waits, reorder a milestone, file and release a task, find the stage outcome behind a task's state; and the legacy console's own journeys | Scripted or walked on Plane and the harness console | Two tools; the console's first journey has a 2 s bar and its bundle a 350 KB budget (HC J1; `check_budget.py`). Steps and times: to capture |
| BL-19 | Credential incidents: outages and hand steps caused by credentials | Driver log and release notes | A sign-out on 2026-11-01; a CLI release that killed every worker started in a six-minute window on 2026-10-27; the Git token's expiry tracked by hand (DRV §5, "Worker CLIs") |
| BL-20 | Operations inventory: every operation an operator or an operator-side agent performs today | Enumerated from DRV §4 "Tools", the console's end-to-end specs and the kinds of board activity | The scripts of CLI-005; console journeys J1 to J8 and 26 end-to-end spec files; steering on the board (order, Backlog, priority, decisions) |
| BL-21 | Usage of the features this specification does not carry | The usage census (MIG-017) | Not measured. To capture |
| BL-22 | Scheduling faults: cases where one fault degraded a whole pass | Task-pickup's conformance table and the items it cites | An exception in one claim aborts the pass (HARNESS-254); a failed clone made a pass order by priority alone (HARNESS-255); a stale record is skipped for ever (HARNESS-256) |
| BL-23 | Stage start: dispatch to the agent's first instruction; builds wasted on a missing base | Stage timings in the frozen ledger | Ten builds burned on one missing head (CPV2-408). Timing: to capture |
| BL-24 | State drift: disagreements between copies of state | The cited items and the drift check's output | Board says Todo while the record says claimed (HARNESS-256); four copies of the plan compared by the drift check, which filed false items on a board with no plan file (SORTYARD-68, SORTYARD-69) |
| BL-25 | Upgrade impact: downtime and failed work for each rollout | CR "API rollouts" and the release records | 30 to 40 seconds with nothing listening at every rollout; 11 rollouts in one day failed reviews, grooming and flake processing; a pass resumes at the next one, up to three minutes later |
| BL-26 | Privilege: the credentials, what each can do, who holds them | The manifests and the driver log | One board key shared by the sync and the driver and, by inference, the filing tools; the Git write credential is the owner's personal token in a cluster Secret; the console's identity header can be forged from inside the cluster (DRV §4, §5; HC decided D2, D16) |
| BL-27 | Reports and notifications: who writes them and at what cost | Driver log | An agent writes throughput reports and Slack cards; the daily pipeline record is a file in a repository (DRV §6; JQ) |
| BL-28 | Recorded limits: what the legacy system's own documents say it cannot do | Those documents | A running task cannot be cancelled (DRV §5, §7); board order cannot be written by API (TR); phase and slot use are only in `state.json` and the revision only a cluster annotation (TP conformance row 7); rank also matches by id prefix (TP §4); no revision is checked where side effects happen (in-flight-steering); the control plane is not protected from worker load (DESIGN §3.7b); code ships in a size-capped bundle (MECH) |

---

## 3. Scorecard

### 3.1 Headline targets

The outcomes the owner named, each with the level the plan aims at and the level a gate
enforces. Every row is an acceptance criterion; the full list follows in 3.2.

| Outcome | Target | Floor | Criterion |
|---|---|---|---|
| Install | One command and 3 minutes to a first task; one more command and 5 more minutes to a finished demo chain | 8 commands and 15 minutes; 30 minutes to the demo | DEP-005 AC1, DEP-005 AC2 |
| Task to merge | Half of one-PR tasks merged within 30 minutes of release when CI takes 10; the control plane adds at most 60 s to a chain | Faster than the legacy baseline at p50 and p90; at most half the legacy control-plane wait | FLW-019 AC2, FLW-019 AC1 |
| Stalls | Every catalogued stall class has a recovery; at least 95% of episodes heal with no person; found within 60 s, recovered within 10 minutes | A higher self-healed share and a lower median recovery time than the legacy system | REC-026 AC1 |
| Operator actions | None on work in flight: zero in a week | Fewer for each 100 merged tasks than the legacy baseline | REC-024 AC3 |
| Console latency | An input shows its result within 100 ms and a route within 200 ms at p95; first load 1 s; Overview in 500 ms | 1 s at p95 and no journey slower than the legacy console; first load 2 s; Overview 2 s | UI-018 AC3, UI-018 AC4, UI-009 AC3 |
| API latency | List and detail at 50 ms p95; a scheduler evaluation in 200 ms | 300 ms p95; 2 s | QLT-016 AC1, QLT-016 AC2 |
| Upgrade | Zero failed requests, zero missed events, zero paused seconds, zero stages retried | Failed requests for at most 5 s; a pause of at most 60 s and never silent; no extra attempt | DEP-010 AC1, REC-015 AC3, DEP-009 AC1 |
| Surface parity | Every command is a REST operation with a CLI path, MCP reach and a console control, at every merge | The same for REST, CLI and MCP at every merge; console exemptions empty at each milestone exit | API-001 AC3, UI-002 AC1 |
| Legacy parity | Every operation the estate performs today has a tested Sortyard equivalent by MS5; replay agrees on every recorded pass | Every operation in use, before the first cutover; replay agrees on at least 99% | CLI-005 AC2, MIG-005 AC1 |
| Slot reuse | A freed slot is claimed within 5 s at p95 | Within 30 s at p95 | SCH-006 AC1 |
| Recovery from a crash | A new leader reconciles within 15 s | Within 60 s | REC-014 AC3 |

### 3.2 Every measured criterion

Generated from the acceptance criteria. <!--gen:measured-->76<!--/gen--> criteria, of which
<!--gen:demo-count-->51<!--/gen--> are demonstrations against a legacy baseline. "Due" is the
milestone at whose exit the floor is enforced.

<!--gen:scorecard-->

| Criterion | Requirement | Method | Due | Target | Floor |
|---|---|---|---|---|---|
| MIG-017 AC1 | A usage census decides the conditional cuts | usage | MS0 | 100% of conditional entries have a count and a recorded outcome before the MS1 gate, and zero used features are left without a schedule or a demonstrated replacement | no feature with a count above zero is dropped at any cutover (BL-21) |
| QLT-012 AC2 | Every pull request runs everything | test | MS0 | 5 minutes | 15 minutes |
| TRK-005 AC1 | Hierarchy: parents and children | test | MS1 | in the same transaction | within 10 s |
| TRK-007 AC4 | Manual order is writable through the API | benchmark | MS1 | one call per move, each shown by the next list call in under 1 s, with nobody dragging | the whole reorder is done through the API in under 5 s per move; the legacy order cannot be written by API at all (BL-28) |
| API-001 AC3 | One versioned REST API with a served OpenAPI document | test | MS1 | 100% on all four at every merge, with no exemption | 100% for REST, CLI and MCP at every merge; console exemptions are dated and empty at each milestone exit (UI-002) |
| API-014 AC3 | Health and identity endpoints | count | MS1 | 100% from `/v1/info` in one call | none needs cluster access; the legacy revision is a cluster annotation (BL-28) |
| API-015 AC1 | Bulk filing | test | MS1 | under 1 s | under 5 s |
| IAM-008 AC4 | No agent can make its own work run | count | MS1 | zero credentials hold both, and 100% of the matrix cells are tested | fewer credentials hold both than in the legacy system, where one shared key does (BL-26) |
| IAM-011 AC2 | Audit log | test | MS1 | 1 s | 5 s |
| UI-002 AC1 | UI-for-everything is measured | test | MS1 | 100% at every merge to `main`, with no exemption | 100% at each milestone exit for the operations introduced in that milestone or earlier |
| UI-003 AC2 | Board and list | test | MS1 | 1 s | 5 s |
| UI-018 AC1 | Performance budgets | test | MS1 | 200 KB | 350 KB, the legacy console's budget |
| UI-018 AC3 | Performance budgets | test | MS1 | p95 at most 100 ms for an input and 200 ms for a route change | p95 at most 1 s, and no journey slower than on the legacy console (BL-18) |
| UI-018 AC4 | Performance budgets | test | MS1 | 1 s | 2 s |
| DEP-005 AC1 | Install time | test | MS1 | one command and 3 minutes | 8 commands and 15 minutes, with no step that requires editing a file |
| DEP-013 AC1 | Footprint | test | MS1 | 0.25 CPU and 512 MiB | 0.5 CPU and 1 GiB |
| DEP-020 AC2 | A release has one identity | count | MS1 | one call returns version, commit and digest, and one command installs a release by version with no build | fewer steps than reading the legacy annotation with cluster access, and no size cap on shipped code (BL-28) |
| QLT-011 AC1 | Coverage targets and floors | test | MS1 | 100%, 90% and 85% | 90%, 80% and 70%; CI fails below a floor |
| TRK-002 AC4 | One task object: tracker fields plus a typed spec | replay | MS2 | 100% of items yield the typed fields the legacy parser read, and 100% of the invisible filings are refused or returned with a non-visible verdict in the filing response itself | every invisible filing is reported in the filing response; the legacy system reported them only at a later sweep (BL-12) |
| TRK-009 AC3 | Labels are for people; flags are for the system | replay | MS2 | 100% map to typed fields, and a task that is eligible in every respect but one names that one in its verdict | no legacy control state is unrepresentable, and no task can be invisible for want of a label (BL-12) |
| TRK-014 AC4 | Board, list and filters | benchmark | MS2 | every journey takes at most half the legacy steps, in one tool, with each view rendered in under 1 s | no journey takes more steps or more time than on the legacy pair, and none needs a second tool (BL-18) |
| RDY-010 AC3 | No side door into the queue | parity | MS2 | 100% are refused at filing with the failing check named, and none is released | none becomes claimable in the Pickup Preview; the legacy system claimed all six (BL-08) |
| SCH-003 AC3 | Milestone rank comes from the parent chain | replay | MS2 | 100% of recorded claim orders are reproduced, with every prefix-ranked task linked to its parent by the importer and none left for a person | no divergence in the replay comparison (MIG-005) is caused by rank, and renaming a task changes no rank, which it can under the legacy rule (BL-28) |
| SCH-008 AC2 | Pickup Preview | test | MS2 | 1 s | 5 s |
| SCH-008 AC4 | Pickup Preview | benchmark | MS2 | one call or one screen answers in under 1 s for 100% of the places | every place is answered in fewer steps than the legacy route, which needs `state.json` from the cluster or a hand derivation (BL-09) |
| SCH-010 AC4 | Decision log | replay | MS2 | 100% answered by one query in under 1 s, each naming the tasks ranked ahead | 100% answered without reading comments or cluster files; the legacy answer is a hand derivation (BL-09) |
| SCH-011 AC3 | Tuning is live, audited data | benchmark | MS2 | one action, in force within 5 s, with its audit entry | a lane change is no slower than the legacy commit route, and a cap or threshold change needs no code change and no release (BL-10) |
| SCH-015 AC3 | Decisions come from one consistent snapshot | chaos | MS2 | zero claims are decided from a partial read, and the health view names the unreadable input within one evaluation | zero evaluations order by fewer keys; the legacy pass ordered by priority alone after a failed clone (BL-22) |
| MIG-005 AC1 | Replay comparison | test | MS2 | 100% | at least 99% |
| TRK-004 AC5 | Task states and reason-carrying transitions | chaos | MS3 | zero runs end with board state and queue status in disagreement, with no repair step | zero disagreements once the controller has restarted; the legacy system recorded this disagreement in production (BL-24) |
| SCH-006 AC1 | A freed slot is reused promptly | benchmark | MS3 | p95 at most 5 s | p95 at most 30 s and maximum at most 120 s; the legacy minimum is one pass, up to 180 s (BL-04) |
| SCH-014 AC3 | Failure isolation between items and projects | chaos | MS3 | every other task and project is evaluated, claimed and advanced in the same cycle, with at most 5 s of added delay | no other task or project is skipped in that cycle; the legacy pass aborted (BL-22) |
| SCH-016 AC3 | Claims are atomic and fenced | chaos | MS3 | zero duplicate chains, zero tasks left Todo with a live record, and no repair step | zero of either after restart; the legacy system left such a task skipped every pass (BL-24) |
| EXE-009 AC3 | Mirrors and run output do not need a shared volume | benchmark | MS3 | p95 at most 20 s on both | it runs on three nodes with no shared volume, and is no slower than the legacy stage start on one node (BL-23) |
| EXE-020 AC1 | The control plane is protected from its workers | chaos | MS3 | API p95 at most 300 ms and event-stream lag at most 5 s, with no control-plane pod evicted or restarted | API p95 at most 1 s and no control-plane pod evicted; the legacy system has no such protection (BL-28) |
| EXE-022 AC1 | A running stage can be cancelled | benchmark | MS3 | the pod is gone and the slot free within 10 s, and 100% of late results are refused | within 60 s, and no late result is accepted (fenced by epoch); the legacy system cannot cancel a running task (BL-28) |
| REC-011 AC2 | Phase and age are always visible | count | MS3 | 100% through the API, the CLI and the console, each within 1 s | none needs cluster access; in the legacy system every one of them does (BL-28) |
| REC-014 AC3 | Controller restart and failover | chaos | MS3 | at most 15 s, with an end state equal to a run with no kills | at most 60 s; the legacy system resumes at its next pass, up to three minutes later (BL-25) |
| REC-015 AC3 | Version skew never pauses delivery silently | chaos | MS3 | zero paused seconds, and a stuck upgrade reported within 60 s | paused at most 60 s and never silently; the legacy system skipped every pass for about 32 minutes with only a log line (BL-08, BL-25) |
| REC-020 AC3 | One writer per chain, enforced at the side-effect boundary | chaos | MS3 | 100% refused at the integrator or the API and recorded as stale | zero stale side effects accepted; the legacy system has no check at that boundary (BL-28) |
| API-002 AC3 | Commands live in the domain layer; the API adds no rules | chaos | MS3 | claims, the advancement of finished stages and landing continue throughout, every result produced meanwhile is accepted when the API returns, and zero stages fail | no evaluation is skipped and no stage fails because the API is down; the legacy conductor skipped every pass while its API was unavailable (BL-25) |
| UI-004 AC3 | Task detail is one timeline | benchmark | MS3 | zero navigation, shown within 1 s of opening the task | fewer steps than the legacy route across two tools (BL-18) |
| UI-009 AC3 | Overview: glance at the floor | test | MS3 | 500 ms | 2 s, the legacy console's bar for the same journey |
| UI-011 AC1 | Logs and traces | test | MS3 | first lines within 300 ms and no frame over 50 ms while scrolling | no frame over 200 ms (frame budget asserted in the e2e test) |
| DEF-002 AC3 | The database is authoritative; files are how definitions travel | chaos | MS3 | 100% refused as a whole with the reason, the last valid version in force throughout, and the refusal visible within one evaluation | zero evaluations run on partial or default configuration; a legacy pass did after a failed clone (BL-22) |
| DEF-003 AC3 | Source lock and pull | benchmark | MS3 | in force within 30 s, with no operator step | within 180 s with no operator step, as the legacy pass does today, and a failed read keeps the last valid version in force (BL-10, BL-22) |
| DEP-001 AC3 | One chart, one image, three control-plane workloads | count | MS3 | three Deployments, one StatefulSet and one migration Job, with zero CronJobs and zero host crons | fewer long-lived workloads, fewer scheduled jobs and fewer stores than the legacy inventory (BL-14) |
| DEP-002 AC3 | Installable by a namespace admin | drill | MS3 | one `helm upgrade`, zero objects applied by hand, the controller's Role rendered by the chart | no release needs an object applied by hand; the legacy release of 2026-11-12 did (BL-11) |
| DEP-005 AC2 | Install time | test | MS3 | one more command and 5 minutes more | 30 minutes in total |
| DEP-009 AC1 | Work in flight survives upgrades and restarts | chaos | MS3 | zero stages failed or retried because of an upgrade, and zero results lost | no extra attempt caused by an upgrade; on such a day the legacy system failed reviews and grooming (BL-25) |
| DEP-010 AC1 | Upgrades without downtime | chaos | MS3 | zero failed requests, zero missed events and at most 15 s without a leader | failed requests for at most 5 s in an upgrade and no event missed after reconnecting; the legacy rollout has nothing listening for 30 to 40 seconds (BL-25) |
| TRK-018 AC4 | Follow-up items never enter the queue by themselves | count | MS4 | zero, with no such state in the schema | zero; the usage census counts the blocked follow-up requests that rejected verifies left in the legacy dispatcher (BL-21) |
| CRD-007 AC4 | Git host credential: least privilege, minted, integrator-only | count | MS4 | a token per operation, scoped to one repository, readable by one pod and revoked when the operation ends | fewer permissions, fewer holders and a shorter lifetime than the legacy personal token, and no expiry date for a person to track (BL-26) |
| FLW-019 AC1 | The control plane adds almost nothing to a task's time | ledger | MS4 | p95 at most 60 s per chain, summed over all its hand-offs | at most half the legacy wait for the same number of hand-offs, each of which waits for the next three-minute or five-minute pass (BL-03) |
| REC-021 AC3 | Steering work in flight | benchmark | MS4 | one action each, in force at the next stage, with only invalidated reviews re-run | each is done from the console with no cluster access and no competing chain; the legacy procedure is manual (BL-28) |
| GRM-007 AC3 | Internal consistency sweep replaces drift consolidation | count | MS5 | zero second copies and zero false findings | fewer copies than the legacy four, and fewer false findings than the legacy check filed on the same boards (BL-24) |
| REC-001 AC3 | Every wait has an exit | parity | MS5 | every slot is freed at its bound with the item parked, handed back or escalated, and no episode needs a person to free a slot | no slot is held past its bound in any catalogued episode; the legacy system held slots for hours in each of them (BL-05) |
| REC-008 AC4 | Blocking causes bring parked work back by themselves | parity | MS5 | back within 60 s for every cause Sortyard observes itself | back within 5 minutes; the legacy poll is at most every 30 minutes (BL-06) |
| REC-024 AC3 | The owner is never a step inside delivery | test | MS5 | zero in a week | fewer for each 100 merged tasks than the legacy baseline (BL-07) |
| REC-026 AC1 | Stalls are detected and recovered in minutes | chaos | MS5 | 100% of catalogued classes have a recovery, at least 95% of episodes heal with no person, detection within 60 s and recovery within 10 minutes at p95 | a higher self-healed share and a lower median time to recovery than the legacy baselines (BL-05, BL-06) |
| MCP-002 AC3 | Curated, role-scoped tools | benchmark | MS5 | 100% of the inventory done with at most 25 tools in view, no cluster access and no shell | every operation the legacy scripts offer is done without cluster access or the shared board key (BL-20, BL-26) |
| CLI-005 AC2 | Parity with the legacy operator tools | test | MS5 | 100% by the MS5 gate | 100% of the operations the usage census (MIG-017) shows in use, before the first cutover |
| EXT-001 AC3 | Three ways to extend, none of them in-process | benchmark | MS5 | each in force within 5 minutes, with zero control-plane restarts and no new control-plane image | none needs a release of the control plane; in the legacy system each is a code change and a release (BL-11) |
| IAM-002 AC4 | Operator sign-in | chaos | MS6 | 100% refused and audited, in every mode | zero forged requests accepted; the legacy backend accepts them until it is locked down (BL-26) |
| UI-026 AC4 | Embedded concierge | test | MS6 | 1 s | no slower than the legacy concierge (BL-18) |
| OBS-009 AC2 | Daily record | ledger | MS6 | byte-identical on every re-run, ready within 60 s of the day's end, with zero model calls | every figure of the legacy report is present and reproducible, and no agent run is spent writing it (BL-27) |
| DEP-003 AC3 | Postgres and one blob location, nothing else | drill | MS6 | one database and one blob location, restored to an identical ledger sequence within 5 minutes | restored within 30 minutes, from fewer stores than the legacy inventory (BL-14) |
| QLT-016 AC1 | Performance bars on a reference workload | test | MS6 | p95 at most 50 ms | p95 at most 300 ms |
| QLT-016 AC2 | Performance bars on a reference workload | test | MS6 | at most 200 ms | at most 2 s |
| QLT-016 AC3 | Performance bars on a reference workload | test | MS6 | at most 250 ms | at most 2 s |
| FLW-019 AC2 | The control plane adds almost nothing to a task's time | ledger | MS7 | p50 at most 30 minutes for a task whose CI takes 10 minutes | a lower p50 and a lower p90 than the legacy baseline for tasks of the same kind (BL-02) |
| OBS-001 AC4 | One ordered ledger, written with the state it describes | count | MS7 | one store, and zero state changes without an event over the whole pilot | fewer stores than the legacy inventory, and zero unexplained differences between tables and events (BL-14, BL-24) |
| OBS-006 AC2 | Delivery cost | ledger | MS7 | no agent-minute is spent on a stage that could not succeed (missing base, unregistered target, unreadable input), and the figure is available for any window and project within 1 s | cost for each merged change no higher than the legacy baseline, and the figure kept as a series for any past window, which the legacy item cannot give (BL-16) |
| MIG-009 AC3 | Hypercare and rollback | drill | MS7 | within 5 minutes, with zero tasks lost, duplicated or claimed by both systems | within 30 minutes with the same zero, and with no sync component running during hypercare; a projection would keep a second copy of every task, and second copies have drifted (BL-24) |
| QLT-024 AC2 | Releases come from CI, from a tag | ledger | MS7 | every merge running within 10 minutes, with no person involved | no person and no hand-applied object involved, and no slower than the legacy merge-to-release time; the legacy release of 2026-11-12 needed a Role applied by hand (BL-11) |
| QLT-020 AC2 | Security policy and response | test | MS8 | one business day and 7 days | three business days and 30 days |

<!--/gen-->

---

## 4. Divergence register

<!--gen:verdicts-->42 entries: 23 diverge, 2 diverge (reshaped), 5 conditional on use, 8 keep legacy, 1 keep legacy (cut reversed), 3 not a divergence<!--/gen-->. The index below lists every requirement of origin `FIX` with
its entry here and its demonstrations; it is generated.

<!--gen:divergence-index-->

| Requirement | Title | Better on | Entry | Demonstrations (due) |
|---|---|---|---|---|
| TRK-002 | One task object: tracker fields plus a typed spec | failure-visibility, safety, simplicity | DIV-02 | AC4 (MS2) |
| TRK-004 | Task states and reason-carrying transitions | safety, failure-visibility, operator-actions | DIV-02 | AC5 (MS3) |
| TRK-007 | Manual order is writable through the API | operator-actions, latency | DIV-01 | AC4 (MS1) |
| TRK-009 | Labels are for people; flags are for the system | failure-visibility, safety | DIV-02 | AC3 (MS2) |
| TRK-014 | Board, list and filters | operator-actions, latency, simplicity, install-effort | DIV-01 | AC4 (MS2) |
| RDY-010 | No side door into the queue | safety, failure-visibility | DIV-03 | AC3 (MS2) |
| GRM-007 | Internal consistency sweep replaces drift consolidation | simplicity, failure-visibility | DIV-22 | AC3 (MS5) |
| SCH-003 | Milestone rank comes from the parent chain | safety, simplicity | DIV-07 | AC3 (MS2) |
| SCH-006 | A freed slot is reused promptly | latency, throughput | DIV-05 | AC1 (MS3) |
| SCH-008 | Pickup Preview | failure-visibility, operator-actions, latency | DIV-06 | AC4 (MS2) |
| SCH-010 | Decision log | failure-visibility, operator-actions | DIV-06 | AC4 (MS2) |
| SCH-011 | Tuning is live, audited data | latency, operator-actions, failure-visibility | DIV-08 | AC3 (MS2) |
| SCH-014 | Failure isolation between items and projects | stall-rate, throughput, safety | DIV-05 | AC3 (MS3) |
| SCH-015 | Decisions come from one consistent snapshot | safety, failure-visibility | DIV-05 | AC3 (MS2) |
| SCH-016 | Claims are atomic and fenced | safety, stall-rate | DIV-05 | AC3 (MS3) |
| EXE-009 | Mirrors and run output do not need a shared volume | install-effort, simplicity, safety | DIV-11 | AC3 (MS3) |
| EXE-020 | The control plane is protected from its workers | safety, stall-rate | DIV-12 | AC1 (MS3) |
| EXE-022 | A running stage can be cancelled | operator-actions, recovery-time, safety | DIV-13 | AC1 (MS3) |
| CRD-007 | Git host credential: least privilege, minted, integrator-only | safety, operator-actions | DIV-17 | AC4 (MS4) |
| FLW-019 | The control plane adds almost nothing to a task's time | latency, throughput | DIV-05 | AC1 (MS4), AC2 (MS7) |
| REC-001 | Every wait has an exit | stall-rate, recovery-time, operator-actions | DIV-14 | AC3 (MS5) |
| REC-008 | Blocking causes bring parked work back by themselves | recovery-time, throughput | DIV-14 | AC4 (MS5) |
| REC-011 | Phase and age are always visible | failure-visibility, operator-actions | DIV-06 | AC2 (MS3) |
| REC-014 | Controller restart and failover | recovery-time, safety, upgrade-effort | DIV-15 | AC3 (MS3) |
| REC-015 | Version skew never pauses delivery silently | stall-rate, failure-visibility, upgrade-effort | DIV-10 | AC3 (MS3) |
| REC-020 | One writer per chain, enforced at the side-effect boundary | safety | DIV-13 | AC3 (MS3) |
| REC-021 | Steering work in flight | operator-actions, safety, cost | DIV-13 | AC3 (MS4) |
| REC-026 | Stalls are detected and recovered in minutes | stall-rate, recovery-time, operator-actions, failure-visibility | DIV-14 | AC1 (MS5) |
| API-002 | Commands live in the domain layer; the API adds no rules | stall-rate, safety, upgrade-effort | DIV-10 | AC3 (MS3) |
| API-014 | Health and identity endpoints | failure-visibility, operator-actions | DIV-18 | AC3 (MS1) |
| MCP-002 | Curated, role-scoped tools | safety, operator-actions, install-effort | DIV-16 | AC3 (MS5) |
| IAM-002 | Operator sign-in | safety | DIV-16 | AC4 (MS6) |
| IAM-008 | No agent can make its own work run | safety | DIV-16 | AC4 (MS1) |
| UI-004 | Task detail is one timeline | operator-actions, latency, failure-visibility | DIV-20 | AC3 (MS3) |
| OBS-001 | One ordered ledger, written with the state it describes | simplicity, safety, failure-visibility | DIV-04 | AC4 (MS7) |
| OBS-006 | Delivery cost | cost, failure-visibility | DIV-21 | AC2 (MS7) |
| OBS-009 | Daily record | cost, failure-visibility | DIV-21 | AC2 (MS6) |
| DEF-002 | The database is authoritative; files are how definitions travel | safety, failure-visibility | DIV-09 | AC3 (MS3) |
| DEF-003 | Source lock and pull | latency, failure-visibility, safety | DIV-09 | AC3 (MS3) |
| EXT-001 | Three ways to extend, none of them in-process | operator-actions, safety, upgrade-effort | DIV-23 | AC3 (MS5) |
| DEP-001 | One chart, one image, three control-plane workloads | simplicity, install-effort, upgrade-effort | DIV-19 | AC3 (MS3) |
| DEP-002 | Installable by a namespace admin | upgrade-effort, operator-actions, safety | DIV-18 | AC3 (MS3) |
| DEP-003 | Postgres and one blob location, nothing else | simplicity, recovery-time, install-effort | DIV-04 | AC3 (MS6) |
| DEP-009 | Work in flight survives upgrades and restarts | upgrade-effort, stall-rate, cost | DIV-18 | AC1 (MS3) |
| DEP-010 | Upgrades without downtime | upgrade-effort, stall-rate, failure-visibility | DIV-18 | AC1 (MS3) |
| DEP-020 | A release has one identity | failure-visibility, install-effort, safety | DIV-18 | AC2 (MS1) |
| QLT-024 | Releases come from CI, from a tag | latency, operator-actions, safety | DIV-18, DIV-27 | AC2 (MS7) |

<!--/gen-->

### DIV-01 — The board is native; Plane is not carried
- **Verdict:** diverge
- **Covers:** CF-03; [01-product-definition.md](01-product-definition.md) §5.1 (views, modules); the decision recorded as settled in [15-open-decisions.md](15-open-decisions.md) (DESIGN §5.2 option C).
- **Legacy baseline:** The operator steers on a Plane board and reads the pipeline in a second tool; the board's order cannot be written by API (BL-18, BL-14, BL-28).
- **Sortyard:** One console over one store: board, list, filters, reorder by drag, keyboard or API (TRK-014, TRK-007, UI-003).
- **Better on:** operator-actions, latency, simplicity, install-effort.
- **Not better on:** breadth of project-management features; see DIV-38.
- **Demonstration:** TRK-014 AC4, TRK-007 AC4.

### DIV-02 — A typed task replaces the spec block, control labels and text marks
- **Verdict:** diverge
- **Covers:** LP-001, LP-030; CF-20; [01-product-definition.md](01-product-definition.md) §5.1 (labels), §5.3 (text marks).
- **Legacy baseline:** The spec is a fenced block in the description; release, queue status and routing are labels; state is also in `state.json`. Filings have been invisible for want of a label, and board and record have disagreed (BL-12, BL-24).
- **Sortyard:** One task object with typed fields; queue status is a field changed in the same transaction as board state (TRK-002, TRK-004, TRK-009).
- **Better on:** failure-visibility, safety, simplicity.
- **Not better on:** nothing found; free-form labels remain for people.
- **Demonstration:** TRK-002 AC4, TRK-004 AC5, TRK-009 AC3.

### DIV-03 — No side door into the queue
- **Verdict:** diverge
- **Covers:** LP-016.
- **Legacy baseline:** Items filed directly on boards with task release off bypass the ready rules and preflight; six such tasks were claimed into an unregistered build target (BL-08).
- **Sortyard:** Every released task passes the same gates, however it was filed (RDY-010).
- **Better on:** safety, failure-visibility.
- **Not better on:** filing an ad-hoc item takes one more check; a task that fails it is refused where today it would start.
- **Demonstration:** RDY-010 AC3.

### DIV-04 — One transactional store replaces the files, the SQLite database, the JSONL ledgers and the sync
- **Verdict:** diverge
- **Covers:** CF-11; [01-product-definition.md](01-product-definition.md) §5.3 (`state.json`), §5.4 (the sync itself), §5.5 (SQLite, JSONL).
- **Legacy baseline:** State and history live in several stores with no common order, kept in step by a sync job; they have disagreed in production (BL-14, BL-24).
- **Sortyard:** Postgres holds state, ledger and queue; every change writes its event in the same transaction; blobs go to one location (OBS-001, DEP-003).
- **Better on:** simplicity, safety, failure-visibility, recovery-time.
- **Not better on:** a database is now required where files sufficed; an operator can no longer read state with `cat`.
- **Demonstration:** OBS-001 AC4, DEP-003 AC3.

### DIV-05 — Scheduling and hand-offs on events replace polling passes
- **Verdict:** diverge
- **Covers:** LP-034, LP-035, LP-036, LP-037; CF-12; [01-product-definition.md](01-product-definition.md) §5.3 (three-minute passes).
- **Legacy baseline:** Everything happens at the next pass: 3 minutes for the driver, 5 for the sync. One exception aborts a pass; one failed read degrades it (BL-03, BL-04, BL-22).
- **Sortyard:** Each item is reconciled on the event that concerns it, with a periodic full evaluation as a backstop; one snapshot for each decision; atomic, fenced claims (SCH-006, SCH-014, SCH-015, SCH-016, FLW-019).
- **Better on:** latency, throughput, stall-rate, safety.
- **Not better on:** a pass log was easy to read end to end; the decision log (DIV-06) has to replace that.
- **Demonstration:** SCH-006 AC1, SCH-014 AC3, SCH-015 AC3, SCH-016 AC3, FLW-019 AC1, FLW-019 AC2.

### DIV-06 — The scheduler explains itself
- **Verdict:** diverge
- **Covers:** LP-041; CF-19 (visibility gaps).
- **Legacy baseline:** Why a task waits is a hand derivation; phase and slot use are in a file on a cluster volume (BL-09, BL-28).
- **Sortyard:** Pickup Preview, reason codes, a decision log and phase visibility through API, CLI and console (SCH-008, SCH-010, REC-011).
- **Better on:** failure-visibility, operator-actions, latency.
- **Not better on:** nothing found.
- **Demonstration:** SCH-008 AC4, SCH-010 AC4, REC-011 AC2.

### DIV-07 — Rank comes from parent links only
- **Verdict:** diverge
- **Covers:** LP-032.
- **Legacy baseline:** Milestone rank also matches a task by id prefix, so text decides order (BL-28).
- **Sortyard:** Rank follows the parent relation; the importer converts prefix matches into parent links once (SCH-003).
- **Better on:** safety, simplicity.
- **Not better on:** a task named by convention but never linked gets no rank until someone links it; the importer's report lists them.
- **Demonstration:** SCH-003 AC3.

### DIV-08 — Tuning is live, audited data
- **Verdict:** diverge
- **Covers:** LP-042.
- **Legacy baseline:** Lanes change by commit; caps and thresholds are literals in three files and need a release (BL-10).
- **Sortyard:** Every tunable is a policy key read at decision time, with history (SCH-011, DEF-005). On a locked installation the change still arrives by commit (DIV-09).
- **Better on:** latency, operator-actions, failure-visibility.
- **Not better on:** nothing found for caps; for lanes on a locked installation the route is the same as today.
- **Demonstration:** SCH-011 AC3.

### DIV-09 — Definitions live in the database; a locked installation pulls them from Git
- **Verdict:** diverge (reshaped)
- **Covers:** CF-06; OD-5; the "definitions sync controller" row of OD-3.
- **Legacy baseline:** `repos.yaml` is read from a Git clone on every pass: a merged change is in force within one pass with no further step. A failed clone degraded a pass (BL-10, BL-22).
- **Sortyard:** Versions in the database, with validation, history and export (DEF-002). A locked installation pulls its definitions from the configured Git source itself, by poll and webhook; the last valid version stays in force (DEF-003). The earlier draft relied on a CI job running `apply`, which was slower and less visible than the legacy pull; that design was dropped.
- **Better on:** latency, failure-visibility, safety.
- **Not better on:** a two-way synchroniser (edit in the console, written back to Git) is still not built; no legacy behaviour depends on one.
- **Demonstration:** DEF-002 AC3, DEF-003 AC3.

### DIV-10 — The controller does not depend on the API, and version skew never pauses delivery silently
- **Verdict:** diverge
- **Covers:** LP-175; CF-07.
- **Legacy baseline:** The conductor is a client of the dispatcher's API and skips its pass on version skew; it skipped every pass for about 32 minutes on 2026-11-12 with no alarm (BL-08, BL-25).
- **Sortyard:** The controller calls the domain layer in-process (API-002). Adjacent versions run side by side; only a schema outside the supported window idles the controller, visibly (REC-015).
- **Better on:** stall-rate, failure-visibility, upgrade-effort, safety.
- **Not better on:** supporting the previous minor's schema and stage contract costs work at every release (DEP-007).
- **Demonstration:** API-002 AC3, REC-015 AC3.

### DIV-11 — Workers reach mirrors over the network, not a shared volume
- **Verdict:** diverge
- **Covers:** LP-056; CF-11.
- **Legacy baseline:** Mirrors and run directories are on one volume mounted by every Job, which needs one node or `ReadWriteMany` storage (BL-14, BL-23).
- **Sortyard:** Read-only Git over HTTP from a mirror service, with commits returned to a staging namespace (EXE-009). The shared-volume mode stays available, and an installation keeps it if the benchmark does not show the network path at least as fast.
- **Better on:** install-effort, simplicity, safety.
- **Not better on:** possibly stage start time on a single node; that is what the benchmark decides.
- **Demonstration:** EXE-009 AC3.

### DIV-12 — The control plane is protected from its workers
- **Verdict:** diverge
- **Covers:** LP-072.
- **Legacy baseline:** Workers run with small requests and no quota or priority class (BL-28).
- **Sortyard:** A worker namespace with ResourceQuota and LimitRange, requests on the control plane, an optional PriorityClass (EXE-020).
- **Better on:** safety, stall-rate.
- **Not better on:** a quota can refuse a stage that would have started; admission caps are sized to stay below it.
- **Demonstration:** EXE-020 AC1.

### DIV-13 — Work in flight can be stopped and steered
- **Verdict:** diverge
- **Covers:** LP-070, LP-187.
- **Legacy baseline:** A running task cannot be cancelled; steering is a prose procedure; no revision is checked where side effects happen (BL-28).
- **Sortyard:** Cancel a stage or a chain, edit a task mid-flight, with an epoch checked at the integrator and the API (EXE-022, REC-020, REC-021).
- **Better on:** operator-actions, recovery-time, safety, cost.
- **Not better on:** nothing found.
- **Demonstration:** EXE-022 AC1, REC-020 AC3, REC-021 AC3.

### DIV-14 — Stalls are bounded, found and healed in minutes
- **Verdict:** diverge
- **Covers:** LP-178; [01-product-definition.md](01-product-definition.md) §5.7 (stall watches).
- **Legacy baseline:** One flat 4-hour stall threshold; causes polled every 30 minutes; watches and a person find the rest. Recorded stalls ran 8 hours to two days (BL-05, BL-06).
- **Sortyard:** Every phase bounded (REC-001); causes re-evaluated on the resolving event (REC-008); bounds from each phase's own history, a no-progress watchdog and an announced self-heal queue (REC-026).
- **Better on:** stall-rate, recovery-time, operator-actions, failure-visibility.
- **Not better on:** a bound learned from history can be wrong for a phase that changes character; the ceiling stays the legacy threshold.
- **Demonstration:** REC-001 AC3, REC-008 AC4, REC-026 AC1.

### DIV-15 — Leader election replaces single-writer by `Forbid` and `Recreate`
- **Verdict:** diverge
- **Covers:** LP-184.
- **Legacy baseline:** One writer is guaranteed by CronJob concurrency and a `Recreate` rollout; interrupted work waits for the next pass (BL-25).
- **Sortyard:** A leader with a fencing epoch that hands over on shutdown (REC-014).
- **Better on:** recovery-time, safety, upgrade-effort.
- **Not better on:** leader election is more machinery than a CronJob flag; the chaos test is what keeps it honest.
- **Demonstration:** REC-014 AC3.

### DIV-16 — Scoped identities replace the shared board key and the proxy header
- **Verdict:** diverge
- **Covers:** LP-223; CF-08, CF-09.
- **Legacy baseline:** One board key is shared by the sync and the driver, and by inference by the filing tools; the console trusts a header that pods can forge; agents operate through scripts that need a cluster shell (BL-26, BL-20).
- **Sortyard:** Roles, scoped tokens, sign-in that cannot be forged from inside the cluster, and curated tools for each role over MCP (IAM-008, IAM-002, MCP-002).
- **Better on:** safety, operator-actions, install-effort.
- **Not better on:** more credentials to issue and rotate than one shared key; expiry is tracked by the product (IAM-005).
- **Demonstration:** IAM-008 AC4, IAM-002 AC4, MCP-002 AC3.

### DIV-17 — A minted Git credential replaces the owner's personal token
- **Verdict:** diverge
- **Covers:** LP-085; CF-25; OD-6.
- **Legacy baseline:** The Git write credential is the owner's personal token in a cluster Secret, with an expiry tracked by hand (BL-26).
- **Sortyard:** A GitHub App whose tokens are minted for one operation and one repository, readable only by the integrator (CRD-007).
- **Better on:** safety, operator-actions.
- **Not better on:** the App must be installed on each organisation, which is the owner's action; a long-lived App key is in the cluster.
- **Demonstration:** CRD-007 AC4.

### DIV-18 — Releases by chart and image replace the bundle, its size cap and the bespoke controller
- **Verdict:** diverge
- **Covers:** LP-260, LP-262, LP-263, LP-264, LP-265, LP-266; [01-product-definition.md](01-product-definition.md) §5.5 (release controller).
- **Legacy baseline:** Code ships as a size-capped bundle; merged was not released; a hand-maintained Role blocked a release; every rollout has 30 to 40 seconds of nothing listening; the revision is a cluster annotation (BL-11, BL-25, BL-28).
- **Sortyard:** Releases only from CI, a development build for every merge, one identity for chart, image and version, a namespace-admin install, surge rollouts and work that survives them (QLT-024, DEP-020, DEP-002, DEP-009, DEP-010, API-014). The legacy guarantees are kept: exact-commit builds, digest pinning, no cluster credential in CI.
- **Better on:** latency, upgrade-effort, operator-actions, failure-visibility, safety.
- **Not better on:** the legacy controller pulls a release into the cluster by itself; Sortyard leaves that to the operator's GitOps tool (DEP-016).
- **Demonstration:** QLT-024 AC2, DEP-020 AC2, DEP-002 AC3, DEP-009 AC1, DEP-010 AC1, API-014 AC3.

### DIV-19 — Fewer moving parts
- **Verdict:** diverge
- **Covers:** CF-10; [01-product-definition.md](01-product-definition.md) §5.7 (host crons).
- **Legacy baseline:** A board installation, an API, CronJobs, a release controller, a health job, host crons and a tools pod (BL-14).
- **Sortyard:** Three Deployments and Postgres; mirror refresh, credential sync and health checks are loops inside the controller, each registered with a freshness window (DEP-001, EXE-008, CRD-006, REC-017).
- **Better on:** simplicity, install-effort, upgrade-effort.
- **Not better on:** a loop inside the controller shares its fate; the health checker runs apart from what it watches (REC-017).
- **Demonstration:** DEP-001 AC3.

### DIV-20 — A task's page is its pipeline
- **Verdict:** diverge
- **Covers:** [01-product-definition.md](01-product-definition.md) §3 problem 8.
- **Legacy baseline:** The ticket is in one tool and its runs in another (BL-18).
- **Sortyard:** One timeline for each task, with its chain, stages, change request and checks (UI-004).
- **Better on:** operator-actions, latency, failure-visibility.
- **Not better on:** nothing found.
- **Demonstration:** UI-004 AC3.

### DIV-21 — Metrics and reports come from the ledger
- **Verdict:** diverge
- **Covers:** LP-154, LP-281; [01-product-definition.md](01-product-definition.md) §5.2 (external dashboards), §5.4 (health summary item), §5.7 (Slack cards and reports).
- **Legacy baseline:** A cost item and a health item are rewritten on each board; an agent writes throughput reports and Slack cards (BL-16, BL-27).
- **Sortyard:** A metric catalogue over the ledger, dashboards in the console, a generated daily record, notifications by rule (OBS-004, OBS-006, OBS-009, OBS-013).
- **Better on:** cost, failure-visibility, latency.
- **Not better on:** an agent's report can comment and judge; a generated record only states. The operator's own agent can still write one over MCP.
- **Demonstration:** OBS-006 AC2, OBS-009 AC2.

### DIV-22 — An internal sweep replaces drift consolidation
- **Verdict:** diverge
- **Covers:** LP-155, LP-156.
- **Legacy baseline:** A check compares four copies of the plan and files what disagrees, false items included (BL-24).
- **Sortyard:** The copies do not exist; a daily sweep reports what can still drift inside one store (GRM-007).
- **Better on:** simplicity, failure-visibility.
- **Not better on:** nothing found, provided no second copy of the plan is kept outside Sortyard; the one-source audit checks that (MIG-011).
- **Demonstration:** GRM-007 AC3.

### DIV-23 — New behaviour without a release of the control plane
- **Verdict:** diverge
- **Covers:** CF-05 (extension).
- **Legacy baseline:** A new check, sensor or workflow step is a change to the conductor's code and a release of its bundle (BL-11, BL-10).
- **Sortyard:** Definitions applied as bundles, containers under a contract, and HTTP (EXT-001).
- **Better on:** operator-actions, safety, upgrade-effort.
- **Not better on:** behaviour that needs new code inside the scheduler is still a release.
- **Demonstration:** EXT-001 AC3.

### DIV-24 — Pull requests belong to their task; issues are not mirrored onto the board
- **Verdict:** conditional on use
- **Covers:** LP-153; [01-product-definition.md](01-product-definition.md) §5.4.
- **Legacy baseline:** The sync projects issues and pull requests onto the board as items (BL-21 for whether anyone acts on them).
- **Sortyard:** A pull request is part of its task's timeline (TRK-017); one opened outside becomes a `review` task (FLW-014); issues are not copied.
- **Better on:** simplicity, failure-visibility.
- **Not better on:** an issue filed on the Git host no longer appears on the board by itself.
- **If used:** an issue-intake sensor files tasks from issues through the API (EXT-004), scheduled in MS5 (WP5.8) and demonstrated on the recorded items.
- **Demonstration:** MIG-017 AC1.

### DIV-25 — Intake is filing and shaping; there is no sentence-to-tasks request
- **Verdict:** conditional on use
- **Covers:** LP-230; [01-product-definition.md](01-product-definition.md) §5.5 (request decomposition).
- **Legacy baseline:** The dispatcher accepts a "new request" in a sentence and decomposes it into tasks, with a landing step (BL-21 for use).
- **Sortyard:** Intake agents file typed tasks and get a verdict (TRK-012, TRK-013); grooming shapes them (GRM-001).
- **Better on:** simplicity, safety.
- **Not better on:** an operator who types a sentence into the console gets no tasks from it unless an agent is asked.
- **If used:** the decomposition is delivered as an intake agent with the `intake` role (MCP-002), scheduled in MS5 (WP5.7) and demonstrated on the recorded requests.
- **Demonstration:** MIG-017 AC1.

### DIV-26 — The concierge and its approval cards are kept
- **Verdict:** keep legacy (cut reversed)
- **Covers:** LP-225; the "embedded concierge" row of OD-3; [01-product-definition.md](01-product-definition.md) §5.2.
- **Legacy baseline:** The console has an embedded chat agent that answers from live state with citations and proposes actions a person approves; it is built, with journeys and end-to-end specs (BL-18, BL-20).
- **Sortyard:** The same, as a client of the operator-agent tools with the operator's permissions, off until a model credential is configured (UI-026, IAM-012). The earlier draft cut it on the argument that the operator's own agent reaches the same data over MCP. That is a different tool, not a better one, and no measurement supported the cut.
- **Kept by:** UI-026, IAM-012.

### DIV-27 — Design-first chains and self-repair of the dispatcher are not shipped
- **Verdict:** conditional on use
- **Covers:** LP-115; the "template workflows, design-first chains, chain self-repair" row of OD-3; [01-product-definition.md](01-product-definition.md) §5.5.
- **Legacy baseline:** The dispatcher has design chains (design, dual review, approval, build, verify) with console views, and a self-repair that edits and redeploys the control plane. The conductor path does not call them (BL-21 for whether anything else does).
- **Sortyard:** The engine can express such a workflow (FLW-017); none is in the default bundle. Changes to the control plane are tasks that Sortyard builds and CI releases (QLT-024, DLV-002).
- **Better on:** safety, simplicity.
- **Not better on:** a design-first flow is not available out of the box.
- **If used:** a design-first workflow is added to the estate bundle in MS5 (WP5.9) and its console views are met by the task page (UI-004). Self-repair is not carried in either case: its job is done by a task on Sortyard's own board, released by CI.
- **Demonstration:** MIG-017 AC1, QLT-024 AC2.

### DIV-28 — The experiment rig, the scorecard battery and the eval views stay outside the product
- **Verdict:** keep legacy
- **Covers:** LP-116, LP-282; CF-23; the "eval runner, scorecard battery, eval grid, experiment rig" row of OD-3; [01-product-definition.md](01-product-definition.md) §5.2, §5.5.
- **Legacy baseline:** An experiment rig shares the legacy control plane: corpus, treatments, compare and eval views, an advisory scorecard battery (BL-21 for use).
- **Sortyard:** Not carried into the product. The rig is kept as its own deployment when the legacy control plane is retired, and archived only if the census shows no use (MIG-013).
- **Kept by:** MIG-013, MIG-017.

### DIV-29 — Skills, context recipes, archetypes and roles are not objects
- **Verdict:** not a divergence
- **Covers:** CF-05; the "archetypes, roles as objects, skills, context recipes" row of OD-3.
- **Legacy baseline:** The conductor injects no skill and builds no recipe: a worker gets a fixed packet, the task text, findings, CI excerpts and a checklist, and reads the repository's own agent guide. Skill files reach a worker only through its image or the repository (CF-05; `grooming.py` excludes the method directories from inputs; `design_review.py` reads its checklist from a skill file).
- **Sortyard:** The same: versioned packet templates and checklists (EXE-015), and a binding that fixes the packet, the commit and the image digest, and so everything a worker reads (EXE-001). The owner's intended-use statement lists skills among what a binding fixes; it does, through the image and the commit.
- **Why the cut stands:** the objects exist only in DESIGN v6. Not building them removes four large corpus tasks and adds no behaviour the estate has.
- **Kept by:** EXE-001, EXE-015.

### DIV-30 — The shipped workflow is the one that runs
- **Verdict:** not a divergence
- **Covers:** CF-04; LP-283 (template workflows).
- **Legacy baseline:** The conductor runs build, code review, test-determinism review, design review for UI changes, and auto-merge. The owner's "Delivery lanes" overrides the older template workflows (CF-04).
- **Sortyard:** `change` and `job`, with that review policy (FLW-002, FLW-003, FLW-005 to FLW-009).
- **Why the cut stands:** the template workflows are not on the conductor path; shipping them would add behaviour the estate has overruled.
- **Kept by:** FLW-002, FLW-005.

### DIV-31 — Plan-only items: the extension registry, the separate runner services, Proposals, the roadmap projection, the fork lane
- **Verdict:** not a divergence
- **Covers:** CF-05, CF-10, CF-22, CF-23; the "extension registry", "Proposals" and "eval runner" rows of OD-3, and its scope exclusions (other Git hosts, a Docker Compose install, translations).
- **Legacy baseline:** None of these exists in the estate. Extension is a code change (DIV-23); reviews and required checks are the gates; pull requests opened outside are adopted (FLW-014); governance is not a product feature. The estate runs on GitHub and Kubernetes, in English.
- **Sortyard:** Three extension mechanisms (EXT-001); three workloads (DEP-001); reviews with declared absent states (FLW-009); provider-hosted CI for forks and governance files for the upstream project (QLT-013, QLT-042).
- **Why the cut stands:** each is a part to build, run and secure with no legacy behaviour behind it. Counted: three extension mechanisms instead of six registry kinds and an SDK; three long-lived workloads instead of six. Revisit when an extension is asked for that the three mechanisms cannot express.
- **Kept by:** EXT-001, FLW-009, FLW-014, QLT-013, QLT-042.

### DIV-32 — Plane is frozen at cutover and archived at the verdict, with a rehearsed way back
- **Verdict:** diverge (reshaped)
- **Covers:** CF-16; OD-4; the "Plane outbound projection" row of OD-3; [01-product-definition.md](01-product-definition.md) §5.1.
- **Legacy baseline:** Plane is the board. The owner's standing default of 2026-11-06 keeps it as a read-only projection for one milestone after a cutover (INTENDED-USE; BL-24 for what a second copy costs).
- **Sortyard:** No projection. At cutover the Plane project is frozen with a pointer to Sortyard; it is archived read-only at the hypercare verdict. Rolling back replays what changed since the cutover from a rollback export, written by the cutover kit and not by Sortyard (MIG-009). The earlier draft rolled back from the frozen snapshot alone, which would have lost the work done since the cutover.
- **Better on:** simplicity, safety, cost.
- **Not better on:** rollback takes minutes where a live projection would make it a switch; anyone still reading Plane sees a frozen board.
- **Demonstration:** MIG-009 AC3.

### DIV-33 — Merging past a quarantined job stays as it is for the estate
- **Verdict:** keep legacy
- **Covers:** LP-123; CF-21; OD-9.
- **Legacy baseline:** With only quarantined flaky jobs failing, the approved head is merged with an admin merge, once for each head (JQ).
- **Sortyard:** The same, as a policy that the estate bundle ships on. New installations get it off by default, which changes nothing for the estate (MRG-004). The earlier draft switched it off everywhere; that would hold changes that merge today, with nothing measured to set against it.
- **Kept by:** MRG-004.

### DIV-34 — Estate rules ship as policy packs, switched on in the estate bundle
- **Verdict:** keep legacy
- **Covers:** LP-018, LP-019, LP-161.
- **Legacy baseline:** Premise rules (intended use, reference clones, access citations), production flips held until preconditions are met, and release verification with shield and revert are enforced for the estate's projects.
- **Sortyard:** The same rules as optional packs and an integration, on in the estate bundle (RDY-009, RDY-014, DLV-003). Off by default only for strangers, who have no such estate.
- **Kept by:** RDY-009, RDY-014, DLV-003.

### DIV-35 — Reality reconciliation keeps running as a sensor
- **Verdict:** keep legacy
- **Covers:** LP-206.
- **Legacy baseline:** Grooming compares task premises with a recorded product-state file and forces a fix task when they differ.
- **Sortyard:** The estate keeps running the comparison, as a sensor that files tasks through the API (EXT-004). A built-in pack follows after 1.0 (GRM-008).
- **Kept by:** GRM-008, EXT-004.

### DIV-36 — No record stands for work that can never run
- **Verdict:** diverge
- **Covers:** LP-117.
- **Legacy baseline:** A rejected verify records a blocked follow-up request in the dispatcher that nothing dispatches: an artefact of two schedulers (DRV §4; BL-21 for how many exist).
- **Sortyard:** One scheduler; a rejected review opens a fix round in the same chain (FLW-010), and follow-ups are tasks in Backlog (TRK-018).
- **Better on:** simplicity, failure-visibility.
- **Not better on:** nothing found.
- **Demonstration:** TRK-018 AC4.

### DIV-37 — Estate mechanisms beyond the pipeline stay watched
- **Verdict:** keep legacy
- **Covers:** LP-280; [01-product-definition.md](01-product-definition.md) §5.7.
- **Legacy baseline:** The mechanism check watches runners, certificates, backups and scheduled CI on three clusters.
- **Sortyard:** They are not product features, and they keep being watched: external heartbeats and an observer integration (REC-018, MIG-012). Nothing is switched off before it is registered or assigned an owner.
- **Kept by:** REC-018, MIG-012.

### DIV-38 — Plane features that the tracker does not carry
- **Verdict:** conditional on use
- **Covers:** [01-product-definition.md](01-product-definition.md) §5.1 (cycles, pages, estimates, the intake module, deploy boards, Plane's own agents, importers and integrations, guests and teams, custom properties, the notifications inbox, attachments).
- **Legacy baseline:** These exist in the board the estate runs. The record shows no use of them in delivery: the driver, the sync and the operations documents read none of them (inference; BL-21 for the count).
- **Sortyard:** A tracker with the fields delivery reads, a closed set of kinds, an owner list and an attention list (TRK-003, UI-007, OBS-014).
- **Better on:** simplicity, install-effort.
- **Not better on:** a team that used the board as a general project tool would lose those features.
- **If used:** each feature with a count above zero is scheduled before the board that uses it is cut over (attachments: TRK-019; saved views are already TRK-015), or its replacement is shown in the journeys of TRK-014 AC4.
- **Demonstration:** MIG-017 AC1.

### DIV-39 — History stays in the frozen snapshot; the baselines are loaded
- **Verdict:** keep legacy
- **Covers:** MIG-014 (importing historical evidence, after 1.0).
- **Legacy baseline:** Past runs, reviews and costs are in the dispatcher's ledger and on the board.
- **Sortyard:** The record stays where it is, frozen and verified (MIG-001). The figures needed to compare — every baseline in section 2 — are loaded as reference series, so dashboards show the legacy line beside Sortyard's (MIG-016).
- **Kept by:** MIG-001, MIG-016.

### DIV-40 — The method's templates, roles, skills, scripts and runbooks stay in meta-harness
- **Verdict:** keep legacy
- **Covers:** LP-283, LP-284; [01-product-definition.md](01-product-definition.md) §5.6.
- **Legacy baseline:** meta-harness holds template workflows, roles, skills, the `dispatch`, `validate` and `emit` scripts, and operating runbooks. Task registers and STATUS.md were retired by the estate itself on 2026-11-08.
- **Sortyard:** Does not replace the method repository. Every enforceable rule in it is mapped to a requirement, a policy or a recorded retirement before the first cutover (MIG-010); runbooks for the legacy system retire with it (MIG-011).
- **Kept by:** MIG-010, MIG-011.

### DIV-41 — The improvement ledger
- **Verdict:** conditional on use
- **Covers:** OBS-018.
- **Legacy baseline:** The measurement contract describes a record for each tuning intervention, with before and after values and a verdict (BL-21 for whether entries exist).
- **Sortyard:** Deferred past 1.0. The scorecard records before and after for every measured criterion, and policy changes are audited (QLT-051, SCH-011).
- **Better on:** simplicity.
- **Not better on:** no single record ties a tuning change to its hypothesis and verdict.
- **If used:** OBS-018 is scheduled in MS6 (WP6.1).
- **Demonstration:** MIG-017 AC1.

### DIV-42 — The estate's execution setup is kept, as settings and images
- **Verdict:** keep legacy
- **Covers:** LP-064, LP-066, LP-084.
- **Legacy baseline:** Build, verify and proof stages can run a privileged container sidecar; proof workers are provisioned for each project (browsers, a systemd executor image); workers use subscription credentials only, with API keys unset (MH).
- **Sortyard:** The same, as settings rather than defaults. The sidecar is a project setting that the cutover kit turns on where it is used today (EXE-016). The estate's proof images are worker images named by its harness profiles (EXE-012). The estate bundle's policy selects the subscription pool only (CRD-002, CRD-003). A new installation starts with an API key and no sidecar, which changes nothing for the estate.
- **Kept by:** EXE-016, EXE-012, CRD-003.

---

## 5. Audit of 2026-11-12

Every divergence in the earlier draft was tested against the rule: is there a credible,
measurable case that it is better? Where there was none, the legacy behaviour was restored or
the design was changed. What follows is the outcome for each item; "what changed" in the
requirement files is in [11-coherence.md](11-coherence.md), Part C.

**Cuts reversed — now requirements.**

| Item | Now | Why |
|---|---|---|
| Embedded concierge | UI-026, MS6 | It is built and shipped in the legacy console. "Use your own agent over MCP" is a different tool, not a measured improvement (DIV-26) |
| Approval mode for agent-proposed actions | IAM-012, MS6 | Part of the same feature; the legacy console has journeys for approving and editing an approval (DIV-26) |

**Designs reshaped so the divergence can be shown better.**

| Item | Before | After | Why |
|---|---|---|---|
| Definitions sync controller | Cut; a locked installation fed by `apply` from CI | A locked installation pulls from Git itself, one way (DEF-003, moved from MS6 to MS3) | The legacy system reads its configuration from Git on every pass. A CI-fed lock would have been slower and less visible (DIV-09) |
| Plane after cutover | Archived at cutover; rollback from the frozen snapshot | Frozen at cutover, archived at the verdict; rollback from an export of what changed, rehearsed (MIG-009) | A snapshot rollback loses the work done since the cutover (DIV-32) |
| Merging past a quarantined job | Off everywhere | On in the estate bundle, off for new installations (MRG-004) | Switching it off would hold changes that merge today (DIV-33) |
| Experiment rig | Archived or kept, by decision | Kept as its own deployment unless the census shows no use (MIG-013) | Archiving something in use is a loss, not an improvement (DIV-28) |
| Blocking causes | Polled every 30 minutes, as today | Re-evaluated on the resolving event (REC-008) | Design changed for the target, not to fix a divergence |
| Version skew | Controller idles until versions agree, as today | Adjacent versions run side by side (REC-015) | The legacy guard is what paused delivery for 32 minutes |

**Cuts that stand, and why each beats having the thing.**

| Item | Verdict | Why it stands |
|---|---|---|
| Extension registry, SDK, scaffold | Not a divergence (DIV-31) | The estate never had one. Three extension mechanisms replace six registry kinds; EXT-001 AC3 shows new behaviour added without a release |
| Skills as objects | Not a divergence (DIV-29) | The conductor injects none. Skills reach a worker through its image and the repository, and the binding records both |
| Context recipes, archetypes, roles as objects | Not a divergence (DIV-29) | The estate renders fixed packet templates, which are kept and versioned (EXE-015) |
| Eval runner as its own service | Not a divergence (DIV-31) | A plan-only service. Reviews and required checks are the gates that run |
| Proposals task type, roadmap projection, publish-back | Not a divergence (DIV-31) | Plan-only. Project governance with standard tooling (QLT-042) |
| Fork-PR lane | Not a divergence (DIV-31) | Plan-only. Outside pull requests are adopted as today (FLW-014); forks run on provider-hosted CI (QLT-013) |
| Two-way definitions sync | Not built (DIV-09) | No legacy behaviour depends on writing back to Git |
| Plane outbound projection | Diverge, reshaped (DIV-32) | No second copy to drift and no sync to run; the rollback drill is the demonstration. The decision stays open (OD-4) |
| Template workflows | Not a divergence (DIV-30) | Overruled by the owner's "Delivery lanes"; not on the conductor path |
| Design-first chains, sentence-to-tasks intake, issue projection, Plane's unused features, improvement ledger | Conditional on use (DIV-27, DIV-25, DIV-24, DIV-38, DIV-41) | Each stands only if the usage census counts no use; otherwise it is scheduled or its replacement is demonstrated |
| Self-repair of the control plane | Not carried (DIV-27) | Replaced by Sortyard building Sortyard with CI releases, shown by QLT-024 AC2 |
| Importing history | Keep legacy (DIV-39) | The record stays readable where it is; the baselines are loaded for comparison |
