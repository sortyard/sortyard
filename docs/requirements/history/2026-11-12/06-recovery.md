# 06 — Recovery, self-heal and no silent failure

Area: **REC**. This is the hard-won part of the estate: what the system does when something
does not go to plan, so that the factory can be left alone. Most of these behaviours were
written after a specific stall, and the incident is cited. The standing rule from the estate's
operating notes applies to the product too: build self-recovery per stall class, and when a fix
lands, retire the watch that used to catch it.

Two owner statements define the area:

- "Nothing waits on Joe. A stuck item gets a comment saying why, moves to Backlog and drops the
  `conductor` label." (`drive.py` docstring)
- "Nothing should ever fail silently around here." (MECHANISMS.md, 2026-11-11)

---

### REC-001 — Every wait has an exit
**MS3** · WP3.7 · MUST · FIX

Every phase of every workflow has an end condition and a bound. When the bound passes, the chain
takes a defined stuck transition (park, hand back, or escalate) that frees its slot. No phase can
hold a slot indefinitely.

- AC1: A generated table lists each phase, its end conditions and its bound; a definition with an unbounded phase is refused at apply time.
- AC2: Scenario tests exist for every row of task-pickup §5 and §7.
- AC3: Demonstration (parity, MS5) — every stall episode in the baseline catalogue (BL-05) is replayed as a scenario. Target: every slot is freed at its bound with the item parked, handed back or escalated, and no episode needs a person to free a slot. Floor: no slot is held past its bound in any catalogued episode; the legacy system held slots for hours in each of them (BL-05).

Baseline: The rule existed in the design, but the released code only commented on a merge that never fired, and two slots were held about nine hours (task-pickup conformance row 1, HARNESS-242; BL-05).

Better on: stall-rate, recovery-time, operator-actions.

Source: task-pickup §2a ("No state in the design holds a slot without an exit") and conformance row 1 (the released code only commented; two slots were held about nine hours).

### REC-002 — Infrastructure failure budget
**MS5** · WP5.1 · MUST · KEEP

A stage whose worker never produced a result (pod lost, CLI install failed, model capacity) is
re-run as the same step: up to 3 immediate retries, then a wait (default 30 min) and a fresh set,
at most 2 waits, then the task parks. Any step that returns a result resets the count. The same
failure reason twice in a row spends the immediate retries and goes straight to the wait.

- AC1: A steady failure parks after 4 attempts, a changing one after at most 10 (scenario test with injected reasons).
- AC2: The re-run submits exactly the same step and inputs.
- AC3: All four numbers are policy data.

