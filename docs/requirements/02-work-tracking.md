# 02 — Work tracking, readiness and grooming

Areas: **TRK** (the tracker: what replaces the Plane board), **RDY** (readiness, preflight and
release to the queue), **GRM** (grooming and shaping).

Format of every requirement: heading `ID — title`; a tag line
`**milestone** · work package · priority · origin`; the statement; acceptance criteria (`AC`);
the estate source. Priority: MUST / SHOULD / LATER. Origin: **KEEP** (preserves a behaviour that
works today), **FIX** (keeps the intent, closes a recorded gap), **NEW** (needed for a
self-hostable product; no estate equivalent). Source abbreviations are in
[17-evidence.md](17-evidence.md).

---

## TRK — the tracker

The tracker is native. It absorbs the subset of Plane the estate actually uses and nothing else
(see [01-product-definition.md](01-product-definition.md) §5.1). The single biggest change from
Plane is that everything the conductor needs is a **typed field**, never a label, a comment
convention or a line of text inside a description.

### TRK-001 — Projects with keys and sequence numbers
**MS1** · WP1.1 · MUST · KEEP

A project has a short upper-case key (`ROVE`) and every task in it gets a monotonically increasing
sequence number; `KEY-N` is a stable, human-quotable identifier that resolves everywhere (API, CLI,
MCP, UI URL, commit trailers).

- AC1: `GET /v1/…/tasks/ROVE-12` and the opaque id return the same task.
- AC2: Sequence numbers are never reused, including after cancel; concurrent creates never collide (tested with 50 parallel creates).
- AC3: The key is unique per workspace and immutable after the first task exists.

Source: Plane identifiers `ROVE-123` are how every doc, comment and PR body refers to work (driver §1, task-pickup §8).

### TRK-002 — One task object: tracker fields plus a typed spec
**MS1** · WP1.1 · MUST · FIX

A task carries tracker fields (title, markdown body, state, priority, parent, blocked-by, rank,
labels, due date) and a typed spec (`kind`, `repo`, `outcome`, `acceptance[]`, `needs[]`,
decision fields, `inputs[]`, `builds_on[]`, `select`, `delivery`). There is exactly one copy of
each fact; the spec is not a YAML block inside the body.

