# 13 — Milestones

Nine milestones, **MS0–MS8**. Each ends in a tagged pre-release that someone could install and
use for what the milestone adds, and each has an exit demonstration. A requirement belongs to
exactly one work package: the requirement lists and the totals in this file are generated from
each requirement's tag line by [tools/gen.py](tools/gen.py), and `requirements.json` holds the
same data.

**Two levels in every measured exit** (QLT-051). The plan, the design and the sizes aim at the
**target**: the best outcome imaginable. A milestone exits, and a project is cut over, on the
**floor**: demonstrably better than the legacy baseline, or the stated absolute bar. The gap
between a measured value and its target is recorded and filed as backlog (rule 12). Each exit
also lists the **comparisons** against the legacy system that are due at that milestone
(QLT-050); the lists are generated from the `Demonstration` criteria, and the baselines they
use are in [18-divergences.md](18-divergences.md).

Two tracks run through them:

- **Product track** — MS1 to MS6 and MS8. Judged on a fresh cluster with nothing from the owner's estate.
- **Migration track** — parts of MS0 and MS2, and all of MS7. Moves the estate onto product releases.

## Overview

| # | Name | Release | Usable increment | Depends on | Size |
|---|---|---|---|---|---|
| MS0 | Foundation close-out | v0.1.x | An honest repository: one-command replica, all checks gating, prototypes ported or retired; legacy evidence frozen and legacy baselines captured | — | <!--gen:size MS0-->≈ 32 tasks · 13 req (13 MUST)<!--/gen--> |
| MS1 | Tracker | v0.2 | A self-hosted task board that agents and the operator share: API, CLI, MCP, console | MS0 | <!--gen:size MS1-->≈ 108 tasks · 80 req (77 MUST)<!--/gen--> |
| MS2 | Queue | v0.3 | The board explains itself: readiness, preflight, release, and a scheduler in observe mode with Pickup Preview. The estate's boards can be mirrored and replayed | MS1 | <!--gen:size MS2-->≈ 80 tasks · 44 req (39 MUST)<!--/gen--> |
| MS3 | Engine | v0.4 | A task becomes a landed change on a plain Git repository with a scripted agent — the quickstart demo and the test rig | MS2 | <!--gen:size MS3-->≈ 107 tasks · 57 req (56 MUST)<!--/gen--> |
| MS4 | GitHub delivery | v0.5 | Real agents, real pull requests: build → reviews → fix rounds → auto-merge | MS3 | <!--gen:size MS4-->≈ 74 tasks · 40 req (28 MUST)<!--/gen--> |
| MS5 | Unattended | v0.6 | It can be left alone: every stall class has a recovery; nothing fails silently | MS4 | <!--gen:size MS5-->≈ 102 tasks · 50 req (33 MUST)<!--/gen--> |
| MS6 | Glass | v0.7 | Dashboards, explorers, the scorecard, backup and restore; the console is complete, concierge included | MS5 (starts after MS3) | <!--gen:size MS6-->≈ 52 tasks · 16 req (8 MUST)<!--/gen--> |
| MS7 | Self-hosting and estate cutover | v0.8–v0.9 | Sortyard builds Sortyard; then every estate project; then the legacy system is switched off | MS5 and WP6.5 for the pilot; MS6 for the other cutovers | <!--gen:size MS7-->≈ 33 tasks · 9 req (7 MUST)<!--/gen-->, plus 63 days of windows |
| MS8 | 1.0 | v1.0.0 | A public release with tested upgrades, signed artefacts, docs and governance | MS6 and the MS7 pilot verdict | <!--gen:size MS8-->≈ 42 tasks · 19 req (14 MUST)<!--/gen--> |

**Sizes.** A work package's size is its estimated number of one-PR tasks: S is 1–5, M is 6–10,
L is 11–18, XL is 19 or more, and the figure after the letter is the estimate. A milestone's
size is the sum of its work packages. These are judgement, not measurement: most requirements
are one or two tasks, and the few that enumerate rows are more (rule 2). Operational work
packages count their operations as tasks. The sizes are for reaching the targets, not only the
floors: the revision of 2026-11-12 added 64 tasks for the baseline capture, the comparisons,
upgrades without downtime, stall detection, event-driven hand-offs, the console's local store
and the concierge.

**Elapsed time (inference; re-baseline at the MS1 gate).** The plan is about
<!--gen:total-tasks-->630<!--/gen--> one-PR tasks for <!--gen:planned-reqs-->328<!--/gen-->
requirements. The evidence on rate is thin. Across the estate, 378 items went through review in
the seven days to 2026-11-10 (conductor README, "Review tripwire"); against the 17 lanes
configured today (`repos.yaml`) that is about 3 items per lane per day, small ones included.
The Sortyard repository itself has four merged pull requests, all on 2026-11-10 — too few to
set a rate. Sortyard's tasks are full features with two reviews each, so plan below the estate
average: 3 to 7 merged tasks a day on the board's 2 lanes. That is
<!--gen:weeks 7-->13<!--/gen--> to <!--gen:weeks 3-->30<!--/gen--> weeks of lane time, and
<!--gen:weeks 5-->18<!--/gen--> weeks at 5 a day. A third lane (OD-11) takes a third off. Two
things sit on top, and no lane count shortens them: the findings each goldfish gate sends back,
and MS7's calendar windows — 14 days of pilot, then seven 7-day project windows, one at a time
(49 days). Of MS7, MS8 needs only the pilot's verdict, so 1.0 does not wait for the last
cutover. MS1 is the calibration sample: at its gate, replace the rate above with Sortyard's own
merged tasks per day and restate the dates.

