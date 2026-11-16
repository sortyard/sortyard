# Current requirements catalog

Generated from requirements-source.json; historical draft is provenance only.
384 requirements; 333 original IDs preserved; 46 explicit amendments.

Implementation status is requirement-only. Native/runtime capability discovery is separate.

<a id="TRK-001"></a>
## TRK-001 — Projects with keys and sequence numbers

**MS1 · MUST · retained**

A project has a short upper-case key (`ROVE`) and every task in it gets a monotonically increasing
sequence number; `KEY-N` is a stable, human-quotable identifier that resolves everywhere (API, CLI,
MCP, UI URL, commit trailers).

- AC1: `GET /v1/…/tasks/ROVE-12` and the opaque id return the same task.
- AC2: Sequence numbers are never reused, including after cancel; concurrent creates never collide (tested with 50 parallel creates).
- AC3: The key is unique per workspace and immutable after the first task exists.

Source: Plane identifiers `ROVE-123` are how every doc, comment and PR body refers to work (driver §1, task-pickup §8).

Historical text: [TRK-001](history/2026-11-12/02-work-tracking.md).

<a id="TRK-002"></a>
## TRK-002 — One task object: tracker fields plus a typed spec

**MS1 · MUST · retained**

A task carries tracker fields (title, markdown body, state, priority, parent, blocked-by, rank,
labels, due date) and a typed spec (`kind`, `repo`, `outcome`, `acceptance[]`, `needs[]`,
decision fields, `inputs[]`, `builds_on[]`, `select`, `delivery`). There is exactly one copy of
each fact; the spec is not a YAML block inside the body.