- AC1: The JSON Schema for Task has `kind`, `repo`, `outcome`, `acceptance`, `needs`, `inputs`, `builds_on`; the current `spec/task.schema.json` (no `kind`, `repo` or `acceptance`) is superseded.
- AC2: Importing a legacy item whose description holds a ```` ```task ```` block produces the same typed fields, with Plane's own fields winning where both exist (title, priority, parent, relations, due date).
- AC3: Editing a field through UI, CLI or MCP changes the same stored value (one round-trip test per surface).

Source: task-ready "The task item" (field ownership table); conductor README "Plane tasks". Gap: the frozen schema drops `kind`/`repo`/`acceptance` that the live ready rules require.

### TRK-003 — Task kinds
**MS1** · WP1.1 · MUST · KEEP

`kind` is a closed set that selects the workflow and the lifecycle: operator kinds `feature`,
`fix`, `deployment`, `decision`, `parent`, `job`; system kinds `triage`, `regression`,
`follow-up`, `review` (an adopted outside PR), `ship` (a stranded build), `condition` (a
system-raised alarm, REC-023).

- AC1: Creating a task with an unknown kind is refused with a problem-detail naming the allowed set.
- AC2: Each kind declares its properties as data: `parent` and `decision` are not claimable, `job` opens no change request, and each kind names its required fields (the ready rules of RDY-001 check them from MS2).
- AC3: System kinds can only be created by system principals (IAM-008); the creator and reason are on the task.

Source: task-ready "Kinds"; driver §4 (ad-hoc jobs, triage, lock-in); conductor README "Plane sync" (`queue_adopt`, `unlanded_builds`).

### TRK-004 — Task states and reason-carrying transitions
**MS1** · WP1.1 · MUST · FIX

Board states: `backlog` (held), `todo` (planned), `in_progress`, `in_review`, `done`,
`cancelled`. Queue status is a separate typed field, not a label: `unreleased`, `released`,
`claimed`, `parked` (with reason), `handed_back` (with reason and evidence), `needs_human`
(with routes). Every transition is a named action that records actor, time and reason.

- AC1: A task cannot be `parked` or `handed_back` without a non-empty reason; the reason is shown inline on board and detail.
- AC2: `PATCH` never changes state or queue status; only action endpoints do (API-006).
- AC3: The legal-transition table is data in the repo and is unit-tested one test per transition plus one per refused transition.
- AC4: A task that is `todo` on the board and in flight in the queue cannot be represented: every action changes board state and queue status in one transaction (the claim itself is SCH-016).

Source: task-pickup §2a (state table), §conformance row 4 (HARNESS-256: board says Todo, record says claimed); labels `conductor`, `self-heal`, `needs-human` are today's queue status (driver §4).

### TRK-005 — Hierarchy: parents and children
**MS1** · WP1.1 · MUST · KEEP

A task may have one parent of kind `parent`; nesting is allowed. A parent is Done when every
planned child is Done, and nested parents close in the same evaluation. A parent in Backlog holds
all its descendants.

- AC1: Closing the last open child closes the parent, and its parent, within one reconcile (≤ 10 s).
- AC2: Moving a parent to Backlog marks every descendant held (`parent in backlog`) and moving it back clears the mark; from MS2 the mark is the reason code `held: parent in backlog` (SCH-009).
- AC3: A parent with an open child cannot be moved to Done by hand without an explicit `force` reason that is audited.

Source: driver §3 `queue_ready` (parent close), 2026-11-01 release note (#204 nested parents close); task-ready "A Backlog parent releases no children".

### TRK-006 — Dependencies are relations, and only relations
**MS1** · WP1.1 · MUST · KEEP

`blocked_by` is a typed relation between tasks in the same workspace. Cycles are refused at write
time. A dependency known only from prose does not exist; preflight (RDY-006) flags prose that
reads like a gate.

- AC1: Creating a relation that closes a cycle is refused and names the cycle.
- AC2: A task whose blockers are not all `done` shows `blocked by KEY-N`, listing each open blocker and its state; from MS2 that is the reason code `held: blocked by` (SCH-009).
- AC3: Cancelling a blocker does not clear the block silently: its dependants show `blocker cancelled` until the relation is removed or replaced.

Source: task-pickup §2 rule 3; task-ready preflight check 5 ("Prose-only gates do not exist"); CORPUS R2 (description-level dependencies are not dependencies).

### TRK-007 — Manual order is writable through the API
**MS1** · WP1.1 · MUST · FIX

Top-level tasks in a project have a manual `rank`. Drag-and-drop in the UI, `sortyardctl task
move`, and the API all write the same rank. Rank is the delivery order the scheduler reads
(SCH-002).

- AC1: `POST …/tasks/{id}/rank {before|after: KEY-N}` reorders; the next list call returns the new order (the Pickup Preview follows it from MS2, SCH-008).
- AC2: Every reorder writes a ledger event with actor, old position, new position and optional reason.
- AC3: A new top-level task lands last and the filing response says so.

Source: task-ready "Only a person dragging on the board can reorder (Plane's API does not write `sort_order`)"; 2026-11-08 release note (the import could not set starting order).

### TRK-008 — Priority tiers
**MS1** · WP1.1 · MUST · KEEP

Priority is one of `urgent`, `high`, `medium`, `low`, `none`. `urgent` is the rush lane
(SCH-005); there is no separate urgent flag.

- AC1: The schema has one field; the frozen `priority.tier` + `priority.urgent` pair is collapsed.
- AC2: Sorting by priority uses rank `urgent 0, high 1, medium 2, low 3, none 4`.

Source: `drive.py` `RANK`; spec NOTES ambiguity 4 (urgent: flag or tier?).

### TRK-009 — Labels are for people; flags are for the system
**MS1** · WP1.1 · MUST · FIX

Free-form labels exist for filtering and have no effect on scheduling. Everything the system
acts on is a typed field or relation: release status, queue status, kind, routes, selection
override, origin.

- AC1: Adding or removing any label changes no system field or state and — from MS2 — no eligibility (property test over random labels).
- AC2: Each legacy control label — `conductor`, `job`, `self-heal`, `needs-human`, `route:*`, `decision`, `follow-up`, `regression`, `red-main`, `task`, `PR` — has a typed field or relation that carries its meaning; the table is in the docs and is the one the importer uses (MIG-003).

Source: driver §3–§4 (labels as control signals); HARNESS-608/615–618 (filings invisible because a label was missing).

### TRK-010 — Notes and one activity timeline
**MS1** · WP1.1 · MUST · KEEP

People and agents can add markdown notes to a task. Notes, system events (state changes,
decisions, stage results, stall notices) and audit entries appear on one ordered timeline per
task. Machine-readable facts are typed event payloads, not text conventions inside notes.

- AC1: `GET …/tasks/{id}/timeline` returns notes and events interleaved by ledger order, paginated both ways.
- AC2: The legacy text marks (`Triage:`, `Regression:`, `Adopt:`, `Ship:`, `Select:`, `Blocking-cause:`, `Delivery:`, `Failure:`, `Builds on:`, `Vendor:`, `Decided:`) each have a typed home; none is parsed from free text at runtime.
- AC3: A system notice of a given kind is posted once per condition, not once per pass (dedupe key on the event).

Source: `drive.py` `MARK` regex and `conductor_line`; conductor README "Blocking causes", "Harness routing"; driver §4 "one comment on its Plane item".

### TRK-011 — Decisions
**MS2** · WP2.3 · MUST · KEEP

A decision task has a question, options, a recorded default, a `decide_by` time, a
`premise_class` flag and a route for whoever applies the answer. The model, the answer action
and the lifecycle (RDY-015) land together in MS2; in MS1 a decision is an ordinary task of kind
`decision`.

- AC1: A decision without `default` and `decide_by` is not ready and says why.
- AC2: An answer is an explicit chosen value recorded through the answer action; a note is never an answer.
- AC3: A decision never blocks a routine build: features are written against the default; only a premise-class decision may be a blocker.

Source: task-ready rule 6; conductor README "Plane tasks" (explicit `Decided:` only; premise-class decisions never stand on a default).

### TRK-012 — File many tasks from one file
**MS1** · WP1.2 · MUST · KEEP

`sortyardctl task file <file>` and one API call file a set of tasks from a YAML document or a
markdown file of ```` ```task ```` blocks: dependencies first, ids already present updated in
place when their text changed, never duplicated.