```
MS0 ─► MS1 ─► MS2 ─► MS3 ─► MS4 ─► MS5 ──► MS7a pilot ──► MS7b cutovers ──► MS7c retirement
                      │             │          │ ▲            ▲
                      │             ▼          │ │ backup     │ complete console
                      └──────────► MS6 ────────┼─┴────────────┘
                                    │          ▼
                                    └───────► MS8 (1.0)
```

The pilot needs backup and restore (WP6.5) as well as MS5: no project is moved onto an
installation that cannot be restored. The other cutovers need the MS6 gate. MS8 needs the MS6
gate and the pilot's verdict.

## Rules for turning this into board items

These let a planner file work without design judgment.

1. **Milestones and work packages are `parent` tasks.** One milestone = one top-level parent, `MSn: <name>`, kept in board order MS0 to MS8 (the top-level order is the pickup rank, SCH-002). One work package = one parent beneath it, `<WP id>: <WP name>`. Each entry in a package's *Depends on* column becomes a `blocked_by` relation from **every child task** of that package to the upstream package's parent task: a parent is Done only when its children are (TRK-005), so the children become eligible when the upstream package completes. A relation placed on the parent itself holds nothing. In that column `MSn gate` is the gate task of that milestone (rule 9), `all of MSn` is every other work package of that milestone, and `OD-n` is that decision's task (rule 8).
2. **One requirement = one to three `feature` tasks** under its work package's parent, with the requirement id as the task id (the board shows `<REQ id>: <requirement title>`), so the index can be reconciled against the board. The task's `outcome` is one sentence with one result, taken from the requirement's statement or from the acceptance criteria it delivers; `repo` is `sortyard/sortyard`. Split when the requirement's acceptance criteria touch more than one surface (task-ready "One PR's worth": one surface per task, at most three acceptance tests). Split ids keep the first piece: `TRK-007`, `TRK-007b`. A requirement delivered in two steps is filed in two places, the later part under the next split id (table below). **Requirements that enumerate rows are split by row instead:** MIG-015 (one task per deliverable it names), RDY-006 (one per check; the Git-host parts are filed under WP4.9), OBS-004 (one per row or pair of rows of the catalogue), UI-015 (one per dashboard group it names), CLI-005 (one per tool whose command exists by MS2; the rest ride with their capability), REC-025 (one for the matrix check, one per section of [16-legacy-parity.md](16-legacy-parity.md) that still lacks scenarios, one per chaos fault), QLT-001 (one per guide, one per generated reference not yet generated).
3. **Acceptance is the ACs.** Each task's acceptance names one test for each AC it covers, in the form the ready rules require (`test:` path and `name:`; the test may be new), at the layer QLT-010 assigns. The test name carries the requirement and the criterion — `test_trk_007_ac1_…` — so that coverage of this specification can be checked by name. An AC performed by a zero-context agent or a person, or one that is an operation on the estate (a rehearsal, a recorded scan, a retention period), belongs to the milestone gate task or to the operational task, not to a feature. Criteria that begin `Demonstration (…)` follow rule 12.
4. **Order.** File a milestone's tasks in work-package order, and inside a work package in requirement-id order, unless a requirement names another as a prerequisite: sequence number is the last pickup key. Add `blocked_by` between tasks only for real merge-order needs.
5. **File by tranche.** The current milestone's parents and tasks are in Todo; the next milestone's are filed in Backlog; later ones stay in this document. Until the pilot (MS7a) the SORTYARD board runs on the legacy system with task release off (`repos.yaml`: `tasks: off`), so nothing there enforces a relation: give a task the `conductor` label only when every blocker is Done. A task released early is a task that can be claimed early (CORPUS R2). After the pilot, Sortyard enforces relations itself (TRK-006).
6. **Priority.** MUST → high; SHOULD → medium. No exit criterion depends on a SHOULD, so one may move to the next milestone: re-parent it there so its work package can close. A SHOULD whose origin is KEEP or FIX is still owed before the estate's cutovers (MS7b exit).
7. **Operations are not builds.** Work packages marked *operational* are `deployment` tasks with `needs`; they are never claimed by a build lane.
8. **Decisions are `decision` tasks** with the default from [15-open-decisions.md](15-open-decisions.md). Every default is adopted as a planning assumption, so work is written against it and no build task waits for an answer. OD-5 to OD-11 are filed as decided by default (2026-11-12) and can be reopened by the owner. OD-1 to OD-4 stay open: file each as a premise-class decision, which never takes its default by date (RDY-015), make it a blocker of the gate task named there (the MS3 gate for OD-1 to OD-3, the MS4 gate for OD-4), and make the irreversible step it guards — publishing the repository, archiving a Plane project — a task blocked by it.
9. **Every milestone ends with a gate task** (the goldfish run, QLT-004) that is blocked by all its work packages and whose acceptance is the exit criteria below. It goes under the work package named "milestone gate" where there is one, and directly under the milestone parent where there is not.
10. **Definition of done for any capability:** domain command + API operation + CLI path + MCP reach + UI control + docs entry + tests at the right layers.
11. **Phrase tasks so that the legacy preflight passes them.** Requirements here are often invariants ("every…", "no…"). Until the pilot, tasks are checked by the legacy preflight (conductor README, "Preflight" checks 8 and 9): a title or outcome quantified over every, all or any page, command, route, file, section or test must name its list (`surfaces`; more than 8 means split), and a task that delivers a detector, guard, enforcer, ratchet, budget or registry-wide test must list its `must_catch` and `must_allow` cases. The acceptance criteria usually contain the list or the cases: copy them into the task.
12. **Targets, floors and demonstrations** (QLT-050, QLT-051). A criterion with `Target:` and `Floor:` becomes a test that asserts the floor and records the measured value in the scorecard; the task is designed and sized to reach the target. When a gate finds a value at or above its floor and below its target, file one `target-gap` task under a parent `MSn-GAPS` in Backlog, low priority and unreleased, naming the criterion and the measured value. A gap never holds a gate. A `Demonstration (<method>, MSn)` criterion is its own task, `<REQ id> AC<n>: demonstration`, blocked by the requirement's feature tasks and by WP0.4 (the baselines): filed with its requirement when MSn is the requirement's milestone, and otherwise under the work package that hosts later comparisons — WP2.8, WP3.10, WP4.7, WP5.11, WP6.4, WP7.2 for MS2 to MS7. A demonstration that misses its floor holds the gate, and for the estate the legacy behaviour is kept until it passes (QLT-050). When the usage census reverses a conditional cut (MIG-017), re-tag the requirement into the milestone its divergence entry names and run the generator.