Source: driver §4 "Infra failures" (`INFRA_RETRIES`, `INFRA_WAIT`, `INFRA_WAITS`; k3s-harness #188, #194 — a full `/work` failed every retry within minutes on 2026-10-28).

### REC-003 — A task failure is not an infrastructure failure
**MS5** · WP5.1 · MUST · KEEP

A stage that ran and failed its declared checks is a task outcome: a build is rebuilt from the
default branch at most twice; a fix round parks. It does not consume the infrastructure budget.

- AC1: `execution_ok: true, pass: false` never increments the infrastructure counters.

Source: driver §4 (k3s-harness #174); `drive.py` note 393.

### REC-004 — Deterministic failures are not retried as if they were transient
**MS5** · WP5.1 · MUST · KEEP

A failure that will recur identically (a base missing from the mirror after seeding, an input
that cannot be verified, a packet over the cap) is retried once at most and then parks with the
specific reason.

- AC1: The missing-base scenario ends after two attempts, not ten.

Source: driver §4 (k3s-harness #193, DV-57; CPV2-408 burned ten builds on one missing head).

### REC-005 — Consecutive errors park one item; outages park none
**MS5** · WP5.1 · MUST · KEEP

An item whose step raises an error 5 times in a row is parked with an `infra` blocking cause. One
successful step clears the count. Errors caused by a dependency being unavailable (control-plane
API restarting, database failover) are logged and do not count.

- AC1: During a simulated 40-second API outage no item is parked and no counter moves.
- AC2: Cluster-API errors are retried up to 6 times before counting.

Source: driver "Recovery" (k3s-harness #183); conductor README "API rollouts" (`Unavailable` never counts toward `errors`); `drive.py` note 400.

### REC-006 — Parking
**MS3** · WP3.7 · MUST · KEEP

A parked task leaves the queue, frees its slot, keeps its change request if any, and gets one
notice saying why and what would bring it back. Requeueing it (one action) resumes it
(FLW-013).

- AC1: The park reason is a typed field shown on the board, the detail page and the Pickup Preview.
- AC2: `sortyardctl requeue KEY-N [note]` and the UI action are the same API call.

Source: driver §4 "blocked"; `requeue.py`.

### REC-007 — Hand-back to self-heal
**MS5** · WP5.2 · MUST · KEEP

A run that makes no change is handed back: the task leaves the build queue for the self-heal
queue, carrying the worker's own account of why. An account that only says it could not read
the CI log is refused once per CI round and the round is re-sent.

- AC1: The hand-back record contains the worker's account, the evidence it cited and the blocking cause it named, if any.
- AC2: A hand-back never loses the chain's history or its open change request.

Source: driver "Recovery" (label `self-heal`); `hand_back` notes 140, 434.

### REC-008 — Blocking causes bring parked work back by themselves
**MS5** · WP5.2 · MUST · FIX

A park or hand-back may carry a typed blocking cause: `pr` (resolved when it merges), `defect`
(when the named task is Done), `check` (when each named check's latest run on the branch head
passed after the park), `infra` (when that infrastructure is healthy again), `decision` (never:
a person decides). A cause is re-evaluated on the event that can resolve it — the task closing,
the merge or the check run being observed, the health state changing — and by a backstop poll
(default every 5 minutes; the legacy poll is 30). A resolved cause returns the item to the queue
with a notice. An `infra` cause returns an item at most twice (default). A `defect` cause naming
no existing task files one.

- AC1: The CPV2-606/607/608 case is a scenario: three items parked on one defect return when the defect's fix merges, with no poll involved.
- AC2: An item with no cause, a `decision` cause or an unknown kind is never auto-returned.
- AC3: Workers can name a cause in their account; the packet asks for it; the self-heal agent or a person can set one.
- AC4: Demonstration (parity, MS5) — the recorded parked items and their causes are replayed, timing from the resolving event to the item being back in the queue. Target: back within 60 s for every cause Sortyard observes itself. Floor: back within 5 minutes; the legacy poll is at most every 30 minutes (BL-06).

Baseline: `causes.tick` polls each parked item at most every 30 minutes, a limit set by the board's rate limit, so resolved work waits up to that long to return (conductor README "Blocking causes"; BL-06).

Better on: recovery-time, throughput.

Source: conductor README "Blocking causes" (`causes.py`, `POLL`, `RETURNS`; Joe 2026-11-06).

### REC-009 — The self-heal contract
**MS5** · WP5.2 · MUST · KEEP

The self-heal queue is worked by an agent or person with access workers lack. Each item ends in
one recorded outcome: **fixed directly** (with verification), **outcome already met** (RDY-008),
**handed back to build** (diagnosis and exact change written at the top of the task), **moot**
(evidence, then Cancelled), or **owner input** (converted to or linked with a decision). Self-heal
principals never merge, approve or review, and never add merge gates.

- AC1: The resolution action requires one of the five outcomes and its evidence field.
- AC2: The self-heal role's token cannot call review or merge operations (authorization matrix test).
- AC3: The list of projects to scan comes from the same configuration the scheduler uses; there is no second list.

Source: conductor `SELF-HEAL.md`; HARNESS-248 (the contract listed the wrong project identifier).

### REC-010 — Self-heal drain
**MS5** · WP5.2 · MUST · KEEP

While any task of a project has been in self-heal or `needs_human` for longer than the drain
limit (default 24 hours, the legacy value), one urgent `SELF-HEAL-STALLED <project>` condition
lists each item, its stop reason and its age. It closes only when nothing of the project remains
in either queue.

- AC1: The condition is updated in place and never duplicated.

Source: conductor README "Self-heal drain" (35 open self-heal items, 21 untouched for 24 h; HARNESS-444).

### REC-011 — Phase and age are always visible
**MS3** · WP3.7 · MUST · FIX

Every in-flight chain's phase, slot use and time in phase are visible through API, CLI and UI. A
chain in one phase longer than the stall threshold (default 4 h) gets exactly one notice saying
where it is stuck.

- AC1: The information the legacy conductor kept only in `state.json` (phase, slot use, stale live records, running revision) is readable without cluster access.
- AC2: Demonstration (count, MS3) — the facts an operator needs about work in flight (phase, slot use, time in phase, stale records, running revision) are listed with where each is read. Target: 100% through the API, the CLI and the console, each within 1 s. Floor: none needs cluster access; in the legacy system every one of them does (BL-28).

Baseline: Phase, slot use, stale live records and the running revision are readable only in `state.json` on a cluster volume or as a cluster annotation (task-pickup conformance row 7, HARNESS-256; BL-28).

Better on: failure-visibility, operator-actions.

Source: driver §4 "Visibility"; task-pickup conformance row 7 (HARNESS-256).

### REC-012 — Side effects are idempotent and recorded when accepted
**MS3** · WP3.7 · MUST · KEEP

Each external write (a Job, a push, a change request, a comment, an auto-merge toggle) is
recorded only once the external system accepted it, so a failure is retried on the next
reconcile; and each has an idempotency marker, so a retry after a lost response does not repeat
it.

- AC1: Lose the response to each kind of write in turn: the effect exists exactly once afterwards (fault-injection matrix).
- AC2: A notice of a given kind for a given condition is posted once.

Source: `drive.py` notes 242, 250, 416, 422 ("persisted first: a partial GitHub failure cannot loop the toggle").

### REC-013 — Idempotent submission
**MS1** · WP1.2 · MUST · KEEP

Creating operations accept an idempotency key: the same key with the same payload returns the
original result; the same key with a different payload is refused.

- AC1: A retried create after a lost response creates one object.
- AC2: Internally, a refusal for key reuse makes the next attempt use a fresh key rather than retrying the same one forever.

Source: driver §5 (`client_request_id` is idempotent); driver "Recovery" (409 advances the attempt counter).

### REC-014 — Controller restart and failover
**MS3** · WP3.7 · MUST · FIX

At most one controller acts at a time (leader election with a fencing epoch). After a crash,
restart or failover a new leader resumes with no duplicate Jobs, change requests, comments or
merges and no lost stage result. A leader that is shutting down hands over instead of letting
its lease lapse.

- AC1: Chaos test: kill the leader at random points during 200 chains; the end state equals a run with no kills.
- AC2: A deposed leader's writes are refused by the epoch check.
- AC3: Demonstration (chaos, MS3) — the leader is killed at random points during 200 chains, timing from the kill to the next reconcile by a leader. Target: at most 15 s, with an end state equal to a run with no kills. Floor: at most 60 s; the legacy system resumes at its next pass, up to three minutes later (BL-25).

Baseline: One writer is guaranteed by `concurrencyPolicy: Forbid` on the CronJobs and `strategy: Recreate` on the API; work interrupted by a crash is picked up at the next pass, and every rollout has 30 to 40 seconds with nothing listening (task-pickup §3; `k8s/deployment.yaml`; BL-25).

Better on: recovery-time, safety, upgrade-effort.

Source: inference from the single-writer constraints today (`concurrencyPolicy: Forbid` on the CronJobs; `strategy: Recreate` "single writer to the sqlite db: never two pods").

### REC-015 — Version skew never pauses delivery silently
**MS3** · WP3.7 · MUST · FIX

Adjacent versions run side by side: the controller and the API of one minor version work with
the schema and the stage contract of the previous one (DEP-007, DEP-009), so an upgrade does not
pause delivery. Only a schema outside that window makes the controller idle: it writes nothing
and reports `skew` in health at once (`/readyz`, `/v1/info`, the Overview); from MS5 its missed
heartbeats also raise a `SILENT` condition (REC-017).

- AC1: During a rolling upgrade between adjacent minors no reconcile is skipped for skew, and no reconcile ever runs against a schema outside the supported window.
- AC2: The skew state is visible wherever health is shown; it is never a silent idle.
- AC3: Demonstration (chaos, MS3) — a rolling upgrade runs during 20 chains, and separately an upgrade is made to stall half-way, measuring the seconds in which no reconcile runs and the time until the stall is reported. Target: zero paused seconds, and a stuck upgrade reported within 60 s. Floor: paused at most 60 s and never silently; the legacy system skipped every pass for about 32 minutes with only a log line (BL-08, BL-25).

Baseline: On version skew the legacy pass ends without writing. On 2026-11-12 every pass was skipped for about 32 minutes while the API pod held an old bundle, with no alarm (conductor README "API rollouts"; BL-08, BL-25).

Better on: stall-rate, failure-visibility, upgrade-effort.

Source: conductor README "API rollouts" (`api_skew`; "ends without touching `state.json`"); 2026-11-12 release stall ("pass skipped, rollout: API bundle …" for about 32 min with no visible alarm).

### REC-016 — Dependency outages are waited out
**MS5** · WP5.1 · MUST · KEEP

Connection-level failures to the database, the API, the Git host or the cluster API are retried
with capped backoff (default schedule, the legacy one: 1, 2, 4, 8, 15 s up to 90 s). A reconcile
that cannot proceed ends without partial writes. No verdict, review outcome or grooming result
is recorded as `failed` or `unavailable` because a dependency was briefly down.

- AC1: Eleven simulated 40-second restarts in a day produce zero failed reviews and zero parked items.

Source: conductor README "API rollouts" (11 rollouts failed grooming, flake processing and test reviews with ECONNREFUSED).

### REC-017 — Every recurring mechanism has a freshness window
**MS5** · WP5.6 · MUST · KEEP

Every loop and scheduled job inside Sortyard is registered with an owner route, a cadence and a
freshness window no shorter than the cadence. One that goes quiet past its window raises one
`SILENT <mechanism>` condition carrying last success, last error, cadence and window, and closes
it when heartbeats resume. The checker runs independently of everything it watches and is itself
registered.

- AC1: Stopping any registered loop produces its `SILENT` condition inside its window (one test per mechanism, generated from the registry).
- AC2: Adding a loop without registering it fails CI (registry coverage test).
- AC3: With the scheduler and the integrator both down, the checker still reports them.

Source: MECHANISMS.md (registry, `conductor-mechanism-health` runs apart from drive and plane-sync; fixtures 1–9); k3s-harness #321.

### REC-018 — External heartbeats
**MS5** · WP5.6 · SHOULD · KEEP

Jobs outside Sortyard can register as mechanisms and post heartbeats
(`{mechanism, status, error?, at?}`) with a token. An unknown name raises `UNREGISTERED <name>`.
A heartbeat that cannot be delivered is noticed by its absence.

- AC1: The heartbeat client is one HTTP call and never fails the job it wraps.
- AC2: Cluster-object and CI-workflow observers (CronJob last success, resource conditions, scheduled workflow runs) are an optional integration, required before legacy retirement (MIG-012).

Source: MECHANISMS.md "Heartbeats from jump-box and Juno-side jobs", heartbeat kinds `cronjob`, `resource`, `workflow`, `pr-runs`.

### REC-019 — Health has four states and never hides the unknown
**MS5** · WP5.6 · MUST · KEEP

Overall health is the worst of: `silent-check` (the checker's own report is stale), `degraded`
(any silent mechanism, low quota, missing reading or unregistered mechanism), `partial` (some
sources unreadable), `healthy`. A source that cannot be read makes its mechanisms `unknown`: not
filed, not closed, named in the report.

- AC1: An unreadable source never yields `healthy`.
- AC2: `/readyz` and the Overview show the state and what is driving it.

Source: MECHANISMS.md "FACTORY-HEALTH-SENSOR input".

### REC-020 — One writer per chain, enforced at the side-effect boundary
**MS3** · WP3.6 · MUST · FIX

A chain has a revision (epoch) that increases on claim, on requeue, on cancel and on an
operator's steering change. Every side-effecting operation carries the epoch it was planned
under and is refused when it is stale: stage result submission, pushes, change-request writes,
merges.

- AC1: A worker from a cancelled or superseded attempt submits a result: it is refused and recorded as stale.
- AC2: The check is in the integrator and the API, not only in the controller's memory.
- AC3: Demonstration (chaos, MS3) — superseded workers, deposed controllers and cancelled attempts each try every side effect (result, push, change-request write, merge) 1,000 times. Target: 100% refused at the integrator or the API and recorded as stale. Floor: zero stale side effects accepted; the legacy system has no check at that boundary (BL-28).

Baseline: No durable per-task revision is checked where side effects happen; the steering document says to report that absence honestly (in-flight-steering; BL-28).

Better on: safety.

Source: in-flight-steering ("A durable per-task revision must eventually be checked by the actual side-effecting execution boundary … Until that path is implemented … report its absence honestly").

### REC-021 — Steering work in flight
**MS3** · WP3.7 · MUST · FIX

An operator can change a task that is already in flight: edit its text (the next stage reads the
new text and stale findings are dropped), cancel the running stage, or stop the chain. Steering
revises the existing chain; it never starts a competing one.

- AC1: After a mid-flight edit there is still exactly one chain for the task, with a higher epoch.
- AC2: Evidence that the change did not invalidate is reused; only invalidated reviews re-run.
- AC3: Demonstration (benchmark, MS4) — a scripted operator edits a task's text mid-build, cancels a stage and stops a chain, counting steps and the reviews that re-run. Target: one action each, in force at the next stage, with only invalidated reviews re-run. Floor: each is done from the console with no cluster access and no competing chain; the legacy procedure is manual (BL-28).

Baseline: Stopping or steering an item in flight is a prose procedure, and stopping one mid-flight is "Not supported yet" (driver §7; in-flight-steering; BL-28).

Better on: operator-actions, safety, cost.

Source: in-flight-steering ("steering revises the existing task"); driver §7 ("Stop an item mid-flight: Not supported yet").

### REC-022 — Work storage is cleaned under pressure, never under a live chain
**MS3** · WP3.7 · SHOULD · KEEP

Finished run directories are kept for a retention time (default 24 h). At or above a usage
threshold (default 85%) retention drops (default 4 h) with no per-pass cap. A directory any live
chain still needs is never deleted. Deletion runs detached so dispatch never waits on it.

- AC1: Filling the volume in a test triggers pressure retention and dispatch latency is unaffected.
- AC2: Volume usage is a metric with a warning threshold (OBS-010) and, from MS5, an attention item (OBS-014), before it is an outage.

Source: driver §5 (`MH_WORK_PRESSURE_PCT`, `MH_WORK_RETENTION_PRESSURE_S`; k3s-harness #187, #189); `mh.py` retention (notes).

### REC-023 — Conditions: one alarm per cause, updated in place, closed by the system
**MS5** · WP5.2 · MUST · KEEP

System-raised alarms are `condition` tasks with a stable key. A condition is created once per
cause, updated in place while the cause persists, never duplicated — even after losing every
cache — and closed with a notice when the cause clears. The v1 conditions: `FILING-INVISIBLE`,
`CONFIG-INVALID`, `GROOMING-STALLED`, `SELF-HEAL-STALLED`, `SILENT`, `QUOTA`, `UNREGISTERED`,
`CITATION-MISMATCH`, `RELEASE-VERIFY-FAILED`.

- AC1: Raising the same cause 100 times yields one open task.
- AC2: Each condition names an owner route and appears in that route's list.

Source: conductor README (each of these items is described as "updated in place, never duplicated, and closed when…"); MECHANISMS.md.

### REC-024 — The owner is never a step inside delivery
**MS5** · WP5.8 · MUST · KEEP

No workflow blocks on a person. People are reached only through decisions (with defaults),
needs routed to them, and escalations. The owner list contains exactly: open decisions due,
premise-class decisions escalated, needs routed to `owner`, and items escalated "to a person".

- AC1: The owner list is one API call; an item appears on it for one of the four reasons, shown.
- AC2: A notification reaches the owner only for an owner-list item or a factory-down state with nothing acting on it (OBS-013).
- AC3: Operator actions on work in flight (requeue, cancel, force, manual state change, resolving a hand-back), counted from the ledger for each week and for each 100 merged tasks (`operator.interventions`). Target: zero in a week. Floor: fewer for each 100 merged tasks than the legacy baseline (BL-07).

Source: driver §6 ("The owner is never a step inside delivery"; "Slack is only for what the owner alone can do, or the factory being down with nothing acting on it").

### REC-025 — Parity and chaos suites
**MS5** · WP5.11 · MUST · NEW

Two suites gate the milestone that makes Sortyard safe to leave alone: a **parity suite** with at
least one scenario for every KEEP or FIX row of [16-legacy-parity.md](16-legacy-parity.md) whose
requirements are MUST and due by MS5, run against the Git host and CI fakes (rows owed by a
SHOULD or by a later milestone gain their scenario with that requirement and are complete
before the estate's cutovers, MIG-010); and a **chaos suite** that injects controller kills, worker
pod loss, database restarts, Git host errors, model-capacity errors, a stale mirror and a full
work volume.

- AC1: The parity matrix is machine-readable: CI fails when a row that is due has no passing scenario, and reports every other row as pending with the milestone that owes it.
- AC2: After each chaos run, every task is in a terminal or owned state and no slot is held past its bound.
- AC3: A scenario that is a demonstration runs with its legacy baseline beside it, writes the measured value to the scorecard (QLT-051) and fails below its floor.

Source: inference — the legacy system encodes its behaviour in `test_conductor.py` (10,364 lines) and `test_mh.py` (3,268 lines); a claims-only shadow comparison cannot exercise the step machine.

### REC-026 — Stalls are detected and recovered in minutes
**MS5** · WP5.2 · MUST · FIX

A stall is found by the system, not by a watch or a person, and is recovered or owned within
minutes. Three mechanisms. (1) Each phase's bound is derived from that phase's own history (a
multiple of its recent p95, policy data) instead of one flat threshold, with the legacy stall
threshold as the ceiling. (2) A no-progress watchdog: a stage that produces no output,
heartbeat or state change for `stage.no_progress_seconds` (default 600) is ended and retried or
parked under its failure budget. (3) A task in self-heal that nothing has picked up within
`selfheal.unpicked_seconds` (default 900) is put on the attention list and sent to its route.
Every stall class in the catalogue has a named recovery, and every episode is recorded
(`stall.episodes`) with its detection and recovery times.

- AC1: Demonstration (chaos, MS5) — every stall class of the baseline catalogue (BL-05) is injected during the 72-hour run and the recorded episodes are replayed. Target: 100% of catalogued classes have a recovery, at least 95% of episodes heal with no person, detection within 60 s and recovery within 10 minutes at p95. Floor: a higher self-healed share and a lower median time to recovery than the legacy baselines (BL-05, BL-06).
- AC2: A bound derived from history is never longer than the ceiling, and a phase with too little history uses the ceiling (default: the legacy stall threshold).
- AC3: Each recovery names the watch or alert it retires, in the migration guide (MIG-011); no new watch is added for a stall class that has a recovery.

Baseline: One flat stall threshold of 4 hours; parked causes polled at most every 30 minutes; 35 self-heal items open with 21 untouched for 24 hours (HARNESS-444); recorded episodes of 8, 9 and 20 hours and of two days (BL-05, BL-06).

Better on: stall-rate, recovery-time, operator-actions, failure-visibility.

Source: conductor README "Self-heal drain" and "Incident notes"; task-pickup §5; the estate's practice of building a recovery for each stall class instead of another watch. The three mechanisms are inference from the recorded episodes.