- AC1: Filing the same file twice creates nothing the second time (idempotent by task `external_id`).
- AC2: The call is atomic per file: a file with an unresolvable dependency files nothing and names it.
- AC3: The response lists a result per task (created, updated, unchanged or failed, with the reason) and the command exits non-zero when any failed; from MS2 each result carries the filing verdict (TRK-013).

Source: task-ready "File tasks with `plane_tasks.py file`"; conductor README "Filing visibility".

### TRK-013 — Filing verdicts: a filing is done when pickup can see it
**MS2** · WP2.1 · MUST · KEEP

Every task has a computed filing verdict: `VISIBLE`, `WILL-RELEASE`, `WAITING` (with each named
blocker), or `FAILED` (with the failed check). The verdict fails closed: an input that cannot be
read is `FAILED (read)`, never visible.

- AC1: The verdict is returned by create, by file-many, by `sortyardctl pickup status KEY-N` and on the task detail page.
- AC2: A task that stays `WILL-RELEASE` for more than 30 minutes becomes `FAILED (release)`; from MS5 it also appears on the project's single `FILING-INVISIBLE` condition (REC-023).
- AC3: Verdict vocabulary and exit codes match `pickup_status.py`, so existing agent prompts keep working.

Source: conductor README "Filing visibility"; task-pickup §9; HARNESS-251.

### TRK-014 — Board, list and filters
**MS1** · WP1.5 · MUST · NEW

The tracker has a board view (columns by state), a list view, and filters on project, state,
kind, priority, label, parent, queue status and text. Filter, sort and selection live in the URL.

- AC1: A URL copied from one browser reproduces the same view in another.
- AC2: Lists are server-paginated with cursors in both directions and show a total count.
- AC3: System-raised tasks (TRK-003 system kinds) are visually distinct and filterable in one click.