**Requirements delivered in two steps.** A requirement has one tag, but these say in their text
that part of them lands later. File the later part under the completing work package, as the
next split id of the same requirement (`UI-011b`); its size is already counted there. An
acceptance criterion that begins with a work package in brackets, or with "From MSn", belongs
to the later part.

| Requirement | First step (its own work package) | Completed in |
|---|---|---|
| DEP-001 workloads | WP1.6: `api` and Postgres | WP3.2 (`controller`), WP3.4 (`integrator`) |
| DEP-002 namespace-admin install | WP1.6: no cluster-scoped objects | WP3.2: the controller's Role |
| DEP-005 install time | WP1.6: install to first task filed | WP3.10: install to finished demo chain |
| IAM-002 operator sign-in | WP1.3: local accounts | WP6.4: OIDC and the proxy mode |
| UI-004 task detail | WP1.5: notes, state changes, decisions | WP3.9: the chain |
| UI-017 administration | WP1.5: users, tokens, projects, system information | WP6.4: the rest |
| UI-002 coverage manifest | WP1.5: the manifest and its check | every gate task; final audit in WP6.4 |
| CLI-002 task-level commands | WP1.4: the tracker commands | each command with the capability it operates |
| RDY-006 preflight checks | WP2.2: the checks that need no Git host | WP4.9: `write-reach`, `evidence-reach`, `inputs` existence, `needs` |
| SCH-005 rush lane | WP2.4: order and lane accounting | WP3.6: running Jobs are never preempted |
| DEF-001 definition kinds | WP2.6: policy, lane, project | WP3.8: workflow, packet template, harness profile, checklist |
| DEF-005 policy keys | WP2.6: the key registry and its two checks | each key with the behaviour that reads it |
| UI-016 explorers | WP2.7: search and one evaluation | WP6.3: saved searches, replay |
| CLI-005 legacy tool parity | WP2.9: the tools whose commands exist by MS2 | each remaining tool with its capability; coverage of the whole operations inventory in WP5.11 |
| EXE-012 harness adapters | WP3.5: `scripted`, `none` | WP4.2: `claude-code`, `codex` |
| FLW-002 `change` workflow | WP3.4: on the plain-git adapter | WP4.1: on GitHub |
| UI-011 logs and traces | WP3.9: the basic log view | WP6.3: search, trace filtering, deep links |
| QLT-015 shipped test assets | WP3.10: the scripted harness and the demo repository | WP4.1: the Git host fake and the CI fake |

---

## MS0 — Foundation close-out

**Usable increment.** The repository tells the truth about itself and a newcomer can run it:
one command to a local replica, every check gating, each Phase 1 prototype either in the product
or retired. On the migration track, the two things that cannot be recovered later are done: the
legacy evidence is frozen, the legacy conductor's inputs are being recorded, and the legacy baselines that
every later comparison is made against are captured.

**Exit criteria.**
1. On a clean machine with Docker, a fresh clone reaches a running replica and a passing `verify`. Target: one command and 5 minutes. Floor: two commands and 15 minutes.
2. CI has no `continue-on-error` job; `pytest spec` gates.
3. Every row of the carry-over table in [14-mapping.md](14-mapping.md) §3 has a final disposition, and `src/` imports nothing from `migration/`.
4. The legacy evidence snapshot verifies and its manifest digest is recorded.
5. Legacy pass inputs are retained and one day of them replays offline. Target: every pass since recording began, with no gap. Floor: 7 consecutive days.
6. **Baselines.** Every baseline in [18-divergences.md](18-divergences.md) §2 has a captured value or an `unmeasurable` record with its reason (MIG-016), and none was filled in from memory.
7. **Comparisons.** Each of these meets its floor, with the measured value in the scorecard: <!--gen:demos MS0-->MIG-017 AC1<!--/gen-->. The census gives every conditional cut a count and an outcome.

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP0.1 | Repository truth: README, guides, replica, CI, decision records, the divergence rule | — | M · 9 | <!--gen:req WP0.1-->DEP-018, QLT-002, QLT-003, QLT-005, QLT-012, QLT-025, QLT-050<!--/gen--> |
| WP0.2 | Prototype close-out and migration quarantine | WP0.1 | M · 10 | <!--gen:req WP0.2-->MIG-006, MIG-015<!--/gen--> |
| WP0.3 | Evidence freeze and pass recording *(operational; start first)* | — | S · 4 | <!--gen:req WP0.3-->MIG-001, MIG-002<!--/gen--> |
| WP0.4 | Legacy baselines and usage census *(migration track; scripts and one capture run)* | WP0.3 | M · 9 | <!--gen:req WP0.4-->MIG-016, MIG-017<!--/gen--> |

## MS1 — Tracker

**Usable increment.** A self-hosted task board with an API, CLI, MCP server and console. A team
could use it as its agents' task tracker even before anything executes.

