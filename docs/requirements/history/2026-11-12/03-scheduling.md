# 03 — Scheduling

Area: **SCH**. The scheduler replaces `drive.py`'s claim half (`Board.ready`, `pickup_order`,
slot counting) and `mh.py`'s admission (`caps_allow`, `_drive_order`). Its design property is
the owner's: "There should be ZERO guess work as to when or how a task will be scheduled"
(task-pickup, 2026-11-05). Everything below is derivable from recorded state, and the derivation
is exposed (SCH-008).

Format and abbreviations: see [02-work-tracking.md](02-work-tracking.md) and
[17-evidence.md](17-evidence.md).

---

### SCH-001 — One definition of eligible
**MS2** · WP2.4 · MUST · KEEP

A task is eligible when all hold: its project has build switched on; it is released (RDY-003);
board state is `todo`; it has no live chain; its kind is claimable; claim-time gates pass
(SCH-017). One function computes this; the Pickup Preview, the scheduler and the filing verdict
all call it.

- AC1: There is exactly one implementation of eligibility in the codebase (import-graph test: preview, scheduler and verdict share it).
- AC2: For every ineligible task the function returns at least one reason code from the catalogue (SCH-009).

Source: task-pickup §4 "Eligible"; CORPUS M1.10 (Pickup Preview and conductor are clients of one evaluator).

### SCH-002 — Pickup order is a total order
**MS2** · WP2.4 · MUST · KEEP

Within a project, eligible tasks are ordered by: (1) `urgent` first; (2) milestone rank —
the position of the task's top-level ancestor in the project's manual order, tasks with no
planned ancestor after all planned work; (3) priority (`high`, `medium`, `low`, `none`);
(4) sequence number ascending. No ties remain.

- AC1: Golden tests reproduce the worked derivation in task-pickup §8 (CPV2-574) from fixture data.
- AC2: The key list is policy data (`prioritization.keys`), defaulting to the order above; weighted scoring is not offered.
- AC3: A project with no planned top-level tasks orders by priority then sequence.

Source: task-pickup §4; driver §4 "Pickup"; DESIGN §3.5 (lexicographic, no weights).

### SCH-003 — Milestone rank comes from the parent chain
**MS2** · WP2.4 · MUST · FIX

A task's milestone rank is found by walking its parent relation to the top-level task. The
legacy fallback that matches a task id by text prefix (`BV-15-F2` ranks with `BV-15`) is applied
only by the importer, which converts prefix matches into parent links.

- AC1: The scheduler contains no title or id string matching.
- AC2: The importer's report lists every task ranked by prefix and the parent link it created for it.
- AC3: Demonstration (replay, MS2) — the recorded passes are replayed with rank taken from parent links only, after the importer has converted prefix matches. Target: 100% of recorded claim orders are reproduced, with every prefix-ranked task linked to its parent by the importer and none left for a person. Floor: no divergence in the replay comparison (MIG-005) is caused by rank, and renaming a task changes no rank, which it can under the legacy rule (BL-28).

Baseline: `milestone_rank` also ranks a task whose id is a text prefix of a top-level task's (task-pickup §4 step 2). Inference from that rule: renaming a task can change its rank (BL-28).

Better on: safety, simplicity.

Source: `milestone_rank` (task-pickup §4 step 2: "equals its task id … or a prefix of these followed by `-`").

### SCH-004 — Lanes: slots per project
**MS2** · WP2.4 · MUST · KEEP

Each project has `lanes`: the most non-urgent chains it may have in flight. A slot is held from
claim until the chain is done, parked, handed back or `awaiting-deployment`. `lanes: 0` pauses
the project. Projects do not compete for each other's lanes.

- AC1: With `lanes: 2` and three eligible tasks, exactly two are claimed; the third shows `held: lanes full (2/2)` naming the two holders and their phases.
- AC2: An in-flight task in phase `merging` still holds its slot; one in `awaiting-deployment` does not.
- AC3: Changing `lanes` takes effect at the next evaluation without a restart (SCH-011) and is audited.

Source: task-pickup §4 "Slots", §5; driver §1 (`lanes`); k3s driver "Running-system delivery" (awaiting-deployment releases the build slot).

### SCH-005 — The rush lane
**MS2** · WP2.4 · MUST · KEEP

An `urgent` task is claimed in addition to the project's lanes, never instead of a claimed task,
and never preempts a running stage. Its stages run at rush priority and use the reserved heavy
slot (SCH-007).