- AC1: The JSON Schema for Task has `kind`, `repo`, `outcome`, `acceptance`, `needs`, `inputs`, `builds_on`; the current `spec/task.schema.json` (no `kind`, `repo` or `acceptance`) is superseded.
- AC2: Importing a legacy item whose description holds a ```` ```task ```` block produces the same typed fields, with Plane's own fields winning where both exist (title, priority, parent, relations, due date).
- AC3: Editing a field through UI, CLI or MCP changes the same stored value (one round-trip test per surface).
- AC4: Demonstration (replay, MS2) — every item of the driven boards, and the recorded invisible filings (HARNESS-608, HARNESS-615 to HARNESS-618), go through the importer's dry run and the filing operation. Target: 100% of items yield the typed fields the legacy parser read, and 100% of the invisible filings are refused or returned with a non-visible verdict in the filing response itself. Floor: every invisible filing is reported in the filing response; the legacy system reported them only at a later sweep (BL-12).

Source: task-ready "The task item" (field ownership table); conductor README "Plane tasks". Gap: the frozen schema drops `kind`/`repo`/`acceptance` that the live ready rules require.

Historical text: [TRK-002](history/2026-11-12/02-work-tracking.md).

<a id="TRK-003"></a>
## TRK-003 — Task kinds

**MS1 · MUST · retained**

`kind` is a closed set that selects the workflow and the lifecycle: operator kinds `feature`,
`fix`, `deployment`, `decision`, `parent`, `job`; system kinds `triage`, `regression`,
`follow-up`, `review` (an adopted outside PR), `ship` (a stranded build), `condition` (a
system-raised alarm, REC-023).

- AC1: Creating a task with an unknown kind is refused with a problem-detail naming the allowed set.
- AC2: Each kind declares its properties as data: `parent` and `decision` are not claimable, `job` opens no change request, and each kind names its required fields (the ready rules of RDY-001 check them from MS2).
- AC3: System kinds can only be created by system principals (IAM-008); the creator and reason are on the task.

Source: task-ready "Kinds"; driver §4 (ad-hoc jobs, triage, lock-in); conductor README "Plane sync" (`queue_adopt`, `unlanded_builds`).

Historical text: [TRK-003](history/2026-11-12/02-work-tracking.md).

<a id="TRK-004"></a>
## TRK-004 — Task states and reason-carrying transitions

**MS1 · MUST · retained**

Board states: `backlog` (held), `todo` (planned), `in_progress`, `in_review`, `done`,
`cancelled`. Queue status is a separate typed field, not a label: `unreleased`, `released`,
`claimed`, `parked` (with reason), `handed_back` (with reason and evidence), `needs_human`
(with routes). Every transition is a named action that records actor, time and reason.

- AC1: A task cannot be `parked` or `handed_back` without a non-empty reason; the reason is shown inline on board and detail.
- AC2: `PATCH` never changes state or queue status; only action endpoints do (API-006).
- AC3: The legal-transition table is data in the repo and is unit-tested one test per transition plus one per refused transition.
- AC4: A task that is `todo` on the board and in flight in the queue cannot be represented: every action changes board state and queue status in one transaction (the claim itself is SCH-016).
- AC5: Demonstration (chaos, MS3) — the claim, requeue and cancel scenarios run 10,000 times with a fault injected at a random point of the action. Target: zero runs end with board state and queue status in disagreement, with no repair step. Floor: zero disagreements once the controller has restarted; the legacy system recorded this disagreement in production (BL-24).

Source: task-pickup §2a (state table), §conformance row 4 (HARNESS-256: board says Todo, record says claimed); labels `conductor`, `self-heal`, `needs-human` are today's queue status (driver §4).

Historical text: [TRK-004](history/2026-11-12/02-work-tracking.md).

<a id="TRK-005"></a>
## TRK-005 — Hierarchy: parents and children

**MS1 · MUST · retained**

A task may have one parent of kind `parent`; nesting is allowed. A parent is Done when every
planned child is Done, and nested parents close in the same evaluation. A parent in Backlog holds
all its descendants.

- AC1: Closing the last open child closes the parent, and its parent. Target: in the same transaction. Floor: within 10 s.
- AC2: Moving a parent to Backlog marks every descendant held (`parent in backlog`) and moving it back clears the mark; from MS2 the mark is the reason code `held: parent in backlog` (SCH-009).
- AC3: A parent with an open child cannot be moved to Done by hand without an explicit `force` reason that is audited.

Source: driver §3 `queue_ready` (parent close), 2026-11-01 release note (#204 nested parents close); task-ready "A Backlog parent releases no children".

Historical text: [TRK-005](history/2026-11-12/02-work-tracking.md).

<a id="TRK-006"></a>
## TRK-006 — Dependencies are relations, and only relations

**MS1 · MUST · retained**

`blocked_by` is a typed relation between tasks in the same workspace. Cycles are refused at write
time. A dependency known only from prose does not exist; preflight (RDY-006) flags prose that
reads like a gate.

- AC1: Creating a relation that closes a cycle is refused and names the cycle.
- AC2: A task whose blockers are not all `done` shows `blocked by KEY-N`, listing each open blocker and its state; from MS2 that is the reason code `held: blocked by` (SCH-009).
- AC3: Cancelling a blocker does not clear the block silently: its dependants show `blocker cancelled` until the relation is removed or replaced.

Source: task-pickup §2 rule 3; task-ready preflight check 5 ("Prose-only gates do not exist"); CORPUS R2 (description-level dependencies are not dependencies).

Historical text: [TRK-006](history/2026-11-12/02-work-tracking.md).

<a id="TRK-007"></a>
## TRK-007 — Manual order is writable through the API

**MS1 · MUST · retained**

Top-level tasks in a project have a manual `rank`. Drag-and-drop in the UI, `sortyardctl task
move`, and the API all write the same rank. Rank is the delivery order the scheduler reads
(SCH-002).

- AC1: `POST …/tasks/{id}/rank {before|after: KEY-N}` reorders; the next list call returns the new order (the Pickup Preview follows it from MS2, SCH-008).
- AC2: Every reorder writes a ledger event with actor, old position, new position and optional reason.
- AC3: A new top-level task lands last and the filing response says so.
- AC4: Demonstration (benchmark, MS1) — a scripted reorder of 40 top-level tasks through the API, the case the 2026-11-08 import needed. Target: one call per move, each shown by the next list call in under 1 s, with nobody dragging. Floor: the whole reorder is done through the API in under 5 s per move; the legacy order cannot be written by API at all (BL-28).

Source: task-ready "Only a person dragging on the board can reorder (Plane's API does not write `sort_order`)"; 2026-11-08 release note (the import could not set starting order).

Historical text: [TRK-007](history/2026-11-12/02-work-tracking.md).

<a id="TRK-008"></a>
## TRK-008 — Priority tiers

**MS1 · MUST · retained**

Priority is one of `urgent`, `high`, `medium`, `low`, `none`. `urgent` is the rush lane
(SCH-005); there is no separate urgent flag.

- AC1: The schema has one field; the frozen `priority.tier` + `priority.urgent` pair is collapsed.
- AC2: Sorting by priority uses rank `urgent 0, high 1, medium 2, low 3, none 4`.

Source: `drive.py` `RANK`; spec NOTES ambiguity 4 (urgent: flag or tier?).

Historical text: [TRK-008](history/2026-11-12/02-work-tracking.md).

<a id="TRK-009"></a>
## TRK-009 — Labels are for people; flags are for the system

**MS1 · MUST · retained**

Free-form labels exist for filtering and have no effect on scheduling. Everything the system
acts on is a typed field or relation: release status, queue status, kind, routes, selection
override, origin.

- AC1: Adding or removing any label changes no system field or state and — from MS2 — no eligibility (property test over random labels).
- AC2: Each legacy control label — `conductor`, `job`, `self-heal`, `needs-human`, `route:*`, `decision`, `follow-up`, `regression`, `red-main`, `task`, `PR` — has a typed field or relation that carries its meaning; the table is in the docs and is the one the importer uses (MIG-003).
- AC3: Demonstration (replay, MS2) — every control-label combination found on the driven boards, and the recorded missing-label filings, are imported. Target: 100% map to typed fields, and a task that is eligible in every respect but one names that one in its verdict. Floor: no legacy control state is unrepresentable, and no task can be invisible for want of a label (BL-12).

Source: driver §3–§4 (labels as control signals); HARNESS-608/615–618 (filings invisible because a label was missing).

Historical text: [TRK-009](history/2026-11-12/02-work-tracking.md).

<a id="TRK-010"></a>
## TRK-010 — Notes and one activity timeline

**MS1 · MUST · retained**

People and agents can add markdown notes to a task. Notes, system events (state changes,
decisions, stage results, stall notices) and audit entries appear on one ordered timeline per
task. Machine-readable facts are typed event payloads, not text conventions inside notes.

- AC1: `GET …/tasks/{id}/timeline` returns notes and events interleaved by ledger order, paginated both ways.
- AC2: The legacy text marks (`Triage:`, `Regression:`, `Adopt:`, `Ship:`, `Select:`, `Blocking-cause:`, `Delivery:`, `Failure:`, `Builds on:`, `Vendor:`, `Decided:`) each have a typed home; none is parsed from free text at runtime.
- AC3: A system notice of a given kind is posted once per condition, not once per pass (dedupe key on the event).

Source: `drive.py` `MARK` regex and `conductor_line`; conductor README "Blocking causes", "Harness routing"; driver §4 "one comment on its Plane item".

Historical text: [TRK-010](history/2026-11-12/02-work-tracking.md).

<a id="TRK-011"></a>
## TRK-011 — Decisions

**MS2 · MUST · amended**

A decision task has a question, options, a recorded default, a `decide_by` time, a
`premise_class` flag and a route for whoever applies the answer. The model, the answer action
and the lifecycle (RDY-015) land together in MS2; in MS1 a decision is an ordinary task of kind
`decision`. Ordinary task decisions retain their project binding. Action-plan approval Decisions are separate records inheriting the exact plan workspace and optional project scope, with no artificial delivery project; they never use a timeout/default as approval.

- AC1: A decision without `default` and `decide_by` is not ready and says why.
- AC2: An answer is an explicit chosen value recorded through the answer action; a note is never an answer.
- AC3: A decision never blocks a routine build: features are written against the default; only a premise-class decision may be a blocker.

Source: task-ready rule 6; conductor README "Plane tasks" (explicit `Decided:` only; premise-class decisions never stand on a default).

Historical text: [TRK-011](history/2026-11-12/02-work-tracking.md).

<a id="TRK-012"></a>
## TRK-012 — Bounded atomic filing and resumable imports

**MS1 · MUST · amended**

Task filing validates the entire dependency graph before writing. A small batch whose writes fit the configured transaction budget is atomic; larger files become explicit resumable imports with per-chunk checkpoints, deterministic external IDs and per-task outcomes.

- AC1: An invalid graph writes nothing.
- AC2: Repeating a completed batch or import chunk creates no duplicate tasks or relations.
- AC3: A large import exposes partial progress and can resume after interrupted responses without claiming file-wide atomicity.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [TRK-012](history/2026-11-12/02-work-tracking.md).

<a id="TRK-013"></a>
## TRK-013 — Filing verdicts: a filing is done when pickup can see it

**MS2 · MUST · retained**

Every task has a computed filing verdict: `VISIBLE`, `WILL-RELEASE`, `WAITING` (with each named
blocker), or `FAILED` (with the failed check). The verdict fails closed: an input that cannot be
read is `FAILED (read)`, never visible.

- AC1: The verdict is returned by create, by file-many, by `sortyardctl pickup status KEY-N` and on the task detail page.
- AC2: A task that stays `WILL-RELEASE` longer than the release limit (default 30 minutes, the legacy sweep interval) becomes `FAILED (release)`; from MS5 it also appears on the project's single `FILING-INVISIBLE` condition (REC-023).
- AC3: Verdict vocabulary and exit codes match `pickup_status.py`, so existing agent prompts keep working.

Source: conductor README "Filing visibility"; task-pickup §9; HARNESS-251.

Historical text: [TRK-013](history/2026-11-12/02-work-tracking.md).

<a id="TRK-014"></a>
## TRK-014 — Board, list and filters

**MS1 · MUST · retained**

The tracker has a board view (columns by state), a list view, and filters on project, state,
kind, priority, label, parent, queue status and text. Filter, sort and selection live in the URL.

- AC1: A URL copied from one browser reproduces the same view in another.
- AC2: Lists are server-paginated with cursors in both directions and show a total count.
- AC3: System-raised tasks (TRK-003 system kinds) are visually distinct and filterable in one click.
- AC4: Demonstration (benchmark, MS2) — the operator journeys of BL-18 (find a task, see the health items, see why a task waits, reorder a milestone, file and release a task) are scripted against Sortyard and against the legacy pair of Plane and the harness console, counting steps, tools and time. Target: every journey takes at most half the legacy steps, in one tool, with each view rendered in under 1 s. Floor: no journey takes more steps or more time than on the legacy pair, and none needs a second tool (BL-18).

Source: harness-console journeys J2; Plane board usage (driver §6 "The owner steers in Plane").

Historical text: [TRK-014](history/2026-11-12/02-work-tracking.md).

<a id="TRK-015"></a>
## TRK-015 — Saved views

**MS6 · SHOULD · retained**

An operator can save a filter set under a name, per user or shared with the workspace.

- AC1: A saved view is an API object; the UI is a client of it.
- AC2: Deleting a shared view is audited.

Source: Plane saved views (DESIGN §5.2 option C: concepts taken, not code).

Historical text: [TRK-015](history/2026-11-12/02-work-tracking.md).

<a id="TRK-016"></a>
## TRK-016 — Bulk edit

**MS6 · SHOULD · retained**

Select many tasks and change state, priority, labels or parent in one audited operation.

- AC1: A bulk change of N tasks is one request, N ledger events, one audit entry linking them.
- AC2: A bulk change that would break an invariant for any task applies to none and names the offenders.

Source: the 2026-11-08 import and the queue audits were bulk operations done by script.

Historical text: [TRK-016](history/2026-11-12/02-work-tracking.md).

<a id="TRK-017"></a>
## TRK-017 — Links

**MS4 · MUST · retained**

A task has typed links: pull requests, commits, CI runs, other tasks, external URLs. Links
created by the system (the PR a chain opened) are facts with an observed-at time.

- AC1: A task's PR link shows state (open, merged, closed) as last observed, with the observation time.
- AC2: An internal-only URL is labelled as such when rendered into anything a worker will read (EXE-015).

Source: `pr_body` incident note (workers followed a tailnet-only Plane link and reported missing evidence).

Historical text: [TRK-017](history/2026-11-12/02-work-tracking.md).

<a id="TRK-018"></a>
## TRK-018 — Follow-up items never enter the queue by themselves

**MS4 · MUST · retained**

Follow-ups from reviews are created in Backlog at low priority, unreleased, linked to the PR and
the originating task; one item per approval, deduplicated across rounds.

- AC1: A follow-up is never claimed until a person or grooming moves it to Todo and releases it.
- AC2: A review that lists the same finding in two rounds produces one follow-up.
- AC3: Filing survives a tracker write failure: queued on the chain record and retried every reconcile.
- AC4: Demonstration (count, MS4) — after the delivery scenario suite, count the records that stand for work but can never run: requests or stages that are neither terminal, nor owned by a live chain, nor a task on the board. Target: zero, with no such state in the schema. Floor: zero; the usage census counts the blocked follow-up requests that rejected verifies left in the legacy dispatcher (BL-21).

Source: driver §4 (reviewing); TEST-REVIEW "Review scope" (PRE-EXISTING → follow-ups, `retry_test_follow_ups`).

Historical text: [TRK-018](history/2026-11-12/02-work-tracking.md).

<a id="TRK-019"></a>
## TRK-019 — File attachments

**LATER · LATER · retained**

Binary attachments on tasks are out of scope for 1.0, on the evidence that links cover the
estate's use. The cut is conditional: if the usage census (MIG-017) counts attachments in use on
a driven board, this requirement is scheduled before that board's cutover.

- AC1: The schema reserves no attachment field in v1; adding one later is an additive API change.

Source: inference — no attachment use found in the conductor, plane-sync or the operations docs.

Historical text: [TRK-019](history/2026-11-12/02-work-tracking.md).

<a id="RDY-001"></a>
## RDY-001 — Ready rules check the task's shape

**MS2 · MUST · retained**

A task is ready when: it names one registered repo and one single-sentence outcome; its
acceptance entries are named tests (`test` + `name`) or journeys; parent and blockers resolve in
the same project; priority is valid; a `deployment` lists its `needs`; a `decision` has a default
and `decide_by`. Required fields per kind follow task-ready's table.

- AC1: Each rule has an id and a message; `GET …/tasks/{id}/readiness` lists every failing rule.
- AC2: Whether acceptance is required is policy data per project (`ready.require_acceptance`, default `true` for `feature` and `fix`) — see open decision OD-10.
- AC3: A feature whose text names a deploy, production, real accounts, credentials or owner sign-off fails rule `placement` and is told to split into a `deployment` or `decision`.

Source: task-ready "Ready rules" 1–6 and "Kinds"; AGENTS.md "Delivery lanes" rule 6.

Historical text: [RDY-001](history/2026-11-12/02-work-tracking.md).

<a id="RDY-002"></a>
## RDY-002 — Sizing lints are warnings

**MS2 · SHOULD · retained**

The "one PR's worth" rules that can be checked mechanically run as warnings that never change
readiness: more than three acceptance tests, "and" joining two results in the outcome, a title
with more than one verb/object.

- AC1: Warnings are returned next to the verdict and shown on the task; they are never errors.
- AC2: False positives are expected: there is no way to turn a warning into a hold without a policy change.

Source: task-ready "One PR's worth" (rules 2–4 as `warn:`).

Historical text: [RDY-002](history/2026-11-12/02-work-tracking.md).

<a id="RDY-003"></a>
## RDY-003 — Release happens once

**MS2 · MUST · retained**

The system releases a ready `feature`, `fix` or `deployment` in Todo exactly once. If a person
withdraws the release, it stays withdrawn until a person releases it again.

- AC1: A task un-released by an operator is never re-released by the system (tested across restarts and upgrades).
- AC2: The release event records which rules and checks passed and their versions.

Source: task-pickup §2 rule 5 ("taking the label off sticks").

Historical text: [RDY-003](history/2026-11-12/02-work-tracking.md).

<a id="RDY-004"></a>
## RDY-004 — Release conditions

**MS2 · MUST · retained**

Release requires: ready (RDY-001); every blocker Done; parent not in Backlog; `repo` belongs to
the project; preflight passed (RDY-005); the project has release switched on. The evaluation
reads one consistent snapshot.

- AC1: With release switched off for a project, decisions and parents still run their lifecycle and nothing is released.
- AC2: A failure to evaluate one task (bad data) holds that task with a reason and never stops others.

Source: task-pickup §2; driver §1 (`tasks: on|off`).

Historical text: [RDY-004](history/2026-11-12/02-work-tracking.md).

<a id="RDY-005"></a>
## RDY-005 — Preflight: named checks against live surfaces

**MS2 · MUST · retained**

Before release, every applicable preflight check must pass against the surface the build will
really use. A check that cannot run is `unverifiable` and holds the task exactly like a failure.
A held task stays visible in Todo, unreleased, with one notice naming each failed check and its
fix; a new notice appears only when the set of failing checks changes.

- AC1: Each check has a stable id, an owner (who fixes it) and a fix hint; results are stored per task with the time and the evidence read.
- AC2: No check reads a parallel store or a cache of the thing it verifies.
- AC3: Preflight re-runs when the task, the project config or a relevant integration changes, and at claim time (SCH-017).

Source: task-ready "De-risking: the preflight gate"; conductor README "Preflight"; the 2026-11-09 Sortyard stall (six tasks claimed into an unregistered build target).

Historical text: [RDY-005](history/2026-11-12/02-work-tracking.md).

<a id="RDY-006"></a>
## RDY-006 — The v1 preflight checks

**MS2 · MUST · retained**

Checks shipped in 1.0, with the legacy ids kept: `build-target` (repo registered and mirrored),
`write-reach` (the landing credential can push), `evidence-reach` (the worker can read what its
job needs), `inputs` (every cited file exists in a repo the build checks out; no workspace
paths), `needs` (each named secret or resource exists — presence only, never values),
`dependency-graph` (anything the text treats as a gate is a relation), `placement` (nothing needs
a live third party mid-build), `checker-cases` (detector tasks enumerate must-catch/must-allow),
`wide-invariant` (a claim over "every X" names its list; more than 8 surfaces → split).

- AC1: `build-target`, `inputs` (path form), `dependency-graph`, `placement`, `checker-cases`, `wide-invariant` work with no Git host configured (MS2); `write-reach`, `evidence-reach`, `inputs` (existence), `needs` run against the Git host adapter (MS4, WP4.9).
- AC2: Each check has a fixture set replayed in CI; the legacy `queue_audit.py --fixtures` cases are imported as fixtures.
- AC3: `checker-cases` and `wide-invariant` mark the task for shaping rather than leaving it plainly held; shaping consumes the mark from MS5 (GRM-006).

Source: conductor README "Preflight" checks 1–9; task-ready preflight 1–8.

Historical text: [RDY-006](history/2026-11-12/02-work-tracking.md).

<a id="RDY-007"></a>
## RDY-007 — Needs are routed to whoever can meet them

**MS2 · MUST · retained**

Each `need` has a description and a route: `devops`, `owner` or `agent` (default `devops`). A
task held only by needs is `needs_human` with its routes. `owner` creates a linked decision;
`agent` queues a linked job with the step and its completion check. Removing a met need
re-evaluates release.

- AC1: The "routed to me" list for each route is one API call and one UI view.
- AC2: A need is discharged by an explicit action recording who, when and the verification reference.
- AC3: With all needs met, a ready task is released on the next evaluation without anyone touching it again.

Source: k3s driver "Discharging needs and decisions"; HARNESS-247.

Historical text: [RDY-007](history/2026-11-12/02-work-tracking.md).

<a id="RDY-008"></a>
## RDY-008 — Outcome already met

**MS2 · SHOULD · retained**

When discharging a deployment's needs delivered its whole outcome, the task closes Done on a
recorded, non-empty verification instead of being built.

- AC1: `outcome_met.verification` must name the check and what it established; an empty value is refused.
- AC2: The task closes as the same item (no duplicate), keeping the verification on its timeline.

Source: k3s driver "Discharging needs and decisions" (`outcome_met`); HARNESS-272.

Historical text: [RDY-008](history/2026-11-12/02-work-tracking.md).

<a id="RDY-009"></a>
## RDY-009 — Premise rules as an optional policy pack

**MS5 · SHOULD · retained**

The estate's premise rules ship as a policy pack, switched on in the estate bundle and off by
default for new installations: `intended_use` recorded as consistent/contradicts;
reference-clone quarantine (capabilities taken, business shape not taken or imported by a
premise-class decision); access tasks cite a decision that decides that specific target.

- AC1: With the pack enabled, a task whose milestone contradicts the project's intended-use record is not ready, and neither is anything under it.
- AC2: A citation of a decision that decides a different question raises one `CITATION-MISMATCH` condition routed to the owner, never duplicated.
- AC3: The pack is data plus checks registered in the preflight framework; core has no NonceLogic-specific wording.

Source: conductor README "Plane tasks" (intended use, reference clones, access citations; grounding cases A05-D1, Loopmentum/Okara).

Historical text: [RDY-009](history/2026-11-12/02-work-tracking.md).

<a id="RDY-010"></a>
## RDY-010 — No side door into the queue

**MS2 · MUST · retained**

A task created directly as released (the legacy `add_item.py` path) passes the same ready and
preflight gates as a planned task. There is no project setting that bypasses them.

- AC1: `sortyardctl task add --release` on a task that fails preflight returns `FAILED (preflight …)` and leaves it unreleased.
- AC2: Ad-hoc `job` tasks run the checks that apply to jobs (`build-target`, `evidence-reach`, `inputs`).
- AC3: Demonstration (parity, MS2) — the six recorded tasks of 2026-11-09 and the HARNESS-504 case are filed with `task add --release` into a project whose build target is not registered. Target: 100% are refused at filing with the failing check named, and none is released. Floor: none becomes claimable in the Pickup Preview; the legacy system claimed all six (BL-08).

Source: task-ready ("directly-filed items on `tasks: off` boards bypass even the ready rules", HARNESS-504).

Historical text: [RDY-010](history/2026-11-12/02-work-tracking.md).

<a id="RDY-011"></a>
## RDY-011 — Retroactive queue audit

**MS2 · SHOULD · retained**

One command re-runs ready and preflight over everything already released or planned and reports
per project; with `--apply` it withdraws release from failing items with one notice each. It
never releases anything.

- AC1: The report is deterministic and diff-able between runs.
- AC2: `--fixtures` writes each failure as a replayable preflight fixture.

Source: conductor README "Retroactive audit" (`queue_audit.py`, COND-505).

Historical text: [RDY-011](history/2026-11-12/02-work-tracking.md).

<a id="RDY-012"></a>
## RDY-012 — A hand-back owes a check or a gap

**MS5 · SHOULD · retained**

Resolving a hand-back requires recording either the preflight check that would have caught it or
a process-gap task explaining why it cannot be checked.

- AC1: The self-heal resolution action refuses to close without `preventable_by` (a check id or a task reference).
- AC2: A monthly report lists hand-backs by `preventable_by`.

Source: task-ready ("every hand-back owes one of two things in the same pass that returns it").

Historical text: [RDY-012](history/2026-11-12/02-work-tracking.md).

<a id="RDY-013"></a>
## RDY-013 — One bad project config never stops the others

**MS2 · MUST · retained**

Project configuration is validated entry by entry. An invalid entry is dropped for that
evaluation and marks the project `config-invalid`, naming the rule it breaks (from MS5 as one
`CONFIG-INVALID <project>` condition, REC-023); every other project runs normally.

- AC1: Injecting an invalid config for one project leaves the claims of the others unchanged (replay test).
- AC2: The mark clears only when that project's config validates.

Source: conductor README "Product configuration failsafe" (2026-11-10).

Historical text: [RDY-013](history/2026-11-12/02-work-tracking.md).

<a id="RDY-014"></a>
## RDY-014 — Estate preconditions for production flips

**MS5 · SHOULD · retained**

A task that flips production cannot be released until the estate facts it assumes are named
blockers or needs and are discharged; urgency alone never exempts it.

- AC1: A production-flip task with an undischarged precondition is ineligible even when `urgent`.
- AC2: The verification dependency stays on the task after the need is removed, so the evidence survives.

Source: conductor README "Plane sync" `cutover_readiness`; `gate_cutover_pickup` note ("Urgency alone cannot exempt a plan-backed production flip"); DESIGN §3.7b (HARNESS-274).

Historical text: [RDY-014](history/2026-11-12/02-work-tracking.md).

<a id="RDY-015"></a>
## RDY-015 — Decision lifecycle

**MS2 · MUST · retained**

An unanswered routine decision takes its default at `decide_by`: a notice, then Done. An answered
decision stays open, routed to whoever applies the answer. A premise-class decision never takes
its default: past `decide_by` it is escalated once to the owner list and stays open. A decision
recorded as decided closes on the next evaluation.

- AC1: Time-travel test: one tick after `decide_by` a routine decision is Done with a "default applied" event; a premise-class one is `needs_human` routed to `owner`.
- AC2: The answer is re-read from the store at every evaluation; nothing is trusted from a cache.
- AC3: Work blocked by a premise-class decision is never released while it is undecided.

Source: conductor README "Plane tasks"; task-pickup §2 table; LOOP-632 and LOOP-DEC-FIRST-CUSTOMER grounding cases.

Historical text: [RDY-015](history/2026-11-12/02-work-tracking.md).

<a id="GRM-001"></a>
## GRM-001 — An empty eligible queue with known work is a defect

**MS5 · MUST · retained**

When a project's eligible queue is empty and known work exists (unshaped milestones, recorded
findings, tripwire items), the system starts a grooming run for that project.

- AC1: With the queue emptied in a fixture, a grooming run is dispatched within one evaluation; with no known work, none is dispatched.
- AC2: New observations arriving during a run stay pending for the next run.

Source: conductor README (grooming process step); DESIGN §3.5 ("never an empty groomed queue").

Historical text: [GRM-001](history/2026-11-12/02-work-tracking.md).

<a id="GRM-002"></a>
## GRM-002 — Grooming runs on the frontier model, or says so

**MS5 · MUST · retained**

Grooming's judgment runs on the model the policy names. A result from another model is rejected
before anything is filed, except a fallback the system itself stamped because no eligible
account existed; the stamp is kept on the run and its receipt.

- AC1: A result whose recorded actual model differs from policy, without a system fallback stamp, files nothing and the run is marked failed with that reason.
- AC2: The model rule is policy data (`grooming.model`, `grooming.accept_stamped_fallback`).

Source: conductor README (grooming: "rejects a missing or non-Opus actual-model receipt … except a Codex result that MH stamped as the model-fallback move").

Historical text: [GRM-002](history/2026-11-12/02-work-tracking.md).

<a id="GRM-003"></a>
## GRM-003 — Validated and scoped grooming changes

**MS2 · MUST · amended**

Grooming proposes creates, edits, dependency/order changes and dispositions against expected revisions. It validates scope, readiness and provenance, preserves Done/in-progress work, and serializes commits per project using a fenced lease. Edits are supported through the same authorized domain API. Queue and lease keys resolve to authority service, installation and canonical source board/project ID; two logical project aliases pointing to the same board share the fence.

- AC1: A stale project lease or task revision refuses the affected edit.
- AC2: A no-work disposition for known unmet work records evidence and remains reviewable.
- AC3: Repeated output applies once; aliases to the same authoritative board cannot groom concurrently, while independent boards may run in parallel.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [GRM-003](history/2026-11-12/02-work-tracking.md).

<a id="GRM-004"></a>
## GRM-004 — Grooming inputs and their bookkeeping

**MS5 · SHOULD · retained**

Inputs are finished findings runs, findings documents, tripwire items and stale premises, each
identified by content hash. An input is consumed only when its disposition is recorded
(`filed`, `covered:<task>`, `no-work:<why>`). Packets fill newest-first to the size cap; what
does not fit is deferred, never dropped.

- AC1: An over-budget packet defers inputs and still dispatches; it is never a terminal failure.
- AC2: The run record holds dispatch identity, inputs, phase, filed ids and per-task pickup evidence.

Source: conductor README (grooming packets, 200,000-character limit, `grooming.json`).

Historical text: [GRM-004](history/2026-11-12/02-work-tracking.md).

<a id="GRM-005"></a>
## GRM-005 — Grooming silence raises an alarm

**MS5 · MUST · retained**

After two consecutive failed grooming attempts, or an eligible queue empty for longer than the
limit with no run dispatched (default 60 minutes, the legacy value), one `GROOMING-STALLED
<project>` condition is raised with the error, attempt count, queue-empty-since time and the
pickup status of every open planned task.

- AC1: The condition is updated in place, never duplicated, and closes when the project has an eligible head again.
- AC2: Both thresholds are policy data.

Source: conductor README ("Silence is the defect").

Historical text: [GRM-005](history/2026-11-12/02-work-tracking.md).

<a id="GRM-006"></a>
## GRM-006 — Shaping turns an unready task into ready ones

**MS5 · SHOULD · retained**

A task that fails readiness or the sizing checks goes to shaping: one agent run, no reviews, that
produces ready children, decisions and deployment tasks under the same parent, keeping the
original id for the first piece.

- AC1: The driver never fills gaps itself: an unready task is never dispatched to a build.
- AC2: Split ids follow `X-F3`, `X-F3b`, `X-F3c`; later pieces depend on earlier ones only where stated.

Source: task-ready ("The driver never fills gaps itself"; "One PR's worth" rules 5–6).

Historical text: [GRM-006](history/2026-11-12/02-work-tracking.md).

<a id="GRM-007"></a>
## GRM-007 — Authority-aware reconciliation

**MS5 · SHOULD · amended**

A consistency sweep checks authoritative owners and labelled projections for duplicate work, invalid parent/task relations, missing evidence and stale integration cursors. Commit-forward meta-harness and Plane remain authoritative during staged migration; reconciliation does not assume those sources have already vanished.

- AC1: A failed source read produces unknown, not clean.
- AC2: One condition deduplicates repeat findings and names its repair owner.
- AC3: A projection cannot overwrite its source to repair drift.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [GRM-007](history/2026-11-12/02-work-tracking.md).

<a id="GRM-008"></a>
## GRM-008 — Reality reconciliation

**LATER · LATER · retained**

Comparing task premises against a recorded product-state file (connected sites, live
installations) and forcing a fix task on divergence is kept as an estate policy pack after 1.0.

- AC1: Until it ships, the estate keeps running the comparison as a sensor that files tasks through the API (EXT-004).

Source: conductor README (grooming `reality:` observations; Joe 2026-11-06).

Historical text: [GRM-008](history/2026-11-12/02-work-tracking.md).

<a id="SCH-001"></a>
## SCH-001 — One definition of eligible

**MS2 · MUST · retained**

A task is eligible when all hold: its project has build switched on; it is released (RDY-003);
board state is `todo`; it has no live chain; its kind is claimable; claim-time gates pass
(SCH-017). One function computes this; the Pickup Preview, the scheduler and the filing verdict
all call it.

- AC1: There is exactly one implementation of eligibility in the codebase (import-graph test: preview, scheduler and verdict share it).
- AC2: For every ineligible task the function returns at least one reason code from the catalogue (SCH-009).

Source: task-pickup §4 "Eligible"; CORPUS M1.10 (Pickup Preview and conductor are clients of one evaluator).

Historical text: [SCH-001](history/2026-11-12/03-scheduling.md).

<a id="SCH-002"></a>
## SCH-002 — Pickup order is a total order

**MS2 · MUST · retained**

Within a project, eligible tasks are ordered by: (1) `urgent` first; (2) milestone rank —
the position of the task's top-level ancestor in the project's manual order, tasks with no
planned ancestor after all planned work; (3) priority (`high`, `medium`, `low`, `none`);
(4) sequence number ascending. No ties remain.

- AC1: Golden tests reproduce the worked derivation in task-pickup §8 (CPV2-574) from fixture data.
- AC2: The key list is policy data (`prioritization.keys`), defaulting to the order above; weighted scoring is not offered.
- AC3: A project with no planned top-level tasks orders by priority then sequence.

Source: task-pickup §4; driver §4 "Pickup"; DESIGN §3.5 (lexicographic, no weights).

Historical text: [SCH-002](history/2026-11-12/03-scheduling.md).

<a id="SCH-003"></a>
## SCH-003 — Milestone rank comes from the parent chain

**MS2 · MUST · retained**

A task's milestone rank is found by walking its parent relation to the top-level task. The
legacy fallback that matches a task id by text prefix (`BV-15-F2` ranks with `BV-15`) is applied
only by the importer, which converts prefix matches into parent links.

- AC1: The scheduler contains no title or id string matching.
- AC2: The importer's report lists every task ranked by prefix and the parent link it created for it.
- AC3: Demonstration (replay, MS2) — the recorded passes are replayed with rank taken from parent links only, after the importer has converted prefix matches. Target: 100% of recorded claim orders are reproduced, with every prefix-ranked task linked to its parent by the importer and none left for a person. Floor: no divergence in the replay comparison (MIG-005) is caused by rank, and renaming a task changes no rank, which it can under the legacy rule (BL-28).

Source: `milestone_rank` (task-pickup §4 step 2: "equals its task id … or a prefix of these followed by `-`").

Historical text: [SCH-003](history/2026-11-12/03-scheduling.md).

<a id="SCH-004"></a>
## SCH-004 — Lanes: slots per project

**MS2 · MUST · retained**

Each project has `lanes`: the most non-urgent chains it may have in flight. A slot is held from
claim until the chain is done, parked, handed back or `awaiting-deployment`. `lanes: 0` pauses
the project. Projects do not compete for each other's lanes.

- AC1: With `lanes: 2` and three eligible tasks, exactly two are claimed; the third shows `held: lanes full (2/2)` naming the two holders and their phases.
- AC2: An in-flight task in phase `merging` still holds its slot; one in `awaiting-deployment` does not.
- AC3: Changing `lanes` takes effect at the next evaluation without a restart (SCH-011) and is audited.

Source: task-pickup §4 "Slots", §5; driver §1 (`lanes`); k3s driver "Running-system delivery" (awaiting-deployment releases the build slot).

Historical text: [SCH-004](history/2026-11-12/03-scheduling.md).

<a id="SCH-005"></a>
## SCH-005 — The rush lane

**MS2 · MUST · retained**

An `urgent` task is claimed in addition to the project's lanes, never instead of a claimed task,
and never preempts a running stage. Its stages run at rush priority and use the reserved heavy
slot (SCH-007).

- AC1: With lanes full, an urgent task is still claimed at the next evaluation.
- AC2: From MS3: no running Job is deleted or deprioritised because an urgent task arrived.
- AC3: Urgent tasks in flight are not counted in lane occupancy.

Source: driver §4 ("Urgent runs as a harness `rush` request and ignores the lane limit"); task-pickup §3 ("Nothing preempts a claimed item").

Historical text: [SCH-005](history/2026-11-12/03-scheduling.md).

<a id="SCH-006"></a>
## SCH-006 — A freed slot is reused promptly

**MS3 · MUST · retained**

When a slot frees, the next eligible task is claimed on that event, not at the next fixed pass.

- AC1: Demonstration (benchmark, MS3) — the scenario suite measures the time from a slot-free event to the next claim event over 1,000 hand-overs. Target: p95 at most 5 s. Floor: p95 at most 30 s and maximum at most 120 s; the legacy minimum is one pass, up to 180 s (BL-04).
- AC2: A periodic full re-evaluation (default every 60 s) guarantees progress even if an event is missed.

Source: task-pickup §3 ("Minimum latency from 'slot freed' to 'next item claimed' is one pass" — three minutes today).

Historical text: [SCH-006](history/2026-11-12/03-scheduling.md).

<a id="SCH-007"></a>
## SCH-007 — Stacked admission caps for heavy stages

**MS3 · MUST · retained**

Stage classes are `light` (shape) and `heavy` (build, verify, proof). Heavy stages start only
within three caps, all policy data: a cluster heavy cap, a train cap for non-rush work (the
difference is reserved for rush), and a per-project heavy cap that rush ignores. Among admissible
stages, rush goes first, then creation order.

- AC1: With caps 4 / 3 / 2, a fourth non-rush heavy stage waits with reason `throttled: train heavy cap (3/3)`; a rush stage still starts.
- AC2: Work that cannot be admitted is never launched to fight for resources: no Job exists for it.
- AC3: Defaults are documented by node size (DEP-021); the chart default is cluster 2 / train 1 / project 1.

Source: `mh.py` `caps_allow`, `_drive_order`; driver §5 "Capacity knobs" (`MH_HEAVY_CAP`, `MH_TRAIN_HEAVY_CAP`, `MH_PROJECT_HEAVY_CAP`).

Historical text: [SCH-007](history/2026-11-12/03-scheduling.md).

<a id="SCH-008"></a>
## SCH-008 — Pickup Preview

**MS2 · MUST · retained**

For any project the system answers: the current queue in claim order, the reason code(s) for
every task that is not claimable now, who holds each slot and in what phase, and a simulation of
the next N claims (default 10). Available through API, CLI (`sortyardctl queue`, `why KEY-N`),
MCP and UI.

- AC1: The preview is computed by the same function the scheduler runs, from the same snapshot type.
- AC2: The time from changing a lane cap, a priority, a rank or a dependency to the preview showing it. Target: 1 s. Floor: 5 s.
- AC3: Every place an item can wait (task-pickup §7's table) corresponds to a reason code shown here.
- AC4: Demonstration (benchmark, MS2) — for each place an item can wait in task-pickup §7's table, a scripted operator asks why a task is not running. Target: one call or one screen answers in under 1 s for 100% of the places. Floor: every place is answered in fewer steps than the legacy route, which needs `state.json` from the cluster or a hand derivation (BL-09).

Source: task-pickup §7 ("Where a reader sees it": several rows say "Not visible"); HARNESS-251, HARNESS-256.

Historical text: [SCH-008](history/2026-11-12/03-scheduling.md).

<a id="SCH-009"></a>
## SCH-009 — A closed catalogue of reason codes

**MS2 · MUST · retained**

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

Historical text: [SCH-009](history/2026-11-12/03-scheduling.md).

<a id="SCH-010"></a>
## SCH-010 — Decision log

**MS2 · MUST · retained**

Every scheduling evaluation records what it decided for each candidate (claim, skip with
reasons) and the inputs it used: policy versions, a hash of the queue snapshot, lane state.

- AC1: "Why was X not claimed at time T" is one query returning the evaluation, X's reasons and the tasks ranked ahead of it.
- AC2: A recorded evaluation can be re-run offline from its stored inputs and yields the same decisions (determinism test).
- AC3: Skips are deduplicated: an unchanged skip reason is stored once with a last-seen time, so the log does not grow per pass.
- AC4: Demonstration (replay, MS2) — the worked case of task-pickup §8 and 20 questions sampled from the recorded passes are answered from the decision log. Target: 100% answered by one query in under 1 s, each naming the tasks ranked ahead. Floor: 100% answered without reading comments or cluster files; the legacy answer is a hand derivation (BL-09).

Source: task-pickup §8 (a derivation done by hand from Plane comments); DESIGN §3.8 DecisionLog.

Historical text: [SCH-010](history/2026-11-12/03-scheduling.md).

<a id="SCH-011"></a>
## SCH-011 — Tuning is live, audited data

**MS2 · MUST · retained**

Lanes, caps, prioritisation keys, thresholds and cadences are stored configuration read at
decision time. A change needs no deploy, takes effect at the next evaluation, records who changed
what from which value, and shows which decisions were made under which version.

- AC1: Changing a project's lanes through UI, CLI or API changes claims within one evaluation.
- AC2: No scheduling constant is a literal in code: a test enumerates the policy keys in the legacy-constants table (DEF-005) and asserts each is read from configuration.
- AC3: Demonstration (benchmark, MS2) — a lane change and a cap change are made through the console, the CLI and the API, timing each from the action to the first evaluation that uses it. Target: one action, in force within 5 s, with its audit entry. Floor: a lane change is no slower than the legacy commit route, and a cap or threshold change needs no code change and no release (BL-10).

Source: driver §1 ("the same values are hardcoded"), task-pickup conformance row 8 (HARNESS-246: merged changes not released).

Historical text: [SCH-011](history/2026-11-12/03-scheduling.md).

<a id="SCH-012"></a>
## SCH-012 — Pause and resume

**MS2 · MUST · retained**

An operator can pause one project or the whole installation. Paused means no new claims and no
new stage launches; running stages finish and their results are recorded. Pause state survives
restarts and upgrades.

- AC1: After `helm upgrade`, a project paused before the upgrade is still paused.
- AC2: Pausing shows `paused: project` or `paused: global` on every affected task.

Source: driver §5 ("Releases keep the live `suspend` state"); driver §1 (`lanes: 0` pauses).

Historical text: [SCH-012](history/2026-11-12/03-scheduling.md).

<a id="SCH-013"></a>
## SCH-013 — Observe mode

**MS2 · MUST · retained**

The scheduler can run per project in `observe` mode: it evaluates and logs decisions exactly as
it would in `active` mode and changes nothing.

- AC1: In observe mode there are zero state transitions and zero Jobs; the decision log is populated.
- AC2: Switching a project from observe to active is one audited action.

Source: `drive.py --dry-run`, `plane_sync.py --dry-run`; the shadow conductor (README "Shadow conductor").

Historical text: [SCH-013](history/2026-11-12/03-scheduling.md).

<a id="SCH-014"></a>
## SCH-014 — Failure isolation between items and projects

**MS2 · MUST · retained**

An error while evaluating, claiming or advancing one task or one project never prevents any other
task or project from being evaluated, claimed or advanced in the same cycle.

- AC1: Fault-injection test: an exception while evaluating project A leaves project B's evaluation unaffected; from MS3 the same test covers claims and the advancement of running chains.
- AC2: The error is recorded on the affected task or project and counted (REC-005).
- AC3: Demonstration (chaos, MS3) — an exception is injected into the evaluation, the claim and the advancement of one task in each of 1,000 cycles across five projects. Target: every other task and project is evaluated, claimed and advanced in the same cycle, with at most 5 s of added delay. Floor: no other task or project is skipped in that cycle; the legacy pass aborted (BL-22).

Source: task-pickup conformance row 2 and §3 ("An exception in a claim aborts the rest of the pass", HARNESS-254).

Historical text: [SCH-014](history/2026-11-12/03-scheduling.md).

<a id="SCH-015"></a>
## SCH-015 — Decisions come from one consistent snapshot

**MS2 · MUST · retained**

Each evaluation reads tasks, relations, ranks, lanes and policies in one database snapshot. There
is no degraded mode that orders by fewer keys; if the snapshot cannot be read, nothing is claimed
and the health view says so.

- AC1: A simulated read failure produces zero claims and a `scheduler: snapshot unavailable` health state.
- AC2: No code path orders by priority alone because rank was unavailable.
- AC3: Demonstration (chaos, MS2) — each input of an evaluation (tasks, relations, ranks, lanes, policies) is made unreadable in turn over the recorded passes. Target: zero claims are decided from a partial read, and the health view names the unreadable input within one evaluation. Floor: zero evaluations order by fewer keys; the legacy pass ordered by priority alone after a failed clone (BL-22).

Source: task-pickup conformance row 3 (HARNESS-255: a failed clone made the pass ignore milestone order); driver §4 ("An unreadable board pauses non-urgent claims").

Historical text: [SCH-015](history/2026-11-12/03-scheduling.md).

<a id="SCH-016"></a>
## SCH-016 — Claims are atomic and fenced

**MS3 · MUST · retained**

A claim creates the chain, moves the task and takes the slot in one transaction, and stamps the
chain with a monotonically increasing epoch. Only the holder of the current epoch may write side
effects for that chain (REC-020).

- AC1: Two controllers racing to claim the same task result in exactly one chain (concurrency test).
- AC2: If the controller dies between claim and first stage launch, the chain is resumed, not re-claimed, after restart.
- AC3: Demonstration (chaos, MS3) — two controllers race for the same tasks, and the leader is killed between claim and launch, over 10,000 claims. Target: zero duplicate chains, zero tasks left Todo with a live record, and no repair step. Floor: zero of either after restart; the legacy system left such a task skipped every pass (BL-24).

Source: task-pickup §4 ("A Todo item with a stale live record is skipped every pass", HARNESS-256); in-flight-steering ("one task, one current route, one writer").

Historical text: [SCH-016](history/2026-11-12/03-scheduling.md).

<a id="SCH-017"></a>
## SCH-017 — Release is necessary, not sufficient

**MS2 · MUST · retained**

Eligibility is recomputed from current rules at claim time. A task released under yesterday's
rules that fails today's readiness or preflight is not claimed; it is shown as held with the
failing rule.

- AC1: Tightening a rule after release makes affected released tasks ineligible at the next evaluation.
- AC2: A claim-time gate added by policy is evaluated at every claim, whatever the task's release state (the production-flip gate of RDY-014 relies on this).

Source: `gate_cutover_pickup` note ("A stale Todo/conductor label must never bypass a production flip's plan").

Historical text: [SCH-017](history/2026-11-12/03-scheduling.md).

<a id="SCH-018"></a>
## SCH-018 — Order among projects at the heavy caps

**MS3 · MUST · retained**

When several projects wait at a cluster-level cap, admission is by stage creation time. The
policy is recorded and shown; nothing depends on poll timing.

- AC1: A fixture with three projects waiting shows admission in creation order, and the preview says which stage is next.
- AC2: The interleaving rule is policy data with one shipped value (`fifo`); other values are refused until implemented.

Source: task-pickup §6 ("in creation order (`created_at`, then id) among non-terminal tasks").

Historical text: [SCH-018](history/2026-11-12/03-scheduling.md).

<a id="SCH-019"></a>
## SCH-019 — Low-priority system work comes after planned work

**MS2 · MUST · retained**

System-created tasks that are not under a planned parent (ship retries, follow-ups once
released) rank after all planned work in the same project unless marked urgent.

- AC1: A `ship` task and a planned `feature` both eligible: the feature is claimed first.
- AC2: At most `ship_cap` ship tasks are open per project (policy data); the rest wait.

Source: conductor README "Plane sync" `unlanded_builds` ("picked up after planned work", `SHIP_CAP`).

Historical text: [SCH-019](history/2026-11-12/03-scheduling.md).

<a id="EXE-001"></a>
## EXE-001 — Execution binding is a recorded, named check set

**MS3 · MUST · retained**

Before a stage is launched the controller records a binding: workflow and stage (pinned
versions), packet template version and packet hash, harness profile (harness, model, effort,
fallback), worker image digest, resource envelope and deadline, repo and base commit with the
mirror's freshness fact, credential selection, materialised inputs. If any element cannot be
resolved the stage is not launched and the task shows `unbound: <element>`.

- AC1: Every stage run references exactly one binding; the Job is rendered from the binding and nothing else.
- AC2: The v1 `unbound` elements are: `mirror-base-missing`, `mirror-stale`, `input-unverified`, `no-eligible-credential`, `image-unresolved`, `packet-too-large`, `definition-invalid`.
- AC3: The binding fixes everything a worker reads: the packet (by hash), the repository at the base commit, the inputs (by digest) and the worker image (by digest), which carries the harness settings and any skill files. Nothing else reaches a worker. Skill versions and context recipes are not separate objects in 1.0, which is how the estate works today ([11-coherence.md](history/2026-11-12/11-coherence.md) CF-05).

Source: DESIGN §3.7b; `ensure_base`, `vendor_inputs`, `_pick_claude_account` (the checks that exist today, in three places).

Historical text: [EXE-001](history/2026-11-12/04-execution.md).

<a id="EXE-002"></a>
## EXE-002 — One stage, one Job, one pod

**MS3 · MUST · retained**

Each stage attempt is one Kubernetes Job with `backoffLimit: 0`, `restartPolicy: Never`,
`activeDeadlineSeconds` equal to the stage deadline, and a TTL after finish. The pod runs as a
non-root user with privilege escalation disabled.

- AC1: A Job is labelled with project, task, chain, stage and attempt; the controller can find its Jobs after a restart from labels alone.
- AC2: Kubernetes never retries a stage; retries are new attempts decided by the controller (FLW-018).

Source: `mh.py` Job render (notes: ns `muse-workloads`, `backoffLimit 0`, `ttlSecondsAfterFinished 86400`, `runAsUser 1000`).

Historical text: [EXE-002](history/2026-11-12/04-execution.md).

<a id="EXE-003"></a>
## EXE-003 — Resource envelopes and deadlines per stage class

**MS3 · MUST · retained**

Every stage has CPU and memory requests and limits and a wall-clock deadline, all policy data.
Shipped defaults: shape 45 min, build 60 min, verify 60 min, proof 120 min; a request may raise a
deadline within 300–10,800 s. Default envelopes (request/limit): shape 0.5 CPU, 1 Gi / 1 CPU,
2 Gi; build and verify 1 CPU, 2 Gi / 1.5 CPU, 8 Gi; proof 2 CPU, 4 Gi / 4 CPU, 6 Gi.

- AC1: A stage that reaches its deadline is killed and recorded as `deadline exceeded`, distinct from a task failure.
- AC2: The agent's own timeout is the deadline minus a collection margin (default 300 s) so results are still collected.
- AC3: The estate's overrides (builds and fix rounds at 3 h) are expressed as policy, not code.

Source: `mh.py` `STAGE_DEADLINE_S`, `STAGE_RESOURCES`; driver §4 (`BUILD_DEADLINE_S`, LOOP-486 timed out three times at 1 h).

Historical text: [EXE-003](history/2026-11-12/04-execution.md).

<a id="EXE-004"></a>
## EXE-004 — Isolated work directories

**MS3 · MUST · retained**

Each stage attempt gets its own working directory with a fresh clone. No two attempts share a
mutable directory. A later stage starts from the previous stage's recorded head, checked out
clean.

- AC1: Concurrency test: two stages of different chains on the same repo cannot observe each other's files.
- AC2: A fix round's checkout equals the head commit of the branch under review exactly (tree hash compared).

Source: DESIGN §3.7b (shared-workdir collision, 2026-09-26); `mh.py` WORKER_TEMPLATE (`MH_START_SHA`, `clean -fd`).

Historical text: [EXE-004](history/2026-11-12/04-execution.md).

<a id="EXE-005"></a>
## EXE-005 — What a worker can reach

**MS3 · MUST · retained**

A worker pod has: its stage token (IAM-007), its model credential, read access to the mirror, and
— only when the binding grants it — a read-only, single-repo Git host token for CI evidence. It
has no Git host write, no tracker credential beyond its stage token, no Kubernetes token, and no
route to the control-plane database. Network egress is limited by a NetworkPolicy to the mirror,
the API, the model provider and declared package registries.

- AC1: A pod-level test proves `kubectl auth can-i` is denied and the API refuses every operation except the two worker operations.
- AC2: After the agent finishes, the wrapper scans the work tree and the new commits for the evidence token; a hit fails the stage and nothing is committed.
- AC3: The evidence token is revoked or expires when the stage ends.

Source: driver §5 ("Jobs never push and never reach GitHub"); `drive.py` `GITHUB_READ`; `mh.py` GH token custody (notes: leak scan, `GH_LEAK`).

Historical text: [EXE-005](history/2026-11-12/04-execution.md).

<a id="EXE-006"></a>
## EXE-006 — The stage contract

**MS3 · MUST · retained**

The contract between Sortyard and any worker image: input is a packet and a run descriptor;
output is a result document with `execution_ok` (the worker ran), `pass` (declared checks and
verdict), check results, declared outputs, the head commit, usage, and the tail of the agent's
report. Declared checks are run by the wrapper after the agent, never self-reported.

- AC1: `execution_ok` false is an infrastructure outcome (REC-002); `execution_ok` true with `pass` false is a task outcome (REC-003). The two are never conflated.
- AC2: A verify stage with no verdict line is `pass: false` with reason `no verdict`.
- AC3: The contract is published as a JSON Schema; the conformance test that any worker image can run follows with EXT-002.

Source: `mh.py` result builder (notes: `execution_ok`, `pass`, `VERDICT:` regex on the last 2,000 chars, checks run after the agent).

Historical text: [EXE-006](history/2026-11-12/04-execution.md).

<a id="EXE-007"></a>
## EXE-007 — Results are validated, not trusted

**MS3 · MUST · retained**

The controller rejects a result whose identity (chain, stage, attempt, Job) does not match, whose
flags contradict its observations (`pass` without `execution_ok`; approve without a verdict), or
whose fields exceed their caps. `execution_ok` also requires that Kubernetes reports the Job
succeeded.

- AC1: A table-driven test covers each contradiction and each cap.
- AC2: A rejected result is recorded as a protocol error with the offending field; the stage is an infrastructure failure.

Source: `mh.py` `_result_protocol_error` (notes).

Historical text: [EXE-007](history/2026-11-12/04-execution.md).

<a id="EXE-008"></a>
## EXE-008 — Mirrors are first-class and their freshness is a fact

**MS3 · MUST · retained**

Workers clone only from Sortyard's read-only mirror. For every dispatch the controller records
the mirror head and its age, ensures the base commit (or PR head) is present — seeding it if
needed — and refuses to dispatch when it is still missing. Mirrors are refreshed by Sortyard, not
by a host cron.

- AC1: A base missing from the mirror is a deterministic `unbound: mirror-base-missing`, retried once after a seed, then the task parks; it is never retried as infrastructure.
- AC2: A mirror older than the freshness threshold (default 300 s) is refreshed before dispatch; the recorded fact shows before and after.
- AC3: Every refresh attempt and its last success are recorded; from MS5 the mirror mechanism is registered with a freshness window (REC-017).

Source: `MIRROR_MISS`, `ensure_base`, `seed_mirror` incident notes (CPV2-408 burned ten builds on one missing head); `mh.py` `mirror_readiness_state` (stale if > 300 s).

Historical text: [EXE-008](history/2026-11-12/04-execution.md).

<a id="EXE-009"></a>
## EXE-009 — Mirrors and run output do not need a shared volume

**MS3 · MUST · retained**

By default workers reach the mirror over the cluster network (read-only Git over HTTP,
authenticated with the stage token) and return commits to a staging namespace on the mirror
service. A shared-volume mode remains as an option, and an installation keeps it when the
comparison below does not show the network path to be at least as fast. No `ReadWriteMany`
storage class is required to install.

- AC1: The default chart installs and runs the demo on a kind cluster and on a three-node cluster with only `ReadWriteOnce` storage.
- AC2: A worker can push only to `refs/sortyard/stage/<stage-run-id>/*` on the mirror service; any other ref is refused.
- AC3: Demonstration (benchmark, MS3) — stage start is timed from dispatch to the agent's first instruction on a 1 GB repository, on one node and on three nodes with `ReadWriteOnce` storage only. Target: p95 at most 20 s on both. Floor: it runs on three nodes with no shared volume, and is no slower than the legacy stage start on one node (BL-23).

Source: inference — today mirrors and run directories live on one PVC (`mh-work`) mounted by the tools pod and every Job, which fixes the topology to one node or RWX storage.

Historical text: [EXE-009](history/2026-11-12/04-execution.md).

<a id="EXE-010"></a>
## EXE-010 — Workers commit; only Sortyard moves commits

**MS3 · MUST · retained**

The wrapper commits the agent's changes locally with trailers naming chain, stage and task. The
controller takes exactly the new commits (base..head) from the stage's staging ref. A stage with
no new commits is recorded as `no change`.

- AC1: Workers never push to the Git host and never open PRs (enforced by EXE-005, verified by a test that the worker image has no host credential helper configured).
- AC2: A head already delivered for this stage is never re-judged as `no change` because a later step failed (idempotent landing, MRG-002).

Source: `fetch_run_commit` (only the new commits by bundle), commit trailers `MH-Stage/MH-Item/MH-Run` (notes); driver "Recovery" (push marker).

Historical text: [EXE-010](history/2026-11-12/04-execution.md).

<a id="EXE-011"></a>
## EXE-011 — External inputs are fetched only when marked, and verified

**MS4 · MUST · retained**

A task names external changes it builds on in `builds_on[]` (PR, commit, branch). Before
dispatch each is fetched into the mirror under a vendor ref and verified; the packet names its
commit. One that cannot be fetched or verified means the stage is not dispatched and the task
parks naming the reference. References in prose are citations: logged, never fetched, never a
stop.

- AC1: A task citing `PR #41` only in prose is dispatched normally and the log says the citation was not vendored.
- AC2: A `builds_on` entry that cannot be fetched parks the task with `not dispatched: <reference>`.
- AC3: File inputs from other tasks are passed as `(repo, commit, path)` and materialised read-only in the work directory.

Source: conductor README "Incident notes" `vendor_inputs` / `external_refs` (HARNESS-239; the 2026-11-09 false stops on evidence citations); `mh.py` attachments (notes).

Historical text: [EXE-011](history/2026-11-12/04-execution.md).

<a id="EXE-012"></a>
## EXE-012 — Harness adapters

**MS3 · MUST · retained**

A harness is a worker image that honours the stage contract. 1.0 ships four: `scripted` (a
deterministic fake for demos, CI and the replica — MS3), `none` (runs declared commands only, for
proof/check stages — MS3), `claude-code` and `codex` (MS4, WP4.2).

- AC1: The whole product test suite runs with `scripted` and no model credential.
- AC2: The same task completes with `claude-code` and with `codex` in the estate cluster.
- AC3: Adding a harness requires an image and a profile definition, no change to the controller.

Source: `mh.py` `validate_request` (harness `claude|codex|none`); AGENTS.md "pipeline purity" (fake providers in the pipeline).

Historical text: [EXE-012](history/2026-11-12/04-execution.md).

<a id="EXE-013"></a>
## EXE-013 — Harness routing and the fallback chain are policy

**MS4 · MUST · retained**

Which harness, model and effort run each stage is policy data. Shipped estate values: build-side
stages on `claude-code`/opus with fallback to `codex`; verify-side stages on `codex` at high
effort. When no account of the first family is eligible, or a usage limit hits mid-stage, the
stage re-dispatches down the chain and the move is stamped in the stage facts.

- AC1: The stage record shows requested and actual harness and model, and `fallback_from`, `fallback_reason` when a fallback happened.
- AC2: The next stage starts again at the top of the chain.

Source: conductor README "Harness routing" (Joe, 2026-11-07); `mh.py` `_fall_back_to_next_family` (notes).

Historical text: [EXE-013](history/2026-11-12/04-execution.md).

<a id="EXE-014"></a>
## EXE-014 — Agent CLI versions are pinned or soaked

**MS4 · SHOULD · retained**

A harness profile either pins the agent CLI version or uses a soak rule: the highest stable
version that has been public for at least N hours (default 6), resolved once and then installed
exactly. The resolved version is a binding fact.

- AC1: A release published less than N hours ago is never installed under the soak rule (clock-injected test).
- AC2: The install step can be disabled, so that an image with the CLI baked in is used unchanged (the air-gapped path, DEP-015).

Source: driver "Worker CLIs" (`MH_CLI_SOAK_HOURS`; `@openai/codex` 0.165.0 killed every worker started in a six-minute window on 2026-10-27).

Historical text: [EXE-014](history/2026-11-12/04-execution.md).

<a id="EXE-015"></a>
## EXE-015 — Packets come from versioned templates and are recorded

**MS3 · MUST · retained**

Each stage's instructions are rendered from a versioned packet template with typed inputs (task
text as it stands now, findings, CI excerpts, checklists, input references). The rendered packet
is stored by content hash and capped at 200,000 characters. Links a worker cannot reach are
labelled as such.

- AC1: A stage run records the template id and version and the packet hash; the packet can be retrieved by an operator.
- AC2: A packet over the cap is refused as `unbound: packet-too-large` before any Job starts; grooming-class stages defer inputs instead of failing (from MS5, GRM-004).
- AC3: Packets are excluded from overview and list responses (API-011).

Source: `drive.py` `BUILD_PACKET`, `FIX_PACKET`, `REVIEW_PACKET`, `CONFLICT`; `mh.py` `MAX_PACKET_CHARS` (notes); `pr_body` incident note.

Historical text: [EXE-015](history/2026-11-12/04-execution.md).

<a id="EXE-016"></a>
## EXE-016 — Containers inside a stage are opt-in

**MS4 · SHOULD · retained**

A project may enable a Docker sidecar for its build/verify/proof stages. It is off by default
because it needs a privileged container; enabling it is an audited project setting and is shown
on the binding.

- AC1: With the setting off, no privileged container exists in any worker pod (admission test).
- AC2: With it on, the sidecar has its own resource limits counted in the envelope.

Source: `mh.py` dind sidecar (notes: privileged, `docker:27-dind`, own limits).

Historical text: [EXE-016](history/2026-11-12/04-execution.md).

<a id="EXE-017"></a>
## EXE-017 — Deterministic check stages with receipts

**MS3 · MUST · retained**

A `none`-harness stage runs declared commands against an exact `(base, candidate)` pair and
produces a receipt bound to both commits. A receipt whose commits differ from the request is
rejected. This is the merge proof for Git hosts without CI (MRG-011).

- AC1: A receipt for another candidate cannot be used to land this one (negative test).
- AC2: `unavailable` (the check could not run) is not a verdict: the stage is an infrastructure failure, never a pass or a fail.

Source: `mh.py` proof receipts (notes: `candidateCommit`/`baseCommit` must equal the request's; `unavailable` ⇒ not `execution_ok`); `ship.py` fence (DESIGN §3.7a).

Historical text: [EXE-017](history/2026-11-12/04-execution.md).

<a id="EXE-018"></a>
## EXE-018 — Usage is captured per stage

**MS3 · MUST · retained**

Each stage records wall time, input/output/cache tokens, turns, the model actually used and the
credential identity (an id, never a secret).

- AC1: Usage fields are present for every finished stage or explicitly `unknown` with a reason.
- AC2: Usage is recorded for failed and cancelled attempts as well as passed ones, so that the delivery-cost metrics (OBS-006) need no other source.

Source: `mh.py` result builder and ledger row (notes: usage, `model_actual`, `account_id`); k3s `docs/usage-accounting.md`.

Historical text: [EXE-018](history/2026-11-12/04-execution.md).

<a id="EXE-019"></a>
## EXE-019 — Agent traces are stored and viewable

**MS6 · SHOULD · retained**

The agent's event stream is captured per stage, redacted, stored as a blob with a retention
policy, and served to the trace viewer (UI-011). Capture failure is recorded as `missing`, never
silently absent.

- AC1: A multi-megabyte trace can be paged and searched without loading it whole.
- AC2: Secrets matching the redaction rules never appear in a stored trace (seeded-secret test).

Source: `mh_trajectories` (status `captured|missing|error`, notes); harness-console J3; TRAJECTORY-CAPTURE-DESIGN.md.

Historical text: [EXE-019](history/2026-11-12/04-execution.md).

<a id="EXE-020"></a>
## EXE-020 — The control plane is protected from its workers

**MS3 · MUST · retained**

Workers run in their own namespace with a ResourceQuota and LimitRange sized from the caps. The
control-plane pods have resource requests and, where the installer allows cluster-scoped objects,
a higher PriorityClass. A runaway worker can fail its own stage; it cannot evict the control
plane.

- AC1: Demonstration (chaos, MS3) — workers are pinned at their CPU and memory limits at the full heavy cap while the API and the controller are measured. Target: API p95 at most 300 ms and event-stream lag at most 5 s, with no control-plane pod evicted or restarted. Floor: API p95 at most 1 s and no control-plane pod evicted; the legacy system has no such protection (BL-28).
- AC2: The chart works without the PriorityClass (namespace-admin install, DEP-002) and says which protection is then missing.

Source: DESIGN §3.7b honesty note ("today it runs with only small requests and no PriorityClass/ResourceQuota protection").

Historical text: [EXE-020](history/2026-11-12/04-execution.md).

<a id="EXE-021"></a>
## EXE-021 — Interrupted stages are reconciled, not lost

**MS3 · MUST · retained**

After a controller restart every non-terminal stage is reconciled against the cluster: a Job
that finished is collected; a Job still running is watched; a stage recorded as launching with no
Job is launched once.

- AC1: Kill the controller at each step of launch and collect: no stage is launched twice, none is left non-terminal without a Job (fault-injection matrix).
- AC2: A lost pod is an infrastructure failure with reason `pod lost`.

Source: `mh.py` `recover_interrupted`, `_drive_task_guarded` reconcile branch.

Historical text: [EXE-021](history/2026-11-12/04-execution.md).

<a id="EXE-022"></a>
## EXE-022 — A running stage can be cancelled

**MS3 · MUST · retained**

An operator can cancel a queued or running stage, or a whole chain. Cancel deletes the Job,
records `operator-cancelled`, frees the slot, and leaves the PR (if any) as chosen in the action:
left open or closed.

- AC1: Demonstration (benchmark, MS3) — running stages are cancelled at random points, 200 times. Target: the pod is gone and the slot free within 10 s, and 100% of late results are refused. Floor: within 60 s, and no late result is accepted (fenced by epoch); the legacy system cannot cancel a running task (BL-28).
- AC2: The confirm dialog and the CLI state the effect before acting.

Source: driver §5 ("A running task can't be cancelled"); driver §7 ("Stop an item mid-flight: Not supported yet").

Historical text: [EXE-022](history/2026-11-12/04-execution.md).

<a id="CRD-001"></a>
## CRD-001 — Custody classes

**MS4 · MUST · retained**

Every credential has a custody class with its own rules: `secret-ref` (a reference to a
Kubernetes Secret, optionally fed by an external secrets operator), `cli-owned` (subscription
credentials the agent CLI refreshes and writes back, kept as files on a dedicated volume), and
`minted` (short-lived tokens Sortyard mints per use, such as Git host installation tokens).
Domain objects hold references and state, never values.

- AC1: No API response, log line, event or trace contains a credential value (seeded-secret scan in CI).
- AC2: Each credential shows its class, health, last use and which stage runs consumed it.

Source: DESIGN §3.7a (CredentialCustody; subscription credentials deliberately not in the secrets store); driver §5 ("Never print, copy or move credential contents").

Historical text: [CRD-001](history/2026-11-12/04-execution.md).

<a id="CRD-002"></a>
## CRD-002 — API-key model credentials are the default path

**MS4 · MUST · retained**

A fresh install can run real agents with one model API key supplied as a Secret reference. The
subscription pool and the broker are optional.

- AC1: The quickstart for real agents needs exactly one Secret and one harness profile.
- AC2: When both an API key and pool accounts exist, policy says which a stage uses; the worker never sees both.

Source: DESIGN §8 Phase 6 ("the system installs and runs on API-key credentials alone"); `mh.py` WORKER_TEMPLATE unsets API keys today (subscription only), so this path is new.

Historical text: [CRD-002](history/2026-11-12/04-execution.md).

<a id="CRD-003"></a>
## CRD-003 — Subscription account pool

**MS4 · MUST · retained**

Pool accounts are selected per stage: eligible accounts exclude, in order, operator-disabled,
excluded after a usage-limit failure for this task, cooling, quarantined, and those without a
valid token. Among eligible accounts: operator priority first, the previous stage's account if
still eligible, otherwise the unleased account with the least usage in the last five hours. A
usage limit cools the account until the reset time the CLI states (default five hours) and
re-queues the stage at most three times.

- AC1: The stage record names the account id, the selection reason and the alternatives rejected with their blocker.
- AC2: The pool selects and isolates failures; it is not a concurrency limiter. Concurrency is bounded only by the caps (SCH-007).
- AC3: Window, cooling time and requeue limit are policy data.

Source: `mh.py` pool (notes: `POOL_USAGE_WINDOW_S` 5 h, `POOL_COOLING_S` 5 h, `POOL_MAX_LIMIT_REQUEUES` 3, blocker order, sticky account, least-burned sort).

Historical text: [CRD-003](history/2026-11-12/04-execution.md).

<a id="CRD-004"></a>
## CRD-004 — Pool health: quarantine and probes

**MS4 · SHOULD · retained**

An authentication failure quarantines the account. A small probe Job checks a quarantined
account no more often than the probe interval (default 15 minutes, the legacy value); recovery
is recorded only when the probe succeeded against the same credential generation and quarantine
generation it started with. Viewing status never triggers a paid probe.

- AC1: Replacing the credential files changes the generation and makes the next probe eligible immediately.
- AC2: A probe that started before a re-authentication cannot clear the new quarantine state.

Source: `mh.py` pool probes (notes: `POOL_PROBE_INTERVAL_S` 15 min, `POOL_PROBE_DEADLINE_S` 900, generation checks); harness-console J4 ("never triggers paid probes just by viewing status").

Historical text: [CRD-004](history/2026-11-12/04-execution.md).

<a id="CRD-005"></a>
## CRD-005 — Broker flows for subscription sign-in

**MS4 · SHOULD · retained**

The operator adds or re-authenticates a pool account from the console: browser OAuth,
setup-token, paste-token, device code. The flow is a server-side state machine that survives
page refresh and navigation, shows progress, retries transient poll errors, and can be
cancelled.

- AC1: Reloading the page mid-flow resumes the same flow instead of failing with a conflict.
- AC2: Every flow ends in one of `connected`, `cancelled`, `failed (reason)`; none is left dangling after its timeout.

Source: harness-console J4 and VISION ("sign-in flows wipe themselves"); driver §5 (`/api/auth/claude/{start,submit,paste-token,probe,qualify}`).

Historical text: [CRD-005](history/2026-11-12/04-execution.md).

<a id="CRD-006"></a>
## CRD-006 — One refresher per rotating credential

**MS4 · SHOULD · retained**

Credentials whose refresh token rotates are refreshed by exactly one keeper, ahead of the point
where a worker's CLI would refresh, under a lock. Worker copies are synchronised from the broker
copy and a newer worker-refreshed credential is never overwritten by an older broker copy.

- AC1: With N concurrent stages on one rotating credential, zero refreshes happen inside workers (asserted from keeper logs in a fixture).
- AC2: Keeper failure sets the credential state to `refresh-failed` with the provider's error code only; the state clears on the next successful sign-in.

Source: driver §5 Codex keeper (k3s-harness #201; the 2026-11-01 sign-out attributed, as inference, to concurrent Jobs spending one rotating refresh token); `cred_sync` compare rule (notes).

Historical text: [CRD-006](history/2026-11-12/04-execution.md).

<a id="CRD-007"></a>
## CRD-007 — Git host credential: least privilege, minted, integrator-only

**MS4 · MUST · retained**

The Git host write credential is used only by the integrator component. The preferred form is a
GitHub App whose installation tokens are minted per operation, scoped to the repository and the
permissions that operation needs, and revoked when it ends; a personal token is supported and
flagged as weaker. Where the credential lives is an owner decision (OD-6).

- AC1: Only the integrator pod mounts the App key or token; API and controller pods do not (manifest test).
- AC2: The App's required permissions are listed in the docs and verified at onboarding; a missing permission degrades by name (for example "cannot cancel superseded runs: Actions write missing").
- AC3: Token expiry is surfaced ahead of time on the credentials screen (UI-012) and, from MS5, as an attention item (OBS-014).
- AC4: Demonstration (count, MS4) — the permissions of the write credential, the pods that can read it and its lifetime are listed for the legacy system and for Sortyard on the same repositories. Target: a token per operation, scoped to one repository, readable by one pod and revoked when the operation ends. Floor: fewer permissions, fewer holders and a shorter lifetime than the legacy personal token, and no expiry date for a person to track (BL-26).

Source: driver §5 (the Git write credential in the cluster is the owner's personal token, with an expiry date; an App credential takes precedence if one is added); 2026-11-04 release note (`actions: write` needed for `cancel_pr_runs`).

Historical text: [CRD-007](history/2026-11-12/04-execution.md).

<a id="CRD-008"></a>
## CRD-008 — Quota awareness

**MS5 · SHOULD · retained**

For each credential with a rate limit Sortyard keeps recent readings, computes the burn rate
inside the reset window, and raises one urgent `QUOTA <credential>` condition when remaining
drops below the low mark (default 20%) or the projection reaches zero before the reset. The
condition lists every mechanism sharing the bucket.

- AC1: A fixture where the bucket burns to zero before reset raises the condition while remaining is still above zero.
- AC2: A credential with no reading inside its window is reported `stale`, not healthy.

Source: MECHANISMS.md (QUOTA items, `quota-reading-<holder>`, fixtures 6 and 9).

Historical text: [CRD-008](history/2026-11-12/04-execution.md).

<a id="CRD-009"></a>
## CRD-009 — Operator account order and task-level selection

**MS4 · SHOULD · retained**

Account priority is data the operator sets per account. A task may carry a selection override:
prefer an account or family, optionally "wait for it", and a selection priority that wins a
contended account.

- AC1: No account identity appears in code; a new account slots in by its priority.
- AC2: The override is a typed task field (TRK-002 `select`) and its effect is recorded in stage facts.

Source: conductor README "Harness routing" (`Select:` line, `select_priority`, account `priority` in `mh_account_state`).

Historical text: [CRD-009](history/2026-11-12/04-execution.md).

<a id="CRD-010"></a>
## CRD-010 — Redaction everywhere

**MS3 · MUST · retained**

Known secret values and secret-shaped strings are redacted from stage results, traces, logs,
packets, notes written by the system, and audit entries before they are stored.

- AC1: CI runs a seeded-secret test through a full chain and greps every store and log for the seed.
- AC2: The worker's evidence token is redacted from its own output before collection.

Source: `runtime.redact`; FACTORY-DASHBOARD-DESIGN "Source model and invariants" (no packet, prompt, tokens or secrets in read APIs); harness-console decided D10.

Historical text: [CRD-010](history/2026-11-12/04-execution.md).

<a id="FLW-001"></a>
## FLW-001 — Workflows are data

**MS3 · MUST · retained**

A workflow is a versioned definition: phases, the stage each phase launches (stage class,
packet template, harness profile), and transitions keyed on observed outcomes. A chain is one
task's run through one pinned workflow version.

- AC1: The built-in workflows are loaded from the default bundle (DEF-008), not hard-coded; replacing a packet template needs no code change.
- AC2: A workflow that declares a stage needing a live third party or a deployment environment is refused at apply time (`pipeline-purity`).
- AC3: There is no human-gate stage type: people act through decisions and needs (RDY-007, RDY-015).

Source: `drive.py` docstring and phases; DESIGN §3.4, §3.6 `pipeline_purity`; AGENTS.md "Delivery lanes".

Historical text: [FLW-001](history/2026-11-12/05-delivery.md).

<a id="FLW-002"></a>
## FLW-002 — The `change` workflow

**MS3 · MUST · retained**

For `feature`, `fix`, `deployment`, `regression` and `triage` tasks:
`claimed → building → landing (branch + change request) → reviewing → merging → [confirming] →
[awaiting-deployment] → done`, with `fixing` loops from review rejection, red required checks and
conflicts, and `parked` / `handed-back` exits from any phase. MS3 delivers it on the plain-git
adapter; MS4 on GitHub.

- AC1: A fixture chain passes through every phase in order and each transition names the observed fact that caused it.
- AC2: Each phase has an end condition and a bound (REC-001); the phase table is generated into the docs from the definition.

Source: task-pickup §2a (state table), §5 (what ends a phase); conductor README "Drive loop".

Historical text: [FLW-002](history/2026-11-12/05-delivery.md).

<a id="FLW-003"></a>
## FLW-003 — The `job` workflow

**MS3 · MUST · retained**

A `job` task runs one verify-class stage on the default branch with the task's title and body as
instructions. The worker's report is attached to the task exactly once and the task goes Done.
No branch, no change request. A run that produces no report is retried twice, then parked.

- AC1: If attaching the report or closing the task fails, the next reconcile retries it and the report still appears once.
- AC2: `urgent` jobs run in the rush lane at the next evaluation.
- AC3: The job packet states what a job cannot do (reach the Git host, CI runners or the cluster) so the report says what is needed instead.

Source: driver §4 "Ad-hoc jobs"; `add_item.py --job`.

Historical text: [FLW-003](history/2026-11-12/05-delivery.md).

<a id="FLW-004"></a>
## FLW-004 — One step per reconcile, on observed facts only

**MS3 · MUST · retained**

Each reconcile advances a chain by at most one transition, and every transition is triggered by
an observed fact (a Job finished, a check concluded, a change request merged), never by a
worker's claim about itself.

- AC1: Replaying a chain's event history reproduces its state (replay test over recorded fixtures).
- AC2: A reconcile is safe to repeat: running it twice with no new facts changes nothing.

Source: AGENTS.md "The rule" ("Advance only on observed state, never on a self-report"); `drive.step` ("Advance one claimed item by one step").

Historical text: [FLW-004](history/2026-11-12/05-delivery.md).

<a id="FLW-005"></a>
## FLW-005 — Code review and its verdict protocol

**MS4 · MUST · retained**

One code review per change request, by a reviewer stage that is not the author stage. It ends
with `VERDICT: approve` or `VERDICT: reject`. Reject only for a blocking finding: the diff does
not do the task or its tests do not exercise it; a bug that breaks behaviour, loses data or
widens access; any defect in code handling auth, money, credentials, outward actions or
irreversible operations. Everything else is approved with at most five `FOLLOW-UP:` lines.
Publishing, deploying, provisioning credentials and live third-party confirmation are named as
`POST-MERGE: <step>` lines and are never reject reasons.

- AC1: A reject consisting only of post-merge steps counts as an approve.
- AC2: Follow-ups become one Backlog task (TRK-018); each post-merge step becomes a `needs_human` task routed to `devops` (DLV-004).
- AC3: The blocking classes, the follow-up cap and the line prefixes are in the packet template and the parser's policy, not in code.

Source: `drive.py` `REVIEW_PACKET`; conductor README "Drive loop" (`LIVE_STEP`, `NOT_LIVE`; CPV2-501, ROVE-713).

Historical text: [FLW-005](history/2026-11-12/05-delivery.md).

<a id="FLW-006"></a>
## FLW-006 — Review scope rules

**MS4 · MUST · retained**

(a) Every review reads the task as the board states it now; findings recorded against an older
text are dropped. (b) The review of a fix head is given the earlier findings and checks those,
without raising new findings about code the earlier review saw. (c) After an approval, a later
round's review covers only that round's change (`diff <approved head>..HEAD`), so a merge of the
default branch does not reopen an approval. (d) A review holds a task to its own scope: a
finding in a surface the task does not change becomes a new `fix` task, not a rejection.

- AC1: Editing a task's body between review rounds makes the next review start clean (fixture).
- AC2: A clean merge of the default branch into an approved change request triggers a review scoped to the merge delta only, before auto-merge is re-armed (MRG-005).

Source: driver §4 (k3s-harness #185, #188); `refresh_task` (CPV2-501); task-ready "One PR's worth" rule 7; `drive.py` note 197 ("Review the new head before re-arming its auto-merge").

Historical text: [FLW-006](history/2026-11-12/05-delivery.md).

<a id="FLW-007"></a>
## FLW-007 — Test-determinism review

**MS4 · MUST · retained**

Every change request whose diff adds or modifies tests gets an independent test review on the
exact head, judged against a named checklist held as data (shipped patterns: STATE-ONCE,
ASYNC-FIRST, ACTION-IN-FLIGHT, SHARED-RESOURCE, SLEEP-SYNC). A blocking finding must cite a
`file:line` inside the changed hunks or code they newly depend on; problems in untouched code are
`PRE-EXISTING:` lines that never block and become follow-ups. Outcomes: `approve`, `reject`,
`not-required`, `unavailable`.

- AC1: `unavailable` (missing verdict, dead worker, incomplete selection, timeout) holds the merge and is reported on the change request and the task: this gate fails closed.
- AC2: A change request with no changed tests is `not-required` without a model call.
- AC3: A later head is reviewed only on that round's hunks; a rewritten branch or a truncated compare gets the whole scope.
- AC4: The review runs no suites; its deadline (default 10 min execution, 15 min including queue) is policy.

Source: TEST-REVIEW.md (HARNESS-278; ROVE-754 for hunk scope).

Historical text: [FLW-007](history/2026-11-12/05-delivery.md).

<a id="FLW-008"></a>
## FLW-008 — Design review for UI changes

**MS5 · SHOULD · retained**

A change request whose diff touches UI files (pages, components, styles, page models — the
selection rules are data) gets one rendered-state review in the change request's preview
environment against a checklist held as data. Only a well-formed
`FAILURE: <item> | page | state | observed | expected` line holds the merge; everything else is a
follow-up. `unavailable` (no preview environment, reviewer failed, checklist missing) is
published and does not hold the merge: this gate fails open.

- AC1: A reject with no well-formed failure line becomes an approve with follow-ups.
- AC2: In a fix round, if no UI file changed since an approved design review, the new head is `not-required`.
- AC3: The checklist text is read from one definition and quoted verbatim in the packet.

Source: DESIGN-REVIEW.md (CONDUCTOR-DESIGN-REVIEW); AGENTS.md "Delivery lanes" rule 7.

Historical text: [FLW-008](history/2026-11-12/05-delivery.md).

<a id="FLW-009"></a>
## FLW-009 — Merge is armed only with every required verdict on the exact head

**MS4 · MUST · retained**

Auto-merge is armed only when each review the policy requires has a ready verdict recorded for
the current head commit. A head that moves needs fresh verdicts; a standalone or older approval
never arms a merge.

- AC1: Property test: for any sequence of pushes and verdicts, auto-merge is armed only in states where all required verdicts match the head.
- AC2: Each gate declares its absent-state behaviour (`block` or `proceed-and-report`) in policy; a gate with no declared absent state is refused at apply time.

Source: TEST-REVIEW "Verdicts and merge enforcement"; `land_approved` note 933; AGENTS.md "Every eval gate defines its absent state".

Historical text: [FLW-009](history/2026-11-12/05-delivery.md).

<a id="FLW-010"></a>
## FLW-010 — Fix rounds continue while the failure changes

**MS4 · MUST · retained**

A rejected review or a red required check starts a fix round on the same change request. Rounds
continue while what is wrong changes. The same failure immediately after a round — the same
failing check set and failing test lines, or the same review findings with run paths and spacing
normalised — parks the task. A backstop (default 10) ends it regardless. A round is counted only
once it was actually submitted.

- AC1: A round that fixes one test and trips another in the same check counts as progress and continues.
- AC2: Two rounds with identical normalised findings park with reason `same failure came back` and both rounds' evidence.
- AC3: A refused submit is not a round.

Source: driver §4 "fixing" (`FIX_ROUNDS = 10`; k3s-harness #199, #210; CPV2-460, ROVE-585); `check_failure`, `same_text`. This closes the design's "one unverified fact" (SORTYARD-1 / HARNESS-286).

Historical text: [FLW-010](history/2026-11-12/05-delivery.md).

<a id="FLW-011"></a>
## FLW-011 — Conflict rounds are counted apart

**MS4 · MUST · retained**

When the default branch conflicts with the change request, the controller performs the merge
itself, commits the conflict with markers into the mirror only, and a fix round resolves the
listed files on top. Nothing with markers is ever pushed to the Git host. Conflict rounds have
their own limit (default 5) because a sibling merging first is not the task's defect.

- AC1: A scan of the pushed head for conflict markers is part of the landing step and blocks the push.
- AC2: Conflict rounds do not count toward the fix-round backstop nor, once it exists, toward the review tripwire (FLW-012).

Source: driver §4 "merging" (`merge_main`, `CONFLICT_ROUNDS = 5`); `drive.py` notes 121, 419.

Historical text: [FLW-011](history/2026-11-12/05-delivery.md).

<a id="FLW-012"></a>
## FLW-012 — Review tripwire

**MS5 · MUST · retained**

Each task keeps cumulative counts of code reviews and test reviews that returned a verdict.
Parks, hand-backs, returns and requeues never reset them; only a merge does. When either count
reaches the tripwire (default 5) without a merge, the task is stopped with reason
`review tripwire`, is never auto-returned, and goes to grooming with its findings to be narrowed
to one PR's worth and split.

- AC1: A requeue of a stopped task stops again at its next review.
- AC2: Reviews that never ran, `unavailable` test reviews, conflict rounds and CI fix rounds are not counted.
- AC3: Grooming's disposition for a tripwire input must be `filed` or `covered`, never `no-work`.

Source: conductor README "Review tripwire" (46 of 378 items reached five or more code reviews and took 44% of all requests, 2026-11-03..10); task-ready rule 10.

Historical text: [FLW-012](history/2026-11-12/05-delivery.md).

<a id="FLW-013"></a>
## FLW-013 — Resuming a parked task

**MS4 · MUST · retained**

A parked task that is requeued while its change request is still open at the head Sortyard last
pushed resumes on it: fresh reviews of that head, then merge or new fix rounds — no rebuild. A
change request moved by someone else is closed as superseded and the task rebuilds from the
default branch. If the change request merged while parked, the task goes Done on the next
reconcile.

- AC1: Verdicts cached before the park are not reused after resume.
- AC2: Rebuilding never collides with an open change request's branch.

Source: driver §4 "blocked"; `resume_parked` incident note (ROVE-754).

Historical text: [FLW-013](history/2026-11-12/05-delivery.md).

<a id="FLW-014"></a>
## FLW-014 — Adopting change requests opened outside Sortyard

**MS4 · SHOULD · retained**

For a green, non-draft change request opened outside Sortyard in a driven repo, with no
hold/do-not-merge/wip label and a plain branch name, Sortyard creates one `review` task per head,
runs the required reviews once, and either arms auto-merge on that exact head or posts the
findings on the change request. It never pushes to or merges into a branch it did not open.

- AC1: A push to an adopted change request after its review creates a new review task for the new head.
- AC2: Branch names are treated as untrusted input everywhere they reach a shell or a ref (MRG-013).

Source: 2026-11-03 release note (#217: loopmentum #498 waited 8 h because no review reached outside PRs); `queue_adopt`; `drive.py` note 417.

Historical text: [FLW-014](history/2026-11-12/05-delivery.md).

<a id="FLW-015"></a>
## FLW-015 — Landing sweep

**MS4 · SHOULD · retained**

On every reconcile, any open change request in a driven repo whose exact head has all required
approvals in Sortyard's record gets auto-merge armed, whoever opened it. Drafts and conflicting
change requests are skipped.

- AC1: An approved, green change request never waits for an agent to remember to land it.

Source: driver §4 "Landing sweep"; conductor README "Drive loop".

Historical text: [FLW-015](history/2026-11-12/05-delivery.md).

<a id="FLW-016"></a>
## FLW-016 — Stranded builds

**MS5 · SHOULD · retained**

A finished build with no change request is detected. If a task requested it, the task is
cancelled or noted with the reason after a grace period; if nothing requested it and its commit
is still held, one low-priority `ship` task retries the landing. If an implausible share of
builds look stranded, the detector raises an alarm about itself and acts on nothing.

- AC1: A build whose run directory no longer holds its head is reported lost once, with no task filed.
- AC2: The self-doubt threshold is policy data.

Source: conductor README "Plane sync" `unlanded_builds` (`STRAND_ACT_HOURS`, `STRAND_ALARM`, `SHIP_CAP`).

Historical text: [FLW-016](history/2026-11-12/05-delivery.md).

<a id="FLW-017"></a>
## FLW-017 — Design-first workflows are expressible, not shipped

**LATER · LATER · retained**

The engine can express a design → reviews → approval → build → verify workflow with a revision
cap. No such workflow, and no self-repair that edits and redeploys the control plane, ships in
1.0. The cut is conditional: if the usage census (MIG-017) counts design chains started in its
window, a design-first workflow is added to the estate bundle before the first cutover.
Self-repair of the control plane is not carried in either case; changes to Sortyard go through
Sortyard and a release.

- AC1: A test bundle defines a three-phase workflow with a review loop and a round cap, and runs on the scripted harness.

Source: `mh.py` chains (`CHAIN_ROUND_CAP = 4`, `CHAIN_REPAIR_MAX_ATTEMPTS = 2`); inference — the conductor path does not call chains (no reference in `control-plane/conductor/*.py`).

Historical text: [FLW-017](history/2026-11-12/05-delivery.md).

<a id="FLW-018"></a>
## FLW-018 — Attempts are immutable history

**MS3 · MUST · retained**

Every stage attempt is kept with its origin (`first`, `retry`, `recovery`), queue-entered time,
schedule time, start, finish and outcome. A failure followed by a successful retry belongs to the
final outcome and keeps its failed-attempt history.

- AC1: Metrics count attempts and chains separately; a retry never appears as an extra chain.
- AC2: Attempt timestamps are sufficient to compute pickup latency and execution time (OBS-007) without proxies.

Source: `mh_task_attempts` (notes); factory-measurement-contract ("Preserve an immutable attempt for each retry/requeue"; `request_updated_at_proxy` as a known weakness).

Historical text: [FLW-018](history/2026-11-12/05-delivery.md).

<a id="FLW-019"></a>
## FLW-019 — The control plane adds almost nothing to a task's time

**MS4 · MUST · retained**

Every hand-off inside a chain — stage finished to next stage dispatched, checks green to
auto-merge armed, review verdict to fix round, merge observed to Done — happens on the event
that enables it, not at the next pass. The time a chain spends waiting on Sortyard itself (not
on an agent, CI, a review or a free slot) is measured per chain as `chain.control_wait` and
shown beside its cycle time.

- AC1: Demonstration (ledger, MS4) — `chain.control_wait` is computed for every chain of the delivery scenario suite and compared with the same hand-offs in the legacy records. Target: p95 at most 60 s per chain, summed over all its hand-offs. Floor: at most half the legacy wait for the same number of hand-offs, each of which waits for the next three-minute or five-minute pass (BL-03).
- AC2: Demonstration (ledger, MS7) — release-to-merge time of one-PR tasks in the pilot, from the ledger, against the same project's legacy figure. Target: p50 at most 30 minutes for a task whose CI takes 10 minutes. Floor: a lower p50 and a lower p90 than the legacy baseline for tasks of the same kind (BL-02).
- AC3: Git host and CI facts arrive by webhook where the installation can receive them and by polling otherwise (API-016); the polling interval for change requests with a chain in flight is policy (default 10 s, with conditional requests, so an unchanged answer costs no rate limit).

Source: task-pickup §3 (pass cadence); AGENTS.md "The rule" (advance on observed state). Inference: a chain's legacy wait is its number of hand-offs times the mean wait for a pass.

Historical text: [FLW-019](history/2026-11-12/05-delivery.md).

<a id="MRG-001"></a>
## MRG-001 — The integrator is the only writer to the Git host

**MS3 · MUST · retained**

One component, the integrator, performs every write to a Git host: pushing branches, opening and
updating change requests, arming and disarming auto-merge, posting verdict comments. It holds the
write credential and nothing else holds it.

- AC1: Manifest test: the write credential is mounted only in the integrator pod.
- AC2: Every write is requested by the controller for a specific chain epoch and refused if the epoch is stale (REC-020).

Source: DESIGN §3.7a (fenced single writer); conductor README ("GitHub writes use the per-run GH_TOKEN").

Historical text: [MRG-001](history/2026-11-12/05-delivery.md).

<a id="MRG-002"></a>
## MRG-002 — Branches and change requests are created idempotently

**MS4 · MUST · retained**

The integrator pushes the stage's commits to a branch named for the task and opens a change
request, or reuses the open one. The body is the task's full text plus a link note. Each step
records a marker before the next, so a failure after the push resumes at change-request creation
and never re-runs the build or duplicates the change request.

- AC1: Kill the integrator after each step: the chain resumes at the next step with no duplicate branch or change request.
- AC2: A leftover branch of a requeued task with no open change request is overwritten; one with an open change request is not.

Source: driver "Recovery" (push marker); `push_branch`, `pr_body` notes.

Historical text: [MRG-002](history/2026-11-12/05-delivery.md).

<a id="MRG-003"></a>
## MRG-003 — Merge only through the host's own gate, bound to the reviewed head

**MS4 · MUST · retained**

Sortyard merges by arming the host's auto-merge for the exact reviewed head commit
(squash by default). It never merges directly, never force-pushes a default branch, and never
adds a merge gate of its own to the repo.

- AC1: The GitHub fake records every API call; the suite asserts zero direct merges and zero admin merges in the default policy.
- AC2: Auto-merge armed for head A does not merge head B (head-match parameter always sent).

Source: driver §4 "Hard rules" ("never `--admin`, never a direct merge, never `ship.py merge`, never a merge gate"); `gh pr merge --auto --squash --match-head-commit`.

Historical text: [MRG-003](history/2026-11-12/05-delivery.md).

<a id="MRG-004"></a>
## MRG-004 — Governed quarantine without inferred bypass authority

**MS4 · SHOULD · amended**

Quarantine requires a recorded reproduction, explicit scope and repair ownership. Required checks continue to gate unless the repository owner has explicitly changed the gate through its governed process. A historical admin-merge behavior is not a grant to bypass protection.

- AC1: No default bundle enables administrative bypass.
- AC2: A required quarantined check reports a named hold until its governance is resolved.
- AC3: A repair preserves the defect record and does not rerun solely to obtain green.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [MRG-004](history/2026-11-12/05-delivery.md).

<a id="MRG-005"></a>
## MRG-005 — Behind or conflicting change requests are brought up to date by Sortyard

**MS4 · MUST · retained**

A change request that is behind or conflicting would wait forever on auto-merge. Sortyard merges
the default branch in: a clean merge is pushed and reviewed (scope: the merge delta) before
auto-merge is re-armed; a conflicted merge starts a conflict round (FLW-011).

- AC1: Auto-merge armed for the old head is disabled before the new head is pushed.
- AC2: For an adopted change request Sortyard never performs the merge; it tells the author.

Source: driver §4 "merging"; `drive.py` notes 196, 197, 417.

Historical text: [MRG-005](history/2026-11-12/05-delivery.md).

<a id="MRG-006"></a>
## MRG-006 — Only required checks drive rounds, and the policy is never guessed

**MS4 · MUST · retained**

The required checks are read from the repo's branch protection or rulesets. Only a failing
required check starts a CI fix round; a non-required failure is noted on the task. If the policy
cannot be read, Sortyard does not guess: it reads again next reconcile. A required check with no
run on the head, once the others are green, starts a fix round — immediately when the host
rejected a workflow file on that head, otherwise after a grace period (default 30 min).

- AC1: With an unreadable protection policy, zero fix rounds start.
- AC2: A required roll-up job (one that needs others and always runs) is replaced by the red jobs it needs when deciding what failed.

Source: conductor README "Incident notes" `ci_round` (LOOP-771, LOOP-774), `missing_checks` (cortexplane #1132 sat 20 h); `CHECKS_GRACE`; `drive.py` notes 239, 1102, 1103.

Historical text: [MRG-006](history/2026-11-12/05-delivery.md).

<a id="MRG-007"></a>
## MRG-007 — A fix head drops the earlier head's auto-merge first

**MS4 · MUST · retained**

Before a fix round's head is pushed, auto-merge armed for the earlier head is disabled, so the
new head merges only after its own reviews.

- AC1: Sequence test: no window exists in which an unreviewed head has auto-merge armed.

Source: driver §4 "fixing" (`gh pr merge --disable-auto`); `drive.py` notes 401, 402.

Historical text: [MRG-007](history/2026-11-12/05-delivery.md).

<a id="MRG-008"></a>
## MRG-008 — Observing the outcome of a merge

**MS4 · MUST · retained**

Merged → the chain proceeds to `confirming`, `awaiting-deployment` or done. Closed without
merging → parked with that reason. A squash that landed while the change request still reads open
is recognised only by proof: the candidate's tree equals the change's merge-base diff applied to
the candidate's parent, and the subject matches.

- AC1: A parked task whose change request merges later goes Done on the next reconcile, through the same completion gate as a normal merge.
- AC2: A task escalated to a person is not turned Done by a later merge sweep.

Source: task-pickup §5; `drive.py` notes 122 (prove a squash landed), 427, 934.

Historical text: [MRG-008](history/2026-11-12/05-delivery.md).

<a id="MRG-009"></a>
## MRG-009 — A stalled merge frees its slot

**MS4 · MUST · retained**

A clean, green, armed change request that has not merged after the stall threshold (default 4 h)
gets auto-merge re-triggered once and another threshold; then the task parks. The re-trigger is
recorded before the host is called, so a partial failure cannot loop it.

- AC1: The worked case in task-pickup §8 (two slots held about nine hours) is a scenario test that ends with both slots freed at the threshold.

Source: task-pickup §5 and conformance row 1 (HARNESS-242); `drive.py` note 416.

Historical text: [MRG-009](history/2026-11-12/05-delivery.md).

<a id="MRG-010"></a>
## MRG-010 — Superseded CI runs are cancelled on merge

**MS4 · SHOULD · retained**

When a change request merges, its own unfinished pull-request runs are cancelled, best effort.
Without the permission, the runs are left to finish and the missing permission is reported once.

- AC1: Cancellation failure never fails or delays the chain.

Source: 2026-11-04 release note (#219: loopmentum #510 merged while its PR CI held 12 jobs queued ahead of main CI).

Historical text: [MRG-010](history/2026-11-12/05-delivery.md).

<a id="MRG-011"></a>
## MRG-011 — Landing on a plain Git remote

**MS3 · MUST · retained**

For a repo with no hosted change requests, the integrator lands an approved candidate on the
default branch only when: a passed receipt exists for the exact `(base, candidate)` pair
(EXE-017); every required review approved the exact candidate; the default branch still equals
`base`, or the candidate is re-proved on the new base; the landed tree is identical to the
candidate's tree.

- AC1: Moving the default branch between proof and landing forces a re-proof; nothing lands on a stale base.
- AC2: The demo and the product's own CI use this adapter; no network access beyond the cluster is needed.

Source: `ship.py` fence as described in DESIGN §3.7a (proof receipt for the exact pair, verify approval of the exact head, tree identity); AGENTS.md "pipeline purity".

Historical text: [MRG-011](history/2026-11-12/05-delivery.md).

<a id="MRG-012"></a>
## MRG-012 — Internal pushes ignore repo hooks

**MS4 · SHOULD · retained**

Pushes between Sortyard's own stores (seeding the mirror, staging refs) bypass the repo's hooks.

- AC1: A repo with a refusing pre-push hook still has its change-request head seeded into the mirror.

Source: driver "Recovery" (`core.hooksPath=/dev/null --no-verify`; Loopmentum's local-proof hook).

Historical text: [MRG-012](history/2026-11-12/05-delivery.md).

<a id="MRG-013"></a>
## MRG-013 — Refs and names from outside are untrusted input

**MS4 · MUST · retained**

Branch names, change-request titles and file paths from the Git host are never interpolated into
a shell or a ref unquoted.

- AC1: A change request whose branch is named `x/$(id)` is handled without executing anything (regression test).

Source: `drive.py` note 376 ("branch names reach a shell: an outside PR's can be `x/$(id)`").

Historical text: [MRG-013](history/2026-11-12/05-delivery.md).

<a id="CIH-001"></a>
## CIH-001 — Sensing a red default branch

**MS5 · MUST · retained**

For each driven repo Sortyard observes: failing push runs on the default branch, failing
scheduled workflows, and workflows triggered by other workflows (deploys). A hand-started run on
the default branch counts as that workflow's newest run. Only live workflows count (active and
present on the default branch), and only runs newer than the repo's onboarding.

- AC1: A red `workflow_run`-triggered deploy on the default branch is sensed.
- AC2: Onboarding a repo files nothing for workflows deleted months ago or runs older than onboarding.
- AC3: If liveness cannot be read, health is shown unfiltered and nothing is triaged that cycle.

Source: driver §3 "Health"; task-pickup conformance row 6 (HARNESS-241); conductor README `live_workflows`, `first_sync` (WALWARDEN-20..24).

Historical text: [CIH-001](history/2026-11-12/05-delivery.md).

<a id="CIH-002"></a>
## CIH-002 — One task owns one incident

**MS5 · MUST · retained**

A red streak has one `triage` task. Later red runs on the same head, or within the incident
window while the task is open, are appended as evidence. A re-run attempt is told apart from a
new run. A streak gets a limited number of triage attempts (default 3); after that the workflow
stops taking lanes, with one notice. A streak ends only on a green run newer than the task's last
failure.

- AC1: Losing every cache does not duplicate triage tasks: ownership is found from typed failure records on the task.
- AC2: A failed re-run of a triaged run is evidence on that task, once per attempt, never a second triage.
- AC3: A triage task parked by Sortyard is reopened by a later red run; one the operator holds in Backlog stays held.

Source: conductor README `queue_triage` (CPV2-597..624: nine items for one outage; ROVE-820/827), `TRIAGE_TRIES`.

Historical text: [CIH-002](history/2026-11-12/05-delivery.md).

<a id="CIH-003"></a>
## CIH-003 — Classify before filing

**MS5 · MUST · retained**

Before a red run is filed its failure is classified from the workflow source and the failing
job's log: **code** (a failing test, or a compile/type/lint/build error with a file and line in
the repo, or a failing step that also runs on change requests) → a `triage` task in the build
lane; **infrastructure** (secrets store, runners, cluster convergence, no failing test) → the
self-heal queue, spending no triage attempt; **estate access** (signing in to the secrets store,
applying or verifying production state, live third-party credentials, a runner refused its
token) → a task routed to `devops`, never to a build; **never started** (zero jobs) → re-run
once, file as infrastructure only on a second zero-job failure; **unrunnable** (a queued job no
online runner's labels can match after the limit, default 30 min) → one urgent task naming the
labels and the nearest runner.

- AC1: Each class has fixtures taken from the recorded incidents; the classifier is versioned and open items are re-classified when its rules change.
- AC2: A log with a failing test is never classified as infrastructure; an application's own "X is not configured" warning does not count as an infrastructure cause.
- AC3: The decision is made at filing, never learned from a worker's hand-back.

Source: conductor README `infra_cause`, `estate_access` (eight red-main items handed back, 630 item-hours), `zero_jobs` (GitHub Actions incident 2026-11-09), `queue_unrunnable` (rove PyPI publish blocked ~33 h; 25 false items when scale sets were not declared).

Historical text: [CIH-003](history/2026-11-12/05-delivery.md).

<a id="CIH-004"></a>
## CIH-004 — Close on green

**MS5 · MUST · retained**

Every open red-main task, whatever its queue status, closes Done with a link to the green run
once a newer run of its workflow on the default branch succeeds. An open, unmerged fix for it is
closed as superseded; a merged fix still confirming is left to finish.

- AC1: A task whose last recorded failure is not older than the green run stays open.
- AC2: An unreadable page of evidence closes nothing and is retried.

Source: conductor README `close_green` (ROVE-664, ROVE-766 stayed open more than a day after main went green).

Historical text: [CIH-004](history/2026-11-12/05-delivery.md).

<a id="CIH-005"></a>
## CIH-005 — Red-main fixes prove themselves causally, then confirm on main

**MS5 · MUST · retained**

A triage chain's build and fix packets ask for each test or step that failed in the red run to
be re-run and shown passing; the review checks that evidence and does not run the whole suite.
After the merge the chain is `confirming`: only a finished run of that workflow on the default
branch decides. Which runs count depends on the workflow (push workflows: the merge's own push
run, counted from the merge time; scheduled suites: scheduled or hand-started runs). A cancelled
or skipped run is no verdict. Green → Done and a lock-in task (CIH-006). Red at the original
failure → another round, up to a limit (default 2 merged fixes), then parked with an escalation
to a person. Red for an infrastructure cause or at none of the original steps closes this fix
and the new failure is filed separately. No verdict within 24 h of the merge parks it with the
runs seen; a workflow no longer on the default branch closes it.

- AC1: Scenario tests cover: push-workflow confirm from merge time (LOOP-518), cancelled run as no verdict (ROVE-615), deleted workflow (CPV2-535), the confirm limit (CPV2-625).
- AC2: Sortyard does not start a second suite on the same runners when the merge's own run will decide.

Source: driver §4 "Red main"; conductor README "Incident notes" (`verdict_events`, `NO_VERDICT`, `CONFIRM_LIMIT`, `moved_on`); `TRIAGE_ROUNDS`, `DISPATCH_GRACE`, `PROOF_WAIT`.

Historical text: [CIH-005](history/2026-11-12/05-delivery.md).

<a id="CIH-006"></a>
## CIH-006 — Lock-in after a red main

**MS5 · MUST · retained**

Closing a red-main incident files a `regression` task (high priority) naming the culprit range:
from the newest green run before the red one to the red head. Its change adds a fast test to the
checks every change request runs; its review runs the test on the culprit commit, where it must
fail, and on the head, where it must pass.

- AC1: Without permission to run workflows, the review degrades to inspection and says so.

Source: driver §4 "The lock-in item".

Historical text: [CIH-006](history/2026-11-12/05-delivery.md).

<a id="CIH-007"></a>
## CIH-007 — Inherited red is held, not fixed

**MS5 · MUST · retained**

Change-request CI runs on the merge with the default branch, so a red main is every open change
request's red. Before a CI fix round, the change request's failing (job, test) pairs are compared
with the latest completed run of the same workflow on the default branch. If all are shared, the
task is held in merging as `inherited: main red`, with one notice naming main's run and its
triage task, and no round is spent. When main's next run is green, main is merged in (or the
failed jobs are re-run) and the chain continues. A held task's stall clock does not run.

- AC1: A failing test main does not share, or a failing job with no test named, is not inherited and gets a normal round.

Source: conductor README "Incident notes" `inherited` (ROVE-764: round 3 spent, main green 24 min later, item in Backlog two days); k3s-harness #318.

Historical text: [CIH-007](history/2026-11-12/05-delivery.md).

<a id="CIH-008"></a>
## CIH-008 — CI evidence goes into the packet

**MS4 · MUST · retained**

For a CI fix round the controller reads each failing required job's log and puts an excerpt in
the packet: the test runner's failure summary and failing tests first, found across the whole
log, otherwise the lines before the error. A failing job whose log cannot be read gets no round;
it is read again each reconcile and the merging stall bounds the wait.

- AC1: The excerpt extractor used by fix rounds has fixtures from the recorded runs; triage reuses the same one (CIH-002).
- AC2: A worker's account that it "could not read the CI log" is refused once per CI round and the round is re-sent.

Source: conductor README "Incident notes" `ci_round`, `infra_cause` (`failed_log` puts the summary first); `hand_back` refusal.

Historical text: [CIH-008](history/2026-11-12/05-delivery.md).

<a id="CIH-009"></a>
## CIH-009 — A job stopped by the runner or the estate is re-run, not built around

**MS5 · MUST · retained**

A required job that failed with no failing test and an infrastructure cause, or was cancelled or
timed out by the runner, is re-run once per head. A repeat goes to self-heal with the evidence,
recording a `check` blocking cause (REC-008). It never starts a build.

- AC1: The second failure produces a self-heal item naming the job, the step and the access needed.

Source: conductor README "Incident notes" `ci_round`; "Blocking causes".

Historical text: [CIH-009](history/2026-11-12/05-delivery.md).

<a id="CIH-010"></a>
## CIH-010 — Evidence-backed test quarantine and governed gates

**MS5 · SHOULD · amended**

Conflicting results at one source head create a flake investigation with reproduction, evidence, scope, owner and retirement/repair condition. Report-only placement or required-check changes use reviewed repository governance; a local quarantine list never grants administrative merge bypass.

- AC1: A suspect check is not rerun merely to seek a green conclusion.
- AC2: An unreadable quarantine/required-check source preserves the declared gate and reports unknown.
- AC3: Repair/disposition preserves the defect history and intended-contract coverage.

Source: JOB-QUARANTINE.md (HARNESS-270); CI-FLAKES.md; TEST-REVIEW "Shared hindsight".

Historical text: [CIH-010](history/2026-11-12/05-delivery.md).

<a id="CIH-011"></a>
## CIH-011 — Flake re-run instead of self-heal

**MS5 · SHOULD · retained**

When a CI fix round is handed back with no change and every recorded failing test names a file
outside the change request's changed files, the failed jobs are re-run once on that head and the
chain returns to merging. The same head handed back again goes to self-heal.

- AC1: A failing job with no recorded tests, or a test with no file, is never treated as a flake.

Source: conductor README "Blocking causes" (`flake_rerun`; ROVE-741/750/817).

Historical text: [CIH-011](history/2026-11-12/05-delivery.md).

<a id="CIH-012"></a>
## CIH-012 — Forbidden remedies

**MS5 · SHOULD · retained**

Triage and CI-fix packets and their reviews forbid, as policy text: moving jobs to
provider-hosted runners, changing runner labels, deleting or skipping a failing test. A review
that sees one rejects.

- AC1: The forbidden list is data in the packet template; an installation can edit it.

Source: 2026-11-03 release note (#217: Rove #627 moved a timing test to a paid hosted runner); AGENTS.md "Testing model" ("A failing test is fixed on the side that is wrong, never deleted or skipped").

Historical text: [CIH-012](history/2026-11-12/05-delivery.md).

<a id="CIH-013"></a>
## CIH-013 — CI is an adapter

**MS4 · MUST · retained**

Everything above talks to CI through an interface: list runs and jobs for a ref, read a job log,
read required checks, re-run failed jobs, cancel a run, start a workflow. 1.0 ships the GitHub
Actions implementation and a fake used by the test suite.

- AC1: The entire CIH scenario suite runs against the fake with no network.
- AC2: A capability the provider or the credential lacks is reported by name and the dependent behaviour degrades as documented.

Source: AGENTS.md "pipeline purity"; CORPUS R6.

Historical text: [CIH-013](history/2026-11-12/05-delivery.md).

<a id="DLV-001"></a>
## DLV-001 — Task completion and delivery outcome are distinct

**MS2 · MUST · amended**

A feature task is complete when its named checks and required review pass and its change is merged. DeliveryGoal/DeploymentObservation separately tracks published artifact, desired revision, native reconciliation and verified product behavior; merged-but-not-delivered remains visible and owned.

- AC1: A feature is not blocked on production access or an owner click.
- AC2: Merged source with red/missing deployment evidence is never reported as delivered.
- AC3: The API and UI show the same task state and separate delivery verdict.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DLV-001](history/2026-11-12/05-delivery.md).

<a id="DLV-002"></a>
## DLV-002 — Native delivery observations and evidence

**MS2 · SHOULD · amended**

Read provider/CI/Argo observations for source, artifact, desired/reconciled revision and health with freshness and provenance. They inform delivery visibility and repair ownership; read-only production status is not substituted for feature acceptance or a new custom release state machine.

- AC1: An older successful rollout cannot certify a newer merged commit.
- AC2: Missing or stale observation remains unknown with a repair owner.
- AC3: Deep links reach the provider proof and corresponding authorized domain records.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DLV-002](history/2026-11-12/05-delivery.md).

<a id="DLV-003"></a>
## DLV-003 — Native release integration

**MS4 · SHOULD · amended**

Promotion and recovery use the platform-owned reviewed CI/GitOps release path. Sortyard exposes authorized requests and observations and does not create bespoke release shield/receipt/restore machinery or run raw product kubectl commands on behalf of the UI.

- AC1: An authorized promotion request follows the registered native path.
- AC2: An unsupported release action returns unavailable rather than invoking shell fallback.
- AC3: The recorded outcome distinguishes request acceptance from observed deployment.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DLV-003](history/2026-11-12/05-delivery.md).

<a id="DLV-004"></a>
## DLV-004 — Owned post-merge work

**MS2 · SHOULD · amended**

Post-merge operational work becomes an owned deployment/integration operation or separate task with explicit needs. Routine configured operations run under standing authority; only actual premise-class boundaries reach the operator. Follow-up task creation is deduplicated.

- AC1: Routine deployment/configuration does not automatically become needs_human.
- AC2: A genuine unresolved credential/public/irreversible/spending boundary names the required decision.
- AC3: One repeated finding creates one follow-up with its source link.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DLV-004](history/2026-11-12/05-delivery.md).

<a id="REC-001"></a>
## REC-001 — Every wait has an exit

**MS3 · MUST · retained**

Every phase of every workflow has an end condition and a bound. When the bound passes, the chain
takes a defined stuck transition (park, hand back, or escalate) that frees its slot. No phase can
hold a slot indefinitely.

- AC1: A generated table lists each phase, its end conditions and its bound; a definition with an unbounded phase is refused at apply time.
- AC2: Scenario tests exist for every row of task-pickup §5 and §7.
- AC3: Demonstration (parity, MS5) — every stall episode in the baseline catalogue (BL-05) is replayed as a scenario. Target: every slot is freed at its bound with the item parked, handed back or escalated, and no episode needs a person to free a slot. Floor: no slot is held past its bound in any catalogued episode; the legacy system held slots for hours in each of them (BL-05).

Source: task-pickup §2a ("No state in the design holds a slot without an exit") and conformance row 1 (the released code only commented; two slots were held about nine hours).

Historical text: [REC-001](history/2026-11-12/06-recovery.md).

<a id="REC-002"></a>
## REC-002 — Infrastructure failure budget

**MS5 · MUST · retained**

A stage whose worker never produced a result (pod lost, CLI install failed, model capacity) is
re-run as the same step: up to 3 immediate retries, then a wait (default 30 min) and a fresh set,
at most 2 waits, then the task parks. Any step that returns a result resets the count. The same
failure reason twice in a row spends the immediate retries and goes straight to the wait.

- AC1: A steady failure parks after 4 attempts, a changing one after at most 10 (scenario test with injected reasons).
- AC2: The re-run submits exactly the same step and inputs.
- AC3: All four numbers are policy data.

Source: driver §4 "Infra failures" (`INFRA_RETRIES`, `INFRA_WAIT`, `INFRA_WAITS`; k3s-harness #188, #194 — a full `/work` failed every retry within minutes on 2026-10-28).

Historical text: [REC-002](history/2026-11-12/06-recovery.md).

<a id="REC-003"></a>
## REC-003 — A task failure is not an infrastructure failure

**MS5 · MUST · retained**

A stage that ran and failed its declared checks is a task outcome: a build is rebuilt from the
default branch at most twice; a fix round parks. It does not consume the infrastructure budget.

- AC1: `execution_ok: true, pass: false` never increments the infrastructure counters.

Source: driver §4 (k3s-harness #174); `drive.py` note 393.

Historical text: [REC-003](history/2026-11-12/06-recovery.md).

<a id="REC-004"></a>
## REC-004 — Deterministic failures are not retried as if they were transient

**MS5 · MUST · retained**

A failure that will recur identically (a base missing from the mirror after seeding, an input
that cannot be verified, a packet over the cap) is retried once at most and then parks with the
specific reason.

- AC1: The missing-base scenario ends after two attempts, not ten.

Source: driver §4 (k3s-harness #193, DV-57; CPV2-408 burned ten builds on one missing head).

Historical text: [REC-004](history/2026-11-12/06-recovery.md).

<a id="REC-005"></a>
## REC-005 — Consecutive errors park one item; outages park none

**MS5 · MUST · retained**

An item whose step raises an error 5 times in a row is parked with an `infra` blocking cause. One
successful step clears the count. Errors caused by a dependency being unavailable (control-plane
API restarting, database failover) are logged and do not count.

- AC1: During a simulated 40-second API outage no item is parked and no counter moves.
- AC2: Cluster-API errors are retried up to 6 times before counting.

Source: driver "Recovery" (k3s-harness #183); conductor README "API rollouts" (`Unavailable` never counts toward `errors`); `drive.py` note 400.

Historical text: [REC-005](history/2026-11-12/06-recovery.md).

<a id="REC-006"></a>
## REC-006 — Parking

**MS3 · MUST · retained**

A parked task leaves the queue, frees its slot, keeps its change request if any, and gets one
notice saying why and what would bring it back. Requeueing it (one action) resumes it
(FLW-013).

- AC1: The park reason is a typed field shown on the board, the detail page and the Pickup Preview.
- AC2: `sortyardctl requeue KEY-N [note]` and the UI action are the same API call.

Source: driver §4 "blocked"; `requeue.py`.

Historical text: [REC-006](history/2026-11-12/06-recovery.md).

<a id="REC-007"></a>
## REC-007 — Hand-back to self-heal

**MS5 · MUST · retained**

A run that makes no change is handed back: the task leaves the build queue for the self-heal
queue, carrying the worker's own account of why. An account that only says it could not read
the CI log is refused once per CI round and the round is re-sent.

- AC1: The hand-back record contains the worker's account, the evidence it cited and the blocking cause it named, if any.
- AC2: A hand-back never loses the chain's history or its open change request.

Source: driver "Recovery" (label `self-heal`); `hand_back` notes 140, 434.

Historical text: [REC-007](history/2026-11-12/06-recovery.md).

<a id="REC-008"></a>
## REC-008 — Blocking causes bring parked work back by themselves

**MS5 · MUST · retained**

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

Source: conductor README "Blocking causes" (`causes.py`, `POLL`, `RETURNS`; Joe 2026-11-06).

Historical text: [REC-008](history/2026-11-12/06-recovery.md).

<a id="REC-009"></a>
## REC-009 — The self-heal contract

**MS5 · MUST · retained**

The self-heal queue is worked by an agent or person with access workers lack. Each item ends in
one recorded outcome: **fixed directly** (with verification), **outcome already met** (RDY-008),
**handed back to build** (diagnosis and exact change written at the top of the task), **moot**
(evidence, then Cancelled), or **owner input** (converted to or linked with a decision). Self-heal
principals never merge, approve or review, and never add merge gates.

- AC1: The resolution action requires one of the five outcomes and its evidence field.
- AC2: The self-heal role's token cannot call review or merge operations (authorization matrix test).
- AC3: The list of projects to scan comes from the same configuration the scheduler uses; there is no second list.

Source: conductor `SELF-HEAL.md`; HARNESS-248 (the contract listed the wrong project identifier).

Historical text: [REC-009](history/2026-11-12/06-recovery.md).

<a id="REC-010"></a>
## REC-010 — Self-heal drain

**MS5 · MUST · retained**

While any task of a project has been in self-heal or `needs_human` for longer than the drain
limit (default 24 hours, the legacy value), one urgent `SELF-HEAL-STALLED <project>` condition
lists each item, its stop reason and its age. It closes only when nothing of the project remains
in either queue.

- AC1: The condition is updated in place and never duplicated.

Source: conductor README "Self-heal drain" (35 open self-heal items, 21 untouched for 24 h; HARNESS-444).

Historical text: [REC-010](history/2026-11-12/06-recovery.md).

<a id="REC-011"></a>
## REC-011 — Phase and age are always visible

**MS3 · MUST · retained**

Every in-flight chain's phase, slot use and time in phase are visible through API, CLI and UI. A
chain in one phase longer than the stall threshold (default 4 h) gets exactly one notice saying
where it is stuck.

- AC1: The information the legacy conductor kept only in `state.json` (phase, slot use, stale live records, running revision) is readable without cluster access.
- AC2: Demonstration (count, MS3) — the facts an operator needs about work in flight (phase, slot use, time in phase, stale records, running revision) are listed with where each is read. Target: 100% through the API, the CLI and the console, each within 1 s. Floor: none needs cluster access; in the legacy system every one of them does (BL-28).

Source: driver §4 "Visibility"; task-pickup conformance row 7 (HARNESS-256).

Historical text: [REC-011](history/2026-11-12/06-recovery.md).

<a id="REC-012"></a>
## REC-012 — Side effects are idempotent and recorded when accepted

**MS3 · MUST · retained**

Each external write (a Job, a push, a change request, a comment, an auto-merge toggle) is
recorded only once the external system accepted it, so a failure is retried on the next
reconcile; and each has an idempotency marker, so a retry after a lost response does not repeat
it.

- AC1: Lose the response to each kind of write in turn: the effect exists exactly once afterwards (fault-injection matrix).
- AC2: A notice of a given kind for a given condition is posted once.

Source: `drive.py` notes 242, 250, 416, 422 ("persisted first: a partial GitHub failure cannot loop the toggle").

Historical text: [REC-012](history/2026-11-12/06-recovery.md).

<a id="REC-013"></a>
## REC-013 — Recoverable submission and external effects

**MS1 · MUST · amended**

Submission records stable operation identity and domain receipt atomically with state/events. A retry recovers that outcome; an uncertain external effect is reconciled by stable provider identity before any repeated instruction.

- AC1: A lost response does not create another chain or external instruction.
- AC2: A conflicting reuse of a key returns an actionable conflict; it does not silently substitute a fresh key.
- AC3: At-least-once delivery and effect receipts survive worker restart.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [REC-013](history/2026-11-12/06-recovery.md).

<a id="REC-014"></a>
## REC-014 — Controller restart and failover

**MS3 · MUST · retained**

At most one controller acts at a time (leader election with a fencing epoch). After a crash,
restart or failover a new leader resumes with no duplicate Jobs, change requests, comments or
merges and no lost stage result. A leader that is shutting down hands over instead of letting
its lease lapse.

- AC1: Chaos test: kill the leader at random points during 200 chains; the end state equals a run with no kills.
- AC2: A deposed leader's writes are refused by the epoch check.
- AC3: Demonstration (chaos, MS3) — the leader is killed at random points during 200 chains, timing from the kill to the next reconcile by a leader. Target: at most 15 s, with an end state equal to a run with no kills. Floor: at most 60 s; the legacy system resumes at its next pass, up to three minutes later (BL-25).

Source: inference from the single-writer constraints today (`concurrencyPolicy: Forbid` on the CronJobs; `strategy: Recreate` "single writer to the sqlite db: never two pods").

Historical text: [REC-014](history/2026-11-12/06-recovery.md).

<a id="REC-015"></a>
## REC-015 — Version skew never pauses delivery silently

**MS3 · MUST · retained**

Adjacent versions run side by side: the controller and the API of one minor version work with
the schema and the stage contract of the previous one (DEP-007, DEP-009), so an upgrade does not
pause delivery. Only a schema outside that window makes the controller idle: it writes nothing
and reports `skew` in health at once (`/readyz`, `/v1/info`, the Overview); from MS5 its missed
heartbeats also raise a `SILENT` condition (REC-017).

- AC1: During a rolling upgrade between adjacent minors no reconcile is skipped for skew, and no reconcile ever runs against a schema outside the supported window.
- AC2: The skew state is visible wherever health is shown; it is never a silent idle.
- AC3: Demonstration (chaos, MS3) — a rolling upgrade runs during 20 chains, and separately an upgrade is made to stall half-way, measuring the seconds in which no reconcile runs and the time until the stall is reported. Target: zero paused seconds, and a stuck upgrade reported within 60 s. Floor: paused at most 60 s and never silently; the legacy system skipped every pass for about 32 minutes with only a log line (BL-08, BL-25).

Source: conductor README "API rollouts" (`api_skew`; "ends without touching `state.json`"); 2026-11-12 release stall ("pass skipped, rollout: API bundle …" for about 32 min with no visible alarm).

Historical text: [REC-015](history/2026-11-12/06-recovery.md).

<a id="REC-016"></a>
## REC-016 — Dependency outages are waited out

**MS5 · MUST · retained**

Connection-level failures to the database, the API, the Git host or the cluster API are retried
with capped backoff (default schedule, the legacy one: 1, 2, 4, 8, 15 s up to 90 s). A reconcile
that cannot proceed ends without partial writes. No verdict, review outcome or grooming result
is recorded as `failed` or `unavailable` because a dependency was briefly down.

- AC1: Eleven simulated 40-second restarts in a day produce zero failed reviews and zero parked items.

Source: conductor README "API rollouts" (11 rollouts failed grooming, flake processing and test reviews with ECONNREFUSED).

Historical text: [REC-016](history/2026-11-12/06-recovery.md).

<a id="REC-017"></a>
## REC-017 — Every recurring mechanism has a freshness window

**MS5 · MUST · retained**

Every loop and scheduled job inside Sortyard is registered with an owner route, a cadence and a
freshness window no shorter than the cadence. One that goes quiet past its window raises one
`SILENT <mechanism>` condition carrying last success, last error, cadence and window, and closes
it when heartbeats resume. The checker runs independently of everything it watches and is itself
registered.

- AC1: Stopping any registered loop produces its `SILENT` condition inside its window (one test per mechanism, generated from the registry).
- AC2: Adding a loop without registering it fails CI (registry coverage test).
- AC3: With the scheduler and the integrator both down, the checker still reports them.

Source: MECHANISMS.md (registry, `conductor-mechanism-health` runs apart from drive and plane-sync; fixtures 1–9); k3s-harness #321.

Historical text: [REC-017](history/2026-11-12/06-recovery.md).

<a id="REC-018"></a>
## REC-018 — External heartbeats

**MS5 · SHOULD · retained**

Jobs outside Sortyard can register as mechanisms and post heartbeats
(`{mechanism, status, error?, at?}`) with a token. An unknown name raises `UNREGISTERED <name>`.
A heartbeat that cannot be delivered is noticed by its absence.

- AC1: The heartbeat client is one HTTP call and never fails the job it wraps.
- AC2: Cluster-object and CI-workflow observers (CronJob last success, resource conditions, scheduled workflow runs) are an optional integration, required before legacy retirement (MIG-012).

Source: MECHANISMS.md "Heartbeats from jump-box and Juno-side jobs", heartbeat kinds `cronjob`, `resource`, `workflow`, `pr-runs`.

Historical text: [REC-018](history/2026-11-12/06-recovery.md).

<a id="REC-019"></a>
## REC-019 — Health has four states and never hides the unknown

**MS5 · MUST · retained**

Overall health is the worst of: `silent-check` (the checker's own report is stale), `degraded`
(any silent mechanism, low quota, missing reading or unregistered mechanism), `partial` (some
sources unreadable), `healthy`. A source that cannot be read makes its mechanisms `unknown`: not
filed, not closed, named in the report.

- AC1: An unreadable source never yields `healthy`.
- AC2: `/readyz` and the Overview show the state and what is driving it.

Source: MECHANISMS.md "FACTORY-HEALTH-SENSOR input".

Historical text: [REC-019](history/2026-11-12/06-recovery.md).

<a id="REC-020"></a>
## REC-020 — One writer per chain, enforced at the side-effect boundary

**MS3 · MUST · retained**

A chain has a revision (epoch) that increases on claim, on requeue, on cancel and on an
operator's steering change. Every side-effecting operation carries the epoch it was planned
under and is refused when it is stale: stage result submission, pushes, change-request writes,
merges.

- AC1: A worker from a cancelled or superseded attempt submits a result: it is refused and recorded as stale.
- AC2: The check is in the integrator and the API, not only in the controller's memory.
- AC3: Demonstration (chaos, MS3) — superseded workers, deposed controllers and cancelled attempts each try every side effect (result, push, change-request write, merge) 1,000 times. Target: 100% refused at the integrator or the API and recorded as stale. Floor: zero stale side effects accepted; the legacy system has no check at that boundary (BL-28).

Source: in-flight-steering ("A durable per-task revision must eventually be checked by the actual side-effecting execution boundary … Until that path is implemented … report its absence honestly").

Historical text: [REC-020](history/2026-11-12/06-recovery.md).

<a id="REC-021"></a>
## REC-021 — Steering work in flight

**MS3 · MUST · retained**

An operator can change a task that is already in flight: edit its text (the next stage reads the
new text and stale findings are dropped), cancel the running stage, or stop the chain. Steering
revises the existing chain; it never starts a competing one.

- AC1: After a mid-flight edit there is still exactly one chain for the task, with a higher epoch.
- AC2: Evidence that the change did not invalidate is reused; only invalidated reviews re-run.
- AC3: Demonstration (benchmark, MS4) — a scripted operator edits a task's text mid-build, cancels a stage and stops a chain, counting steps and the reviews that re-run. Target: one action each, in force at the next stage, with only invalidated reviews re-run. Floor: each is done from the console with no cluster access and no competing chain; the legacy procedure is manual (BL-28).

Source: in-flight-steering ("steering revises the existing task"); driver §7 ("Stop an item mid-flight: Not supported yet").

Historical text: [REC-021](history/2026-11-12/06-recovery.md).

<a id="REC-022"></a>
## REC-022 — Work storage is cleaned under pressure, never under a live chain

**MS3 · SHOULD · retained**

Finished run directories are kept for a retention time (default 24 h). At or above a usage
threshold (default 85%) retention drops (default 4 h) with no per-pass cap. A directory any live
chain still needs is never deleted. Deletion runs detached so dispatch never waits on it.

- AC1: Filling the volume in a test triggers pressure retention and dispatch latency is unaffected.
- AC2: Volume usage is a metric with a warning threshold (OBS-010) and, from MS5, an attention item (OBS-014), before it is an outage.

Source: driver §5 (`MH_WORK_PRESSURE_PCT`, `MH_WORK_RETENTION_PRESSURE_S`; k3s-harness #187, #189); `mh.py` retention (notes).

Historical text: [REC-022](history/2026-11-12/06-recovery.md).

<a id="REC-023"></a>
## REC-023 — Conditions: one alarm per cause, updated in place, closed by the system

**MS5 · MUST · retained**

System-raised alarms are `condition` tasks with a stable key. A condition is created once per
cause, updated in place while the cause persists, never duplicated — even after losing every
cache — and closed with a notice when the cause clears. The v1 conditions: `FILING-INVISIBLE`,
`CONFIG-INVALID`, `GROOMING-STALLED`, `SELF-HEAL-STALLED`, `SILENT`, `QUOTA`, `UNREGISTERED`,
`CITATION-MISMATCH`, `RELEASE-VERIFY-FAILED`.

- AC1: Raising the same cause 100 times yields one open task.
- AC2: Each condition names an owner route and appears in that route's list.

Source: conductor README (each of these items is described as "updated in place, never duplicated, and closed when…"); MECHANISMS.md.

Historical text: [REC-023](history/2026-11-12/06-recovery.md).

<a id="REC-024"></a>
## REC-024 — The owner is never a step inside delivery

**MS5 · MUST · retained**

No workflow blocks on a person. People are reached only through decisions (with defaults),
needs routed to them, and escalations. The owner list contains exactly: open decisions due,
premise-class decisions escalated, needs routed to `owner`, and items escalated "to a person".

- AC1: The owner list is one API call; an item appears on it for one of the four reasons, shown.
- AC2: A notification reaches the owner only for an owner-list item or a factory-down state with nothing acting on it (OBS-013).
- AC3: Operator actions on work in flight (requeue, cancel, force, manual state change, resolving a hand-back), counted from the ledger for each week and for each 100 merged tasks (`operator.interventions`). Target: zero in a week. Floor: fewer for each 100 merged tasks than the legacy baseline (BL-07).

Source: driver §6 ("The owner is never a step inside delivery"; "Slack is only for what the owner alone can do, or the factory being down with nothing acting on it").

Historical text: [REC-024](history/2026-11-12/06-recovery.md).

<a id="REC-025"></a>
## REC-025 — Parity and chaos suites

**MS5 · MUST · retained**

Two suites gate the milestone that makes Sortyard safe to leave alone: a **parity suite** with at
least one scenario for every KEEP or FIX row of [16-legacy-parity.md](history/2026-11-12/16-legacy-parity.md) whose
requirements are MUST and due by MS5, run against the Git host and CI fakes (rows owed by a
SHOULD or by a later milestone gain their scenario with that requirement and are complete
before the estate's cutovers, MIG-010); and a **chaos suite** that injects controller kills, worker
pod loss, database restarts, Git host errors, model-capacity errors, a stale mirror and a full
work volume.

- AC1: The parity matrix is machine-readable: CI fails when a row that is due has no passing scenario, and reports every other row as pending with the milestone that owes it.
- AC2: After each chaos run, every task is in a terminal or owned state and no slot is held past its bound.
- AC3: A scenario that is a demonstration runs with its legacy baseline beside it, writes the measured value to the scorecard (QLT-051) and fails below its floor.

Source: inference — the legacy system encodes its behaviour in `test_conductor.py` (10,364 lines) and `test_mh.py` (3,268 lines); a claims-only shadow comparison cannot exercise the step machine.

Historical text: [REC-025](history/2026-11-12/06-recovery.md).

<a id="REC-026"></a>
## REC-026 — Stalls are detected and recovered in minutes

**MS5 · MUST · retained**

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

Source: conductor README "Self-heal drain" and "Incident notes"; task-pickup §5; the estate's practice of building a recovery for each stall class instead of another watch. The three mechanisms are inference from the recorded episodes.

Historical text: [REC-026](history/2026-11-12/06-recovery.md).

<a id="API-001"></a>
## API-001 — One versioned REST API with a served OpenAPI document

**MS1 · MUST · retained**

The API lives under `/v1`, is described by an OpenAPI 3.1 document served at
`/v1/openapi.json`, and CI fails if the implementation and the document disagree. Resource shapes
come from the JSON Schemas in `spec/`, from which the Python models are generated.

- AC1: A contract test calls every operation in the document against a running server and validates each response against its schema.
- AC2: `python -m sortyard.models.codegen --check` and the OpenAPI drift check gate every PR; the `spec` job is no longer `continue-on-error`.
- AC3: Surface parity, measured at every merge to `main`: the share of the commands a person or an agent may perform that are REST operations, and the share of REST operations that have a CLI path, MCP reach and, when operator-facing, a console control. Target: 100% on all four at every merge, with no exemption. Floor: 100% for REST, CLI and MCP at every merge; console exemptions are dated and empty at each milestone exit (UI-002).

Source: spec NOTES "API conventions"; `.github/workflows/ci.yml` (the `spec` job currently fails on main and does not gate); goldfish GF1-02, GF1-09.

Historical text: [API-001](history/2026-11-12/07-interfaces.md).

<a id="API-002"></a>
## API-002 — Commands live in the domain layer; the API adds no rules

**MS1 · MUST · retained**

State machines, invariants and ledger writes are enforced in the domain layer (and by database
constraints where possible). HTTP handlers authenticate, authorise, validate shape and call a
command.

- AC1: The same command called from an HTTP handler and called in-process (the controller's path) produces identical state and events (shared test).
- AC2: No invariant test depends on going through HTTP.
- AC3: Demonstration (chaos, MS3) — the API is stopped for 10 minutes while chains are in flight. Target: claims, the advancement of finished stages and landing continue throughout, every result produced meanwhile is accepted when the API returns, and zero stages fail. Floor: no evaluation is skipped and no stage fails because the API is down; the legacy conductor skipped every pass while its API was unavailable (BL-25).

Source: DESIGN §4 ("API service — the only door"); see CF-07 for why the controller does not use HTTP.

Historical text: [API-002](history/2026-11-12/07-interfaces.md).

<a id="API-003"></a>
## API-003 — Conventions

**MS1 · MUST · retained**

Lists use opaque cursors in both directions with `limit` (default 50, max 200), filters and sort
as query parameters, and return a total where it is cheap. Errors are RFC 9457 problem details
with a stable `code`. Status codes: 400 malformed, 401, 403, 404, 409 refused by a state machine
or policy, 412 stale precondition, 422 fails schema validation, 429, 503 dependency unavailable.
Timestamps are RFC 3339 UTC; durations are integer seconds.

- AC1: Every list endpoint passes a shared pagination conformance test (stable order under concurrent inserts, no duplicates or gaps across pages).
- AC2: Every error body validates against the problem schema, for every method on every path.

Source: spec NOTES "API conventions"; harness-console J2 ("server cursors in both directions"), decided D6; goldfish GF1-06 (HTML 501 page).

Historical text: [API-003](history/2026-11-12/07-interfaces.md).

<a id="API-004"></a>
## API-004 — Optimistic concurrency

**MS1 · MUST · retained**

Every mutable object has a revision returned as an `ETag`. `PATCH` and action endpoints accept
`If-Match`; a stale revision returns 412. The console always sends it.

- AC1: Two clients editing the same task: the second write fails with 412 and loses nothing.
- AC2: In-process callers (the controller's path) pass through the same revision check.

Source: inference — the frozen API replaces whole documents by merge patch with no precondition, while the operator, agents and the controller all write tasks; Plane writes of a pod on old code overwrote three specs during the 2026-11-08 import.

Historical text: [API-004](history/2026-11-12/07-interfaces.md).

<a id="API-005"></a>
## API-005 — Authorized idempotent commands

**MS1 · MUST · amended**

Non-idempotent create/trigger commands require idempotency keys scoped by stable authority principal, workspace and action and bound to normalized arguments, targets and expected revisions. Retention and expiry are declared; execution and replay both recheck current authority.

- AC1: Same key/payload returns the recorded operation after current authorization checks.
- AC2: Different payload under one key returns409 idempotency_key_conflict.
- AC3: Lost-response recovery reads the operation receipt before issuing a new key; expired transport replay never promises indefinite exactly-once effects.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [API-005](history/2026-11-12/07-interfaces.md).

<a id="API-006"></a>
## API-006 — State changes are named actions

**MS1 · MUST · retained**

`PATCH` edits fields and never changes state or queue status. Each transition is its own
endpoint (`POST …/tasks/{id}/release`, `/requeue`, `/cancel`, `/hand-back/resolve`,
`/decisions/{id}/answer`, …) with its own roles and its required reason fields.

- AC1: A `PATCH` containing `state` is rejected with 422 naming the action to use.

Source: spec NOTES "API conventions".

Historical text: [API-006](history/2026-11-12/07-interfaces.md).

<a id="API-007"></a>
## API-007 — Server-assigned ids, client-supplied external ids

**MS1 · MUST · retained**

The server assigns ids and sequence numbers. A client may supply an `external_id` unique within
a project, which makes creates idempotent and lets a file be re-applied.

- AC1: Creating two tasks with the same `external_id` in one project yields one task.
- AC2: No operation requires the client to invent a primary key.

Source: spec NOTES API ambiguity 10 ("`POST` takes the whole object with a client-chosen `id`") — a gap in the frozen spec, not in the estate: Plane assigns ids and sequence numbers today, and `plane_tasks.py file` re-applies a file by task id.

Historical text: [API-007](history/2026-11-12/07-interfaces.md).

<a id="API-008"></a>
## API-008 — Authorized resumable event feeds

**MS1 · MUST · amended**

Event feeds expose durable cursor-based authorized observations with at-least-once delivery, stable event IDs, per-owner/workspace order, declared retention and filter binding. Cross-service timelines use causal links and observed times, not invented global commit order.

- AC1: Reconnect/replay can duplicate events but stable IDs permit deduplication without loss within retention.
- AC2: An expired cursor returns410 retention_gap with an authorized snapshot/resync route.
- AC3: Membership/permission revocation affects resumed and open streams within the declared bound.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [API-008](history/2026-11-12/07-interfaces.md).

<a id="API-009"></a>
## API-009 — Outbound webhooks

**MS5 · SHOULD · retained**

An operator can register webhook endpoints for event kinds. Deliveries are signed (HMAC-SHA256
over the body with a per-endpoint secret, timestamped), retried with backoff, and logged with
their outcome. Destinations are checked against private, loopback and link-local ranges unless
explicitly allowed.

- AC1: A receiver can verify signature and timestamp from the documentation alone.
- AC2: A webhook pointed at a metadata address or a cluster-internal service is refused by default.

Source: DESIGN §7 ("Webhooks/events out"); Plane benchmark (signed webhooks; nine SSRF advisories — see [12-quality-bar.md](history/2026-11-12/12-quality-bar.md)).

Historical text: [API-009](history/2026-11-12/07-interfaces.md).

<a id="API-010"></a>
## API-010 — Rate limiting

**MS8 · MUST · retained**

Requests are rate-limited per token and per session; over-limit requests get 429 with
`Retry-After`. Limits are configuration.

- AC1: Default limits never throttle the bundled console or CLI in the scenario suite.

Source: Plane benchmark (API key limit default 60/minute); conductor `causes.tick` polls each parked item at most every 30 minutes "for Plane's rate limit".

Historical text: [API-010](history/2026-11-12/07-interfaces.md).

<a id="API-011"></a>
## API-011 — Bounded responses and an explicit redaction contract

**MS1 · MUST · retained**

No endpoint returns an unbounded collection. Overview and list responses are built from field
allowlists and never include packets, prompts, check commands, free-form worker facts, tokens or
secrets. Detail endpoints that expose sensitive material (a packet, a trace) are separate
operations with their own role.

- AC1: A test enumerates every list and overview schema and asserts none references a sensitive field.
- AC2: Response size for any list call is bounded independently of history size.

Source: FACTORY-DASHBOARD-DESIGN "Decision and boundary" and "Source model and invariants"; harness-console decided D10.

Historical text: [API-011](history/2026-11-12/07-interfaces.md).

<a id="API-012"></a>
## API-012 — Unknown is not zero

**MS2 · MUST · retained**

Every aggregate carries `as_of` and a coverage state. A value whose source is unread, stale or
incomplete is `null` with a `reason`; a ratio with a zero denominator is `null` with
`no_eligible_items`, never a number.

- AC1: Shared helper and a lint: aggregate fields are typed as `value | null + reason`.
- AC2: The UI renders `unknown` for null (UI-024).

Source: FACTORY-DASHBOARD-DESIGN ("They must not be rendered as zero while unconnected"); harness-console J1; factory-measurement-contract "Sources, windows, and missingness".

Historical text: [API-012](history/2026-11-12/07-interfaces.md).

<a id="API-013"></a>
## API-013 — Stability and deprecation

**MS8 · MUST · retained**

At 1.0 the `/v1` API is frozen: only additive changes within the major. A deprecation is
announced in the changelog and by a `Deprecation` header and stays for at least two minor
releases or six months, whichever is longer. CI checks every PR for breaking changes against the
last released OpenAPI document.

- AC1: A PR that removes a field or tightens a type fails the compatibility job.
- AC2: Before 1.0, each minor's breaking changes are listed in its upgrade notes.

Source: CORPUS M6.3 ("API backward-compatibility checks against the published OpenAPI"); Plane benchmark (no written deprecation policy found in the repo).

Historical text: [API-013](history/2026-11-12/07-interfaces.md).

<a id="API-014"></a>
## API-014 — Truthful health and runtime identity

**MS1 · MUST · amended**

Liveness is process health; readiness verifies the supported Appwrite endpoint/project, authenticated runtime access, required schema/index readiness and mandatory role capabilities. Runtime identity exposes deployed source/version and implemented capability manifest without needing cluster access.

- AC1: A wrong project/session or missing required index/permission fails readiness.
- AC2: An unavailable optional connector is visible and does not masquerade as an empty successful response.
- AC3: The capability manifest belongs to the running revision, independently of planned design operations.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [API-014](history/2026-11-12/07-interfaces.md).

<a id="API-015"></a>
## API-015 — Transaction-budget-aware bulk work

**MS1 · MUST · amended**

Bulk filing reports the configured atomic limit and supports resumable import operations beyond it. The backend accounts for task, relation, receipt, audit and event writes; the advertised number of tasks is not the transaction operation budget.

- AC1: The largest supported atomic batch commits completely or rolls back.
- AC2: A request exceeding that budget is refused or explicitly converted to a resumable operation.
- AC3: Partial import progress and failures are observable in UI, REST, MCP and CLI.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [API-015](history/2026-11-12/07-interfaces.md).

<a id="API-016"></a>
## API-016 — Inbound Git host webhooks are an accelerator, not a dependency

**MS4 · SHOULD · retained**

Sortyard works by polling the Git host. If inbound webhooks are configured, they only shorten
the time to observe a fact; every fact is still confirmed by reading it. Webhook payloads are
verified by signature.

- AC1: The full scenario suite passes with webhooks disabled.
- AC2: A forged webhook changes nothing.

Source: AGENTS.md "The rule" (observed state); the estate today polls (`drive` every 3 min, `plane_sync` every 5 min) and cannot receive webhooks on a tailnet-only host.

Historical text: [API-016](history/2026-11-12/07-interfaces.md).

<a id="API-017"></a>
## API-017 — Operator requests and fenced system transitions

**MS1 · MUST · amended**

Operator-facing actions request release, repair, requeue or promotion through the public API; system-only claiming/advancement and landing execute behind controller/integrator fencing. A client cannot assert a system actor. Internal protocol endpoints, if any, are separately authenticated and excluded from operator discovery.

- AC1: A delegated operator can request every action allowed to that operator.
- AC2: A worker or forged actor header cannot claim, advance another attempt or instruct landing.
- AC3: Public tool discovery contains no callable system-only transition.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [API-017](history/2026-11-12/07-interfaces.md).

<a id="API-018"></a>
## API-018 — Scoped workspaces and collaboration profiles

**MS1 · SHOULD · amended**

Resource identities, queries, graph edges, cache keys, events and credentials include installation/workspace/project scope. Individual collaborators in one workspace ship first; independent operations/workspaces are a supported target with explicit isolation qualification, not an assumed guarantee from a field.

- AC1: Two projects in one workspace enforce membership and delegated scopes.
- AC2: A distinct workspace cannot be inferred through search, events, exports or relationships.
- AC3: An unqualified independent-workspace profile reports unavailable with its missing setup/proof rather than enabling unsafe tenancy.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [API-018](history/2026-11-12/07-interfaces.md).

<a id="MCP-001"></a>
## MCP-001 — MCP over HTTP from the API service, plus a stdio shim

**MS1 · MUST · retained**

The API service serves MCP over Streamable HTTP at `/mcp`, authenticated by the same tokens as
REST. `sortyardctl mcp` is a stdio shim for clients that only speak stdio. Both expose the same
tools.

- AC1: A remote agent with a URL and a token lists and calls tools with no local install.
- AC2: Redirects are never followed with a token attached.

Source: the prototype is stdio only (`clients/mcp_server.py`); legacy `cp_mcp.py` (HTTP, protocol versions 2025-03-26 to 2025-11-25).

Historical text: [MCP-001](history/2026-11-12/07-interfaces.md).

<a id="MCP-002"></a>
## MCP-002 — Discoverable domain tool packs

**MS1 · MUST · amended**

Role/domain tool packs keep the active tool list small; every authorized implemented operation remains discoverable through paginated generic describe/call operations. Planned, uninstalled, unavailable and forbidden operations are distinguished.

- AC1: An operator agent can discover governance and integration actions beyond the task tools.
- AC2: No generic tool bypasses action authorization or names an arbitrary backend URL.
- AC3: A missing backend capability returns a specific unavailable reason.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [MCP-002](history/2026-11-12/07-interfaces.md).

<a id="MCP-003"></a>
## MCP-003 — Full reach through three generic tools

**MS1 · MUST · retained**

Every API operation the token may call is reachable through `list_operations`,
`describe_operation` and `call_operation`. This is how "APIs for everything, for agents" holds
without hundreds of tools.

- AC1: Parity test: for each role, the operations reachable through MCP equal the role's column of the permission matrix.

Source: DESIGN §7; `clients/README.md` parity rule ("every API operation is exactly one MCP tool").

Historical text: [MCP-003](history/2026-11-12/07-interfaces.md).

<a id="MCP-004"></a>
## MCP-004 — Bounded, honest tool results

**MS1 · MUST · retained**

Tool results are capped (default 48,000 characters) with a continuation cursor, say `unknown`
where the API returned null with a reason, and carry MCP annotations (`readOnlyHint`,
`destructiveHint`, `idempotentHint`). A refusal from the API is passed back unchanged.

- AC1: A result over the cap is truncated at a record boundary and names how to continue.

Source: `cp_mcp.py` (`MAX_RESULT_CHARS` 48,000; "A source reported unknown/unavailable is unknown, not zero").

Historical text: [MCP-004](history/2026-11-12/07-interfaces.md).

<a id="MCP-005"></a>
## MCP-005 — Worker tools are the stage contract

**MS3 · MUST · retained**

A stage token can do two things: read its own packet and submit its own result. Both are
available as REST operations and as MCP tools.

- AC1: A stage token calling any other operation gets 403; calling another stage's packet gets 404.

Source: DESIGN §7 ("a build worker can read its own context packet and submit its own stage result — nothing else").

Historical text: [MCP-005](history/2026-11-12/07-interfaces.md).

<a id="CLI-001"></a>
## CLI-001 — `sortyardctl`

**MS1 · MUST · retained**

One CLI, installable with `pipx` and shipped in the image. Configuration: API URL and token from
environment, a profile file, or `--token-file`; a token is never accepted as an argument. Exit
codes: 0 success, 1 refused by the API, 2 usage, 3 unreachable.

- AC1: `sortyardctl --help` works offline and lists every command.
- AC2: The process list never shows a token.

Source: `clients/README.md` (`SORTYARD_API_URL`, `SORTYARD_TOKEN`, exit codes).

Historical text: [CLI-001](history/2026-11-12/07-interfaces.md).

<a id="CLI-002"></a>
## CLI-002 — Commands for the things people and agents actually do

**MS1 · MUST · retained**

Task-level commands with readable output and `--json`: `task file|add|get|list|edit|move|note`,
`pickup status`, `queue`, `why`, `requeue`, `cancel`, `job run`, `decision list|answer`,
`needs list|discharge`, `lanes get|set`, `pause`, `resume`, `apply`, `export`, `audit`,
`health`, `backup`. Commands arrive with the capability they operate.

- AC1: Each command maps to exactly one documented sequence of API calls.
- AC2: Human output and `--json` output are both covered by snapshot tests.

Source: driver §4 "Tools", §7 "Common operations".

Historical text: [CLI-002](history/2026-11-12/07-interfaces.md).

<a id="CLI-003"></a>
## CLI-003 — Every API operation is reachable

**MS1 · MUST · retained**

`sortyardctl api <operationId> [--param k=v] [--body JSON|@file|-]` calls any operation. A parity
test fails if an operation has no CLI path.

- AC1: Unknown operations or arguments send nothing.

Source: `clients/README.md` parity rule; DESIGN §7 ("everything the CLI does is an API call (no back doors)").

Historical text: [CLI-003](history/2026-11-12/07-interfaces.md).

<a id="CLI-004"></a>
## CLI-004 — Dry run

**MS2 · SHOULD · retained**

Mutating task-level commands accept `--dry-run` and print what would change, using the server's
own evaluation.

- AC1: `task file --dry-run` returns the verdict each task would get and writes nothing.

Source: `drive.py --dry-run`, `plane_sync.py --dry-run`.

Historical text: [CLI-004](history/2026-11-12/07-interfaces.md).

<a id="CLI-005"></a>
## CLI-005 — Parity with the legacy operator tools

**MS2 · MUST · retained**

Each legacy tool has a documented equivalent: `add_item.py` → `task add --release`;
`add_item.py --job` → `job run`; `requeue.py` → `requeue`; `plane_tasks.py file` → `task file`;
`pickup_status.py` → `pickup status` (same verdicts and exit codes); `file_verify.py` → the
verdict returned by `task file`; `queue_audit.py` → `queue audit`; `repos_check.py` → `apply
--validate`; `preflight` → `task preflight`.

- AC1: The migration guide has this table and each row has a test.
- AC2: Coverage of the legacy operations inventory (BL-20: the tools above, the legacy console's journeys and the steering done on the Plane board), as the share with a documented and tested Sortyard equivalent. Target: 100% by the MS5 gate. Floor: 100% of the operations the usage census (MIG-017) shows in use, before the first cutover.

Source: driver §4 "Tools"; conductor README (tool descriptions).

Historical text: [CLI-005](history/2026-11-12/07-interfaces.md).

<a id="IAM-001"></a>
## IAM-001 — Appwrite-backed first-run administrator binding

**MS1 · MUST · amended**

Bootstrap binds a verified Appwrite user to the first installation admin using a one-time, expiring setup grant. It creates no separate password database, default password or shared admin token.

- AC1: A setup grant cannot be reused or applied by an unverified identity.
- AC2: Later administrators are granted through explicit authorized membership/domain actions.
- AC3: Setup status identifies missing substrate configuration without exposing secrets.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [IAM-001](history/2026-11-12/07-interfaces.md).

<a id="IAM-002"></a>
## IAM-002 — Appwrite human identity and sessions

**MS1 · MUST · amended**

Use the supported self-hosted Appwrite Account/session/JWT and Teams capabilities selected in SY-DEC-004. Resolve users by issuer/project/user ID. Alternative providers flow through supported Appwrite identity; no new local password store or trusted raw proxy identity is required.

- AC1: Invalid/expired sessions and forged identity headers are refused.
- AC2: Pending invitations grant no project access.
- AC3: Cloud OAuth-server/installation features are not advertised without a verified supported installation.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [IAM-002](history/2026-11-12/07-interfaces.md).

<a id="IAM-003"></a>
## IAM-003 — Session and request hardening

**MS1 · MUST · retained**

Cookie sessions are `HttpOnly`, `Secure`, `SameSite=Lax`, with CSRF protection; mutations require
a same-origin request with a JSON body. Token-authenticated requests need no CSRF. The console
ships a strict Content-Security-Policy.

- AC1: A cross-site form post to any mutation is rejected.
- AC2: A security-headers test runs against every route.

Source: harness-console VISION ("mutation routes accept any same-network POST"), decided D2.

Historical text: [IAM-003](history/2026-11-12/07-interfaces.md).

<a id="IAM-004"></a>
## IAM-004 — Scoped human roles and explicit delegation

**MS1 · MUST · amended**

Viewer, operator and admin apply only within granted workspace/project/installation scope and registered service capabilities. An Appwrite Team owner is not installation-admin; no human grant implicitly confers system-executor identity, backend root credentials or another application authority.

- AC1: The published permission matrix distinguishes membership, domain actions and system-only execution.
- AC2: Project-admin cannot grant workspace/installation rights or another project scope.
- AC3: Delegated rights intersect the live human grant and resource policy.

Source: PERMISSIONS.md; DESIGN §3.9.

Historical text: [IAM-004](history/2026-11-12/07-interfaces.md).

<a id="IAM-005"></a>
## IAM-005 — Service accounts and tokens

**MS1 · MUST · retained**

A service account has a role and a scope. Tokens are shown once, stored hashed, expire (default
90 days), can be revoked, and record last use. Issuing, rotating and revoking are audited.

- AC1: A database dump contains no usable token.
- AC2: An expiring token is flagged in the token list ahead of expiry (default 14 days) and, from MS5, raises an attention item (OBS-014).

Source: `identity/README.md` (scopes issued and revoked as data, every mutation audited); the owner's GitHub token expiry is tracked by hand today (driver §5).

Historical text: [IAM-005](history/2026-11-12/07-interfaces.md).

<a id="IAM-006"></a>
## IAM-006 — Purpose-bound accounts and operator delegation

**MS1 · MUST · amended**

Separate autonomous intake/grooming/sensor/worker service accounts from agents delegated by an operator. Delegated agents can use the operator action surface under the intersection of issuer authority, resource policy and explicit scope/action/expiry restrictions.

- AC1: A delegated operator may create tasks and propose permitted policy changes through their normal gates.
- AC2: A narrow worker cannot introduce arbitrary work, impersonate a system actor or self-widen its grant.
- AC3: Issuer removal, expiry or revocation invalidates delegated rights within the declared bound.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [IAM-006](history/2026-11-12/07-interfaces.md).

<a id="IAM-007"></a>
## IAM-007 — Stage tokens

**MS3 · MUST · retained**

The controller mints one token per stage attempt, confined to that attempt and its chain epoch,
expiring at the stage deadline plus a margin, and revoked when the stage ends.

- AC1: A stage token used after its stage ended is refused.

Source: `identity/README.md` ("a build-worker token, confined to one `stage_run_id`").

Historical text: [IAM-007](history/2026-11-12/07-interfaces.md).

<a id="IAM-008"></a>
## IAM-008 — Independent execution gates without disabling operator agency

**MS1 · MUST · amended**

No model-driven principal may self-claim work, become the controller/integrator or bypass independent execution/release gates. Operator delegation preserves actions that the human may legitimately perform, including task creation and allowed governance changes; sensitive authorization changes retain their own authority requirements.

- AC1: Across simultaneous grants a worker cannot accumulate forbidden create-plus-claim or system authority.
- AC2: The same authorized operator action has the same outcome through UI and delegated-agent transport.
- AC3: A policy edit does not give the editing agent direct claim/landing authority.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [IAM-008](history/2026-11-12/07-interfaces.md).

<a id="IAM-009"></a>
## IAM-009 — Authorisation is central, default-deny and object-scoped

**MS1 · MUST · retained**

One authorisation function decides every request from the operation's declared roles and the
caller's bindings. An operation with no declared role is unreachable. Object access is scoped in
the data-access layer: every query is constrained by the caller's workspace and project scope,
so an id from another scope behaves as not found.

- AC1: No handler contains its own role check (lint).
- AC2: A request for an object outside the caller's scope returns 404, never 403 with details and never the object.

Source: Plane benchmark — 57 of 89 published advisories are authorisation flaws (CWE-639, 862, 284, 863); see [12-quality-bar.md](history/2026-11-12/12-quality-bar.md).

Historical text: [IAM-009](history/2026-11-12/07-interfaces.md).

<a id="IAM-010"></a>
## IAM-010 — The authorisation matrix is tested cell by cell

**MS1 · MUST · retained**

For every operation × role there is an automated test asserting allow or deny, generated from
the matrix; and for every operation that takes an object id, a test that an id from another
project and another workspace is refused.

- AC1: Adding an operation without declaring its roles fails CI.
- AC2: The generated suite runs on every PR in under two minutes.

Source: `test_openapi.py` already checks the matrix document against the spec; this extends the check to the running service.

Historical text: [IAM-010](history/2026-11-12/07-interfaces.md).

<a id="IAM-011"></a>
## IAM-011 — Audit log

**MS1 · MUST · retained**

Every mutation records actor, time, target, before and after (redacted), request id, client and
result, in an append-only store. A refused request is logged separately from mutations. The
audit trail of an object is visible on that object.

- AC1: The append-only guarantee is enforced by the database (update, delete and truncate refused), as in the existing migration.
- AC2: The time from a mutating UI action to its entry in the entity's audit trail. Target: 1 s. Floor: 5 s.

Source: harness-console J5 ("an audit entry (actor, time, target, result) is visible on the entity"); migration `0001` (refuse triggers).

Historical text: [IAM-011](history/2026-11-12/07-interfaces.md).

<a id="IAM-012"></a>
## IAM-012 — Standing delegation and exact optional approvals

**MS1 · SHOULD · amended**

Standing delegation allows routine authorized actions without per-action human confirmation. Where policy requires approval, it binds the normalized plan hash, target revision, authority and expiry; edits invalidate approval. Proposer, authority principal, executor and approver are separately audited. A required approval is a Decision with decision_kind=action_plan_approval and immutable plan binding. decision.answer approves or rejects that exact plan through the public action contract; preparing an edit supersedes the prior plan and invalidates its approval. Approval Decisions inherit the plan workspace and optional project scope; a workspace action needs no invented project and cannot be approved by a project-only grant.

- AC1: An agent action within standing scope executes without an invented extra approval.
- AC2: A changed/stale plan cannot reuse an approval.
- AC3: Silence or an expired decision cannot grant credential, public, spending or irreversible authority.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [IAM-012](history/2026-11-12/07-interfaces.md).

<a id="UI-001"></a>
## UI-001 — The console is a client of the public API

**MS2 · MUST · retained**

A single-page app served as static files by the API service. It uses only public API operations
and the event stream. There is no console-only endpoint.

- AC1: A test serves the console against a mock built from the OpenAPI document alone and every route renders.
- AC2: A lint forbids request paths outside the generated API client.

Source: DESIGN §6 rule; SY-DEC-001 (Vite SPA, static files served by the API service).

Historical text: [UI-001](history/2026-11-12/08-console.md).

<a id="UI-002"></a>
## UI-002 — UI-for-everything is measured

**MS2 · MUST · retained**

Operations are annotated `operator-facing` in the OpenAPI document. A coverage manifest maps
each to the route and control that invokes it. CI fails when an operator-facing operation has no
UI path, unless it carries a dated exemption.

- AC1: Coverage of operator-facing operations by a console control, from the manifest check. Target: 100% at every merge to `main`, with no exemption. Floor: 100% at each milestone exit for the operations introduced in that milestone or earlier.
- AC2: The manifest is published as a docs page ("where is X in the UI").

Source: Joe's objective ("there is a UI for everything"); CORPUS M5.6 defers every write surface to Phase 5 — see CF-03.

Historical text: [UI-002](history/2026-11-12/08-console.md).

<a id="UI-003"></a>
## UI-003 — Board and list

**MS1 · MUST · retained**

The board shows tasks in columns by state; the list shows them in rows. Both support filters
(TRK-014), reordering of top-level tasks by drag or keyboard (TRK-007), and inline display of
park and hand-back reasons. Dragging changes rank only; state and priority are changed from the
item.

- AC1: Every drag has a keyboard equivalent and an undo.
- AC2: The time from a drag to every open board and list showing the new order, without a reload. Target: 1 s. Floor: 5 s.

Source: DESIGN §6 view 1 ("Dragging is defined, not magic"); task-ready ("To reorder delivery, drag top-level tasks on the board").

Historical text: [UI-003](history/2026-11-12/08-console.md).

<a id="UI-004"></a>
## UI-004 — Task detail is one timeline

**MS2 · MUST · retained**

One page per task: fields and spec, relations, the filing verdict and reasons, and one ordered
timeline of notes, state changes, decisions and — from MS3 — the chain: stages with attempts,
durations and outcomes, the change request, checks, review verdicts, usage. There is no separate
"pipeline" record to click through to.

- AC1: From a task, the stage outcome that explains its current state is on the same page (zero navigation).
- AC2: Every timeline entry has a stable deep link.
- AC3: Demonstration (benchmark, MS3) — from a task, a scripted operator finds the stage outcome that explains its current state, on Sortyard and on the legacy pair. Target: zero navigation, shown within 1 s of opening the task. Floor: fewer steps than the legacy route across two tools (BL-18).

Source: DESIGN §6.0 ("A task's detail *is* its chain"); Joe 2026-11-06 (the dashboard "connects tickets with the pipeline").

Historical text: [UI-004](history/2026-11-12/08-console.md).

<a id="UI-005"></a>
## UI-005 — Creating and editing tasks

**MS1 · MUST · retained**

A form for the tracker fields and the typed spec with inline readiness feedback, a raw YAML view
of the same spec, and paste-or-upload of a task file with a per-task verdict preview before
filing.

- AC1: Form and YAML views round-trip without loss.
- AC2: Readiness errors appear as the user types, from the server's evaluation.

Source: task-ready "The task item"; `plane_tasks.py file`.

Historical text: [UI-005](history/2026-11-12/08-console.md).

<a id="UI-006"></a>
## UI-006 — Pickup Preview and "why"

**MS2 · MUST · retained**

Per project: the queue in claim order, slot holders with phase and age, the reason code for
every task not claimable now, and the next-N simulation. On every task detail page: a "why is
this not running" panel with the same reasons and the tasks ranked ahead.

- AC1: Each reason code links to its documentation and, where an operator can fix it, to the control that does.
- AC2: The view states the evaluation time and the policy versions it used.

Source: task-pickup §7 (the "Where a reader sees it" column); HARNESS-251, HARNESS-256.

Historical text: [UI-006](history/2026-11-12/08-console.md).

<a id="UI-007"></a>
## UI-007 — Owner list and decision inbox

**MS2 · MUST · retained**

One view of everything waiting on a person, grouped by route: decisions with their default and
time left, escalated premise-class decisions, needs routed to the viewer's route, items escalated
to a person. Decisions are answered here.

- AC1: Answering a decision records the chosen value and the route that will apply it.
- AC2: A decision past its date that took its default shows as such, not as open.

Source: driver §6 (the owner "answers `decision` items; defaults apply on their date"); conductor README (depends-on-Joe list, `needs-human`, `route:owner`).

Historical text: [UI-007](history/2026-11-12/08-console.md).

<a id="UI-008"></a>
## UI-008 — Lanes and tuning

**MS2 · MUST · retained**

Edit lanes per project, pause and resume, admission caps and the scheduling policy values, with
the current value, the default, who last changed it and when. Saving shows the diff and its
effect on the Pickup Preview before it applies.

- AC1: A lane change needs no deploy and no file edit.
- AC2: Every value shows the legacy constant it replaces where there is one (DEF-005).

Source: driver §1 (knobs in `repos.yaml`, hardcoded copies in three files); DESIGN §5.3.

Historical text: [UI-008](history/2026-11-12/08-console.md).

<a id="UI-009"></a>
## UI-009 — Overview: glance at the floor

**MS2 · MUST · retained**

The landing page: health state and what drives it; per project running, waiting, parked and
handed-back counts with oldest ages; slots and heavy-cap use; recent merges; the attention list.
It updates live.

- AC1: A source that is unknown or stale renders `unknown`, never 0.
- AC2: Every number links to the list that produces it.
- AC3: Render time of the Overview on the reference fixture. Target: 500 ms. Floor: 2 s, the legacy console's bar for the same journey.

Source: harness-console J1; FACTORY-DASHBOARD-DESIGN "Screen and feedback loop".

Historical text: [UI-009](history/2026-11-12/08-console.md).

<a id="UI-010"></a>
## UI-010 — Chains and actions

**MS2 · MUST · retained**

For a chain: the stage timeline with attempts, durations, the reason a stage is waiting or
failed, and the binding. Actions — requeue, cancel, stop, resume — are offered only where the
API says they are legal, behind a dialog that states the effect; the result and its audit entry
appear inline.

- AC1: An action the API would refuse is not offered.
- AC2: A run detail page never returns an error for an existing run; ids are unique.

Source: harness-console J3, J5; VISION ("run detail currently 502s").

Historical text: [UI-010](history/2026-11-12/08-console.md).

<a id="UI-011"></a>
## UI-011 — Logs and traces

**MS2 · MUST · retained**

A stage's log and, where captured, its agent trace: live tail with follow mode, virtualised for
multi-megabyte content, searchable, with deep-linkable lines. The basic log view ships in MS3;
search, trace filtering and deep links are complete by MS6 .

- AC1: Opening a 5 MB log or trace. Target: first lines within 300 ms and no frame over 50 ms while scrolling. Floor: no frame over 200 ms (frame budget asserted in the e2e test).

Source: harness-console J3; DESIGN §6 view 4.

Historical text: [UI-011](history/2026-11-12/08-console.md).

<a id="UI-012"></a>
## UI-012 — Credentials

**MS4 · MUST · retained**

Accounts and keys with health, expiry and last use; add and re-authenticate through a stepper
that survives refresh and navigation, shows progress on slow steps, retries transient errors and
can be cancelled. Values are never shown and never entered except through the provider's own
flow or a paste-once field.

- AC1: Viewing the page triggers no paid probe.
- AC2: A stuck flow can be cancelled for any provider.

Source: harness-console J4; console routes `credentials`, components `add-account`, `sign-in`.

Historical text: [UI-012](history/2026-11-12/08-console.md).

<a id="UI-013"></a>
## UI-013 — Parked and self-heal queues

**MS2 · MUST · retained**

Lists of parked and handed-back work with reason, blocking cause, age and what would bring each
back; the resolution actions of the self-heal contract (REC-009).

- AC1: Items older than the self-heal drain limit (default 24 h) are marked and match the `SELF-HEAL-STALLED` condition's list.

Source: conductor README "Self-heal drain", "Blocking causes".

Historical text: [UI-013](history/2026-11-12/08-console.md).

<a id="UI-014"></a>
## UI-014 — Health

**MS2 · MUST · retained**

Mechanisms with cadence, window, last success and last error; credential quotas with burn rate;
open conditions. The page shows the four-state health (REC-019) and exactly which entries cause
it.

- AC1: A silent mechanism is findable from the Overview in two clicks.

Source: MECHANISMS.md; `GET /api/mh/factory/mechanisms`.

Historical text: [UI-014](history/2026-11-12/08-console.md).

<a id="UI-015"></a>
## UI-015 — Evidence-backed ecosystem dashboards

**MS2 · MUST · amended**

Project and portfolio dashboards derive throughput, blockers, delivery, cost, policy, membership and integration health from authorized records with observed_at, coverage and evidence links. Appwrite is the native substrate; optional external observability is not required for core dashboards.

- AC1: Unknown/partial source coverage is shown rather than counted as zero.
- AC2: A person and delegated agent receive the same metric definition and accessible source references.
- AC3: A dashboard value can be reproduced from its retained input/version window.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [UI-015](history/2026-11-12/08-console.md).

<a id="UI-016"></a>
## UI-016 — Decision log and audit explorers

**MS2 · MUST · retained**

Search scheduling decisions by task, reason code, time and policy version, and open one
evaluation to see its inputs; browse the audit log by actor, object and time. A basic version
ships in MS2; saved searches and replay of an evaluation are complete by MS6.

- AC1: "Why was X not claimed at T" is answerable from the UI without the CLI.

Source: DESIGN §6 (DecisionLog explorer); harness-console `audit-trail` component.

Historical text: [UI-016](history/2026-11-12/08-console.md).

<a id="UI-017"></a>
## UI-017 — Administration

**MS2 · MUST · retained**

Users, role bindings, service accounts and tokens; projects and repositories with an onboarding
wizard; system information (version, schema, image digest). Integrations, definitions and backup
controls join as their capabilities land; the page is complete at MS6 .

- AC1: A new project can be created and its first task filed without leaving the UI.

Source: DESIGN §6 view 12; onboarding.md (today: edit `repos.yaml`, push, wait for the onboarding check).

Historical text: [UI-017](history/2026-11-12/08-console.md).

<a id="UI-018"></a>
## UI-018 — Performance budgets

**MS1 · MUST · retained**

The console keeps a normalised local store fed by the event stream, applies an operator's change
optimistically and reconciles with the server's answer, so that no action waits for a round trip
before it shows. Initial JavaScript is budgeted and enforced in CI. Grids are virtualised (about
50 rows mounted) and scroll 10,000 fixture rows smoothly. Lists use server cursors. Route code
is lazy-loaded and the next likely route is preloaded.

- AC1: Initial JavaScript, gzipped, enforced by the budget check. Target: 200 KB. Floor: 350 KB, the legacy console's budget.
- AC2: An e2e test asserts the mounted-row bound on a 10,000-row fixture.
- AC3: Interaction latency on the reference workload, from an input (click, key, end of a drag) to its visible result and from a route change to its content. Target: p95 at most 100 ms for an input and 200 ms for a route change. Floor: p95 at most 1 s, and no journey slower than on the legacy console (BL-18).
- AC4: First load on a cold cache, to interactive, on the reference connection. Target: 1 s. Floor: 2 s.
- AC5: An optimistic change that the server refuses is rolled back visibly, with the reason.

Source: `console/check_budget.py` (`BUDGET_BYTES = 350 * 1024`); harness-console J2; decided D4. The local store and optimistic updates are a design change made on 2026-11-12 to reach the latency target (inference: a round trip for every action cannot meet it).

Historical text: [UI-018](history/2026-11-12/08-console.md).

<a id="UI-019"></a>
## UI-019 — Accessibility

**MS1 · MUST · retained**

Target WCAG 2.2 AA. CI runs an automated accessibility scan on every route with zero serious or
critical violations, and every journey test is also run keyboard-only. Focus is managed on route
change and in dialogs; live updates are announced politely.

- AC1: The accessibility and keyboard specs are required checks.
- AC2: Colour is never the only carrier of state.

Source: harness-console journeys preamble ("keyboard-only, with zero serious/critical axe violations"); `console/e2e/tests/a11y.spec.ts`, `keyboard.spec.ts`; components `route-focus`, `announce`.

Historical text: [UI-019](history/2026-11-12/08-console.md).

<a id="UI-020"></a>
## UI-020 — Responsive

**MS1 · MUST · retained**

Every journey passes at 390, 834 and 1440 pixels wide.

- AC1: The e2e matrix runs the journeys at the three widths.

Source: harness-console journeys preamble; VISION ("on a laptop or a phone").

Historical text: [UI-020](history/2026-11-12/08-console.md).

<a id="UI-021"></a>
## UI-021 — Live without reload

**MS2 · MUST · retained**

Views update from the event stream, falling back to polling. A stale or disconnected view says
so.

- AC1: Killing the stream connection shows a "reconnecting" state and recovers without a reload.

Source: harness-console J1; decided D5; console `lib/live.ts`.

Historical text: [UI-021](history/2026-11-12/08-console.md).

<a id="UI-022"></a>
## UI-022 — Command palette

**MS2 · SHOULD · retained**

A keyboard palette jumps to any task, chain or run by id or text and runs common actions.

- AC1: Typing `ROVE-12` and Enter opens that task from any page.

Source: harness-console J2 ("⌘K palette jumps to any request/chain/run by id"); console `command-palette` component.

Historical text: [UI-022](history/2026-11-12/08-console.md).

<a id="UI-023"></a>
## UI-023 — Design tokens and brand

**MS1 · SHOULD · retained**

One token set (colour, type, spacing) with light and dark themes, using the Sortyard brand kit.

- AC1: No component hard-codes a colour.

Source: meta-harness `projects/sortyard/branding/`; harness-console decided D3.

Historical text: [UI-023](history/2026-11-12/08-console.md).

<a id="UI-024"></a>
## UI-024 — Empty, error and unknown states are designed

**MS1 · MUST · retained**

Every view has a designed state for: nothing yet, loading, failed to load, and value unknown.
An absent value is never rendered as zero, a blank or a spinner that never ends.

- AC1: Storybook (or equivalent) has a story per state per view, and the e2e suite visits the failed and unknown states.

Source: AGENTS.md "Testing model" (one story per machine state; every gate defines its absent state); harness-console J1.

Historical text: [UI-024](history/2026-11-12/08-console.md).

<a id="UI-025"></a>
## UI-025 — Strings are externalised; English only

**MS1 · MUST · retained**

All user-visible strings go through a message catalogue with locale-aware dates and numbers.
1.0 ships English only and documents how a locale is added.

- AC1: A lint fails on a hard-coded user-visible string in a component.
- AC2: A pseudo-locale build renders every route without clipped or missing text.

Source: Plane benchmark (22 locales, an i18n sync check in CI); see [12-quality-bar.md](history/2026-11-12/12-quality-bar.md) for the stance.

Historical text: [UI-025](history/2026-11-12/08-console.md).

<a id="UI-026"></a>
## UI-026 — Embedded concierge

**MS2 · SHOULD · retained**

The console keeps the embedded concierge of the existing console: ask a question, get an answer
grounded in live state with citations, and approve proposed actions (IAM-012). It is a client of
the operator-agent tools (MCP-002) with the signed-in operator's permissions, it has no private
endpoint, and it is off until a model credential is configured for it. Its ambient half, the
attention list, ships in MS5 (OBS-014).

- AC1: The legacy concierge journeys (J6, and the second concierge journey of J12) pass against Sortyard.
- AC2: Every statement the concierge makes about state cites the record it came from; text from tasks, logs and traces is treated as data, never as instructions.
- AC3: With no model credential the entry point says how to enable it, and nothing else in the console changes.
- AC4: Time to the first token of an answer on the reference workload. Target: 1 s. Floor: no slower than the legacy concierge (BL-18).

Source: harness-console J6–J8, decided D7–D9, D14–D15; console `components/concierge/*`, `concierge.py`; e2e `j6-concierge`, `j12-concierge-2`. Cut reversed on 2026-11-12: the feature is built and shipped in the legacy console, and no measured case showed that removing it is better; how much it is used is counted by the census (MIG-017). Owner decision OD-3.

Historical text: [UI-026](history/2026-11-12/08-console.md).

<a id="OBS-001"></a>
## OBS-001 — Atomic owner ledger and causal ecosystem timeline

**MS1 · MUST · amended**

Sortyard domain state, append-only audit/event, receipts and outbox commit atomically. Durable order is scoped to its authoritative owner/workspace; cross-service events retain source cursor/sequence, correlation and causal references. Realtime arrival order is not global commit order.

- AC1: The actual runtime writer cannot update/delete history through direct/transaction/upsert/bulk or table-security changes.
- AC2: Identical event identity/content replays once; conflicting content refuses.
- AC3: Authorized replay preserves late-visible events or explicitly reports a retention/resync gap.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [OBS-001](history/2026-11-12/09-observability.md).

<a id="OBS-002"></a>
## OBS-002 — History of any object

**MS1 · MUST · retained**

For any object the API returns its events in order, with who, when, before and after.

- AC1: The current state of a task equals the fold of its events (replay test).

Source: `sortyard.object_history(kind, id)`; harness-console J5.

Historical text: [OBS-002](history/2026-11-12/09-observability.md).

<a id="OBS-003"></a>
## OBS-003 — Read models are projections and say so

**MS2 · MUST · retained**

Aggregates (queue census, throughput windows, dashboards) are computed from the ledger and
state tables, are recomputable at will, store nothing authoritative, and are labelled with
`as_of`. A read model never feeds a scheduling decision.

- AC1: Dropping and rebuilding every read model changes no API result other than `as_of`.
- AC2: A read endpoint causes no write, no Job and no outbound call.

Source: FACTORY-DASHBOARD-DESIGN ("The read model is a projection of source records, never a second authority"; "No request body, database write, Job creation, or trace span is caused by these reads").

Historical text: [OBS-003](history/2026-11-12/09-observability.md).

<a id="OBS-004"></a>
## OBS-004 — The metric catalogue

**MS6 · MUST · retained**

Sortyard ships one catalogue in which each metric has an id, an exact definition (numerator,
denominator, clock, window, cohort), a unit and its coverage rule. The v1 catalogue:

| Id | Definition |
|---|---|
| `queue.actionable` | Eligible tasks and admissible stages now, by project and state. Age runs from the release or queued transition to first schedule; open waits use `as_of`. |
| `stage.pickup_latency` | For stages first scheduled in the window: `first_scheduled − eligible_since`, where `eligible_since` is the later of the queued transition and the predecessor's pass. Dependency wait is reported separately and is never called a scheduler delay. |
| `stage.execution` | For attempts terminal in the window: scheduled→running, running→collecting, collecting→terminal. Missing endpoints are counted, not dropped. |
| `chain.outcomes` | Chains that reached a terminal outcome in the window, once each, by outcome (done, parked, handed-back, cancelled), with shares. |
| `chain.cycle_time` | For chains done in the window: done − claimed. Open chains are shown by current age, not included in percentiles. |
| `task.lead_time` | For tasks done in the window: done − created; and time in each board state. |
| `merges` | Change requests merged into a default branch in the window, by host merge time, unique by repo and number. |
| `merge.open_to_first_green` / `merge.green_to_merge` / `merge.open_to_merge` | From the change request's history and its required check runs. |
| `review.rounds` | Reviews with a verdict per task; share of tasks at or over the tripwire. |
| `fix.rounds`, `conflict.rounds` | Per task and per window. |
| `lanes.utilisation` | Slot-seconds held ÷ slot-seconds available, by project; same for each heavy cap. |
| `handback.count`, `park.count` | By reason and blocking-cause kind. |
| `cost.agent_minutes_per_merge` | Agent wall time of every finished stage for a project (builds, reviews, fix rounds, triage, failures) ÷ changes merged in its repos, same window. |
| `cost.stages_per_merge`, `cost.tokens_per_merge` | Same cohort; tokens where recorded. |
| `main.health` | Per repo: latest completed required run on the default branch, its conclusion, and the age of the last success. |
| `chain.control_wait` | For chains terminal in the window: the sum of the gaps between an enabling event and the action it enables (stage finished → next dispatched, checks green → merge armed, verdict → next round, merge observed → Done). Excludes time in agents, CI, reviews and waiting for a slot (FLW-019). |
| `stall.episodes` | Episodes in the window in which a chain passed a phase bound or a stage made no progress: count, share recovered with no person, time to detection, time to recovery (REC-026). |
| `operator.interventions` | Mutations by a person on work in flight (requeue, cancel, force, manual state change, resolving a hand-back), for each week and for each 100 merged tasks; owner-list answers are counted separately (REC-024). |
| `upgrade.impact` | For each upgrade: failed API requests, missed events, time without a leader, stages failed or retried because of it (DEP-010). |

- AC1: Each metric has a fixture with a hand-computed expected value.
- AC2: A metric whose source is incomplete returns `null` with a reason (API-012).
- AC3: Percentiles use nearest-rank and state `n`.
- AC4: The four comparison metrics (`chain.control_wait`, `stall.episodes`, `operator.interventions`, `upgrade.impact`) have one definition each, shared by the tests that record them from MS3 on and by the catalogue, so a demonstration and a dashboard cannot disagree.

Source: factory-measurement-contract "Metric definitions"; `metrics/analyze.py` (merged per day, open→first green, last green→merge, open→merge, review rounds, auto-merge use); conductor README `cost_item`.

Historical text: [OBS-004](history/2026-11-12/09-observability.md).

<a id="OBS-005"></a>
## OBS-005 — Throughput windows

**MS6 · MUST · retained**

Catalogue metrics are available per hour, day and week, by project, lane and workflow. Windows
describe the past and gate nothing.

- AC1: Window boundaries are half-open and in UTC; a record is counted in exactly one window.

Source: DESIGN §3.8 ThroughputWindow; Joe 2026-11-05 (time survives only as looking back at throughput).

Historical text: [OBS-005](history/2026-11-12/09-observability.md).

<a id="OBS-006"></a>
## OBS-006 — Delivery cost

**MS6 · MUST · retained**

For each project and window: agent-minutes per merged change and stages per merged change,
computed from recorded stage usage. Stages whose usage is unreadable are named, not guessed.

- AC1: The published number and the list of excluded stages always appear together.
- AC2: Demonstration (ledger, MS7) — agent-minutes and stages for each merged change over the pilot's window, from the ledger, against the same project's legacy figure. Target: no agent-minute is spent on a stage that could not succeed (missing base, unregistered target, unreadable input), and the figure is available for any window and project within 1 s. Floor: cost for each merged change no higher than the legacy baseline, and the figure kept as a series for any past window, which the legacy item cannot give (BL-16).

Source: driver §3 "Delivery cost" (k3s-harness #186: "Unreadable requests are named, not guessed").

Historical text: [OBS-006](history/2026-11-12/09-observability.md).

<a id="OBS-007"></a>
## OBS-007 — Wait versus work

**MS6 · MUST · retained**

For any chain and any window the time is decomposed into: waiting on dependencies, waiting for a
slot, waiting for admission, executing, waiting on CI, waiting on review, waiting on a person.

- AC1: The components sum to the cycle time within one second.
- AC2: Each component maps to reason codes (SCH-009), so the dashboard and the Pickup Preview agree.

Source: factory-measurement-contract ("Stage timing waterfall and wait-vs-execution decomposition"); FACTORY-STAGE-ATTEMPTS-DESIGN.

Historical text: [OBS-007](history/2026-11-12/09-observability.md).

<a id="OBS-008"></a>
## OBS-008 — Queue census

**MS3 · MUST · retained**

A cheap, bounded endpoint returns current counts: eligible, held by reason, claimed by phase,
stages queued, running and collecting, slots and caps in use. Downstream stages of an open chain
are future work, not queue depth.

- AC1: The census never counts a stage under a terminal chain as runnable.

Source: `GET /api/mh/queue-census`; FACTORY-DASHBOARD-DESIGN (`eligible_queued_stages` rule).

Historical text: [OBS-008](history/2026-11-12/09-observability.md).

<a id="OBS-009"></a>
## OBS-009 — Daily record

**MS6 · SHOULD · retained**

One generated record per day and project: what merged, what did not and why, what is parked or
handed back, incidents on main, quarantined jobs, cost. Generated from the ledger; nobody writes
it by hand.

- AC1: The record for a past day is reproducible byte for byte.
- AC2: Demonstration (ledger, MS6) — the daily record is generated twice for 14 past days of the reference workload. Target: byte-identical on every re-run, ready within 60 s of the day's end, with zero model calls. Floor: every figure of the legacy report is present and reproducible, and no agent run is spent writing it (BL-27).

Source: DESIGN §6 view 13 ("no hand-written status ever again"); JOB-QUARANTINE.md (`ledger/pipeline-daily/YYYY-MM-DD.md`).

Historical text: [OBS-009](history/2026-11-12/09-observability.md).

<a id="OBS-010"></a>
## OBS-010 — System metrics endpoint

**MS3 · MUST · retained**

Each component serves Prometheus metrics: reconcile duration and lag, claim latency, queue
depth, Job counts by phase, API latency and error rate, database pool use, mirror age, ledger
append rate.

- AC1: The metric names and labels are documented and covered by a snapshot test.
- AC2: Scraping needs no credential beyond network reach, or a token when configured.

Source: inference — the legacy system exposes `/api/health` and OTLP only; the standard for Kubernetes installs is a scrape endpoint.

Historical text: [OBS-010](history/2026-11-12/09-observability.md).

<a id="OBS-011"></a>
## OBS-011 — Structured logs with correlation ids

**MS1 · MUST · retained**

Logs are JSON lines with level, component, request id and — where they apply — project, task,
chain, stage and attempt.

- AC1: One `grep` by a correlation id — request or task id in MS1, chain id from MS3 — across component logs yields the whole story.
- AC2: Error output from child processes is captured, not discarded.

Source: 2026-11-12 release stall ("stderr is discarded, so it was reproduced with a server-side dry run").

Historical text: [OBS-011](history/2026-11-12/09-observability.md).

<a id="OBS-012"></a>
## OBS-012 — OpenTelemetry export

**MS6 · SHOULD · retained**

Optional export of lifecycle spans over OTLP, with W3C trace context carried from task to chain
to stage. Export uses an outbox with a bounded backlog; drops are counted and reported. The
ledger stays the record: telemetry never overwrites state.

- AC1: With the collector down, nothing blocks and the gap is visible in health.

Source: `mh.py` trace outbox (notes: trim pending over 5,000, prune delivered after 7 days); OTLP-TRACE-DESIGN; factory-measurement-contract ("Never overwrite authoritative business state with telemetry").

Historical text: [OBS-012](history/2026-11-12/09-observability.md).

<a id="OBS-013"></a>
## OBS-013 — Notifications

**MS5 · MUST · retained**

Routing rules send events to channels (webhook, Slack-compatible webhook, email). Shipped
defaults notify a person only for owner-list items (REC-024) and for a factory-down state with
nothing acting on it. Everything else goes to the pipeline: a task, a condition, a queue.
Notifications are de-duplicated per condition and their delivery is logged.

- AC1: A red main with an active triage chain sends no notification.
- AC2: A notification that could not be delivered is itself a condition after its retry budget.

Source: driver §6 ("Findings go to the pipeline, not to the owner … The stall watch stays quiet about a red that has an active conductor item"); DV40-ALERT-READBACK-DESIGN.

Historical text: [OBS-013](history/2026-11-12/09-observability.md).

<a id="OBS-014"></a>
## OBS-014 — Attention list

**MS5 · MUST · retained**

A computed list of what needs a look now: chains past their phase bound, credentials expiring or
quarantined, red main with nothing acting, silent mechanisms, low quota, open conditions. Each
entry carries its evidence links. An entry can be dismissed with a reason and restored.

- AC1: The list is the same through API, MCP (`get_attention`) and UI.
- AC2: Dismissal is audited and expires when the underlying condition changes.

Source: harness-console J8; API.md "Needs-attention insights (HC-14)"; console calls `/api/insights`, `/dismiss`, `/restore`.

Historical text: [OBS-014](history/2026-11-12/09-observability.md).

<a id="OBS-015"></a>
## OBS-015 — No phone-home

**MS1 · MUST · retained**

Sortyard sends nothing to its authors or any third party. There is no usage telemetry in 1.0;
any later telemetry is opt-in and documented field by field.

- AC1: A network-policy test runs the full scenario suite with egress limited to the configured Git host and model provider.

Source: Plane benchmark (instance telemetry defaults to enabled).

Historical text: [OBS-015](history/2026-11-12/09-observability.md).

<a id="OBS-016"></a>
## OBS-016 — Retention

**MS6 · MUST · retained**

Retention is configuration with documented defaults: ledger events (keep), traces and stage
logs (90 days), run directories (REC-022), webhook delivery logs (30 days). Expiry is a
registered mechanism.

- AC1: Expired blobs are removed and their references say "expired", not "missing".

Source: `mh.py` retention (notes); DESIGN §3.6 `retention` policy kind (parameters left open in the frozen schema).

Historical text: [OBS-016](history/2026-11-12/09-observability.md).

<a id="OBS-017"></a>
## OBS-017 — Main-branch release health

**MS5 · SHOULD · retained**

Per repo: the latest completed required run on the default branch and the age of the last
success. A failing required run is a factory-down signal until a later success; an owner-accepted
hold changes its disposition, not its colour.

- AC1: Green change-request checks never dilute this state.

Source: factory-measurement-contract "Mainline release health".

Historical text: [OBS-017](history/2026-11-12/09-observability.md).

<a id="OBS-018"></a>
## OBS-018 — Improvement ledger

**LATER · LATER · retained**

A record for each tuning intervention with hypothesis, pre and post cohort values and a verdict
(`improved`, `regressed`, `inconclusive`, `not_live`). Deferred past 1.0 on the evidence that
the estate's ledger of this kind is not in regular use; the cut is conditional on the usage
census (MIG-017), and the scorecard (QLT-051) already records before and after values for every
measured criterion.

- AC1: Until it ships, the audit of policy changes (SCH-011) plus the windowed metrics give the raw material.

Source: factory-measurement-contract "Sense → respond → improve loop".

Historical text: [OBS-018](history/2026-11-12/09-observability.md).

<a id="DEF-001"></a>
## DEF-001 — Versioned meta-harness resources

**MS2 · MUST · amended**

Archetypes, workflows, workflow roles/personas, skills, context recipes, quality bars, eval packs, integration definitions and policy references are first-class versioned resources. Immutable content/version is separate from mutable assignments and activation; newest published content is not automatically active.

- AC1: Publishing identical content is idempotent; a published version cannot change.
- AC2: A project pins and explicitly adopts an archetype/skill/workflow version.
- AC3: Candidate policy/definition publication alone does not activate it.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEF-001](history/2026-11-12/10-platform.md).

<a id="DEF-002"></a>
## DEF-002 — One owner and one write route per resource family

**MS1 · MUST · amended**

Each family has a registered authoritative owner and epoch. Sortyard owns its native domain; existing policy service, Git definitions and partner product records remain authoritative until an explicit family handover. Appwrite materializations are labelled read projections when the owner is external.

- AC1: Editing a projection uses the owner command or is refused.
- AC2: Source hashes/versions and observation freshness remain visible.
- AC3: No successful command is inferred from a local projection update.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEF-002](history/2026-11-12/10-platform.md).

<a id="DEF-003"></a>
## DEF-003 — Git-managed definitions with an API proposal path

**MS2 · MUST · amended**

A definition assignment may be source-locked to a reviewed Git ref. Both UI and delegated agents can propose a managed change through the same API; ordinary review/CI/GitOps publishes it. A read-only materialization does not eliminate the operator command surface.

- AC1: Source-lock refuses direct version/activation mutation.
- AC2: A proposal links its task/change request and eventual published version.
- AC3: A failed pull preserves the last accepted version and reports freshness.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEF-003](history/2026-11-12/10-platform.md).

<a id="DEF-004"></a>
## DEF-004 — Pinned execution context and explicit live policy resolution

**MS2 · MUST · amended**

A binding pins workflow, role/persona, skill and context-packet versions. Each runtime policy decision records the exact effective policy family/variant/version, snapshot, reason and fallback used at that decision point. Updating a definition does not silently rewrite an active stage packet.

- AC1: A recipe/skill edit leaves an existing packet hash unchanged.
- AC2: A later policy decision identifies its actual policy versions.
- AC3: Explicit emergency revocation is governed and audited separately.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEF-004](history/2026-11-12/10-platform.md).

<a id="DEF-005"></a>
## DEF-005 — Policy consumers and declared defaults

**MS2 · MUST · amended**

Tunables are registered decision points with documented defaults, owner source/version, scope resolution and consumer support. The legacy constant inventory is a migration input to re-observe; it is not evidence that every old literal is the current policy.

- AC1: A policy with no supported consumer is visibly ineffective at that decision point.
- AC2: Conflicting equal-rank variants return a named conflict rather than an arbitrary winner.
- AC3: Missing source uses only the declared absent-state rule and records its fallback.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEF-005](history/2026-11-12/10-platform.md).

<a id="DEF-006"></a>
## DEF-006 — Definitions are validated when applied

**MS3 · MUST · retained**

`apply` validates schema and meaning and refuses with a message naming the definition and the
rule: an unbounded phase (REC-001), a gate with no absent-state (FLW-009), a stage that breaks
pipeline purity (FLW-001), a reference to a missing template or profile, a threshold outside its
allowed range.

- AC1: `apply --validate` runs the same checks without writing and is usable in CI.
- AC2: A partially valid bundle applies nothing.

Source: meta-harness tradition of script refusals (DESIGN §3.6 "prose rule → script refusal"); `repos_check.py`.

Historical text: [DEF-006](history/2026-11-12/10-platform.md).

<a id="DEF-007"></a>
## DEF-007 — See the effect before saving

**MS2 · SHOULD · retained**

Changing a policy, lane or project setting shows a diff and a what-if: how the Pickup Preview
would differ.

- AC1: The what-if uses the scheduler's own evaluator with the proposed values.

Source: DESIGN §6 view 7 (simulate); UI-008.

Historical text: [DEF-007](history/2026-11-12/10-platform.md).

<a id="DEF-008"></a>
## DEF-008 — A default bundle ships with every release

**MS3 · MUST · retained**

Each release carries a default bundle: the `change` and `job` workflows, their packet templates,
the review checklists, harness profiles for the shipped harnesses, and default policies. A fresh
install applies it. On upgrade, changed defaults are offered as a diff the operator accepts; an
installation's edits are never overwritten. An installation may layer its own bundle on top; the
estate's does, and keeps the legacy settings that are not defaults for strangers (MIG-010).

- AC1: A fresh install can run the demo with no definition authored by the user.
- AC2: An upgrade never changes behaviour by silently replacing a definition the operator edited.

Source: `definitions/seed/` (9 workflows, 4 roles, 2 archetypes, 4 context recipes, 8 lanes, 10 policies — to be re-cut to the kinds in DEF-001); CORPUS M1.2.

Historical text: [DEF-008](history/2026-11-12/10-platform.md).

<a id="DEF-009"></a>
## DEF-009 — Onboarding a project is one object and one check

**MS4 · MUST · retained**

A project is onboarded by creating it with its repositories, lanes, build and release switches.
An onboarding check then verifies and reports: the landing credential can push; auto-merge is
allowed; at least one required check exists (or the plain-git adapter is chosen); the mirror is
created. Claims start only when the check passes.

- AC1: A project whose check fails shows exactly which item failed and stays unbuilt.
- AC2: Onboarding needs no edit to any file outside Sortyard.

Source: onboarding.md (one `repos.yaml` entry; the onboarding check; "GitHub requirements per repo"); SY-DEC-003 (registration sequence: build registry first, driver last).

Historical text: [DEF-009](history/2026-11-12/10-platform.md).

<a id="EXT-001"></a>
## EXT-001 — Versioned extension registry with isolated execution

**MS2 · MUST · amended**

Skills, archetype/workflow/eval packs, sensors and API integrations have registry entries, compatibility/capability metadata, owners and per-project assignments. Extensions execute through versioned definitions, isolated containers or governed HTTP adapters; they do not load arbitrary code inside the control plane.

- AC1: A compatible skill pack can be registered and assigned without a control-plane image change.
- AC2: Missing tools, credentials or compatibility block binding with a named reason.
- AC3: Installation cannot silently widen a project/worker grant.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [EXT-001](history/2026-11-12/10-platform.md).

<a id="EXT-002"></a>
## EXT-002 — Worker image contract and conformance kit

**MS8 · MUST · retained**

The stage contract (EXE-006) is published with a conformance kit: a container that plays the
controller's side against a candidate worker image and reports pass or fail per clause. The
shipped harness images pass it in CI.

- AC1: A third party can build a harness image and verify it with one command and no Sortyard install.

Source: CORPUS M5.7 (conformance test kit); EXE-012.

Historical text: [EXT-002](history/2026-11-12/10-platform.md).

<a id="EXT-003"></a>
## EXT-003 — Git host adapters

**MS3 · MUST · retained**

Everything Sortyard needs from a Git host is one interface: fetch, push a branch, open or update
a change request, read its state and checks, arm and disarm auto-merge, comment, read protection
rules, mint a read-only token. 1.0 ships `plain-git` and `github`.

- AC1: The scenario suite is written against the interface and runs on both a fake and `plain-git`.
- AC2: A capability an adapter lacks is declared, and dependent features say so (plain-git has no hosted checks, so CIH features are inactive).

Source: DESIGN §5.2 ("GitHub Issues and Linear … integrations, never dependencies"); AGENTS.md "pipeline purity".

Historical text: [EXT-003](history/2026-11-12/10-platform.md).

<a id="EXT-004"></a>
## EXT-004 — Sensors are scheduled jobs that call the API

**MS5 · SHOULD · retained**

A sensor is a container run on a schedule by the same Job machinery as stages, in its own lane
outside the delivery pipeline, with a sensor token. It files findings and heartbeats through the
API. Sensors may reach live systems; delivery stages may not.

- AC1: A sensor's schedule is a registered mechanism with a freshness window (REC-017).
- AC2: A finding is de-duplicated by a stable key: repeats update its last-seen time.

Source: DESIGN §3.7 (Sensor), §1.4; factory-measurement-contract ("repeat sweeps update age instead of duplicating incidents").

Historical text: [EXT-004](history/2026-11-12/10-platform.md).

<a id="EXT-005"></a>
## EXT-005 — Bundles from a repository at a pinned ref

**MS8 · SHOULD · retained**

`apply` accepts a Git URL and a commit or tag; the bundle's source and content hash are recorded
on every version it creates.

- AC1: An unpinned ref (a branch name) is refused unless explicitly allowed.

Source: DESIGN §3.7 (registry "git-backed in v1"); CORPUS M3.2.

Historical text: [EXT-005](history/2026-11-12/10-platform.md).

<a id="EXT-006"></a>
## EXT-006 — Tracker import adapters

**MS2 · MUST · retained**

Importing from an external tracker is an interface with one shipped implementation (Plane):
list projects, items, relations, states, order and comments read-only.

- AC1: The adapter holds a read-only credential and issues only read requests (asserted by the HTTP fake).

Source: `src/sortyard/shadow/sources.py` (GET only; refuses redirects that would carry the key elsewhere); MIG-003.

Historical text: [EXT-006](history/2026-11-12/10-platform.md).

<a id="EXT-007"></a>
## EXT-007 — Contracts are versioned

**MS8 · MUST · retained**

The stage contract, the adapter interfaces and the bundle format carry versions. A release
states which versions it supports; a contract version is supported for at least two minor
releases after its successor ships.

- AC1: A worker image built for the previous contract version still runs on the current release.

Source: DESIGN §11.2 ("an API-stability/versioning commitment").

Historical text: [EXT-007](history/2026-11-12/10-platform.md).

<a id="DEP-001"></a>
## DEP-001 — Small control plane on the existing substrate

**MS1 · MUST · amended**

A Helm package installs API/UI, controller and fenced integrator as needed plus ephemeral worker Jobs. Appwrite is an explicit existing/separately operated substrate prerequisite. The migration source Postgres remains only until accepted migration; the package does not silently install another Appwrite estate.

- AC1: Rendered target architecture includes no default second application SQL database.
- AC2: Each workload has a clear privilege boundary.
- AC3: Current Postgres chart behavior is labelled implementation baseline until the adapter ships.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEP-001](history/2026-11-12/10-platform.md).

<a id="DEP-002"></a>
## DEP-002 — Installable by a namespace admin

**MS1 · MUST · retained**

The chart needs no CustomResourceDefinitions and no cluster-scoped objects by default. Optional
cluster-scoped extras (a PriorityClass, a second namespace for workers) are flags, each
documented with what is lost without it.

- AC1: `helm install` succeeds with a ServiceAccount that has admin on one namespace only.
- AC2: From MS3, when the controller ships: its Role is limited to Jobs, Pods, Pods/log, ConfigMaps and Secrets in the worker namespace.
- AC3: Demonstration (drill, MS3) — a release that adds a workload and a permission is installed by upgrade with a namespace-admin account, on a fresh install and on an upgraded one. Target: one `helm upgrade`, zero objects applied by hand, the controller's Role rendered by the chart. Floor: no release needs an object applied by hand; the legacy release of 2026-11-12 did (BL-11).

Source: 2026-11-12 release stall (a new CronJob could not be applied because a hand-maintained Role did not name it); `k8s/mh-rbac.yaml`.

Historical text: [DEP-002](history/2026-11-12/10-platform.md).

<a id="DEP-003"></a>
## DEP-003 — Appwrite application state and private artifacts

**MS1 · MUST · amended**

Use Appwrite native rows/transactions for Sortyard-owned state, ledger, receipts and outbox and private Storage for large content. External product data remains with its owner. Blob upload is verified before database metadata publication and reconciled on interruption.

- AC1: State/event/receipt/outbox commit together within the supported transaction budget.
- AC2: A failed upload or metadata commit never advertises an incomplete artifact as ready.
- AC3: Partner-store unavailability does not cause an independent writable copy.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEP-003](history/2026-11-12/10-platform.md).

<a id="DEP-004"></a>
## DEP-004 — Supported self-hosted Appwrite profile

**MS0 · MUST · amended**

The default profile targets the verified self-hosted Appwrite version/capabilities and compatible SDK. Setup explicitly provisions a dedicated logical project and least-privilege schema/runtime identities through the estate custody route. Hybrid SQL requires a demonstrated unsupported invariant.

- AC1: Qualification checks server/SDK compatibility and configured transaction limits.
- AC2: Runtime lacks schema/admin and broad resource-bypass API keys.
- AC3: A distinct installation cannot read another application project.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEP-004](history/2026-11-12/10-platform.md).

<a id="DEP-005"></a>
## DEP-005 — Install time

**MS1 · MUST · retained**

From a clean cluster with the prerequisites present, one command installs a running Sortyard and
prints its address and the setup token; one more runs the demo. Both paths are scripted and
timed in CI on every release candidate, using published artefacts only.

- AC1: Install to first task filed, on the reference runner and a kind cluster. Target: one command and 3 minutes. Floor: 8 commands and 15 minutes, with no step that requires editing a file.
- AC2: Install to the demo chain finished. Target: one more command and 5 minutes more. Floor: 30 minutes in total.
- AC3: The CI job fails when a floor is missed and writes the measured times to the scorecard (QLT-051).
- AC4: The comparison with the estate is recorded once: what a second installation of the legacy system needs (BL-13) beside the measured install.

Source: DESIGN §1.9 ("`helm install` it on a fresh cluster in an afternoon") — tightened; DESIGN §0 (standing the legacy system up elsewhere means about six repositories, a jump box and a private network); goldfish GF1-05 (no prerequisite check, no one-command replica).

Historical text: [DEP-005](history/2026-11-12/10-platform.md).

<a id="DEP-006"></a>
## DEP-006 — Explicit substrate and connector setup

**MS1 · MUST · amended**

Configuration names the Appwrite endpoint/logical project, supported version, custody references, required indexed schema, canonical origins and registered connectors. Setup identifies missing capabilities; no secret values enter ordinary config objects or public health.

- AC1: A missing project/grant/index is actionable rather than an empty successful install.
- AC2: A small core install needs no Ranker/Closer/Walwarden deployment to run unrelated work.
- AC3: Values are schema-checked and provider credentials stay in their existing custody.

Source: `charts/sortyard/values.yaml`; Plane benchmark (58 variables in the self-host env file).

Historical text: [DEP-006](history/2026-11-12/10-platform.md).

<a id="DEP-007"></a>
## DEP-007 — Versioned Appwrite schema evolution

**MS1 · MUST · amended**

Provision indexed columns, permissions and schema versions with supported Appwrite APIs. Released data mappings are immutable; changes follow compatible expansion then contraction. Index readiness is part of readiness. The old SQL migrations remain accurate only for the retained source store.

- AC1: Previous and next application readers work during an additive change.
- AC2: A newer unsupported schema or missing index fails readiness.
- AC3: Migration interruption resumes from durable checkpoints without changing published historical content.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEP-007](history/2026-11-12/10-platform.md).

<a id="DEP-008"></a>
## DEP-008 — Upgrade guarantees

**MS8 · MUST · retained**

From 1.0: any 1.x upgrades directly to any later 1.y; this is tested in CI from the last patch
of every earlier minor, with data. Rolling back the application by one minor without restoring
the database is supported. Before 1.0: each 0.x upgrades from 0.(x−1), tested, with any
exception in the upgrade notes.

- AC1: The upgrade matrix job seeds data with the old version, upgrades, and runs the new version's scenario suite.
- AC2: Every release has upgrade notes even when they say "nothing to do".

Source: CORPUS M6.3; Plane benchmark (an upgrade option in `setup.sh` and a one-off `migration-0.13-0.14.sh`; no stated guarantee found in the repo).

Historical text: [DEP-008](history/2026-11-12/10-platform.md).

<a id="DEP-009"></a>
## DEP-009 — Work in flight survives upgrades and restarts

**MS3 · MUST · retained**

Upgrading or restarting the control plane does not fail running stages. Jobs keep running;
their results are accepted afterwards; chains resume. The stage contract of the previous minor
is accepted by the current one.

- AC1: Demonstration (chaos, MS3) — the control plane is upgraded and restarted eleven times in a day during 20 running chains. Target: zero stages failed or retried because of an upgrade, and zero results lost. Floor: no extra attempt caused by an upgrade; on such a day the legacy system failed reviews and grooming (BL-25).

Source: conductor README "API rollouts" (strategy Recreate leaves 30–40 s with nothing listening; 11 rollouts in a day failed reviews and grooming).

Historical text: [DEP-009](history/2026-11-12/10-platform.md).

<a id="DEP-010"></a>
## DEP-010 — Upgrades without downtime

**MS3 · MUST · retained**

An upgrade is a rolling replacement with a surge: the new API pod is ready before the old one
stops, connections drain, and event-stream clients resume from their last event id. This must
hold with the default volume-backed blob store on `ReadWriteOnce` storage as well as with S3.
The controller and the integrator hand leadership over on shutdown instead of letting a lease
lapse (REC-014). It holds with one replica of each as well as with two, so the smallest
installation upgrades without a gap in the API.

- AC1: Demonstration (chaos, MS3) — a continuous read and write probe and an event-stream client run during 20 upgrades, with one replica and with two. Target: zero failed requests, zero missed events and at most 15 s without a leader. Floor: failed requests for at most 5 s in an upgrade and no event missed after reconnecting; the legacy rollout has nothing listening for 30 to 40 seconds (BL-25).
- AC2: No control-plane workload uses the `Recreate` strategy by default; the chart test checks the rendered strategies.
- AC3: Each upgrade records its own impact (`upgrade.impact`, OBS-004).

Source: `k8s/deployment.yaml` (`replicas: 1`, `strategy: Recreate` because of a single-writer SQLite database).

Historical text: [DEP-010](history/2026-11-12/10-platform.md).

<a id="DEP-011"></a>
## DEP-011 — Provider-native recovery with domain verification

**MS6 · MUST · amended**

Use supported substrate backup/export/recovery mechanisms and retained application metadata rather than a custom release controller. A disposable replica recovery verifies identities, relationships, ledger replay and artifact hashes. Provision/release mechanics remain platform-native.

- AC1: Recovered state preserves scoped identities, pinned versions and history.
- AC2: The recovery point and pending external effects are explicit.
- AC3: No restore or credential operation occurs as a side effect of a read.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEP-011](history/2026-11-12/10-platform.md).

<a id="DEP-012"></a>
## DEP-012 — Data custody survives application removal

**MS1 · MUST · amended**

Uninstalling Sortyard control-plane workloads does not delete the shared Appwrite service, other projects or retained migration source data. Destructive cleanup is a separately authorized operation with named scope.

- AC1: Uninstall leaves substrate/project data in its documented custody.
- AC2: No wildcard delete spans application projects.
- AC3: The same operation scope is visible to UI and delegated agents.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEP-012](history/2026-11-12/10-platform.md).

<a id="DEP-013"></a>
## DEP-013 — Measure application and substrate footprint separately

**MS1 · SHOULD · amended**

Sizing reports the Sortyard control-plane requests and the separately operated shared Appwrite dependency. Published installation claims include required substrate setup; existing Appwrite capacity is not presented as no dependency or free resources.

- AC1: The chart and setup report name both application and required substrate components.
- AC2: A reference replica records resource usage and configuration.
- AC3: Optional plugins do not become mandatory core dependencies.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [DEP-013](history/2026-11-12/10-platform.md).

<a id="DEP-014"></a>
## DEP-014 — Pod security and network policy

**MS1 · MUST · retained**

Every Sortyard pod runs as non-root with a read-only root filesystem, no added capabilities and
the default seccomp profile, and passes the Kubernetes `restricted` pod security standard — the
only exception being the opt-in container sidecar (EXE-016). The chart ships NetworkPolicies:
the API is reachable only from the ingress and Sortyard's own pods; workers reach only what
EXE-005 lists.

- AC1: The chart test validates manifests against the `restricted` standard.
- AC2: A pod in another namespace cannot reach the API port when policies are enforced.

Source: `Dockerfile` (`USER 10001`); `k8s/networkpolicy.yaml` (`control-plane-ingress-node-only`); HC02-BACKEND-LOCKDOWN-DESIGN; Plane benchmark (no `USER` directive in its API, web and live Dockerfiles).

Historical text: [DEP-014](history/2026-11-12/10-platform.md).

<a id="DEP-015"></a>
## DEP-015 — Air-gapped install

**MS8 · SHOULD · retained**

The control plane needs no outbound network at runtime beyond the configured Git host and model
provider. The release lists every image by digest; worker images can have agent CLIs baked in so
that nothing is downloaded at stage start.

- AC1: The install test passes with a registry mirror and no other egress.

Source: DESIGN §4 ("Air-gapped-ish install possible"); `mh.py` worker init container installs CLIs from npm at start (notes).

Historical text: [DEP-015](history/2026-11-12/10-platform.md).

<a id="DEP-016"></a>
## DEP-016 — GitOps-friendly

**MS3 · MUST · retained**

The chart renders deterministically, keeps generated secrets stable across upgrades, and works
under Argo CD and Flux, including its migration hook.

- AC1: `helm template` twice gives identical output; an Argo CD sync of the chart in CI ends Healthy and Synced.

Source: DESIGN §4 ("GitOps-friendly"); `postgres-secret.yaml` (password kept across upgrades).

Historical text: [DEP-016](history/2026-11-12/10-platform.md).

<a id="DEP-017"></a>
## DEP-017 — Supported Kubernetes versions

**MS8 · MUST · retained**

Each release states the Kubernetes minors it supports (the current and two previous at release
time) and CI runs the install and demo on each, on kind and on k3s.

- AC1: The matrix is in the release notes and the CI configuration.

Source: the estate runs k3s; the quickstart uses kind.

Historical text: [DEP-017](history/2026-11-12/10-platform.md).

<a id="DEP-018"></a>
## DEP-018 — One-command local replica

**MS0 · MUST · retained**

One command on a machine with Docker checks prerequisites and their versions, creates a local
cluster, builds and loads the image, installs the chart in the deployment's own shape, and
prints how to reach it. The same environment runs the scenario suite.

- AC1: A zero-context agent goes from a fresh clone to a passing `verify` with two commands.
- AC2: The replica uses the scripted harness and the plain-git adapter; it needs no account anywhere.

Source: goldfish GF1-05; CORPUS M1.1; AGENTS.md "Local-first delivery" (the local replica is the deployment shape); SORTYARD-13 (open).

Historical text: [DEP-018](history/2026-11-12/10-platform.md).

<a id="DEP-019"></a>
## DEP-019 — Multi-architecture images

**MS8 · SHOULD · retained**

Images are published for `amd64` and `arm64`.

- AC1: The demo passes on an arm64 kind cluster in CI.

Source: inference (contributors on Apple-silicon laptops).

Historical text: [DEP-019](history/2026-11-12/10-platform.md).

<a id="DEP-020"></a>
## DEP-020 — A release has one identity

**MS1 · MUST · retained**

Chart version, image tag and application version are tied; the image is referenced by digest in
the rendered manifests of a release; `/v1/info` and the console footer show version, commit and
digest.

- AC1: The quickstart never asks the reader to build an image or match a tag by hand.
- AC2: Demonstration (count, MS1) — the steps to learn what is running and to install an exact release are counted. Target: one call returns version, commit and digest, and one command installs a release by version with no build. Floor: fewer steps than reading the legacy annotation with cluster access, and no size cap on shipped code (BL-28).

Source: README quickstart (build locally, "the tag must match `appVersion`"); goldfish "Not verified: whether the image is published"; k3s driver (digest annotations on the deployment).

Historical text: [DEP-020](history/2026-11-12/10-platform.md).

<a id="DEP-021"></a>
## DEP-021 — Sizing guidance

**MS8 · SHOULD · retained**

The docs give cap and envelope defaults by node size, with the reasoning, starting from the
estate's experience.

- AC1: The guidance includes a worked example for the estate's node size (D16s_v6).

Source: DESIGN §3.7b (proof-class sizing on D8s_v6 versus D16s_v6); driver §5.

Historical text: [DEP-021](history/2026-11-12/10-platform.md).

<a id="MIG-001"></a>
## MIG-001 — Freeze the legacy evidence now

**MS0 · MUST · retained**

Before any legacy component changes because of Sortyard: capture the control-plane ledger, the
scorecard battery corpus and baselines, and a Plane export; hash them; publish the manifest
digest.

- AC1: `legacy_evidence.py verify` passes on the snapshot, and its digest is recorded on the tracking item.
- AC2: This is the first item worked in MS0.

Source: `legacy-evidence/README.md`; CORPUS M1.15 ("the only corpus item that becomes impossible later"). Status 2026-11-12: the tool is merged (SORTYARD-11 Done) but no snapshot exists; the capture items SORTYARD-70 and SORTYARD-71 are still Todo.

Historical text: [MIG-001](history/2026-11-12/10-platform.md).

<a id="MIG-002"></a>
## MIG-002 — Record the legacy conductor's inputs, pass by pass

**MS0 · MUST · retained**

The legacy conductor's per-pass inputs (board view, project configuration, gating output) and
its claims are retained with the legacy revision that produced them, as a replay corpus.

- AC1: At least 7 consecutive days are retained before MS2's comparison, and retention continues until the last cutover.
- AC2: Each recorded pass names the legacy bundle digest it ran on.

Source: README "Shadow conductor" (pass feed; "A pass with no retained inputs can only be read live while it is the newest"); CORPUS R5 (the baseline moves); SORTYARD-79 (still Todo).

Historical text: [MIG-002](history/2026-11-12/10-platform.md).

<a id="MIG-003"></a>
## MIG-003 — Plane importer

**MS2 · MUST · retained**

Import one Plane project into a Sortyard project: tasks with their spec blocks parsed into typed
fields, parents, blocked-by relations, states, manual order, priorities, due dates, notes, and
the control labels mapped to typed fields (TRK-009). A dry run prints an object-class difference
report and changes nothing.

- AC1: For each driven board, the dry-run report shows zero unmapped control labels and zero dropped relations.
- AC2: The eligible set and its order after import equal the legacy conductor's for the same instant (checked by MIG-005).
- AC3: Importing twice is idempotent.

Source: 2026-11-08 release note (the registers→Plane import: counts per board, 252 relations, order could not be set through Plane's API); conductor README "Plane tasks".

Historical text: [MIG-003](history/2026-11-12/10-platform.md).

<a id="MIG-004"></a>
## MIG-004 — Read-only mirror mode

**MS2 · MUST · retained**

A Sortyard project can mirror an external board continuously and read-only. Mirrored projects
run the scheduler in observe mode only (SCH-013) and are labelled as mirrors everywhere.

- AC1: A mirrored project cannot be switched to active without the cutover action (MIG-007).
- AC2: Sortyard issues no write to the mirrored tracker.

Source: README "Shadow conductor" ("It never claims, merges, comments or writes anywhere but its own database").

Historical text: [MIG-004](history/2026-11-12/10-platform.md).

<a id="MIG-005"></a>
## MIG-005 — Replay comparison

**MS2 · MUST · retained**

Run Sortyard's real evaluator over the recorded legacy passes (MIG-002) and compare claim
decisions. Every divergence is stored and classified: input difference, policy mismatch,
implementation defect, side effect the replay cannot know, or unclassified with the reason.

- AC1: Replay over at least 2,000 recorded passes, with every divergence classified and no open implementation defect: the share of passes whose claim decisions agree. Target: 100%. Floor: at least 99%.
- AC2: The comparison is a repeatable offline job (minutes, not weeks) and runs in CI on a fixed sample.

Source: `claim-comparison/README.md` (pairing, classification); DESIGN §8 Phase 1; CF-13 for replacing the live soak.

Historical text: [MIG-005](history/2026-11-12/10-platform.md).

<a id="MIG-006"></a>
## MIG-006 — Migration code stays out of the core

**MS0 · MUST · retained**

Everything specific to the legacy estate (the Plane/`products.json`/gating adapters, the
comparator, the evidence tool, the cutover kit) lives under a `migration/` tree with its own
tests and is not imported by the `sortyard` package. The core has no NonceLogic project names,
hosts or file formats.

- AC1: An import-graph test fails if `sortyard.*` imports from `migration.*`.
- AC2: A grep gate fails on estate-specific names (`noncelogic`, internal hostnames, `products.json`) in `src/`, `charts/` and the public docs. `migration/` is exempt; `docs/requirements/` is exempt until the publication step in [README.md](README.md) ("Before this directory is public").

Source: `src/sortyard/shadow/` and `charts/…/shadow-conductor.yaml` are in the core today; DESIGN §1.9 ("no NonceLogic-specific assumptions in the core"); goldfish GF1-04 (internal hosts in the README).

Historical text: [MIG-006](history/2026-11-12/10-platform.md).

<a id="MIG-007"></a>
## MIG-007 — Cutover kit

**MS7 · MUST · retained**

One scripted procedure per project: dry-run report; freeze the legacy side (build off);
snapshot; import; verify counts, order and eligible set; switch the Sortyard project to active;
hypercare window; verdict. Each step is recorded and resumable.

- AC1: The kit is first executed end to end in the replica against a copy of the project.
- AC2: Running a step twice is safe.
- AC3: The kit carries the settings the legacy configuration implies for the project — lanes, build and release switches, the container sidecar where it is used today, the estate bundle's packs — and lists them in the dry-run report.

Source: CORPUS M4.1; SY-DEC-003 (the proven registration sequence).

Historical text: [MIG-007](history/2026-11-12/10-platform.md).

<a id="MIG-008"></a>
## MIG-008 — One authority at a time

**MS7 · MUST · retained**

For any project at any moment exactly one system claims work. The kit refuses to activate a
Sortyard project while the legacy driver still has build on for it, and refuses to re-enable the
legacy driver while Sortyard is active.

- AC1: An attempt to activate with the legacy side still on fails with the evidence.

Source: driver §6 ("Nothing else should build or merge for a project that has `build` on"); in-flight-steering.

Historical text: [MIG-008](history/2026-11-12/10-platform.md).

<a id="MIG-009"></a>
## MIG-009 — Hypercare and rollback

**MS7 · MUST · retained**

Each cutover has a hypercare window (default 7 days; 14 for the pilot) with a written verdict:
claims correct, landings fenced, hand-backs owned, and every divergence the project relies on at
or above its floor (QLT-050). Until the verdict, rollback is possible: stop Sortyard for the
project, write what changed since the cutover (states, order, relations, notes) back to the
legacy board from a rollback export, using the cutover kit and not Sortyard itself, and
re-enable the legacy driver. After the verdict the legacy side for that project is switched off,
not kept as a fallback.

- AC1: The rollback path is rehearsed once in the replica before the pilot.
- AC2: A verdict lists every operator intervention during the window.
- AC3: Demonstration (drill, MS7) — in the replica a project is cut over, worked through a day of recorded activity and rolled back, timing from the decision to the legacy driver claiming again. Target: within 5 minutes, with zero tasks lost, duplicated or claimed by both systems. Floor: within 30 minutes with the same zero, and with no sync component running during hypercare; a projection would keep a second copy of every task, and second copies have drifted (BL-24).

Source: CORPUS M3.14, M4.5–M4.7; the estate's standing rule that legacy paths are shut down or cut over, never kept as a fallback.

Historical text: [MIG-009](history/2026-11-12/10-platform.md).

<a id="MIG-010"></a>
## MIG-010 — Rule conformance ledger

**MS7 · MUST · retained**

Every enforceable rule of the legacy system is mapped to a requirement in this specification, a
policy key, a policy pack, or a recorded retirement with its reason.
[16-legacy-parity.md](history/2026-11-12/16-legacy-parity.md) is the seed; it is completed against `AGENTS.md`, the
templates and the skills before the first product cutover.

- AC1: No row is left "unmapped" at the pilot's verdict.
- AC2: Before each cutover, every KEEP and FIX row the project relies on has a passing parity scenario (REC-025) or a dated waiver by the owner.
- AC3: The estate bundle exists in the estate's Git source before the pilot: its definitions, the packs it switches on, and the legacy value of every policy key except those a divergence entry changes ([18-divergences.md](history/2026-11-12/18-divergences.md)). Applying it to a default install reproduces the settings that [16-legacy-parity.md](history/2026-11-12/16-legacy-parity.md) and DEF-005 record, checked by a parity scenario.

Source: CORPUS M5.1, M5.5 ("each prose rule either becomes a Policy or is consciously retired").

Historical text: [MIG-010](history/2026-11-12/10-platform.md).

<a id="MIG-011"></a>
## MIG-011 — Capability-by-capability retirement

**MS7 · MUST · amended**

Retire a legacy writer/mechanism only after its named replacement and dependency consumers pass parity/cutover acceptance. Previously retired mechanisms are recorded as such, not recreated. Meta-harness remains commit-forward for unmigrated definitions/records; other products keep their owned processes.

- AC1: Each retirement names replacement or explicit owner disposition.
- AC2: No remaining source family is archived because a different family migrated.
- AC3: Consumers cannot continue writing an old owner epoch after handover.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [MIG-011](history/2026-11-12/10-platform.md).

<a id="MIG-012"></a>
## MIG-012 — Estate mechanism observers

**MS7 · MUST · retained**

The estate mechanisms the legacy check watches beyond the pipeline (CronJobs and resources on
three clusters, scheduled CI workflows, host timers) keep being watched: through external
heartbeats (REC-018) and an optional observer integration for cluster objects and CI schedules.

- AC1: Before the legacy mechanism check is switched off, every entry of `mechanisms.yaml` is either registered in Sortyard or recorded as out of scope with an owner.

Source: `mechanisms.yaml` (68 entries across HARNESS, DEVOPS, ROVE, CPV2, LOOP boards).

Historical text: [MIG-012](history/2026-11-12/10-platform.md).

<a id="MIG-013"></a>
## MIG-013 — The experiment rig gets an explicit fate

**MS7 · MUST · retained**

The experiment rig that shares the legacy control plane (corpus, treatments, compare and eval
views, the scorecard battery) is inventoried and kept as its own deployment, outside Sortyard,
when the legacy control plane is retired. It is archived instead only by a recorded decision,
and only if the usage census (MIG-017) shows no use in its window. It is not carried into
Sortyard.

- AC1: The decision record exists before the legacy control plane is removed.

Source: CORPUS M4.4; harness-console decided D11 (experiment views moved under "Lab").

Historical text: [MIG-013](history/2026-11-12/10-platform.md).

<a id="MIG-014"></a>
## MIG-014 — Historical evidence remains navigable

**MS7 · LATER · amended**

Preserve legacy evidence with provenance and access controls. Link or import it through typed external references/projections; dashboards distinguish missing coverage, historical source and native records. Do not drop historical explainability merely because the storage backend changed.

- AC1: A pre-cutover record resolves to its preserved source or an explicit gap.
- AC2: Imported evidence preserves source IDs/hashes and observation time.
- AC3: Private history is not exposed through graph/search imports.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [MIG-014](history/2026-11-12/10-platform.md).

<a id="MIG-015"></a>
## MIG-015 — Close out the Phase 1 prototypes

**MS0 · MUST · retained**

Each Phase 1 deliverable that was merged into meta-harness instead of the product repository is
either ported into `sortyard/sortyard` with its tests or recorded as retired: the identity matrix
(`identity/`), the generated clients (`clients/`), the definitions loader and seed
(`definitions/`), the claim comparator (`claim-comparison/`), the evidence tool
(`legacy-evidence/`), the latency instrument (`one-loop-latency/`), `spec/PERMISSIONS.md`.

- AC1: [14-mapping.md](history/2026-11-12/14-mapping.md)'s carry-over table has a final disposition for every row.
- AC2: `pytest spec` gates CI.

Source: meta-harness `projects/sortyard/` (about 5,000 lines across six folders); `ci.yml` (`spec` job fails on main); board: SORTYARD-9, 10, 11, 12, 14, 15 are Done while the product repo holds only PRs #1–#4.

Historical text: [MIG-015](history/2026-11-12/10-platform.md).

<a id="MIG-016"></a>
## MIG-016 — Legacy baselines are captured before anything changes

**MS0 · MUST · retained**

Every baseline in [18-divergences.md](history/2026-11-12/18-divergences.md) (the `BL` ids) gets a value, the
method that produced it and the evidence it came from, taken from the frozen evidence
(MIG-001), the recorded passes (MIG-002), the Git host's history and a board export. A baseline
that cannot be measured is recorded as `unmeasurable` with the reason, and the demonstrations
that cite it fall back to their absolute floor. The capture scripts live under
`migration/baselines/` and are re-run for each project before its cutover, because the legacy
system keeps changing. The values are loaded into Sortyard as reference series, so dashboards
and the scorecard show the legacy figure beside Sortyard's.

- AC1: Each baseline has a value file with value, unit, window, cohort, method, script, evidence digest and capture date, under the id used in [18-divergences.md](history/2026-11-12/18-divergences.md).
- AC2: The capture is repeatable: a script run twice on the same frozen evidence gives the same value.
- AC3: Every baseline marked "to capture" has a value or an `unmeasurable` record before the MS1 gate; none is filled in from memory.
- AC4: A demonstration never passes against a missing baseline: the scorecard shows `no baseline`, and the gate treats it as a missed floor unless the criterion states an absolute floor.

Source: the owner, 2026-11-12 (a divergence must be shown better than "the cobbled solution we have in hand"); CORPUS R5 (the baseline moves); conductor README, driver log and task-pickup for the figures known today. Inference: which baselines are measurable from the frozen evidence is not yet verified ([17-evidence.md](history/2026-11-12/17-evidence.md)).

Historical text: [MIG-016](history/2026-11-12/10-platform.md).

<a id="MIG-017"></a>
## MIG-017 — Inventory informs migration, never silently cuts scope

**MS0 · MUST · amended**

A current usage/conformance inventory identifies consumers, artifact destinations and missing mechanisms. Lack of observed usage prioritizes migration research; it does not remove an explicitly requested archetype/skill/recipe/extension or other capability without owner disposition.

- AC1: Every artifact/behavior family retains a requirement or explicit named disposition.
- AC2: Done/in-progress work is preserved; residual gaps are follow-ups, not rewritten history.
- AC3: No unused/conditional-cut label overrides current owner scope.

Source: the owner, 2026-11-12 (divergence rule); inference — use of these features was not measured for this specification ([17-evidence.md](history/2026-11-12/17-evidence.md), "Not verified").

Historical text: [MIG-017](history/2026-11-12/10-platform.md).

<a id="QLT-001"></a>
## QLT-001 — The docs are a tested product surface

**MS8 · MUST · retained**

A docs site built from the repository, with: quickstart, install, upgrade, concepts, an
operations guide written around reason codes and absent states, troubleshooting, and generated
references (API, CLI, policy keys, reason codes, permission matrix, metrics, chart values). Every
command block in the docs is executed in CI against the replica.

- AC1: A doc command that fails breaks the build.
- AC2: The generated references are never edited by hand (drift check).
- AC3: The public docs contain no internal host, project or person names (grep gate, MIG-006).

Source: `tests/test_readme.py` (the quickstart is already tested); goldfish GF1-04; CORPUS M6.1.

Historical text: [QLT-001](history/2026-11-12/12-quality-bar.md).

<a id="QLT-002"></a>
## QLT-002 — README

**MS0 · MUST · retained**

The README says what Sortyard is, shows the quickstart, links the docs, and states the project's
status honestly. Charter, tracking notes and internal references move out.

- AC1: Top to bottom, the README has no statement that contradicts another part of it.

Source: goldfish GF1-04 (the charter half contradicts the top half and links internal hosts).

Historical text: [QLT-002](history/2026-11-12/12-quality-bar.md).

<a id="QLT-003"></a>
## QLT-003 — Contributor and agent guide

**MS0 · MUST · retained**

`AGENTS.md` and `CONTRIBUTING.md` at the root: the architecture map, how to run the replica and
the checks, the conventions (schema-first models, domain commands, one event per change), how to
add a requirement-bearing change, and the definition of done.

- AC1: A zero-context agent lands a small, correct change using only the repository (the goldfish test for contributors), and its friction list is empty of blockers.

Source: goldfish GF1-03 (no `AGENTS.md`); DESIGN §11.2; SORTYARD-13.

Historical text: [QLT-003](history/2026-11-12/12-quality-bar.md).

<a id="QLT-004"></a>
## QLT-004 — Goldfish gate at every milestone

**MS1 · MUST · retained**

At each milestone exit a zero-context agent, given only the public repository and docs, installs
the release candidate and performs the milestone's exit demonstration. Its findings are filed;
blockers hold the milestone. The run must happen on a machine that has the prerequisites and
network the docs assume.

- AC1: The report follows the existing format (run log, findings with severity and evidence, verdict).
- AC2: Findings from the previous report are fixed, not just filed, before the next one runs.

Source: `docs/goldfish/phase-1-install-smoke.md` (verdict: blocked; the cluster steps were not run because the environment had no tools or network); CORPUS R7 (the legibility thread).

Historical text: [QLT-004](history/2026-11-12/12-quality-bar.md).

<a id="QLT-005"></a>
## QLT-005 — Decision records and changelog

**MS0 · MUST · retained**

Architecture decisions are records with a date, an owner and a status in `DECISIONS.md` (or one
file each). `CHANGELOG.md` follows Keep a Changelog; every user-visible change has an entry.

- AC1: The product repository's `DECISIONS.md` contains SY-DEC-001 to SY-DEC-003 and the decisions this specification asks for (see [15-open-decisions.md](history/2026-11-12/15-open-decisions.md)).

Source: `DECISIONS.md` in the repo holds only SY-DEC-001; the meta-harness copy also has 002 and 003.

Historical text: [QLT-005](history/2026-11-12/12-quality-bar.md).

<a id="QLT-010"></a>
## QLT-010 — Contract tests and real substrate qualification

**MS0 · MUST · amended**

Test domain transitions and refusal cases at the cheapest adequate layer. CI exercises the public contract and doc-derived provider fixtures; stood-up Appwrite/other dependencies run in the local replica and substrate migration/upgrade event per current placement doctrine. Existing required checks remain until classified changes land.

- AC1: No test asserts only the fixture implementation or retries to seek green.
- AC2: The pinned real Appwrite qualification exercises concurrency/history/identity rather than a fake SQL replacement.
- AC3: UI and delegated-agent journeys exercise the same command effects, scopes and evidence links.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [QLT-010](history/2026-11-12/12-quality-bar.md).

<a id="QLT-011"></a>
## QLT-011 — Coverage targets and floors

**MS1 · MUST · retained**

Coverage is measured for each layer and enforced in CI: branch coverage of the domain layer,
line coverage of the whole backend, statement coverage of the console beside the journey suite.
The floors only rise.

- AC1: Coverage of the domain layer, the whole backend and the console, in that order. Target: 100%, 90% and 85%. Floor: 90%, 80% and 70%; CI fails below a floor.

Source: inference — Plane publishes no coverage figure; the legacy `test_conductor.py` (10,364 lines for 2,589 of code) sets the house standard.

Historical text: [QLT-011](history/2026-11-12/12-quality-bar.md).

<a id="QLT-012"></a>
## QLT-012 — Every pull request runs everything

**MS0 · MUST · retained**

Lint, format, strict type-check, generated-code and generated-document drift (including this
directory's `tools/gen.py --check`), all test layers, chart lint and render, image build and the
install smoke run on every pull request and are required. No job is `continue-on-error`.

- AC1: `main` is never red: a failing required check on `main` is treated as an incident.
- AC2: The p95 duration of the required checks on a pull request. Target: 5 minutes. Floor: 15 minutes.

Source: AGENTS.md "Green main, stop the line" (the estate's own standard, kept); `.github/workflows/ci.yml` (the `spec` job is `continue-on-error`, a gap in the prototype repository).

Historical text: [QLT-012](history/2026-11-12/12-quality-bar.md).

<a id="QLT-013"></a>
## QLT-013 — Fork pull requests are safe to run

**MS8 · MUST · retained**

Pull requests from forks run the full required checks on provider-hosted runners with no
secrets and read-only permissions. Nothing in the required checks needs a secret.

- AC1: A fork pull request gets the same green or red as a branch pull request.

Source: DESIGN §11.2 (fork-PR verification); `ci.yml` already uses `ubuntu-latest` with `contents: read`. The estate's "no GitHub-hosted runners" rule is about estate work and does not apply to this public repository.

Historical text: [QLT-013](history/2026-11-12/12-quality-bar.md).

<a id="QLT-014"></a>
## QLT-014 — Repair flaky tests against the intended contract

**MS1 · MUST · amended**

A reproduced flaky test is fixed or explicitly quarantined with scope, owner, evidence and exit condition. Retirement requires a recorded reason/coverage replacement, not a desire for green. Test debt and its affected delivery risk are visible.

- AC1: Contradictory results retain the reproduction.
- AC2: No automation deletes/skips/retries a required test solely to merge.
- AC3: A target-gap or quarantine remains owned until its verified disposition.

Source: AGENTS.md "Testing model" ("Never rerun just to seek a green result").

Historical text: [QLT-014](history/2026-11-12/12-quality-bar.md).

<a id="QLT-015"></a>
## QLT-015 — Scenario suite as a product asset

**MS3 · MUST · retained**

The scripted harness and the demo repository (MS3), and the Git host fake and the CI fake (MS4,
built with their adapters in WP4.1), are shipped and documented, so that adopters and extension
authors can test against them.

- AC1: The fakes implement the adapter interfaces (EXT-003, CIH-013) and pass the same conformance tests as the real adapters where the behaviour is defined.

Source: AGENTS.md "Delivery lanes" rule 5 ("fakes encode the providers' documented behaviour").

Historical text: [QLT-015](history/2026-11-12/12-quality-bar.md).

<a id="QLT-016"></a>
## QLT-016 — Performance bars on a reference workload

**MS6 · MUST · retained**

On the reference workload (20 projects, 50,000 tasks, 5,000 open, 200 chains in flight) the
product stays fast enough that nobody waits for it. A load job measures the bars below before
each release; console latency is in UI-009 and UI-018.

- AC1: List and detail API latency. Target: p95 at most 50 ms. Floor: p95 at most 300 ms.
- AC2: Scheduler evaluation of one project. Target: at most 200 ms. Floor: at most 2 s.
- AC3: Event-stream lag from commit to a subscribed client. Target: at most 250 ms. Floor: at most 2 s.
- AC4: The load job's results are in the release notes and the scorecard (QLT-051).

Source: harness-console J1 (2 s), J2 (10,000 rows); `architecture.md` ("datasets of ~10^3–10^4 requests").

Historical text: [QLT-016](history/2026-11-12/12-quality-bar.md).

<a id="QLT-020"></a>
## QLT-020 — Security policy and response

**MS8 · MUST · retained**

`SECURITY.md`: a private reporting channel; a stated time to acknowledge a report; a stated time
to a fix or mitigation for high and critical findings; advisories published with affected
versions.

- AC1: The reporting channel is tested before 1.0.
- AC2: Time to acknowledge a report, and time to a fix or mitigation for a high or critical finding. Target: one business day and 7 days. Floor: three business days and 30 days.

Source: Plane `SECURITY.md` (three business days) — matched, with fix targets added.

Historical text: [QLT-020](history/2026-11-12/12-quality-bar.md).

<a id="QLT-021"></a>
## QLT-021 — Threat model and security review before 1.0

**MS8 · MUST · retained**

A written threat model covering: the permission matrix and token scopes; stage tokens and the
worker boundary; the integrator and its credential; packets carrying untrusted task text to
agents (prompt injection that tries to exfiltrate credentials or write outside the task); inbound
and outbound webhooks; the proxy-header sign-in mode. An independent adversarial review tests it;
findings are closed or accepted in writing.

- AC1: The review includes an attempt to make a worker act outside its binding and an attempt to reach another project's objects.

Source: CORPUS M6.2 ("an adversarial review of the binding path"); Plane's advisory profile.

Historical text: [QLT-021](history/2026-11-12/12-quality-bar.md).

<a id="QLT-022"></a>
## QLT-022 — Dependencies are pinned and scanned

**MS1 · MUST · retained**

Python and JavaScript dependencies are locked with hashes. Dependency updates arrive by bot.
CodeQL, a dependency audit and a container scan run in CI; a known high or critical
vulnerability with a fix available blocks release.

- AC1: The image contains no package without a locked version.

Source: `pyproject.toml` (ranges, no lock file today); Plane benchmark (CodeQL workflow, `.trivyignore`, `uv sync --locked`).

Historical text: [QLT-022](history/2026-11-12/12-quality-bar.md).

<a id="QLT-023"></a>
## QLT-023 — Signed artefacts with provenance

**MS8 · MUST · retained**

Each release publishes images and the chart to an OCI registry, signed (keyless), with an SBOM
and a build-provenance attestation. The docs show how to verify them, and the install test
verifies them.

- AC1: A tampered image fails verification in the install test.

Source: CORPUS M6.2 ("image signing and build provenance"); the legacy release controller's digest pinning and source-ancestry checks (CI-RELEASE.md) — the guarantee is kept, the bespoke controller is not.

Historical text: [QLT-023](history/2026-11-12/12-quality-bar.md).

<a id="QLT-024"></a>
## QLT-024 — Releases come from CI, from a tag

**MS1 · MUST · retained**

A release is produced only by the release workflow from a signed tag on `main`, and every merge
to `main` publishes a development build the same way, so the newest merged code is always
installable. Nothing is built on a laptop. The workflow holds no cluster credential.

- AC1: The release workflow is the only identity allowed to push release artefacts.
- AC2: Demonstration (ledger, MS7) — for every merge to `main` during the pilot, the time from the merge to the running installation serving it, from the release workflow and the ledger. Target: every merge running within 10 minutes, with no person involved. Floor: no person and no hand-applied object involved, and no slower than the legacy merge-to-release time; the legacy release of 2026-11-12 needed a Role applied by hand (BL-11).

Source: DESIGN §9 ("the reboot's own releases go through CI like everything else"); CI-RELEASE.md ("It has no Kubernetes credential or cluster network path").

Historical text: [QLT-024](history/2026-11-12/12-quality-bar.md).

<a id="QLT-025"></a>
## QLT-025 — Secrets never enter the repository

**MS0 · MUST · retained**

A secret scanner runs on every pull request and on history before the repository is made
public.

- AC1: The pre-publication history scan is recorded with its result.

Source: the repository is private today and was seeded from an internal folder.

Historical text: [QLT-025](history/2026-11-12/12-quality-bar.md).

<a id="QLT-030"></a>
## QLT-030 — Semantic versioning with one number for app, chart and API

**MS1 · MUST · retained**

The application, the image and the chart share one version. Before 1.0, minors may break with
notice; from 1.0, semantic versioning applies to the API, the CLI, the chart values, the stage
contract and the database upgrade path.

- AC1: One version string is stamped into the image, the chart and the served OpenAPI document, and CI fails when they differ. What counts as breaking is defined mechanically by the compatibility jobs when they land (API-013, DEP-008, EXT-007).

Source: DEP-020; `Chart.yaml` (`version` and `appVersion` both 0.1.0).

Historical text: [QLT-030](history/2026-11-12/12-quality-bar.md).

<a id="QLT-031"></a>
## QLT-031 — Release notes and upgrade notes, always

**MS1 · MUST · retained**

Every release has notes generated from the changelog plus an upgrade section (migrations,
duration, anything to do by hand). Each milestone ends in a tagged pre-release.

- AC1: The release workflow fails without an upgrade section.

Source: Plane benchmark (release notes of 62–99 characters on some stable releases).

Historical text: [QLT-031](history/2026-11-12/12-quality-bar.md).

<a id="QLT-032"></a>
## QLT-032 — Release cadence and support window

**MS8 · SHOULD · retained**

After 1.0: a minor about every six weeks; security fixes for the latest two minors.

- AC1: The policy is in `GOVERNANCE.md` and the docs.

Source: inference; Plane ships about monthly.

Historical text: [QLT-032](history/2026-11-12/12-quality-bar.md).

<a id="QLT-040"></a>
## QLT-040 — Licence and contribution terms

**MS8 · MUST · retained**

Apache-2.0. Contributions under the Developer Certificate of Origin, checked mechanically; no
CLA. A licence scan keeps copyleft dependencies out of the distributed image. Confirmation is
the owner's (OD-1).

- AC1: A commit without sign-off fails the DCO check.
- AC2: The licence scan is a required check.

Source: `LICENSE` (Apache-2.0, SY-DEC-001 seed); INTENDED-USE.md standing default; DESIGN §11.5.

Historical text: [QLT-040](history/2026-11-12/12-quality-bar.md).

<a id="QLT-041"></a>
## QLT-041 — No withheld pieces

**MS8 · MUST · retained**

Everything needed to run Sortyard as described in its docs is in the public repository under the
project licence. There is no enterprise edition of the code.

- AC1: The docs describe no feature that the public artefacts do not contain.

Source: DESIGN §11.6.

Historical text: [QLT-041](history/2026-11-12/12-quality-bar.md).

<a id="QLT-042"></a>
## QLT-042 — Governance files

**MS8 · MUST · retained**

`GOVERNANCE.md` (who decides, how a maintainer is added), `MAINTAINERS`, `CODE_OF_CONDUCT.md`,
issue and pull-request templates, a trademark note for the name and logo, and a public roadmap
kept as milestones in the repository's own tracker.

- AC1: The roadmap is generated from, or is, the real milestone list — not a separate page.

Source: DESIGN §11.5; CORPUS M6.6.

Historical text: [QLT-042](history/2026-11-12/12-quality-bar.md).

<a id="QLT-043"></a>
## QLT-043 — Name clearance

**MS3 · MUST · retained**

A trademark search for "Sortyard" is completed and recorded, and the package namespaces (GitHub
organisation, PyPI, npm, container registry) are claimed, before the repository is made public.

- AC1: The record is in `DECISIONS.md`.

Source: DESIGN §10 item 1 ("Still owed before public launch: a formal trademark search"; namespaces unclaimed at check time).

Historical text: [QLT-043](history/2026-11-12/12-quality-bar.md).

<a id="QLT-050"></a>
## QLT-050 — Every divergence from the estate is demonstrably better, or the legacy behaviour is kept

**MS0 · MUST · retained**

Wherever Sortyard behaves differently from the estate's system — a requirement with origin
`FIX`, a legacy parity row that is not `KEEP`, a cut, a finding that replaces a mechanism — this
specification records the legacy baseline with its evidence, the dimensions on which the new
behaviour is better, and a demonstration: a measured comparison against the baseline with a
threshold, made by replay, the parity suite, ledger metrics, a scripted benchmark, fault
injection, a count, a drill or the usage census. "Different but equivalent" does not pass. A
divergence whose demonstration misses its floor is not shipped to the estate: the legacy
behaviour stays, as the estate bundle's setting or as the requirement itself, until the
demonstration passes.

- AC1: `tools/gen.py --check` fails when a `FIX` requirement lacks its `Baseline:`, its `Better on:` or its demonstration; when a parity row that is not `KEEP`, a cut or a replacing finding cites no divergence entry; and when a divergence entry lacks the fields its verdict needs.
- AC2: Each demonstration is a named test or job (rule 3 of [13-milestones.md](history/2026-11-12/13-milestones.md)) that reads its baseline from the captured values (MIG-016) and fails below its floor.
- AC3: A change that introduces a new divergence adds its entry and its demonstration in the same pull request; review rejects it otherwise.
- AC4: Before each cutover the divergences the project relies on are listed with their measured results in the hypercare plan (MIG-009); one that missed its floor is switched to the legacy behaviour for that project.

Source: the owner, 2026-11-12 ("Anywhere sortyard diverges from the cobbled solution we have in hand, the divergence needs to evolve into something that's demonstrably better in as many ways possible").

Historical text: [QLT-050](history/2026-11-12/12-quality-bar.md).

<a id="QLT-051"></a>
## QLT-051 — Quality targets and explicit acceptance floors

**MS0 · MUST · amended**

Requirements retain aspirational measured targets and justified acceptance floors. Changes are judged against real retained baselines and intended product behavior. No calendar/lane-time estimates or automatically multiplied task counts govern delivery; board work is decomposed into bounded one-PR slices.

- AC1: Every retained requirement has an acceptance criterion and provenance.
- AC2: A quality gap has an explicit requirement/owner rather than an invented pass.
- AC3: The current baseline contains all legacy requirement IDs with explicit amendment traceability.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

Historical text: [QLT-051](history/2026-11-12/12-quality-bar.md).

<a id="ECO-001"></a>
## ECO-001 — One ecosystem control surface

**MS1 · MUST · new**

UI, concierge, CLI and operator-delegated agents use one public action/resource contract; each authoritative service still owns its records and execution.

- AC1: Equivalent requests across transports yield the same authorized effect and evidence.
- AC2: No console-only or agent-only privileged backdoor exists.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="ECO-002"></a>
## ECO-002 — Authority registry and epochs

**MS1 · MUST · new**

Each resource family registers one owner, installation, scope mapping, write route, schema/capability version and authority epoch.

- AC1: Projection writes cannot become source authority.
- AC2: An old-epoch mutation after handover is refused.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="ECO-003"></a>
## ECO-003 — CortexPlane goals and process ownership

**MS2 · MUST · new**

CortexPlane owns operator intent, goals/key results and outer process orchestration. Sortyard exposes scoped references and harness effects that CP consumes through delegated API access.

- AC1: A delivery/improvement can link to its authorized intent/KR.
- AC2: An unavailable CP capability is explicit; no second writable goal record is invented.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="ECO-004"></a>
## ECO-004 — Walwarden memory and supersession

**MS2 · MUST · new**

Walwarden owns durable knowledge/observation supersession. Meta-harness/Git/boards/vault/sessions are provenance sources; Sortyard exposes authorized references and decisions without treating retrieval rank as authority.

- AC1: Superseded knowledge is visibly linked to its successor.
- AC2: A private or unavailable memory record cannot leak through graph edges.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="DOM-001"></a>
## DOM-001 — Meta-harness artifact catalog

**MS1 · MUST · new**

Archetypes, workflow/persona roles, skills, recipes, guidance, policies, quality bars, decisions and procedures are typed resources or linked versioned artifacts with explicit owner and scope.

- AC1: The resource catalog identifies schema, identity, lifecycle and supported actions.
- AC2: Every meta artifact family has a disposition; unsupported content remains a provenance-linked artifact rather than vanishing.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="DOM-002"></a>
## DOM-002 — Archetype inheritance and project adoption

**MS2 · MUST · new**

A project pins an archetype version; defaults compose workflows, roles, context, skills, substrate/deploy profiles and quality bars, with explicit overrides and an adoption impact diff.

- AC1: An upgrade does not silently change existing project/running-stage bindings.
- AC2: A local override and inherited value identify the winning source/version.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="DOM-003"></a>
## DOM-003 — Workflow roles differ from authorization roles

**MS1 · MUST · new**

Workflow RoleDefinition/persona is an immutable context/tool/model definition; Membership/CapabilityGrant controls who may act.

- AC1: A persona edit grants no user/service authority.
- AC2: The UI/API use distinct types and references for these roles.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="DOM-004"></a>
## DOM-004 — Inspectable context packets

**MS2 · MUST · new**

Versioned allowlist recipes produce immutable packets with exact source/skill/policy versions, hashes, token budget and provenance.

- AC1: A project/role/stage preview matches the packet used by a binding.
- AC2: Forbidden content is excluded and missing required context produces a named binding failure.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="DOM-005"></a>
## DOM-005 — Quality and verification definitions

**MS2 · MUST · new**

Quality bars, contracts, eval packs and acceptance profiles are versioned/assignable resources; observed outcomes remain separate immutable evidence.

- AC1: An edit creates a candidate version, not a rewritten historical verdict.
- AC2: Missing evidence is not converted into success by a configuration change.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="DOM-006"></a>
## DOM-006 — Complete meta-harness conformance inventory

**MS0 · MUST · new**

Map every current templates/skills/roles/workflows/contracts/guidance/decision artifact family to a native resource or preserved external artifact and record lineage.

- AC1: Every inventory row names destination owner/type or explicit retained artifact route.
- AC2: No field/status is copied from a historical task register as current state.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="AGT-001"></a>
## AGT-001 — Authority and executor identity

**MS1 · MUST · new**

Record authority principal, executor principal, delegation, approver where applicable and system executor separately, all server-resolved.

- AC1: Forged on_behalf_of/system headers are refused.
- AC2: Audit links the exact grant and acting agent without token values.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="AGT-002"></a>
## AGT-002 — Narrow standing delegation

**MS1 · MUST · new**

Effective authority intersects current issuer grants/membership, delegation action/resource scope, audience, policy and expiry; child delegation is denied by default.

- AC1: Ordinary authorized delegated actions need no invented per-action confirmation.
- AC2: A child/self edit cannot widen scope or outlive its parent.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="AGT-003"></a>
## AGT-003 — Revocation across every surface

**MS1 · MUST · new**

Membership/session/parent-grant revocation invalidates future requests, active feeds and cached capability/search/graph access within a declared tested bound.

- AC1: An old cursor/token cannot preserve removed access.
- AC2: Cached decisions identify their invalidation/revalidation bound.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="AGT-004"></a>
## AGT-004 — Truthful callable capability manifest

**MS1 · MUST · new**

Distinguish implemented, installed, configured, operational, authorized and valid-in-state capabilities of the actual running revision.

- AC1: Planned operations in design artifacts are never advertised as callable.
- AC2: Missing integration support gives a structured unavailable reason.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="AGT-005"></a>
## AGT-005 — Canonical references and deep links

**MS1 · MUST · new**

Typed references include service/installation/workspace/project/kind/domain ID and version as applicable; UI/API/history/evidence links use canonical configured origins.

- AC1: Renames and physical Appwrite-ID migration preserve logical references.
- AC2: A deep link carries no bearer token and does not grant access.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="AGT-006"></a>
## AGT-006 — Revision-bound optional action plans

**MS1 · MUST · new**

A preview/plan normalizes targets, inputs, expected revisions, policy versions, impact and expiry; execution rechecks current state and authority. ActionPlan.approval_ref names its approval Decision. The same decision.answer operation is used by the UI and an authorized delegated approver; hash, revision, expiry and current authority are checked before the plan can become approved.

- AC1: Editing or expiry invalidates a required approval.
- AC2: Preview does not mutate delivery state or reserve a future lane implicitly.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="AGT-007"></a>
## AGT-007 — Observable asynchronous operations

**MS1 · MUST · new**

Accepted commands expose an Operation resource with acceptance, committed mutation, external acceptance and verified effect distinguished. Cancellation states its actual effect.

- AC1: Lost responses recover a stable operation.
- AC2: An ambiguous external result stays pending reconciliation rather than success or blind retry.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="AGT-008"></a>
## AGT-008 — Operator/API parity coverage

**MS1 · MUST · new**

Each operator action maps to a UI route/control, public action contract and discoverable agent/CLI path with the same permission/acceptance cases.

- AC1: A coverage manifest identifies missing transports before milestone acceptance.
- AC2: Generic tool calls cannot bypass the curated tool permissions.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-001"></a>
## INT-001 — Versioned service connectors

**MS1 · MUST · new**

Connections declare trusted endpoint identity, contract version, resource families, auth/custody references, scope mapping, read/actions/events and observed health.

- AC1: Client input cannot supply an arbitrary upstream URL/path or reuse a token across services.
- AC2: Unsupported/misconfigured capability is distinguishable from forbidden and empty.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-002"></a>
## INT-002 — Policy API authority and action routing

**MS2 · MUST · new**

The existing policy engine remains authoritative for its policy families. Sortyard lists/resolves/proposes/edits/promotes through supported owner operations, preserving lifecycle, scope variants and promotion restrictions.

- AC1: A permitted change is reflected only after the owner accepts it.
- AC2: An agent cannot jump enforcement/activation by editing a local projection.
- AC3: Both UI and delegated agents can request the same permitted policy action.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-003"></a>
## INT-003 — Policy decisions and conflict explanations

**MS2 · MUST · new**

Resolve effective policy with source family/variant/version, consumer, input snapshot, conflict/absence behavior and actual decision result; separate configured policy from a firing consumer.

- AC1: A stall explanation links the exact policy or absent consumer/evidence.
- AC2: Equal-rank conflicting variants do not select an arbitrary winner.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-004"></a>
## INT-004 — Full policy authority migration

**MS7 · MUST · new**

Optional policy migration captures every version body, scope variant, history and import provenance under a freeze/epoch/checkpoint contract. Current-only export is not a complete snapshot.

- AC1: Missing full-snapshot capability blocks only migration, not the existing owner proxy.
- AC2: Old writer epoch is fenced and retained-input resolution matches before switch.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-005"></a>
## INT-005 — Existing harness and Plane ownership adapters

**MS2 · MUST · new**

Read current tasks/execution through bounded projections and route authorized actions to the current owner. Transfer only explicitly selected projects/families.

- AC1: One task never has two independent schedulers.
- AC2: A command rejected by the owner cannot succeed via materialized data.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-006"></a>
## INT-006 — Durable integration delivery

**MS2 · MUST · new**

Transactional outbox, owner-scoped cursors, idempotent effect IDs, delivery receipts and reconciliation handle duplicate, out-of-order and interrupted partner calls.

- AC1: A duplicate event creates one intended task/loop/effect.
- AC2: An unavailable optional service leaves an owned wait without blocking unrelated work.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-007"></a>
## INT-007 — Notifications and owner routing

**MS5 · MUST · new**

Notifications/acknowledgement use the existing notification service contract with explicit loop/system owner and escalation to the operator intent chain.

- AC1: A repeated condition deduplicates while its source remains visible.
- AC2: No new outbound communication occurs without its declared policy/authority.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-008"></a>
## INT-008 — Native CI and GitOps control

**MS2 · MUST · new**

Git/CI/Argo integrations expose authorized request/observation contracts; promotion mutates reviewed Git/native release inputs rather than applying product kubectl from an agent/UI shell.

- AC1: Merged-but-undelivered and red-main evidence are visible separately.
- AC2: A missing promotion API is unavailable, not replaced with an ad hoc shell action.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-009"></a>
## INT-009 — Rove and external execution boundaries

**MS5 · MUST · new**

Registered browsing/external-action capabilities retain their provider/approval/receipt contracts and project scope; ecosystem references do not create standing authority to communicate or purchase.

- AC1: A delegated task cannot bypass required external-action approval.
- AC2: An unsupported API can surface a governed browsing option without executing it automatically.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-010"></a>
## INT-010 — Product Lab experiment references

**MS6 · MUST · new**

Experiments/hypotheses/treatments/baselines/results are typed owner references linked to proposals and adopted changes, with unknown results explicit.

- AC1: A proposed experiment is not reported as a measured outcome.
- AC2: Unavailable experiment APIs remain capability-gated.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="GRF-001"></a>
## GRF-001 — Typed operational and provenance relationships

**MS2 · MUST · new**

Edges have typed source/target refs, owner/provenance, observed/valid time and access scope; graph views project the same authoritative records.

- AC1: A relationship kind has valid source/target types and no dangling success reference.
- AC2: An inferred edge is distinguished from a confirmed owner relationship.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="GRF-002"></a>
## GRF-002 — Authorization-safe graph traversal

**MS2 · MUST · new**

Every hop, search result, count, mention and reverse link applies current scope and source permissions; pagination is bounded and cycle-aware.

- AC1: A private source cannot be inferred from an edge/count or timing-dependent fallback.
- AC2: Traversal resumes without crossing its cursor/filter scope.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="GRF-003"></a>
## GRF-003 — Supersession and impact analysis

**MS2 · MUST · new**

Definitions, policies and knowledge keep explicit supersedes/derived_from/assigned_to/used_by/evidence_for edges; proposed changes show affected projects/next bindings and unknown coverage.

- AC1: A superseded version remains historically navigable to authorized readers.
- AC2: Impact is not claimed complete when a source is stale or absent.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="OPS-001"></a>
## OPS-001 — Serialized project grooming

**MS2 · MUST · new**

Grooming is a first-class request/pass with project-scoped queue, fenced lease, input snapshot, model policy, proposed edits, applied results and handback reasons. Serialization keys use the canonical authoritative installation and source board/project identity, not logical project aliases.

- AC1: Two requests for one project serialize; another project can proceed.
- AC2: An expired lease holder cannot commit edits.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="OPS-002"></a>
## OPS-002 — Triage cases and bounded repairs

**MS2 · MUST · new**

TriageCase links a condition/evidence, owner, classification, repair budget, attempted operations and observed resolution; a running agent is not evidence of recovery.

- AC1: A repeated finding updates one case rather than creating unbounded tasks.
- AC2: Repair attempts stop/escalate at the configured limit with a named owner.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="OPS-003"></a>
## OPS-003 — Agent definitions and actual runs

**MS2 · MUST · new**

AgentDefinition/profile is separate from AgentRun with scope, delegation, binding, attempt, phase, timestamps, source/policy versions and outcome.

- AC1: The operator/agent can see what is running and under whose authority.
- AC2: A definition edit does not rewrite a completed run.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="OPS-004"></a>
## OPS-004 — Mechanism freshness and independent observation

**MS2 · MUST · new**

Registered recurring mechanisms declare expected cadence/freshness, independent observer, owner and absence behavior; stale monitoring is not healthy.

- AC1: A stopped producer yields an owned stale/unknown condition.
- AC2: A consumer cannot manufacture its producer proof to turn itself green.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="IMP-001"></a>
## IMP-001 — Discovery and ranking provenance

**MS6 · MUST · new**

A discovery preserves original/source/provenance, classification and a Ranker result tied to project/archetype/stage and scoring-policy version.

- AC1: A ranking explains evidence and applicability.
- AC2: Repeated/superseded candidates remain traceable and deduplicated.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="IMP-002"></a>
## IMP-002 — Explicit pursuit and loop intake

**MS6 · MUST · new**

Pursuing an ImprovementProposal under operator authority creates/links a Closer loop and bounded harness work through a durable idempotent handoff. Ranking alone creates no commitment.

- AC1: Duplicate pursuit delivery yields one linked loop/task.
- AC2: A rejected/unaccepted proposal causes no production change.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="IMP-003"></a>
## IMP-003 — Reviewed version publication and adoption

**MS2 · MUST · new**

A skill/definition improvement lands through normal review/CI, publishes immutable content and is adopted into an explicit project/archetype version with impact/rollback information.

- AC1: A landing is distinct from activation/adoption.
- AC2: A skill install cannot widen agent tools/credentials silently.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="IMP-004"></a>
## IMP-004 — Usage and outcome evidence

**MS6 · MUST · new**

Link a published version to adoption, bindings/runs that actually used it and observed outcomes. Distinguish promised benefit, measured association and stronger experimental evidence.

- AC1: Merge alone does not close adoption/effectiveness.
- AC2: Confounding concurrent model/policy changes and absent measurements remain explicit.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="IMP-005"></a>
## IMP-005 — Private partner data remains with its owner

**MS2 · MUST · new**

Ranker corpus/score state and Closer commitments remain authoritative in their services; Sortyard stores scoped refs/projections and necessary outcome fields only.

- AC1: Project membership does not imply access to personal corpora/loops.
- AC2: An unavailable partner never produces fabricated empty success or a competing writable record.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="SUB-001"></a>
## SUB-001 — Appwrite atomic claim qualification

**MS0 · MUST · new**

Exercise the pinned real self-hosted substrate with concurrent same-task/final-lane-slot claims, rollback, stale fencing, receipt replay and interrupted response handling.

- AC1: At most one same-task/final-slot claim commits with matching state/event/receipt.
- AC2: A stale release cannot clear a new owner; failures leave no orphan chain.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="SUB-002"></a>
## SUB-002 — Appwrite immutable history qualification

**MS0 · MUST · new**

Use the actual non-admin runtime principal with rowSecurity=false and read/create-only table grants; attempt direct/transaction/upsert/delete, malicious row grants and schema-security changes.

- AC1: The writer can append but all attempts to mutate/delete accepted history fail.
- AC2: No schema/admin/broad resource-bypass key is needed at runtime.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="SUB-003"></a>
## SUB-003 — Supported runtime identity and credential renewal

**MS1 · MUST · new**

Runtime substrate identity is distinct from human/agent authority, and its session/JWT renewal/revocation works without copying an Appwrite global secret.

- AC1: Expired/revoked credentials fail closed with an owned condition.
- AC2: Renewal does not grant schema or other application access.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="SUB-004"></a>
## SUB-004 — Domain identity and blob publication

**MS1 · MUST · new**

Map logical IDs including workspace/type/version to deterministic collision-checked physical IDs, keep typed indices and canonical schema/hash validation, and publish only verified blobs.

- AC1: Long/escaped domain IDs round-trip through API, storage and links.
- AC2: Interrupted blob upload/metadata publication is recoverable without exposing incomplete data.

Source: Owner control-plane requirements, 2026-11-15 America/New_York; SY-DEC-004; company/INTENTS.md I1/I3/I5 and BIG-PICTURE.md (source date 2026-11-16).

<a id="INT-011"></a>
## INT-011 — Scoped and attributable policy-owner writes

**MS2 · MUST · new**

The policy owner exposes a policy-only authenticated writer scope and verified gateway context. It refuses other harness operations and wrong policy/project scope; source receipts distinguish service identity from authenticated gateway-asserted operator attribution. Until this is supported, multi-user policy writes remain unavailable while read integration can ship.

- AC1: A policy-only caller cannot invoke job, credential or controller mutation routes.
- AC2: Wrong family/project scope or forged direct end-user actor context is refused.
- AC3: An accepted proposal/edit/promotion links original authority, gateway identity and source version/receipt.

Source: Inspected current policy API _policy_post: conductor writer and hard-coded conductor actor; current owner operator-agent requirements.

<a id="OPS-005"></a>
## OPS-005 — First-class operational actors

**MS2 · MUST · new**

Named detector, classifier, diagnostician, repair executor, verifier, groomer and coordinator actors have stable identity, responsible operator, executor binding, scoped grants and enabled/paused/retired lifecycle. Actors may be deterministic services or agents; a persona grants no privileges.

- AC1: The same actor status/configuration/actions are visible through operator UI and delegated-agent discovery.
- AC2: Actor registration cannot mint grants or inherit cluster/conductor credentials; revocation prevents new effects.

Source: Owner operating-process direction, 2026-11-16 UTC; operating-processes.md and pinned legacy source evidence.

<a id="OPS-006"></a>
## OPS-006 — Versioned operating processes and runs

**MS2 · MUST · new**

OperationalProcessVersion declares trigger correlation, actor roles, stage graph, owner actions, policy decision points, verification and escalation. OperationalProcessRun pins it and records actual bindings, lease epoch, budgets and evidence while linking existing cases/attempts/operations.

- AC1: A run displays which actor owns each stage and the policy/definition versions used.
- AC2: Duplicate trigger delivery creates one active owner/run; alias/restart cannot erase history or budget.

Source: Owner operating-process direction, 2026-11-16 UTC; operating-processes.md and pinned legacy source evidence.

<a id="OPS-007"></a>
## OPS-007 — Seeded policies with consumer coverage

**MS2 · MUST · new**

Install source-neutral versioned triage/self-heal seed templates with provenance, typed parameters, compatible consumer contracts and absent-policy behavior. Installation, proposal, adoption and enforcement activation are distinct. A parameter is effective only when its bound consumer declares and tests that exact parameter.

- AC1: A copied policy with no compatible installed consumer is visibly unsupported, never an active guard.
- AC2: Upgrades preserve local overrides and approved policy authority; no auto-promotion or overwriting live families.

Source: Owner operating-process direction, 2026-11-16 UTC; operating-processes.md and pinned legacy source evidence.

<a id="OPS-008"></a>
## OPS-008 — Explicit triage and self-heal process catalog

**MS2 · MUST · new**

Seed delivery triage, diagnosis, bounded repair, cause-cleared return and mechanism-liveness processes. Classify product, infrastructure, transient, missing evidence/access, owner input and obsolete premise separately; preserve project holds and shared fault-domain incidents.

- AC1: Infrastructure diagnosis cannot silently become infrastructure mutation; effect routes to a separately authorized owner.
- AC2: Shared outages correlate without producing one speculative code fix per project; missing evidence stays unknown.

Source: Owner operating-process direction, 2026-11-16 UTC; operating-processes.md and pinned legacy source evidence.

<a id="OPS-009"></a>
## OPS-009 — Cumulative budgets and ambiguous-effect recovery

**MS5 · MUST · new**

Execute processes under one fenced owner with stage and cumulative attempt/time/token/external-effect budgets; owner command receipts retain committed/not_committed/unknown. Reconciliation precedes replay. Pauses, new leases, process versions and child runs cannot reset the originating case budget.

- AC1: Restart/lease takeover/child run cannot exceed the same original case budget or duplicate an unknown effect.
- AC2: Exhaustion parks/escalates to a named owner under existing authority without a hidden infinite repair loop.

Source: Owner operating-process direction, 2026-11-16 UTC; operating-processes.md and pinned legacy source evidence.

<a id="OPS-010"></a>
## OPS-010 — Evidence-based recovery and process improvement

**MS5 · MUST · new**

A registered verifier must observe fresh positive evidence for the exact condition/revision before recovery. Agent exit, merged code, acknowledgement, cancelled workflow and healthy API do not prove recovered product delivery. Failed processes emit owned conditions and improvement proposals through the normal version/publication/adoption loop.

- AC1: Obsolete premise closes as premise_removed rather than recovered; verification cannot consume the actor self-attestation alone.
- AC2: Changed policy/procedure requires normal publication/adoption; repair actors cannot weaken their own guards.

Source: Owner operating-process direction, 2026-11-16 UTC; operating-processes.md and pinned legacy source evidence.