Source: harness-console journeys J2; Plane board usage (driver §6 "The owner steers in Plane").

### TRK-015 — Saved views
**MS6** · WP6.4 · SHOULD · NEW

An operator can save a filter set under a name, per user or shared with the workspace.

- AC1: A saved view is an API object; the UI is a client of it.
- AC2: Deleting a shared view is audited.

Source: Plane saved views (DESIGN §5.2 option C: concepts taken, not code).

### TRK-016 — Bulk edit
**MS6** · WP6.4 · SHOULD · NEW

Select many tasks and change state, priority, labels or parent in one audited operation.

- AC1: A bulk change of N tasks is one request, N ledger events, one audit entry linking them.
- AC2: A bulk change that would break an invariant for any task applies to none and names the offenders.

Source: the 2026-11-08 import and the queue audits were bulk operations done by script.

### TRK-017 — Links
**MS4** · WP4.1 · MUST · KEEP

A task has typed links: pull requests, commits, CI runs, other tasks, external URLs. Links
created by the system (the PR a chain opened) are facts with an observed-at time.

- AC1: A task's PR link shows state (open, merged, closed) as last observed, with the observation time.
- AC2: An internal-only URL is labelled as such when rendered into anything a worker will read (EXE-015).

Source: `pr_body` incident note (workers followed a tailnet-only Plane link and reported missing evidence).

### TRK-018 — Follow-up items never enter the queue by themselves
**MS4** · WP4.4 · MUST · KEEP

Follow-ups from reviews are created in Backlog at low priority, unreleased, linked to the PR and
the originating task; one item per approval, deduplicated across rounds.

- AC1: A follow-up is never claimed until a person or grooming moves it to Todo and releases it.
- AC2: A review that lists the same finding in two rounds produces one follow-up.
- AC3: Filing survives a tracker write failure: queued on the chain record and retried every reconcile.

Source: driver §4 (reviewing); TEST-REVIEW "Review scope" (PRE-EXISTING → follow-ups, `retry_test_follow_ups`).

### TRK-019 — File attachments
**LATER** · — · LATER · NEW

Binary attachments on tasks are out of scope for 1.0; links cover the estate's use.

- AC1: The schema reserves no attachment field in v1; adding one later is an additive API change.

Source: inference — no attachment use found in the conductor, plane-sync or the operations docs.

---

## RDY — readiness, preflight and release

Three gates stand between "a task exists" and "a task may be claimed": **ready** (its shape),
**preflight** (the world the build will run in), **release** (handing it to the scheduler once).
Today they live in `plane_tasks.py`, `preflight.py` and `plane_sync._queue_ready`.

### RDY-001 — Ready rules check the task's shape
**MS2** · WP2.1 · MUST · KEEP

A task is ready when: it names one registered repo and one single-sentence outcome; its
acceptance entries are named tests (`test` + `name`) or journeys; parent and blockers resolve in
the same project; priority is valid; a `deployment` lists its `needs`; a `decision` has a default
and `decide_by`. Required fields per kind follow task-ready's table.

- AC1: Each rule has an id and a message; `GET …/tasks/{id}/readiness` lists every failing rule.
- AC2: Whether acceptance is required is policy data per project (`ready.require_acceptance`, default `true` for `feature` and `fix`) — see open decision OD-10.
- AC3: A feature whose text names a deploy, production, real accounts, credentials or owner sign-off fails rule `placement` and is told to split into a `deployment` or `decision`.

Source: task-ready "Ready rules" 1–6 and "Kinds"; AGENTS.md "Delivery lanes" rule 6.

### RDY-002 — Sizing lints are warnings
**MS2** · WP2.1 · SHOULD · KEEP

The "one PR's worth" rules that can be checked mechanically run as warnings that never change
readiness: more than three acceptance tests, "and" joining two results in the outcome, a title
with more than one verb/object.

- AC1: Warnings are returned next to the verdict and shown on the task; they are never errors.
- AC2: False positives are expected: there is no way to turn a warning into a hold without a policy change.

Source: task-ready "One PR's worth" (rules 2–4 as `warn:`).