**Exit criteria** (goldfish agent, public docs only, clean kind cluster):
1. Install to first task filed. Target: one command and 3 minutes. Floor: 8 commands and 15 minutes.
2. Bootstrap the first admin with the setup token; create a project.
3. File a 12-task file with dependencies through the CLI; file two more through MCP with an intake token; every filing returns a result.
4. Reorder top-level tasks by drag and by keyboard; the API shows the new order.
5. A viewer token is refused on every mutation; a token from another project cannot read this project's tasks; the generated authorisation suite is green.
6. The same task shows identical state in console, CLI and MCP, and its timeline shows every action above with its actor.
7. Accessibility scan, keyboard journeys and the three viewport widths pass. Initial JavaScript, gzipped — Target: 200 KB. Floor: 350 KB.
8. An input on the board shows its result, at p95 on the reference workload — Target: within 100 ms. Floor: within 1 s.
9. **Comparisons.** Each of these meets its floor against its legacy baseline, with the measured value in the scorecard and a `target-gap` task for each one short of its target: <!--gen:demos MS1-->TRK-007 AC4, API-014 AC3, IAM-008 AC4, DEP-020 AC2<!--/gen-->.

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP1.1 | Domain core: task model, state machine, relations, order, notes, ledger, scorecard | WP0.2 | XL · 24 | <!--gen:req WP1.1-->TRK-001, TRK-002, TRK-003, TRK-004, TRK-005, TRK-006, TRK-007, TRK-008, TRK-009, TRK-010, OBS-001, OBS-002, QLT-010, QLT-011, QLT-014, QLT-022, QLT-051<!--/gen--> |
| WP1.2 | API service and conventions | WP1.1 | XL · 20 | <!--gen:req WP1.2-->TRK-012, REC-013, API-001, API-002, API-003, API-004, API-005, API-006, API-007, API-008, API-011, API-014, API-015, API-017, API-018, OBS-011<!--/gen--> |
| WP1.3 | Identity, authorisation, audit | WP1.1 | L · 14 | <!--gen:req WP1.3-->IAM-001, IAM-002, IAM-003, IAM-004, IAM-005, IAM-006, IAM-008, IAM-009, IAM-010, IAM-011<!--/gen--> |
| WP1.4 | CLI and MCP | WP1.2, WP1.3 | M · 9 | <!--gen:req WP1.4-->MCP-001, MCP-002, MCP-003, MCP-004, CLI-001, CLI-002, CLI-003<!--/gen--> |
| WP1.5 | Console v1: shell, local store, board, task detail, filing, admin basics | WP1.2, WP1.3 | XL · 21 | <!--gen:req WP1.5-->TRK-014, UI-001, UI-002, UI-003, UI-004, UI-005, UI-017, UI-018, UI-019, UI-020, UI-021, UI-023, UI-024, UI-025<!--/gen--> |
| WP1.6 | Chart, one-command install and release pipeline | WP1.2 | L · 18 | <!--gen:req WP1.6-->OBS-015, DEP-001, DEP-002, DEP-003, DEP-004, DEP-005, DEP-006, DEP-007, DEP-012, DEP-013, DEP-014, DEP-020, QLT-024, QLT-030, QLT-031<!--/gen--> |
| WP1.7 | Milestone gate | WP1.4, WP1.5, WP1.6 | S · 2 | <!--gen:req WP1.7-->QLT-004<!--/gen--> |

## MS2 — Queue

**Usable increment.** The board knows which tasks are ready, which will be released, and in
what order they would run — and says why not, for every task. The scheduler runs in observe
mode: no execution yet, full reasoning. For the estate: its Plane boards are mirrored read-only
and the legacy conductor's recorded passes replay through Sortyard's evaluator.

**Exit criteria.**
1. For the 14 tasks from MS1, the Pickup Preview shows the claim order and a reason code for every task that is not claimable.
2. Changing lanes, a priority, the order and a dependency each change the preview, from the console, with an audit entry. Target: within 1 s. Floor: within 5 s.
3. A task that fails a preflight check is held with the check named and the fix stated; fixing the cause releases it without anyone touching it again.
4. A routine decision takes its default at its date in a clock-controlled test; a premise-class one escalates to the owner list.
5. "Why was X not claimed at T" is answered from the decision log in the console.
6. Migration track: the importer's dry run for each driven board shows no unmapped control label. Replay of at least 2,000 recorded legacy passes, with every divergence classified and no open implementation defect, shows claim agreement — Target: 100%. Floor: at least 99%.
7. **Comparisons.** Each of these meets its floor against its legacy baseline, with the measured value in the scorecard and a `target-gap` task for each one short of its target: <!--gen:demos MS2-->TRK-002 AC4, TRK-009 AC3, TRK-014 AC4, RDY-010 AC3, SCH-003 AC3, SCH-008 AC4, SCH-010 AC4, SCH-011 AC3, SCH-015 AC3<!--/gen-->.

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP2.1 | Readiness and release | WP1.1 | M · 8 | <!--gen:req WP2.1-->TRK-013, RDY-001, RDY-002, RDY-003, RDY-004, RDY-010<!--/gen--> |
| WP2.2 | Preflight framework and native checks | WP2.1 | M · 8 | <!--gen:req WP2.2-->RDY-005, RDY-006<!--/gen--> |
| WP2.3 | Lifecycle automations: decisions, needs, outcome-met | WP2.1 | M · 6 | <!--gen:req WP2.3-->TRK-011, RDY-007, RDY-008, RDY-015<!--/gen--> |
| WP2.4 | Scheduler core in observe mode | WP2.1 | L · 16 | <!--gen:req WP2.4-->RDY-013, SCH-001, SCH-002, SCH-003, SCH-004, SCH-005, SCH-012, SCH-013, SCH-014, SCH-015, SCH-017, SCH-019<!--/gen--> |
| WP2.5 | Pickup Preview, reason codes, decision log | WP2.4 | M · 9 | <!--gen:req WP2.5-->SCH-008, SCH-009, SCH-010, API-012, OBS-003<!--/gen--> |
| WP2.6 | Live configuration and tuning | WP1.2 | M · 7 | <!--gen:req WP2.6-->SCH-011, DEF-001, DEF-005, DEF-007<!--/gen--> |
| WP2.7 | Queue screens | WP2.5, WP2.6 | M · 6 | <!--gen:req WP2.7-->UI-006, UI-007, UI-008, UI-016<!--/gen--> |
| WP2.8 | Plane import, mirror mode, replay comparison; hosts the comparisons due at MS2 *(migration track)* | WP2.4, WP0.3, WP0.4 | L · 15 | <!--gen:req WP2.8-->EXT-006, MIG-003, MIG-004, MIG-005<!--/gen--> |
| WP2.9 | CLI parity with the legacy operator tools | WP2.1, WP2.5 | S · 5 | <!--gen:req WP2.9-->RDY-011, CLI-004, CLI-005<!--/gen--> |

