# 05 — Delivery flow, landing, CI health and delivery verification

Areas: **FLW** (workflows and the chain state machine), **MRG** (landing and merge safety),
**CIH** (CI and main-branch health), **DLV** (post-merge delivery verification). Together they
replace `drive.py`'s step machine, `design_review.py`, `test_review.py`, `release_verify.py`,
`delivery.py`, the triage half of `plane_sync.py`, and `ship.py`.

What ships is the flow that runs today — the owner's "Delivery lanes" (AGENTS.md, 2026-10-25):
build, one code review, a test-determinism review, a design review for UI changes, auto-merge.
The older template workflows (Frame → Judge → Shape → Build → Verify) and the three review
"regimes" of DESIGN §3.6 are not built in; the engine can express them as definitions later.

---

## FLW — workflows and chains

### FLW-001 — Workflows are data
**MS3** · WP3.1 · MUST · KEEP

A workflow is a versioned definition: phases, the stage each phase launches (stage class,
packet template, harness profile), and transitions keyed on observed outcomes. A chain is one
task's run through one pinned workflow version.

- AC1: The built-in workflows are loaded from the default bundle (DEF-008), not hard-coded; replacing a packet template needs no code change.
- AC2: A workflow that declares a stage needing a live third party or a deployment environment is refused at apply time (`pipeline-purity`).
- AC3: There is no human-gate stage type: people act through decisions and needs (RDY-007, RDY-015).

Source: `drive.py` docstring and phases; DESIGN §3.4, §3.6 `pipeline_purity`; AGENTS.md "Delivery lanes".

### FLW-002 — The `change` workflow
**MS3** · WP3.4 · MUST · KEEP

For `feature`, `fix`, `deployment`, `regression` and `triage` tasks:
`claimed → building → landing (branch + change request) → reviewing → merging → [confirming] →
[awaiting-deployment] → done`, with `fixing` loops from review rejection, red required checks and
conflicts, and `parked` / `handed-back` exits from any phase. MS3 delivers it on the plain-git
adapter; MS4 on GitHub.

- AC1: A fixture chain passes through every phase in order and each transition names the observed fact that caused it.
- AC2: Each phase has an end condition and a bound (REC-001); the phase table is generated into the docs from the definition.

Source: task-pickup §2a (state table), §5 (what ends a phase); conductor README "Drive loop".

### FLW-003 — The `job` workflow
**MS3** · WP3.1 · MUST · KEEP

A `job` task runs one verify-class stage on the default branch with the task's title and body as
instructions. The worker's report is attached to the task exactly once and the task goes Done.
No branch, no change request. A run that produces no report is retried twice, then parked.

- AC1: If attaching the report or closing the task fails, the next reconcile retries it and the report still appears once.
- AC2: `urgent` jobs run in the rush lane at the next evaluation.
- AC3: The job packet states what a job cannot do (reach the Git host, CI runners or the cluster) so the report says what is needed instead.

Source: driver §4 "Ad-hoc jobs"; `add_item.py --job`.

### FLW-004 — One step per reconcile, on observed facts only
**MS3** · WP3.1 · MUST · KEEP

Each reconcile advances a chain by at most one transition, and every transition is triggered by
an observed fact (a Job finished, a check concluded, a change request merged), never by a
worker's claim about itself.

- AC1: Replaying a chain's event history reproduces its state (replay test over recorded fixtures).
- AC2: A reconcile is safe to repeat: running it twice with no new facts changes nothing.

Source: AGENTS.md "The rule" ("Advance only on observed state, never on a self-report"); `drive.step` ("Advance one claimed item by one step").

### FLW-005 — Code review and its verdict protocol
**MS4** · WP4.4 · MUST · KEEP

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

### FLW-006 — Review scope rules
**MS4** · WP4.4 · MUST · KEEP

(a) Every review reads the task as the board states it now; findings recorded against an older
text are dropped. (b) The review of a fix head is given the earlier findings and checks those,
without raising new findings about code the earlier review saw. (c) After an approval, a later
round's review covers only that round's change (`diff <approved head>..HEAD`), so a merge of the
default branch does not reopen an approval. (d) A review holds a task to its own scope: a
finding in a surface the task does not change becomes a new `fix` task, not a rejection.