- AC1: With lanes full, an urgent task is still claimed at the next evaluation.
- AC2: From MS3: no running Job is deleted or deprioritised because an urgent task arrived.
- AC3: Urgent tasks in flight are not counted in lane occupancy.

Source: driver §4 ("Urgent runs as a harness `rush` request and ignores the lane limit"); task-pickup §3 ("Nothing preempts a claimed item").

### SCH-006 — A freed slot is reused promptly
**MS3** · WP3.6 · MUST · FIX

When a slot frees, the next eligible task is claimed on that event, not at the next fixed pass.

- AC1: Demonstration (benchmark, MS3) — the scenario suite measures the time from a slot-free event to the next claim event over 1,000 hand-overs. Target: p95 at most 5 s. Floor: p95 at most 30 s and maximum at most 120 s; the legacy minimum is one pass, up to 180 s (BL-04).
- AC2: A periodic full re-evaluation (default every 60 s) guarantees progress even if an event is missed.

Baseline: A freed slot is reused at the next pass, and passes run every three minutes (task-pickup §3; BL-04).

Better on: latency, throughput.

Source: task-pickup §3 ("Minimum latency from 'slot freed' to 'next item claimed' is one pass" — three minutes today).

### SCH-007 — Stacked admission caps for heavy stages
**MS3** · WP3.6 · MUST · KEEP

Stage classes are `light` (shape) and `heavy` (build, verify, proof). Heavy stages start only
within three caps, all policy data: a cluster heavy cap, a train cap for non-rush work (the
difference is reserved for rush), and a per-project heavy cap that rush ignores. Among admissible
stages, rush goes first, then creation order.

- AC1: With caps 4 / 3 / 2, a fourth non-rush heavy stage waits with reason `throttled: train heavy cap (3/3)`; a rush stage still starts.
- AC2: Work that cannot be admitted is never launched to fight for resources: no Job exists for it.
- AC3: Defaults are documented by node size (DEP-021); the chart default is cluster 2 / train 1 / project 1.

Source: `mh.py` `caps_allow`, `_drive_order`; driver §5 "Capacity knobs" (`MH_HEAVY_CAP`, `MH_TRAIN_HEAVY_CAP`, `MH_PROJECT_HEAVY_CAP`).

### SCH-008 — Pickup Preview
**MS2** · WP2.5 · MUST · FIX

For any project the system answers: the current queue in claim order, the reason code(s) for
every task that is not claimable now, who holds each slot and in what phase, and a simulation of
the next N claims (default 10). Available through API, CLI (`sortyardctl queue`, `why KEY-N`),
MCP and UI.