### RDY-003 — Release happens once
**MS2** · WP2.1 · MUST · KEEP

The system releases a ready `feature`, `fix` or `deployment` in Todo exactly once. If a person
withdraws the release, it stays withdrawn until a person releases it again.

- AC1: A task un-released by an operator is never re-released by the system (tested across restarts and upgrades).
- AC2: The release event records which rules and checks passed and their versions.

Source: task-pickup §2 rule 5 ("taking the label off sticks").

### RDY-004 — Release conditions
**MS2** · WP2.1 · MUST · KEEP

Release requires: ready (RDY-001); every blocker Done; parent not in Backlog; `repo` belongs to
the project; preflight passed (RDY-005); the project has release switched on. The evaluation
reads one consistent snapshot.

- AC1: With release switched off for a project, decisions and parents still run their lifecycle and nothing is released.
- AC2: A failure to evaluate one task (bad data) holds that task with a reason and never stops others.

Source: task-pickup §2; driver §1 (`tasks: on|off`).

### RDY-005 — Preflight: named checks against live surfaces
**MS2** · WP2.2 · MUST · KEEP

Before release, every applicable preflight check must pass against the surface the build will
really use. A check that cannot run is `unverifiable` and holds the task exactly like a failure.
A held task stays visible in Todo, unreleased, with one notice naming each failed check and its
fix; a new notice appears only when the set of failing checks changes.

- AC1: Each check has a stable id, an owner (who fixes it) and a fix hint; results are stored per task with the time and the evidence read.
- AC2: No check reads a parallel store or a cache of the thing it verifies.
- AC3: Preflight re-runs when the task, the project config or a relevant integration changes, and at claim time (SCH-017).

Source: task-ready "De-risking: the preflight gate"; conductor README "Preflight"; the 2026-11-09 Sortyard stall (six tasks claimed into an unregistered build target).

### RDY-006 — The v1 preflight checks
**MS2** · WP2.2 · MUST · KEEP

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

### RDY-007 — Needs are routed to whoever can meet them
**MS2** · WP2.3 · MUST · KEEP

Each `need` has a description and a route: `devops`, `owner` or `agent` (default `devops`). A
task held only by needs is `needs_human` with its routes. `owner` creates a linked decision;
`agent` queues a linked job with the step and its completion check. Removing a met need
re-evaluates release.

- AC1: The "routed to me" list for each route is one API call and one UI view.
- AC2: A need is discharged by an explicit action recording who, when and the verification reference.
- AC3: With all needs met, a ready task is released on the next evaluation without anyone touching it again.

Source: k3s driver "Discharging needs and decisions"; HARNESS-247.

### RDY-008 — Outcome already met
**MS2** · WP2.3 · SHOULD · KEEP

When discharging a deployment's needs delivered its whole outcome, the task closes Done on a
recorded, non-empty verification instead of being built.

- AC1: `outcome_met.verification` must name the check and what it established; an empty value is refused.
- AC2: The task closes as the same item (no duplicate), keeping the verification on its timeline.

Source: k3s driver "Discharging needs and decisions" (`outcome_met`); HARNESS-272.

### RDY-009 — Premise rules as an optional policy pack
**MS5** · WP5.10 · SHOULD · KEEP

The estate's premise rules ship as a policy pack, off by default: `intended_use` recorded as
consistent/contradicts; reference-clone quarantine (capabilities taken, business shape not taken
or imported by a premise-class decision); access tasks cite a decision that decides that
specific target.

- AC1: With the pack enabled, a task whose milestone contradicts the project's intended-use record is not ready, and neither is anything under it.
- AC2: A citation of a decision that decides a different question raises one `CITATION-MISMATCH` condition routed to the owner, never duplicated.
- AC3: The pack is data plus checks registered in the preflight framework; core has no NonceLogic-specific wording.

Source: conductor README "Plane tasks" (intended use, reference clones, access citations; grounding cases A05-D1, Loopmentum/Okara).

### RDY-010 — No side door into the queue
**MS2** · WP2.1 · MUST · FIX

A task created directly as released (the legacy `add_item.py` path) passes the same ready and
preflight gates as a planned task. There is no project setting that bypasses them.