- AC1: Editing a task's body between review rounds makes the next review start clean (fixture).
- AC2: A clean merge of the default branch into an approved change request triggers a review scoped to the merge delta only, before auto-merge is re-armed (MRG-005).

Source: driver §4 (k3s-harness #185, #188); `refresh_task` (CPV2-501); task-ready "One PR's worth" rule 7; `drive.py` note 197 ("Review the new head before re-arming its auto-merge").

### FLW-007 — Test-determinism review
**MS4** · WP4.5 · MUST · KEEP

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

### FLW-008 — Design review for UI changes
**MS5** · WP5.9 · SHOULD · KEEP

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

### FLW-009 — Merge is armed only with every required verdict on the exact head
**MS4** · WP4.4 · MUST · KEEP

Auto-merge is armed only when each review the policy requires has a ready verdict recorded for
the current head commit. A head that moves needs fresh verdicts; a standalone or older approval
never arms a merge.

- AC1: Property test: for any sequence of pushes and verdicts, auto-merge is armed only in states where all required verdicts match the head.
- AC2: Each gate declares its absent-state behaviour (`block` or `proceed-and-report`) in policy; a gate with no declared absent state is refused at apply time.

Source: TEST-REVIEW "Verdicts and merge enforcement"; `land_approved` note 933; AGENTS.md "Every eval gate defines its absent state".

### FLW-010 — Fix rounds continue while the failure changes
**MS4** · WP4.6 · MUST · KEEP

A rejected review or a red required check starts a fix round on the same change request. Rounds
continue while what is wrong changes. The same failure immediately after a round — the same
failing check set and failing test lines, or the same review findings with run paths and spacing
normalised — parks the task. A backstop (default 10) ends it regardless. A round is counted only
once it was actually submitted.

- AC1: A round that fixes one test and trips another in the same check counts as progress and continues.
- AC2: Two rounds with identical normalised findings park with reason `same failure came back` and both rounds' evidence.
- AC3: A refused submit is not a round.

Source: driver §4 "fixing" (`FIX_ROUNDS = 10`; k3s-harness #199, #210; CPV2-460, ROVE-585); `check_failure`, `same_text`. This closes the design's "one unverified fact" (SORTYARD-1 / HARNESS-286).

### FLW-011 — Conflict rounds are counted apart
**MS4** · WP4.6 · MUST · KEEP

When the default branch conflicts with the change request, the controller performs the merge
itself, commits the conflict with markers into the mirror only, and a fix round resolves the
listed files on top. Nothing with markers is ever pushed to the Git host. Conflict rounds have
their own limit (default 5) because a sibling merging first is not the task's defect.

- AC1: A scan of the pushed head for conflict markers is part of the landing step and blocks the push.
- AC2: Conflict rounds do not count toward the fix-round backstop nor, once it exists, toward the review tripwire (FLW-012).

Source: driver §4 "merging" (`merge_main`, `CONFLICT_ROUNDS = 5`); `drive.py` notes 121, 419.

### FLW-012 — Review tripwire
**MS5** · WP5.3 · MUST · KEEP

Each task keeps cumulative counts of code reviews and test reviews that returned a verdict.
Parks, hand-backs, returns and requeues never reset them; only a merge does. When either count
reaches the tripwire (default 5) without a merge, the task is stopped with reason
`review tripwire`, is never auto-returned, and goes to grooming with its findings to be narrowed
to one PR's worth and split.

- AC1: A requeue of a stopped task stops again at its next review.
- AC2: Reviews that never ran, `unavailable` test reviews, conflict rounds and CI fix rounds are not counted.
- AC3: Grooming's disposition for a tripwire input must be `filed` or `covered`, never `no-work`.

Source: conductor README "Review tripwire" (46 of 378 items reached five or more code reviews and took 44% of all requests, 2026-11-03..10); task-ready rule 10.

### FLW-013 — Resuming a parked task
**MS4** · WP4.7 · MUST · KEEP

A parked task that is requeued while its change request is still open at the head Sortyard last
pushed resumes on it: fresh reviews of that head, then merge or new fix rounds — no rebuild. A
change request moved by someone else is closed as superseded and the task rebuilds from the
default branch. If the change request merged while parked, the task goes Done on the next
reconcile.

- AC1: Verdicts cached before the park are not reused after resume.
- AC2: Rebuilding never collides with an open change request's branch.

Source: driver §4 "blocked"; `resume_parked` incident note (ROVE-754).

### FLW-014 — Adopting change requests opened outside Sortyard
**MS4** · WP4.7 · SHOULD · KEEP

For a green, non-draft change request opened outside Sortyard in a driven repo, with no
hold/do-not-merge/wip label and a plain branch name, Sortyard creates one `review` task per head,
runs the required reviews once, and either arms auto-merge on that exact head or posts the
findings on the change request. It never pushes to or merges into a branch it did not open.

- AC1: A push to an adopted change request after its review creates a new review task for the new head.
- AC2: Branch names are treated as untrusted input everywhere they reach a shell or a ref (MRG-013).

Source: 2026-11-03 release note (#217: loopmentum #498 waited 8 h because no review reached outside PRs); `queue_adopt`; `drive.py` note 417.

### FLW-015 — Landing sweep
**MS4** · WP4.7 · SHOULD · KEEP

On every reconcile, any open change request in a driven repo whose exact head has all required
approvals in Sortyard's record gets auto-merge armed, whoever opened it. Drafts and conflicting
change requests are skipped.

- AC1: An approved, green change request never waits for an agent to remember to land it.

Source: driver §4 "Landing sweep"; conductor README "Drive loop".

### FLW-016 — Stranded builds
**MS5** · WP5.9 · SHOULD · KEEP

A finished build with no change request is detected. If a task requested it, the task is
cancelled or noted with the reason after a grace period; if nothing requested it and its commit
is still held, one low-priority `ship` task retries the landing. If an implausible share of
builds look stranded, the detector raises an alarm about itself and acts on nothing.

- AC1: A build whose run directory no longer holds its head is reported lost once, with no task filed.
- AC2: The self-doubt threshold is policy data.

Source: conductor README "Plane sync" `unlanded_builds` (`STRAND_ACT_HOURS`, `STRAND_ALARM`, `SHIP_CAP`).

### FLW-017 — Design-first workflows are expressible, not shipped
**LATER** · — · LATER · KEEP

The engine can express a design → reviews → approval → build → verify workflow with a revision
cap. No such workflow, and no self-repair that edits and redeploys the control plane, ships in
1.0. The cut is conditional: if the usage census (MIG-017) counts design chains started in its
window, a design-first workflow is added to the estate bundle before the first cutover.
Self-repair of the control plane is not carried in either case; changes to Sortyard go through
Sortyard and a release.

- AC1: A test bundle defines a three-phase workflow with a review loop and a round cap, and runs on the scripted harness.

Source: `mh.py` chains (`CHAIN_ROUND_CAP = 4`, `CHAIN_REPAIR_MAX_ATTEMPTS = 2`); inference — the conductor path does not call chains (no reference in `control-plane/conductor/*.py`).

### FLW-018 — Attempts are immutable history
**MS3** · WP3.1 · MUST · KEEP

Every stage attempt is kept with its origin (`first`, `retry`, `recovery`), queue-entered time,
schedule time, start, finish and outcome. A failure followed by a successful retry belongs to the
final outcome and keeps its failed-attempt history.

- AC1: Metrics count attempts and chains separately; a retry never appears as an extra chain.
- AC2: Attempt timestamps are sufficient to compute pickup latency and execution time (OBS-007) without proxies.

Source: `mh_task_attempts` (notes); factory-measurement-contract ("Preserve an immutable attempt for each retry/requeue"; `request_updated_at_proxy` as a known weakness).

### FLW-019 — The control plane adds almost nothing to a task's time
**MS4** · WP4.7 · MUST · FIX

Every hand-off inside a chain — stage finished to next stage dispatched, checks green to
auto-merge armed, review verdict to fix round, merge observed to Done — happens on the event
that enables it, not at the next pass. The time a chain spends waiting on Sortyard itself (not
on an agent, CI, a review or a free slot) is measured per chain as `chain.control_wait` and
shown beside its cycle time.

- AC1: Demonstration (ledger, MS4) — `chain.control_wait` is computed for every chain of the delivery scenario suite and compared with the same hand-offs in the legacy records. Target: p95 at most 60 s per chain, summed over all its hand-offs. Floor: at most half the legacy wait for the same number of hand-offs, each of which waits for the next three-minute or five-minute pass (BL-03).
- AC2: Demonstration (ledger, MS7) — release-to-merge time of one-PR tasks in the pilot, from the ledger, against the same project's legacy figure. Target: p50 at most 30 minutes for a task whose CI takes 10 minutes. Floor: a lower p50 and a lower p90 than the legacy baseline for tasks of the same kind (BL-02).
- AC3: Git host and CI facts arrive by webhook where the installation can receive them and by polling otherwise (API-016); the polling interval for change requests with a chain in flight is policy (default 10 s, with conditional requests, so an unchanged answer costs no rate limit).

Baseline: Every hand-off waits for the next pass: the drive pass runs every 3 minutes and the sync every 5 (task-pickup §3; BL-03). Time from release to merge is not measured today (BL-02).

Better on: latency, throughput.

Source: task-pickup §3 (pass cadence); AGENTS.md "The rule" (advance on observed state). Inference: a chain's legacy wait is its number of hand-offs times the mean wait for a pass.

---

## MRG — landing and merge safety

### MRG-001 — The integrator is the only writer to the Git host
**MS3** · WP3.4 · MUST · KEEP

One component, the integrator, performs every write to a Git host: pushing branches, opening and
updating change requests, arming and disarming auto-merge, posting verdict comments. It holds the
write credential and nothing else holds it.

- AC1: Manifest test: the write credential is mounted only in the integrator pod.
- AC2: Every write is requested by the controller for a specific chain epoch and refused if the epoch is stale (REC-020).

Source: DESIGN §3.7a (fenced single writer); conductor README ("GitHub writes use the per-run GH_TOKEN").

### MRG-002 — Branches and change requests are created idempotently
**MS4** · WP4.1 · MUST · KEEP

The integrator pushes the stage's commits to a branch named for the task and opens a change
request, or reuses the open one. The body is the task's full text plus a link note. Each step
records a marker before the next, so a failure after the push resumes at change-request creation
and never re-runs the build or duplicates the change request.

- AC1: Kill the integrator after each step: the chain resumes at the next step with no duplicate branch or change request.
- AC2: A leftover branch of a requeued task with no open change request is overwritten; one with an open change request is not.

Source: driver "Recovery" (push marker); `push_branch`, `pr_body` notes.

### MRG-003 — Merge only through the host's own gate, bound to the reviewed head
**MS4** · WP4.1 · MUST · KEEP

Sortyard merges by arming the host's auto-merge for the exact reviewed head commit
(squash by default). It never merges directly, never force-pushes a default branch, and never
adds a merge gate of its own to the repo.

- AC1: The GitHub fake records every API call; the suite asserts zero direct merges and zero admin merges in the default policy.
- AC2: Auto-merge armed for head A does not merge head B (head-match parameter always sent).

Source: driver §4 "Hard rules" ("never `--admin`, never a direct merge, never `ship.py merge`, never a merge gate"); `gh pr merge --auto --squash --match-head-commit`.

### MRG-004 — Merging past a quarantined job is a policy, and the estate keeps it
**MS5** · WP5.5 · SHOULD · KEEP

The legacy system lands an approved head past a quarantined flaky job with an admin merge, once
per head, when every other required check has an accepted conclusion. Sortyard keeps the
behaviour as a policy (`merge.quarantine_bypass`): when on, it needs a credential with bypass
rights, acts once per head, and records the quarantined jobs it passed. The estate bundle ships
it on, as today. The default bundle for new installations ships it off, which is a default for
strangers and not a change for the estate (OD-9).

- AC1: With the policy off, a change request held only by a quarantined job waits and shows `held: quarantined job gates merge`.
- AC2: With the policy on and any non-quarantined required check not accepted, no bypass happens.
- AC3: With the estate bundle applied, the JOB-QUARANTINE scenario — only quarantined jobs failing, every other required check accepted — merges the approved head once, as the legacy system does.

Source: JOB-QUARANTINE.md "Quarantine" (`gh pr merge --squash --admin --match-head-commit`), which contradicts the driver's "never `--admin`". Owner decision OD-9. Kept for the estate on 2026-11-12: switching it off there would hold approved changes that merge today, with no measured gain to set against that.

### MRG-005 — Behind or conflicting change requests are brought up to date by Sortyard
**MS4** · WP4.6 · MUST · KEEP

A change request that is behind or conflicting would wait forever on auto-merge. Sortyard merges
the default branch in: a clean merge is pushed and reviewed (scope: the merge delta) before
auto-merge is re-armed; a conflicted merge starts a conflict round (FLW-011).

- AC1: Auto-merge armed for the old head is disabled before the new head is pushed.
- AC2: For an adopted change request Sortyard never performs the merge; it tells the author.

Source: driver §4 "merging"; `drive.py` notes 196, 197, 417.

### MRG-006 — Only required checks drive rounds, and the policy is never guessed
**MS4** · WP4.1 · MUST · KEEP

The required checks are read from the repo's branch protection or rulesets. Only a failing
required check starts a CI fix round; a non-required failure is noted on the task. If the policy
cannot be read, Sortyard does not guess: it reads again next reconcile. A required check with no
run on the head, once the others are green, starts a fix round — immediately when the host
rejected a workflow file on that head, otherwise after a grace period (default 30 min).

- AC1: With an unreadable protection policy, zero fix rounds start.
- AC2: A required roll-up job (one that needs others and always runs) is replaced by the red jobs it needs when deciding what failed.

Source: conductor README "Incident notes" `ci_round` (LOOP-771, LOOP-774), `missing_checks` (cortexplane #1132 sat 20 h); `CHECKS_GRACE`; `drive.py` notes 239, 1102, 1103.

### MRG-007 — A fix head drops the earlier head's auto-merge first
**MS4** · WP4.6 · MUST · KEEP

Before a fix round's head is pushed, auto-merge armed for the earlier head is disabled, so the
new head merges only after its own reviews.

- AC1: Sequence test: no window exists in which an unreviewed head has auto-merge armed.

Source: driver §4 "fixing" (`gh pr merge --disable-auto`); `drive.py` notes 401, 402.

### MRG-008 — Observing the outcome of a merge
**MS4** · WP4.1 · MUST · KEEP

Merged → the chain proceeds to `confirming`, `awaiting-deployment` or done. Closed without
merging → parked with that reason. A squash that landed while the change request still reads open
is recognised only by proof: the candidate's tree equals the change's merge-base diff applied to
the candidate's parent, and the subject matches.

- AC1: A parked task whose change request merges later goes Done on the next reconcile, through the same completion gate as a normal merge.
- AC2: A task escalated to a person is not turned Done by a later merge sweep.

Source: task-pickup §5; `drive.py` notes 122 (prove a squash landed), 427, 934.

### MRG-009 — A stalled merge frees its slot
**MS4** · WP4.6 · MUST · KEEP

A clean, green, armed change request that has not merged after the stall threshold (default 4 h)
gets auto-merge re-triggered once and another threshold; then the task parks. The re-trigger is
recorded before the host is called, so a partial failure cannot loop it.

- AC1: The worked case in task-pickup §8 (two slots held about nine hours) is a scenario test that ends with both slots freed at the threshold.

Source: task-pickup §5 and conformance row 1 (HARNESS-242); `drive.py` note 416.

### MRG-010 — Superseded CI runs are cancelled on merge
**MS4** · WP4.6 · SHOULD · KEEP

When a change request merges, its own unfinished pull-request runs are cancelled, best effort.
Without the permission, the runs are left to finish and the missing permission is reported once.

- AC1: Cancellation failure never fails or delays the chain.

Source: 2026-11-04 release note (#219: loopmentum #510 merged while its PR CI held 12 jobs queued ahead of main CI).

### MRG-011 — Landing on a plain Git remote
**MS3** · WP3.4 · MUST · NEW

For a repo with no hosted change requests, the integrator lands an approved candidate on the
default branch only when: a passed receipt exists for the exact `(base, candidate)` pair
(EXE-017); every required review approved the exact candidate; the default branch still equals
`base`, or the candidate is re-proved on the new base; the landed tree is identical to the
candidate's tree.

- AC1: Moving the default branch between proof and landing forces a re-proof; nothing lands on a stale base.
- AC2: The demo and the product's own CI use this adapter; no network access beyond the cluster is needed.

Source: `ship.py` fence as described in DESIGN §3.7a (proof receipt for the exact pair, verify approval of the exact head, tree identity); AGENTS.md "pipeline purity".

### MRG-012 — Internal pushes ignore repo hooks
**MS4** · WP4.6 · SHOULD · KEEP

Pushes between Sortyard's own stores (seeding the mirror, staging refs) bypass the repo's hooks.

- AC1: A repo with a refusing pre-push hook still has its change-request head seeded into the mirror.

Source: driver "Recovery" (`core.hooksPath=/dev/null --no-verify`; Loopmentum's local-proof hook).

### MRG-013 — Refs and names from outside are untrusted input
**MS4** · WP4.1 · MUST · KEEP

Branch names, change-request titles and file paths from the Git host are never interpolated into
a shell or a ref unquoted.

- AC1: A change request whose branch is named `x/$(id)` is handled without executing anything (regression test).

Source: `drive.py` note 376 ("branch names reach a shell: an outside PR's can be `x/$(id)`").

---

## CIH — CI and main-branch health

The CI provider is an adapter (CIH-013). Requirements below are stated for GitHub Actions, the
one adapter 1.0 ships.

### CIH-001 — Sensing a red default branch
**MS5** · WP5.4 · MUST · KEEP

For each driven repo Sortyard observes: failing push runs on the default branch, failing
scheduled workflows, and workflows triggered by other workflows (deploys). A hand-started run on
the default branch counts as that workflow's newest run. Only live workflows count (active and
present on the default branch), and only runs newer than the repo's onboarding.

- AC1: A red `workflow_run`-triggered deploy on the default branch is sensed.
- AC2: Onboarding a repo files nothing for workflows deleted months ago or runs older than onboarding.
- AC3: If liveness cannot be read, health is shown unfiltered and nothing is triaged that cycle.

Source: driver §3 "Health"; task-pickup conformance row 6 (HARNESS-241); conductor README `live_workflows`, `first_sync` (WALWARDEN-20..24).

### CIH-002 — One task owns one incident
**MS5** · WP5.4 · MUST · KEEP

A red streak has one `triage` task. Later red runs on the same head, or within the incident
window while the task is open, are appended as evidence. A re-run attempt is told apart from a
new run. A streak gets a limited number of triage attempts (default 3); after that the workflow
stops taking lanes, with one notice. A streak ends only on a green run newer than the task's last
failure.

- AC1: Losing every cache does not duplicate triage tasks: ownership is found from typed failure records on the task.
- AC2: A failed re-run of a triaged run is evidence on that task, once per attempt, never a second triage.
- AC3: A triage task parked by Sortyard is reopened by a later red run; one the operator holds in Backlog stays held.

Source: conductor README `queue_triage` (CPV2-597..624: nine items for one outage; ROVE-820/827), `TRIAGE_TRIES`.

### CIH-003 — Classify before filing
**MS5** · WP5.4 · MUST · KEEP

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

### CIH-004 — Close on green
**MS5** · WP5.4 · MUST · KEEP

Every open red-main task, whatever its queue status, closes Done with a link to the green run
once a newer run of its workflow on the default branch succeeds. An open, unmerged fix for it is
closed as superseded; a merged fix still confirming is left to finish.

- AC1: A task whose last recorded failure is not older than the green run stays open.
- AC2: An unreadable page of evidence closes nothing and is retried.

Source: conductor README `close_green` (ROVE-664, ROVE-766 stayed open more than a day after main went green).

### CIH-005 — Red-main fixes prove themselves causally, then confirm on main
**MS5** · WP5.4 · MUST · KEEP

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

### CIH-006 — Lock-in after a red main
**MS5** · WP5.4 · MUST · KEEP

Closing a red-main incident files a `regression` task (high priority) naming the culprit range:
from the newest green run before the red one to the red head. Its change adds a fast test to the
checks every change request runs; its review runs the test on the culprit commit, where it must
fail, and on the head, where it must pass.

- AC1: Without permission to run workflows, the review degrades to inspection and says so.

Source: driver §4 "The lock-in item".

### CIH-007 — Inherited red is held, not fixed
**MS5** · WP5.5 · MUST · KEEP

Change-request CI runs on the merge with the default branch, so a red main is every open change
request's red. Before a CI fix round, the change request's failing (job, test) pairs are compared
with the latest completed run of the same workflow on the default branch. If all are shared, the
task is held in merging as `inherited: main red`, with one notice naming main's run and its
triage task, and no round is spent. When main's next run is green, main is merged in (or the
failed jobs are re-run) and the chain continues. A held task's stall clock does not run.

- AC1: A failing test main does not share, or a failing job with no test named, is not inherited and gets a normal round.

Source: conductor README "Incident notes" `inherited` (ROVE-764: round 3 spent, main green 24 min later, item in Backlog two days); k3s-harness #318.

### CIH-008 — CI evidence goes into the packet
**MS4** · WP4.8 · MUST · KEEP

For a CI fix round the controller reads each failing required job's log and puts an excerpt in
the packet: the test runner's failure summary and failing tests first, found across the whole
log, otherwise the lines before the error. A failing job whose log cannot be read gets no round;
it is read again each reconcile and the merging stall bounds the wait.

- AC1: The excerpt extractor used by fix rounds has fixtures from the recorded runs; triage reuses the same one (CIH-002).
- AC2: A worker's account that it "could not read the CI log" is refused once per CI round and the round is re-sent.

Source: conductor README "Incident notes" `ci_round`, `infra_cause` (`failed_log` puts the summary first); `hand_back` refusal.

### CIH-009 — A job stopped by the runner or the estate is re-run, not built around
**MS5** · WP5.5 · MUST · KEEP

A required job that failed with no failing test and an infrastructure cause, or was cancelled or
timed out by the runner, is re-run once per head. A repeat goes to self-heal with the evidence,
recording a `check` blocking cause (REC-008). It never starts a build.

- AC1: The second failure produces a self-heal item naming the job, the step and the access needed.

Source: conductor README "Incident notes" `ci_round`; "Blocking causes".

### CIH-010 — Flaky jobs are quarantined on evidence
**MS5** · WP5.5 · SHOULD · KEEP

Results of one job at one head must agree. The second contradictory result marks the job a flake
suspect and quarantines it: it runs report-only and does not open fix rounds, matched by
workflow and job name. Exit after 7 days or 20 consecutive clean runs (defaults). Re-entry
within 7 days of exit happens on the first contradiction and files one high-priority task.
Per-test flake accounting keeps a ledger and feeds the test-review checklist.

- AC1: A job scripted fail, pass, fail on one head is quarantined at the third run with all three runs as evidence.
- AC2: If the quarantine ledger cannot be read, every required check gates.
- AC3: Quarantined jobs are listed by name on the health view and, once it exists, in the daily record (OBS-009).

Source: JOB-QUARANTINE.md (HARNESS-270); CI-FLAKES.md; TEST-REVIEW "Shared hindsight".

### CIH-011 — Flake re-run instead of self-heal
**MS5** · WP5.5 · SHOULD · KEEP

When a CI fix round is handed back with no change and every recorded failing test names a file
outside the change request's changed files, the failed jobs are re-run once on that head and the
chain returns to merging. The same head handed back again goes to self-heal.

- AC1: A failing job with no recorded tests, or a test with no file, is never treated as a flake.

Source: conductor README "Blocking causes" (`flake_rerun`; ROVE-741/750/817).

### CIH-012 — Forbidden remedies
**MS5** · WP5.4 · SHOULD · KEEP

Triage and CI-fix packets and their reviews forbid, as policy text: moving jobs to
provider-hosted runners, changing runner labels, deleting or skipping a failing test. A review
that sees one rejects.

- AC1: The forbidden list is data in the packet template; an installation can edit it.

Source: 2026-11-03 release note (#217: Rove #627 moved a timing test to a paid hosted runner); AGENTS.md "Testing model" ("A failing test is fixed on the side that is wrong, never deleted or skipped").

### CIH-013 — CI is an adapter
**MS4** · WP4.1 · MUST · NEW

Everything above talks to CI through an interface: list runs and jobs for a ref, read a job log,
read required checks, re-run failed jobs, cancel a run, start a workflow. 1.0 ships the GitHub
Actions implementation and a fake used by the test suite.

- AC1: The entire CIH scenario suite runs against the fake with no network.
- AC2: A capability the provider or the credential lacks is reported by name and the dependent behaviour degrades as documented.

Source: AGENTS.md "pipeline purity"; CORPUS R6.

---

## DLV — delivery verification after the merge

### DLV-001 — Done can mean more than merged
**MS5** · WP5.9 · MUST · KEEP

A project's completion policy is `merged` (default) or `deployed-verified`. Under the second, a
merged change that touches running-system paths enters `awaiting-deployment`: it stays In
Review, releases its build slot, and holds its dependants until the verification is recorded. A
docs- or test-only change completes at merge.

- AC1: The path classification uses the complete file list including renames and removals.
- AC2: Unknown probes, unreadable deployment data and missing or stale receipts keep the task open; an empty declaration cannot disable the gate.

Source: k3s driver "Running-system delivery"; conductor README header ("stay In Review with phase `awaiting-deployment`").

### DLV-002 — Deployed-source and mechanism proof
**MS7** · WP7.2 · SHOULD · KEEP

For `deployed-verified` projects two facts close a task: the running deployment's source commit
equals or descends from the merge commit (Git ancestry, not merge time or CI colour), and the
mechanism the change affects has run from that deployment (a receipt carrying the deployment's
identity).

- AC1: A receipt from before the deployment cannot close the task.
- AC2: A task may name the mechanism to verify in a typed `delivery` field.

Source: k3s driver "Running-system delivery" (ancestry; receipts under `delivery-evidence/`; `Delivery:` line). Needed first for Sortyard building Sortyard (MS7a).

### DLV-003 — Release verification with automatic shield (optional integration)
**MS7** · WP7.3 · SHOULD · KEEP

An optional integration for GitOps deployers (Argo CD first): each completed sync is verified by
running the repo's `verify.sh` in an isolated pod that shares no credential, volume or token with
Sortyard. Pass advances the verified-good marker. Fail, or no verdict within an hour, files one
urgent task and shields: pins the deployer to the verified-good revision and turns automated sync
off; then opens a revert of the breaking delta, sends the tasks whose merges are in the delta back
to grooming with the evidence, redeploys the reverted build, and lifts the hold only on a pass.

- AC1: Every sync is verified even if superseded before its turn; a verification that could not run is not a verdict.
- AC2: Each step (shielded, reverted, regroomed, redeployed, lifted) is an idempotent recorded event, retried until it lands.
- AC3: The integration is off by default and required before the Cortexplane cutover (MS7b).

Source: conductor README "Release verification" (HARNESS-RV-VERIFY-AUTO, -SHIELD-AUTO, -REVERT-STEP).

### DLV-004 — Post-merge steps become owned work
**MS4** · WP4.4 · SHOULD · KEEP

Each `POST-MERGE:` step from a review becomes a `needs_human` task routed to `devops`, linked to
the change request. Steps a release carries out by itself (deploy, roll out, restart) close
automatically once the deployed source includes the merge; steps needing a secret, credential or
owner input stay open.

- AC1: Filing is retried until it lands and never files the same step twice.

Source: conductor README "Drive loop" (`post_merge`, `retry_post_merge`), "Self-heal drain" (auto-closing `Deploy after PR #N` items).