## MS3 — Engine

**Usable increment.** On a fresh cluster with no accounts anywhere, a task becomes a landed
change: claim, build, review, land, done — with a scripted agent and a bundled Git repository.
This is the quickstart demo, and the rig on which every later behaviour is tested.

**Exit criteria.**
1. `sortyardctl demo` on a fresh install: three tasks run build → review → land on the demo repository, and the task page shows each stage with its facts. Target: within 3 minutes. Floor: within 10 minutes.
2. Install plus demo from the public docs (goldfish). Target: two commands and 8 minutes. Floor: 30 minutes.
3. With lanes 1 and heavy cap 1, the three tasks run strictly in preview order; raising lanes to 2 changes that at the next evaluation.
4. Killing the controller mid-chain: the chain resumes with no second Job. Target: within 15 s. Floor: within 60 s.
5. Cancelling a running stage ends its pod and frees the slot; a late result from it is refused. Target: within 10 s. Floor: within 60 s.
6. A workflow with an unbounded phase is refused by `apply`.
7. Upgrading the chart during running chains loses none of them. Target: zero failed requests and zero seconds in which nothing reconciles. Floor: failed requests for at most 5 s, and a pause of at most 60 s that is never silent.
8. With the source lock on, a definition cannot be edited in the console, and a change merged in the source repository takes effect by itself. Target: within 30 s. Floor: within 180 s.
9. The trademark search is recorded and namespaces are claimed (needed before any public preview).
10. **Comparisons.** Each of these meets its floor against its legacy baseline, with the measured value in the scorecard and a `target-gap` task for each one short of its target: <!--gen:demos MS3-->TRK-004 AC5, SCH-006 AC1, SCH-014 AC3, SCH-016 AC3, EXE-009 AC3, EXE-020 AC1, EXE-022 AC1, REC-011 AC2, REC-014 AC3, REC-015 AC3, REC-020 AC3, API-002 AC3, UI-004 AC3, DEF-002 AC3, DEF-003 AC3, DEP-001 AC3, DEP-002 AC3, DEP-009 AC1, DEP-010 AC1<!--/gen-->.

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP3.1 | Workflow engine and chains | WP2.4 | M · 9 | <!--gen:req WP3.1-->FLW-001, FLW-003, FLW-004, FLW-018, DEF-004<!--/gen--> |
| WP3.2 | Stage Jobs: binding, launcher, envelope, contract, cancel | WP3.1 | L · 18 | <!--gen:req WP3.2-->EXE-001, EXE-002, EXE-003, EXE-004, EXE-005, EXE-006, EXE-007, EXE-020, EXE-021, EXE-022, MCP-005, IAM-007<!--/gen--> |
| WP3.3 | Mirror service and commit custody | WP3.2 | M · 8 | <!--gen:req WP3.3-->EXE-008, EXE-009, EXE-010<!--/gen--> |
| WP3.4 | Plain-git adapter, integrator, check stages | WP3.3 | M · 9 | <!--gen:req WP3.4-->EXE-017, FLW-002, MRG-001, MRG-011, EXT-003<!--/gen--> |
| WP3.5 | Scripted harness, packet templates, usage, redaction | WP3.2 | M · 7 | <!--gen:req WP3.5-->EXE-012, EXE-015, EXE-018, CRD-010<!--/gen--> |
| WP3.6 | Admission caps, atomic claims, epochs | WP3.1 | M · 8 | <!--gen:req WP3.6-->SCH-006, SCH-007, SCH-016, SCH-018, REC-020<!--/gen--> |
| WP3.7 | Recovery basics; upgrades without downtime | WP3.2, WP3.6 | L · 18 | <!--gen:req WP3.7-->REC-001, REC-006, REC-011, REC-012, REC-014, REC-015, REC-021, REC-022, DEP-009, DEP-010, DEP-016<!--/gen--> |
| WP3.8 | Definitions: apply, export, source lock and pull, default bundle | WP3.1, WP3.3 | M · 10 | <!--gen:req WP3.8-->DEF-002, DEF-003, DEF-006, DEF-008, EXT-001<!--/gen--> |
| WP3.9 | Engine screens and system metrics | WP3.2 | M · 8 | <!--gen:req WP3.9-->UI-009, UI-010, UI-011, OBS-008, OBS-010<!--/gen--> |
| WP3.10 | Demo, shipped test assets, name clearance, the comparisons due at MS3, milestone gate | WP3.4, WP3.5, WP3.7, WP3.8, WP3.9, WP0.4 | L · 12 | <!--gen:req WP3.10-->QLT-015, QLT-043<!--/gen--> |

## MS4 — GitHub delivery

**Usable increment.** A team with a GitHub repository and a model API key gets tasks delivered
as pull requests: built, reviewed, fixed and merged through the repository's own gates.