- AC1: `sortyardctl task add --release` on a task that fails preflight returns `FAILED (preflight …)` and leaves it unreleased.
- AC2: Ad-hoc `job` tasks run the checks that apply to jobs (`build-target`, `evidence-reach`, `inputs`).

Source: task-ready ("directly-filed items on `tasks: off` boards bypass even the ready rules", HARNESS-504).

### RDY-011 — Retroactive queue audit
**MS2** · WP2.9 · SHOULD · KEEP

One command re-runs ready and preflight over everything already released or planned and reports
per project; with `--apply` it withdraws release from failing items with one notice each. It
never releases anything.

- AC1: The report is deterministic and diff-able between runs.
- AC2: `--fixtures` writes each failure as a replayable preflight fixture.

Source: conductor README "Retroactive audit" (`queue_audit.py`, COND-505).

### RDY-012 — A hand-back owes a check or a gap
**MS5** · WP5.2 · SHOULD · KEEP

Resolving a hand-back requires recording either the preflight check that would have caught it or
a process-gap task explaining why it cannot be checked.

- AC1: The self-heal resolution action refuses to close without `preventable_by` (a check id or a task reference).
- AC2: A monthly report lists hand-backs by `preventable_by`.

Source: task-ready ("every hand-back owes one of two things in the same pass that returns it").

### RDY-013 — One bad project config never stops the others
**MS2** · WP2.4 · MUST · KEEP

Project configuration is validated entry by entry. An invalid entry is dropped for that
evaluation and marks the project `config-invalid`, naming the rule it breaks (from MS5 as one
`CONFIG-INVALID <project>` condition, REC-023); every other project runs normally.

- AC1: Injecting an invalid config for one project leaves the claims of the others unchanged (replay test).
- AC2: The mark clears only when that project's config validates.

Source: conductor README "Product configuration failsafe" (2026-11-10).

### RDY-014 — Estate preconditions for production flips
**MS5** · WP5.10 · SHOULD · KEEP

A task that flips production cannot be released until the estate facts it assumes are named
blockers or needs and are discharged; urgency alone never exempts it.

- AC1: A production-flip task with an undischarged precondition is ineligible even when `urgent`.
- AC2: The verification dependency stays on the task after the need is removed, so the evidence survives.

Source: conductor README "Plane sync" `cutover_readiness`; `gate_cutover_pickup` note ("Urgency alone cannot exempt a plan-backed production flip"); DESIGN §3.7b (HARNESS-274).

### RDY-015 — Decision lifecycle
**MS2** · WP2.3 · MUST · KEEP

An unanswered routine decision takes its default at `decide_by`: a notice, then Done. An answered
decision stays open, routed to whoever applies the answer. A premise-class decision never takes
its default: past `decide_by` it is escalated once to the owner list and stays open. A decision
recorded as decided closes on the next evaluation.

- AC1: Time-travel test: at `decide_by + 1 s` a routine decision is Done with a "default applied" event; a premise-class one is `needs_human` routed to `owner`.
- AC2: The answer is re-read from the store at every evaluation; nothing is trusted from a cache.
- AC3: Work blocked by a premise-class decision is never released while it is undecided.

Source: conductor README "Plane tasks"; task-pickup §2 table; LOOP-632 and LOOP-DEC-FIRST-CUSTOMER grounding cases.

---

## GRM — grooming and shaping

Grooming is a system function. It is implemented as ordinary workflow runs (FLW-001) with a
validator in front of the tracker, not as a separate service.

### GRM-001 — An empty eligible queue with known work is a defect
**MS5** · WP5.7 · MUST · KEEP

When a project's eligible queue is empty and known work exists (unshaped milestones, recorded
findings, tripwire items), the system starts a grooming run for that project.

- AC1: With the queue emptied in a fixture, a grooming run is dispatched within one evaluation; with no known work, none is dispatched.
- AC2: New observations arriving during a run stay pending for the next run.

Source: conductor README (grooming process step); DESIGN §3.5 ("never an empty groomed queue").

### GRM-002 — Grooming runs on the frontier model, or says so
**MS5** · WP5.7 · MUST · KEEP