- AC1: The preview is computed by the same function the scheduler runs, from the same snapshot type.
- AC2: The time from changing a lane cap, a priority, a rank or a dependency to the preview showing it. Target: 1 s. Floor: 5 s.
- AC3: Every place an item can wait (task-pickup §7's table) corresponds to a reason code shown here.
- AC4: Demonstration (benchmark, MS2) — for each place an item can wait in task-pickup §7's table, a scripted operator asks why a task is not running. Target: one call or one screen answers in under 1 s for 100% of the places. Floor: every place is answered in fewer steps than the legacy route, which needs `state.json` from the cluster or a hand derivation (BL-09).

Baseline: Several of the places an item can wait are "Not visible" to a reader (task-pickup §7); phase and slot use are in `state.json` on a cluster volume (HARNESS-251, HARNESS-256; BL-09).

Better on: failure-visibility, operator-actions, latency.

Source: task-pickup §7 ("Where a reader sees it": several rows say "Not visible"); HARNESS-251, HARNESS-256.

### SCH-009 — A closed catalogue of reason codes
**MS2** · WP2.5 · MUST · NEW

Reason codes are an enum with a documented meaning, the fix, and who can fix it. The v1 set
covers at least: `not-ready:<rule>`, `preflight:<check>`, `preflight-unverifiable:<check>`,
`held: backlog`, `held: parent in backlog`, `held: blocked by`, `held: blocker cancelled`,
`held: release withdrawn`, `held: project release off`, `held: project build off`,
`held: needs`, `held: decision`, `held: lanes full`, `held: ranked behind`, `paused: project`,
`paused: global`, `throttled: <cap>`, `unbound: <element>`, `parked: <reason>`,
`handed-back`, `awaiting-deployment`, `inherited: main red`.

- AC1: The API schema types the code as an enum; a free-text reason is rejected in CI.
- AC2: The documentation page for reason codes is generated from the enum.
- AC3: Adding a code is an additive API change; removing or renaming one follows the deprecation policy (API-013).

Source: DESIGN §6 view 2 (reason codes as display strings); spec NOTES ambiguity 13 (DecisionLog `reason_codes` left free-text).

### SCH-010 — Decision log
**MS2** · WP2.5 · MUST · FIX

Every scheduling evaluation records what it decided for each candidate (claim, skip with
reasons) and the inputs it used: policy versions, a hash of the queue snapshot, lane state.

- AC1: "Why was X not claimed at time T" is one query returning the evaluation, X's reasons and the tasks ranked ahead of it.
- AC2: A recorded evaluation can be re-run offline from its stored inputs and yields the same decisions (determinism test).
- AC3: Skips are deduplicated: an unchanged skip reason is stored once with a last-seen time, so the log does not grow per pass.
- AC4: Demonstration (replay, MS2) — the worked case of task-pickup §8 and 20 questions sampled from the recorded passes are answered from the decision log. Target: 100% answered by one query in under 1 s, each naming the tasks ranked ahead. Floor: 100% answered without reading comments or cluster files; the legacy answer is a hand derivation (BL-09).

Baseline: Why a task was not picked is derived by hand from board comments and `state.json` (task-pickup §8; BL-09).

Better on: failure-visibility, operator-actions.

Source: task-pickup §8 (a derivation done by hand from Plane comments); DESIGN §3.8 DecisionLog.

### SCH-011 — Tuning is live, audited data
**MS2** · WP2.6 · MUST · FIX

Lanes, caps, prioritisation keys, thresholds and cadences are stored configuration read at
decision time. A change needs no deploy, takes effect at the next evaluation, records who changed
what from which value, and shows which decisions were made under which version.

- AC1: Changing a project's lanes through UI, CLI or API changes claims within one evaluation.
- AC2: No scheduling constant is a literal in code: a test enumerates the policy keys in the legacy-constants table (DEF-005) and asserts each is read from configuration.
- AC3: Demonstration (benchmark, MS2) — a lane change and a cap change are made through the console, the CLI and the API, timing each from the action to the first evaluation that uses it. Target: one action, in force within 5 s, with its audit entry. Floor: a lane change is no slower than the legacy commit route, and a cap or threshold change needs no code change and no release (BL-10).

Baseline: Lanes change by a commit to `repos.yaml`, read at the next pass; caps and thresholds are literals in three files and need a code change and a release (driver §1; task-pickup conformance row 8, HARNESS-246; BL-10).

Better on: latency, operator-actions, failure-visibility.

Source: driver §1 ("the same values are hardcoded"), task-pickup conformance row 8 (HARNESS-246: merged changes not released).

### SCH-012 — Pause and resume
**MS2** · WP2.4 · MUST · KEEP

An operator can pause one project or the whole installation. Paused means no new claims and no
new stage launches; running stages finish and their results are recorded. Pause state survives
restarts and upgrades.

- AC1: After `helm upgrade`, a project paused before the upgrade is still paused.
- AC2: Pausing shows `paused: project` or `paused: global` on every affected task.

Source: driver §5 ("Releases keep the live `suspend` state"); driver §1 (`lanes: 0` pauses).

### SCH-013 — Observe mode
**MS2** · WP2.4 · MUST · KEEP

The scheduler can run per project in `observe` mode: it evaluates and logs decisions exactly as
it would in `active` mode and changes nothing.

- AC1: In observe mode there are zero state transitions and zero Jobs; the decision log is populated.
- AC2: Switching a project from observe to active is one audited action.

Source: `drive.py --dry-run`, `plane_sync.py --dry-run`; the shadow conductor (README "Shadow conductor").

### SCH-014 — Failure isolation between items and projects
**MS2** · WP2.4 · MUST · FIX

An error while evaluating, claiming or advancing one task or one project never prevents any other
task or project from being evaluated, claimed or advanced in the same cycle.

- AC1: Fault-injection test: an exception while evaluating project A leaves project B's evaluation unaffected; from MS3 the same test covers claims and the advancement of running chains.
- AC2: The error is recorded on the affected task or project and counted (REC-005).
- AC3: Demonstration (chaos, MS3) — an exception is injected into the evaluation, the claim and the advancement of one task in each of 1,000 cycles across five projects. Target: every other task and project is evaluated, claimed and advanced in the same cycle, with at most 5 s of added delay. Floor: no other task or project is skipped in that cycle; the legacy pass aborted (BL-22).

Baseline: An exception in one claim aborts the rest of the pass (task-pickup §3 and conformance row 2, HARNESS-254; BL-22).

Better on: stall-rate, throughput, safety.

Source: task-pickup conformance row 2 and §3 ("An exception in a claim aborts the rest of the pass", HARNESS-254).

### SCH-015 — Decisions come from one consistent snapshot
**MS2** · WP2.4 · MUST · FIX

Each evaluation reads tasks, relations, ranks, lanes and policies in one database snapshot. There
is no degraded mode that orders by fewer keys; if the snapshot cannot be read, nothing is claimed
and the health view says so.

- AC1: A simulated read failure produces zero claims and a `scheduler: snapshot unavailable` health state.
- AC2: No code path orders by priority alone because rank was unavailable.
- AC3: Demonstration (chaos, MS2) — each input of an evaluation (tasks, relations, ranks, lanes, policies) is made unreadable in turn over the recorded passes. Target: zero claims are decided from a partial read, and the health view names the unreadable input within one evaluation. Floor: zero evaluations order by fewer keys; the legacy pass ordered by priority alone after a failed clone (BL-22).

Baseline: A failed clone of the plan made the pass ignore milestone order and claim by priority alone (task-pickup conformance row 3, HARNESS-255; BL-22).

Better on: safety, failure-visibility.

Source: task-pickup conformance row 3 (HARNESS-255: a failed clone made the pass ignore milestone order); driver §4 ("An unreadable board pauses non-urgent claims").

### SCH-016 — Claims are atomic and fenced
**MS3** · WP3.6 · MUST · FIX

A claim creates the chain, moves the task and takes the slot in one transaction, and stamps the
chain with a monotonically increasing epoch. Only the holder of the current epoch may write side
effects for that chain (REC-020).

- AC1: Two controllers racing to claim the same task result in exactly one chain (concurrency test).
- AC2: If the controller dies between claim and first stage launch, the chain is resumed, not re-claimed, after restart.
- AC3: Demonstration (chaos, MS3) — two controllers race for the same tasks, and the leader is killed between claim and launch, over 10,000 claims. Target: zero duplicate chains, zero tasks left Todo with a live record, and no repair step. Floor: zero of either after restart; the legacy system left such a task skipped every pass (BL-24).

Baseline: A Todo item with a stale live record is skipped every pass and nothing shows it (task-pickup §4, HARNESS-256; BL-24).

Better on: safety, stall-rate.

Source: task-pickup §4 ("A Todo item with a stale live record is skipped every pass", HARNESS-256); in-flight-steering ("one task, one current route, one writer").

### SCH-017 — Release is necessary, not sufficient
**MS2** · WP2.4 · MUST · KEEP

Eligibility is recomputed from current rules at claim time. A task released under yesterday's
rules that fails today's readiness or preflight is not claimed; it is shown as held with the
failing rule.

- AC1: Tightening a rule after release makes affected released tasks ineligible at the next evaluation.
- AC2: A claim-time gate added by policy is evaluated at every claim, whatever the task's release state (the production-flip gate of RDY-014 relies on this).

Source: `gate_cutover_pickup` note ("A stale Todo/conductor label must never bypass a production flip's plan").

### SCH-018 — Order among projects at the heavy caps
**MS3** · WP3.6 · MUST · KEEP

When several projects wait at a cluster-level cap, admission is by stage creation time. The
policy is recorded and shown; nothing depends on poll timing.

- AC1: A fixture with three projects waiting shows admission in creation order, and the preview says which stage is next.
- AC2: The interleaving rule is policy data with one shipped value (`fifo`); other values are refused until implemented.

Source: task-pickup §6 ("in creation order (`created_at`, then id) among non-terminal tasks").

### SCH-019 — Low-priority system work comes after planned work
**MS2** · WP2.4 · MUST · KEEP

System-created tasks that are not under a planned parent (ship retries, follow-ups once
released) rank after all planned work in the same project unless marked urgent.

- AC1: A `ship` task and a planned `feature` both eligible: the feature is claimed first.
- AC2: At most `ship_cap` ship tasks are open per project (policy data); the rest wait.

Source: conductor README "Plane sync" `unlanded_builds` ("picked up after planned work", `SHIP_CAP`).