**Exit criteria** (against the GitHub fake in CI, and once against a sandbox repository):
1. A task becomes a pull request, gets a code review and a test review, and merges by auto-merge on the reviewed head.
2. A rejected review leads to a fix round and a merge; two identical rejections park the task.
3. A pull request that falls behind is brought up to date, re-reviewed on the delta, and merges; a conflicting one gets a conflict round.
4. A missing required check produces a fix round after the grace period; a non-required failure does not.
5. Across the whole suite the fake records zero direct merges, zero admin merges, zero pushes to a default branch.
6. The same task completes with the Claude Code harness and with the Codex harness on an API key. In the estate cluster, the subscription pool selects, cools and falls back as specified.
7. A project is onboarded from the console; its onboarding check names anything missing.
8. Only the integrator pod mounts the Git host credential.
9. The time a chain waits on Sortyard itself, summed over its hand-offs, across the suite — Target: p95 at most 60 s. Floor: at most half the legacy wait for the same hand-offs.
10. **Comparisons.** Each of these meets its floor against its legacy baseline, with the measured value in the scorecard and a `target-gap` task for each one short of its target: <!--gen:demos MS4-->TRK-018 AC4, CRD-007 AC4, FLW-019 AC1, REC-021 AC3<!--/gen-->.

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP4.1 | GitHub and CI adapters, with their fakes | WP3.4 | L · 16 | <!--gen:req WP4.1-->TRK-017, CRD-007, MRG-002, MRG-003, MRG-006, MRG-008, MRG-013, CIH-013, API-016<!--/gen--> |
| WP4.2 | Real harnesses and routing | WP3.5 | M · 7 | <!--gen:req WP4.2-->EXE-013, EXE-014, EXE-016<!--/gen--> |
| WP4.3 | Credentials: keys, pool, broker, keeper, screens | WP4.2 | L · 12 | <!--gen:req WP4.3-->CRD-001, CRD-002, CRD-003, CRD-004, CRD-005, CRD-006, CRD-009, UI-012<!--/gen--> |
| WP4.4 | Code review, follow-ups, post-merge steps | WP4.1 | M · 8 | <!--gen:req WP4.4-->TRK-018, FLW-005, FLW-006, FLW-009, DLV-004<!--/gen--> |
| WP4.5 | Test-determinism review | WP4.4 | S · 3 | <!--gen:req WP4.5-->FLW-007<!--/gen--> |
| WP4.6 | Fix and conflict rounds, behind handling, stalled merge | WP4.4 | M · 10 | <!--gen:req WP4.6-->FLW-010, FLW-011, MRG-005, MRG-007, MRG-009, MRG-010, MRG-012<!--/gen--> |
| WP4.7 | Resume, adoption, landing sweep, event-driven hand-offs; hosts the comparisons due at MS4 | WP4.6, WP0.4 | M · 9 | <!--gen:req WP4.7-->FLW-013, FLW-014, FLW-015, FLW-019<!--/gen--> |
| WP4.8 | Inputs and CI evidence | WP4.1 | S · 4 | <!--gen:req WP4.8-->EXE-011, CIH-008<!--/gen--> |
| WP4.9 | Project onboarding (also completes the Git-host checks of RDY-006) | WP4.1 | S · 5 | <!--gen:req WP4.9-->DEF-009<!--/gen--> |

## MS5 — Unattended

**Usable increment.** It can be left alone. Every way the legacy system learned to stall has a
recovery or an owned item, and anything that goes quiet is noticed. This is the bar for putting
real projects on it.

**Exit criteria.**
1. The parity suite has a passing scenario for every KEEP and FIX row of [16-legacy-parity.md](16-legacy-parity.md) whose requirements are MUST and due by MS5; CI lists every other row as pending, with the milestone that owes it.
2. The chaos suite passes: controller kills, pod loss, database restart, Git host errors, model-capacity errors, a stale mirror, a full work volume.
3. A 72-hour unattended run on the sandbox workload (at least 100 tasks, with every stall class of the baseline catalogue injected) ends with every task Done, parked with a reason, or handed back with an owner, and no slot held past its bound. Its stalls, recoveries and operator actions are compared with the legacy figures from the driver log and the frozen ledger (BL-05, BL-06, BL-07). Target: at least 95% of stalls heal with no person, each found within 60 s and recovered within 10 minutes at p95, and zero operator actions. Floor: a higher self-healed share, a lower median time to recovery and fewer operator actions for each 100 tasks than the legacy system.
4. Stopping any registered mechanism raises its `SILENT` condition inside its window; restarting closes it.
5. A red main in the fixture is classified, triaged, fixed, confirmed on main and locked in, with no person involved; an infrastructure red goes to self-heal and spends no build.
6. An item parked on a defect returns by itself when the defect's fix merges.
7. The owner list contains only decisions, owner-routed needs and escalations.
8. **Comparisons.** Each of these meets its floor against its legacy baseline, with the measured value in the scorecard and a `target-gap` task for each one short of its target: <!--gen:demos MS5-->GRM-007 AC3, REC-001 AC3, REC-008 AC4, REC-026 AC1, MCP-002 AC3, EXT-001 AC3<!--/gen-->.

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP5.1 | Failure budgets and classification | WP4.6 | M · 7 | <!--gen:req WP5.1-->REC-002, REC-003, REC-004, REC-005, REC-016<!--/gen--> |
| WP5.2 | Park, hand-back, causes, self-heal, conditions, stall detection | WP5.1 | L · 16 | <!--gen:req WP5.2-->RDY-012, REC-007, REC-008, REC-009, REC-010, REC-023, REC-026, UI-013<!--/gen--> |
| WP5.3 | Review tripwire | WP4.5 | S · 3 | <!--gen:req WP5.3-->FLW-012<!--/gen--> |
| WP5.4 | Red main: sensing, triage, confirmation, lock-in | WP4.8 | L · 12 | <!--gen:req WP5.4-->CIH-001, CIH-002, CIH-003, CIH-004, CIH-005, CIH-006, CIH-012, OBS-017<!--/gen--> |
| WP5.5 | CI anomalies: inherited red, stopped jobs, flakes, quarantine | WP5.4 | M · 7 | <!--gen:req WP5.5-->MRG-004, CIH-007, CIH-009, CIH-010, CIH-011<!--/gen--> |
| WP5.6 | Mechanism health, heartbeats, quota | WP3.7 | M · 8 | <!--gen:req WP5.6-->CRD-008, REC-017, REC-018, REC-019, UI-014<!--/gen--> |
| WP5.7 | Grooming and shaping | WP5.3, WP2.3 | L · 11 | <!--gen:req WP5.7-->GRM-001, GRM-002, GRM-003, GRM-004, GRM-005, GRM-006, GRM-007<!--/gen--> |
| WP5.8 | Notifications, attention list, webhooks, sensors | WP5.2 | M · 8 | <!--gen:req WP5.8-->REC-024, API-009, OBS-013, OBS-014, EXT-004<!--/gen--> |
| WP5.9 | Delivery verification, design review, stranded builds | WP4.7 | M · 6 | <!--gen:req WP5.9-->FLW-008, FLW-016, DLV-001<!--/gen--> |
| WP5.10 | Premise policy pack | WP2.2 | S · 4 | <!--gen:req WP5.10-->RDY-009, RDY-014<!--/gen--> |
| WP5.11 | Parity and chaos suites, 72-hour run against the legacy baselines, the comparisons due at MS5, milestone gate | all of MS5, WP0.4 | XL · 20 | <!--gen:req WP5.11-->REC-025<!--/gen--> |