Grooming's judgment runs on the model the policy names. A result from another model is rejected
before anything is filed, except a fallback the system itself stamped because no eligible
account existed; the stamp is kept on the run and its receipt.

- AC1: A result whose recorded actual model differs from policy, without a system fallback stamp, files nothing and the run is marked failed with that reason.
- AC2: The model rule is policy data (`grooming.model`, `grooming.accept_stamped_fallback`).

Source: conductor README (grooming: "rejects a missing or non-Opus actual-model receipt … except a Codex result that MH stamped as the model-fallback move").

### GRM-003 — Grooming output is validated before it reaches the board
**MS5** · WP5.7 · MUST · KEEP

The validator rejects: missing hindsight citations, repeated root causes, unready builds, builds
gated on routine decisions, dependency cycles, edits to existing tasks, report-only results, and
a no-work disposition for an input that requires work. Every new task must be `VISIBLE` or
`WAITING` on named board work.

- AC1: Each rejection reason has a fixture; a rejected run files nothing.
- AC2: A plan-caused pickup failure triggers one repair run restricted to the ids it filed; filed ids are corrected in place, never duplicated.
- AC3: A lost response is recovered by id from the store; the same input never files twice.

Source: conductor README (grooming validation, repair, `grooming.json` recovery).

### GRM-004 — Grooming inputs and their bookkeeping
**MS5** · WP5.7 · SHOULD · KEEP

Inputs are finished findings runs, findings documents, tripwire items and stale premises, each
identified by content hash. An input is consumed only when its disposition is recorded
(`filed`, `covered:<task>`, `no-work:<why>`). Packets fill newest-first to the size cap; what
does not fit is deferred, never dropped.

- AC1: An over-budget packet defers inputs and still dispatches; it is never a terminal failure.
- AC2: The run record holds dispatch identity, inputs, phase, filed ids and per-task pickup evidence.

Source: conductor README (grooming packets, 200,000-character limit, `grooming.json`).

### GRM-005 — Grooming silence raises an alarm
**MS5** · WP5.7 · MUST · KEEP

After two consecutive failed grooming attempts, or an eligible queue empty for more than 60
minutes with no run dispatched, one `GROOMING-STALLED <project>` condition is raised with the
error, attempt count, queue-empty-since time and the pickup status of every open planned task.

- AC1: The condition is updated in place, never duplicated, and closes when the project has an eligible head again.
- AC2: Both thresholds are policy data.

Source: conductor README ("Silence is the defect").

### GRM-006 — Shaping turns an unready task into ready ones
**MS5** · WP5.7 · SHOULD · KEEP

A task that fails readiness or the sizing checks goes to shaping: one agent run, no reviews, that
produces ready children, decisions and deployment tasks under the same parent, keeping the
original id for the first piece.

- AC1: The driver never fills gaps itself: an unready task is never dispatched to a build.
- AC2: Split ids follow `X-F3`, `X-F3b`, `X-F3c`; later pieces depend on earlier ones only where stated.

Source: task-ready ("The driver never fills gaps itself"; "One PR's worth" rules 5–6).

### GRM-007 — Internal consistency sweep replaces drift consolidation
**MS5** · WP5.7 · SHOULD · FIX

A daily sweep reports what can still drift inside one store: duplicate tasks, Done parents with
open children, Done tasks with open PRs they own, open failure items with no recorded reason.
Each finding is one deduplicated condition.

- AC1: The plan↔board↔STATUS.md↔register comparisons of `drift.py` have no equivalent because those copies no longer exist; the sweep's scope is documented as exactly the list above.
- AC2: A sweep whose read fails reports failure and is retried; it never reports "clean".

Source: conductor README "Drift consolidation" and `queue_reconciliation`; HARNESS-249.

### GRM-008 — Reality reconciliation
**LATER** · — · LATER · KEEP

Comparing task premises against a recorded product-state file (connected sites, live
installations) and forcing a fix task on divergence is kept as an estate policy pack after 1.0.

- AC1: Until it ships, the estate keeps running the comparison as a sensor that files tasks through the API (EXT-004).

Source: conductor README (grooming `reality:` observations; Joe 2026-11-06).