## MS6 — Glass

**Usable increment.** The console is complete: dashboards over the ledger, the scorecard, explorers, a full
trace viewer, administration, the concierge, backup and restore. Nothing needs a second tool.

**Exit criteria.**
1. Operator journeys J1–J5 and J8 pass end to end at three widths, keyboard-only, with no serious accessibility violation. The concierge and approval journeys (J6, J7) pass when WP6.6 ships; it is a SHOULD, owed before the estate's cutovers.
2. The UI coverage manifest has no exemption: every operator-facing operation has a control.
3. Every dashboard tile equals its hand-computed fixture and shows its definition, `as_of` and coverage.
4. Backup, restore into a fresh install, and the read checks pass in CI. Target: restored within 5 minutes. Floor: within 30 minutes.
5. On the reference workload every criterion of QLT-016, UI-009 and UI-018 is at or above its floor, and each one short of its target has a `target-gap` task.
6. The scorecard dashboard shows value, floor, target and trend for every measured criterion, with the legacy baselines as reference lines.
7. **Comparisons.** Each of these meets its floor against its legacy baseline, with the measured value in the scorecard and a `target-gap` task for each one short of its target: <!--gen:demos MS6-->IAM-002 AC4, OBS-009 AC2, DEP-003 AC3<!--/gen-->.

Work packages WP6.3 and WP6.5 depend only on MS3 and can be built alongside MS4 and MS5 when a
lane is free. WP6.5 must be done before the pilot starts (WP7.2).

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP6.1 | Metric read models and catalogue | WP3.9, WP5.4 | L · 13 | <!--gen:req WP6.1-->OBS-004, OBS-005, OBS-006, OBS-007, OBS-009<!--/gen--> |
| WP6.2 | Dashboards | WP6.1 | M · 6 | <!--gen:req WP6.2-->UI-015<!--/gen--> |
| WP6.3 | Explorers, trace viewer, palette, OTLP (completes UI-011, UI-016) | WP3.9 | M · 7 | <!--gen:req WP6.3-->EXE-019, UI-022, OBS-012<!--/gen--> |
| WP6.4 | Admin completeness, views, bulk edit, performance, scorecard dashboard; hosts the comparisons due at MS6 (completes UI-017 and IAM-002; final UI-002 audit) | WP6.2, WP0.4 | L · 11 | <!--gen:req WP6.4-->TRK-015, TRK-016, QLT-016<!--/gen--> |
| WP6.5 | Backup, restore, retention | WP3.7 | S · 5 | <!--gen:req WP6.5-->OBS-016, DEP-011<!--/gen--> |
| WP6.6 | Concierge and approval mode | WP5.8, WP6.2 | M · 10 | <!--gen:req WP6.6-->IAM-012, UI-026<!--/gen--> |

## MS7 — Self-hosting and estate cutover

**Usable increment.** For the estate: one system. In order — **7a** the pilot (the SORTYARD
project itself); **7b** every other driven project, smallest and safest first, one at a time;
**7c** the legacy system switched off. For the product: proof that it carries real delivery.

**Exit criteria.**
1. **7a, the pilot.** Sortyard has built Sortyard through its hypercare window (default 14 days for the pilot, MIG-009) with at least 50 merged tasks; the legacy driver is off for SORTYARD; a written verdict lists every operator intervention; the conformance ledger has no unmapped rule.
2. **7a, against the legacy system.** The pilot's figures from the ledger are set beside the project's legacy baselines: merged tasks a day for each lane (BL-01), release-to-merge time (BL-02), stalls and recovery (BL-05, BL-06), operator interventions (BL-07), review churn (BL-15), cost for each merged change (BL-16), time main is red (BL-17) and credential incidents (BL-19). Target: half of one-PR tasks merged within 30 minutes of release, zero operator actions on work in flight, at least 95% of stalls healed with no person, and every other figure better than its baseline. Floor: no figure worse than its baseline, and release-to-merge time, stall recovery and operator interventions each better than theirs.
3. **7b, before each cutover.** The conformance ledger is re-checked: every KEEP and FIX row the project relies on has a passing scenario or the owner's waiver. The baselines are captured again for the project and the usage census is re-run (MIG-016, MIG-017). Every divergence the project relies on is at or above its floor, or is switched to the legacy behaviour for that project (QLT-050).
4. **7b, each cutover.** Each remaining project has a recorded verdict after its window (default 7 days), with the same comparison as the pilot's at the same floor; at no moment did two systems claim for one project. Proposed order (OD-7): WALWARDEN, CRANK, CLOSER, NONCE, ROVE, LOOP, CPV2. HARNESS is not migrated.
5. **7c, retirement.** The legacy conductor CronJobs, dispatcher and release controller are removed; Plane projects are archived read-only; every entry of `mechanisms.yaml` is registered in Sortyard or recorded as out of scope with an owner; the one-source audit list is empty; the experiment rig runs as its own deployment, or is archived by a recorded decision because the census showed no use.
6. **Comparisons.** Each of these meets its floor against its legacy baseline, with the measured value in the scorecard and a `target-gap` task for each one short of its target: <!--gen:demos MS7-->FLW-019 AC2, OBS-001 AC4, OBS-006 AC2, MIG-009 AC3, QLT-024 AC2<!--/gen-->.

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP7.1 | Cutover kit and rollback export, rehearsed in the replica | WP2.8, MS5 gate | M · 7 | <!--gen:req WP7.1-->MIG-007, MIG-008, MIG-009<!--/gen--> |
| WP7.2 | Pilot: Sortyard builds Sortyard; hosts the comparisons due at MS7 | WP7.1, WP6.5, WP0.4 | M · 8 (plus the 14-day window) | <!--gen:req WP7.2-->DLV-002, MIG-010<!--/gen--> |
| WP7.3 | Estate integrations: release verification, mechanism observers | WP7.2 | M · 7 | <!--gen:req WP7.3-->DLV-003, MIG-012<!--/gen--> |
| WP7.4 | Project cutovers *(operational, one at a time; Cortexplane needs WP7.3)* | WP7.2, MS6 gate | M · 7 (one per project, 7 days each) | — (executes MIG-007 to MIG-009 per project) |
| WP7.5 | Legacy retirement and one-source audit | WP7.4 | S · 4 | <!--gen:req WP7.5-->MIG-011, MIG-013<!--/gen--> |

## MS8 — 1.0

**Usable increment.** A public release strangers can rely on.

**Exit criteria.**
1. `v1.0.0` is tagged; images and chart are signed with SBOM and provenance, and the install test verifies them.
2. Upgrading with data through every pre-release from v0.5 to v1.0.0, one minor at a time, passes (DEP-008).
3. The threat model is written and the independent review's findings are closed or accepted in writing.
4. Gauntlet: three independent zero-context agents and one person who has not worked on Sortyard each install from the public docs and run the demo; blockers are fixed. Target: two commands and 8 minutes. Floor: 30 minutes.
5. Docs site live, every command executed in CI; generated references in place.
6. Licence, DCO check, governance and security files are in place; a fork pull request runs the full checks with no secrets.
7. The supported Kubernetes versions matrix is green.
8. On the release candidate every measured criterion in [18-divergences.md](18-divergences.md) §3 is at or above its floor, and each one short of its target has an open `target-gap` task or a recorded decision to retire it.

MS8 needs MS6 and the MS7 pilot verdict. It does not wait for the remaining cutovers or for
legacy retirement.

| WP | Name | Depends on | Size | Requirements |
|---|---|---|---|---|
| WP8.1 | Documentation site | MS6 gate | L · 12 | <!--gen:req WP8.1-->QLT-001<!--/gen--> |
| WP8.2 | Security and supply chain | MS6 gate | M · 8 | <!--gen:req WP8.2-->API-010, QLT-020, QLT-021, QLT-023<!--/gen--> |
| WP8.3 | Upgrade and compatibility guarantees | MS6 gate | M · 8 | <!--gen:req WP8.3-->API-013, EXT-007, DEP-008, DEP-017<!--/gen--> |
| WP8.4 | Extension contracts and kits | MS4 gate | S · 4 | <!--gen:req WP8.4-->EXT-002, EXT-005<!--/gen--> |
| WP8.5 | Governance, licence, fork CI, cadence | OD-1 | M · 6 | <!--gen:req WP8.5-->QLT-013, QLT-032, QLT-040, QLT-041, QLT-042<!--/gen--> |
| WP8.6 | Distribution: air-gap, architectures, sizing guide | WP8.2 | S · 4 | <!--gen:req WP8.6-->DEP-015, DEP-019, DEP-021<!--/gen--> |

## Deferred past 1.0

Recorded so they are not lost: <!--gen:later-->TRK-019, GRM-008, FLW-017, OBS-018, MIG-014<!--/gen-->.
Each is covered by an entry in [18-divergences.md](18-divergences.md): the legacy behaviour is
kept another way meanwhile, or the deferral is conditional on the usage census (MIG-017) and
the requirement is re-tagged into a milestone if the feature turns out to be used.

## The three threads that cross milestones

CORPUS R7 named three chains that are easy to break by tidying. They survive as:

- **Evidence:** MIG-001 (freeze, MS0) → MIG-002 (record, MS0) → MIG-016 and MIG-017 (baselines and census, MS0) → MIG-005 (replay, MS2) → REC-025 (parity, MS5) → MIG-009 (hypercare, MS7). Every comparison in this plan reads from this chain (QLT-050).
- **Legibility:** DEP-018 and QLT-003 (replica and guides, MS0) → QLT-004 (a goldfish gate at every milestone) → QLT-001 (docs executed in CI, MS8) → the gauntlet.
- **Custody:** IAM-008 to IAM-010 (matrix, MS1) → IAM-007 and EXE-005 (stage tokens and the worker boundary, MS3) → CRD-007 and MRG-001 (the integrator's credential, MS4) → QLT-021 (threat model and review, MS8).
