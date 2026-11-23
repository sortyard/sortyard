# Governed operating processes

Sortyard must go beyond reproducing the current Kubernetes harness. Delivery, triage,
self-heal, grooming and ongoing improvement are named processes that an operator or delegated
agent can inspect and govern. Controllers, runners and agent jobs are execution components of
those processes. The initial [seed catalog](seeds/operating-processes.json) is a reviewed template
input, not a live policy import, installed executor or permission grant.

## Domain model

| Object | Meaning |
| --- | --- |
| OperationalActor | Named detector, classifier, diagnostician, repair executor, verifier, groomer or coordinator; responsible operator, registered executor, scoped grants and draft/enabled/paused/retired lifecycle |
| OperationalProcessVersion | Immutable trigger/correlation contract, stage graph, actor roles, allowed owner actions, policy decision points, verification and escalation contract |
| OperationalProcessRun | One correlated incident/process execution: pinned version, actual actor bindings, lease/fence, current stage, cumulative budget, decisions, receipts and outcome |
| Existing related records | TriageCase describes the issue; RepairAttempt one attempted repair; AgentRun one agent execution; Mechanism recurring evidence expectations; Operation an accepted command; PolicyDecision the actual rule resolution |

These extend the resource, schema and action catalogs. An actor can execute as deterministic
controller code, an agent profile or a registered service. It has a stable identity even when
its worker changes. Display names and workflow personas confer no authority. Registering an
actor creates a draft record; it cannot issue grants or copy the conductor's credentials.
The server binds the responsible operator to verified authority and independently issued grants.
The public actor.enable action admits a draft actor; actor.resume admits only a paused actor.
actor.retire terminates a draft/enabled/paused registration without erasing effects or history.
Enabling or changing an executor verifies its declared capabilities against those live grants.
A paused/retired actor accepts no new work; in-flight effects retain their actual disposition.

Process definitions use the existing DefinitionProposal -> reviewed publication -> immutable
version -> DefinitionAssignment/adoption path. They are not a second workflow registry.
WorkflowVersion describes a bound delivery chain. OperationalProcessVersion describes the
outer event-driven process across cases, waits, owner commands and observations. Execution
reuses the current registered scheduler/operation/lease machinery; this design does not create
another independent conductor. Git-locked definitions keep their existing source owner.

Scope is workspace with optional project binding. Each subject/actor/evidence hop is authorized.
A workspace incident may link several authorized project cases, without inventing a project or
leaking another project's evidence. No cross-project mutation follows from correlation alone.

## Seeded processes

| Process | Stages and disposition |
| --- | --- |
| Delivery triage | Observe failed delivery/progress -> correlate case -> collect fresh evidence -> classify -> route product fix, infrastructure repair, access Need or owner Decision -> verify outcome |
| Self-heal diagnosis | Claim case -> diagnose with prior attempts -> propose resume, reshape, owner input or satisfied -> validate fresh revisions/authority -> apply permitted disposition or retain unknown |
| Bounded repair | Select versioned procedure -> check authority/policy/budget -> fenced attempt -> owner command -> reconcile receipt -> verify -> recover, wait or escalate |
| Cause-cleared return | Observe typed blocking cause -> establish fresh owner proof -> check unchanged task/case -> request return -> observe actual eligibility/pickup or keep owned wait |
| Mechanism liveness | Observe cadence/producer proof -> classify healthy, silent or unknown -> correlate owned case -> diagnose/repair -> independently verify liveness |

Classification distinguishes product defect, infrastructure, transient, missing evidence/access,
owner input and obsolete premise. Shared runner/quota/provider failures correlate at the shared
fault domain; they do not generate a speculative code fix per affected product. A missing log or
an inaccessible API remains unknown. Existing operator Backlog holds remain authoritative.

A sandbox diagnostician and an infrastructure repair executor are separate actors. Diagnosis
can produce a typed plan; it cannot become cluster access. Repairs call supported owner actions.
Code fixes take the ordinary task/review/CI/GitOps path. Existing native release owners handle
release requests. Historical direct-apply instructions do not grant kubectl, merge bypass,
arbitrary shell execution, automatic rollback or unbounded resource expansion.

## Ownership, budgets and outcomes

Trigger correlation uses source owner/installation, subject, condition kind, condition revision
and originating incident identity. One active run owns that key; duplicates append evidence.
Claims and mutations require an unexpired lease and matching fence. Grooming additionally keys
on the canonical source board, so logical project aliases share its queue.

Run actor bindings retain actor/configuration revision, executor reference/revision and grant
references. The owner retains immutable configuration/executor snapshots at those revisions so
later actor.configure edits cannot rewrite a run. Ordinary configuration applies to future
bindings; a revocation/pause still applies to new effects of existing runs. A binding cannot
inherit rights added to a newer actor configuration. The run exposes lease owner, fence epoch
and lease_expires_at; only a current unexpired lease may advance it.

Run actors and process/procedure versions are pinned. Every decision records the actual resolved
policy versions at decision time; emergency revocation applies to new effects. Stage, process,
originating case and shared-connection budgets all apply: attempts, elapsed time, agent tokens
and external effects. Limits must be explicit before admission. A zero token/effect allowance
permits no such consumption. Operator start arguments request limits only; spent counters are
server-owned. Limits cannot exceed current grants/policy and cannot increase an originating
case's remaining budget. No default elapsed/cost threshold is invented by installing a seed.

Pausing, replacing a worker, taking a lease, spawning a child or upgrading a process does not
reset case/shared budgets. Reserve/consume budgets transactionally with owner receipts. An
ambiguous effect remains unknown; reconcile its stable owner effect ID before replay. A new
lease cannot blindly repeat it. Unsupported owner capability is an owned unavailable wait.

Run states are queued -> running -> waiting/verifying, with paused and explicit terminal
recovered, escalated, cancelled, failed or premise_removed outcomes. Resume checks the original
budget and grants. Cancellation records what actually stopped; it is not rollback of an accepted
effect. Terminal runs remain immutable history; a recurrence creates a linked new run retaining
the origin's relevant budget/correlation history. Domain validation keeps state/outcome consistent
and current_step in the pinned graph; actor bindings must satisfy required roles and scope.

A verifier reads fresh positive owner evidence for the exact condition/revision and required
outcome, independently of the repair actor's self-report. Verification may reuse an executor
only when its evidence is obtained from an independently authenticated authoritative observer;
model self-attestation is insufficient. A merge, agent exit, acknowledgement, green API health,
removed workflow or absent alert does not prove restored delivery. An obsolete premise closes
as premise_removed; actual recovery uses recovered. Exhaustion/escalation has a named owner,
remaining need and declared next event. Notifications are outputs, not the recovery mechanism.

## Seed policy contracts and adoption

Seeds are installation-neutral templates. They contain no estate cluster names, operator account
names, secrets, installed refs or inferred permission grants. An installer resolves source/owner
bindings, exact consumer contract versions, actor executors and required typed parameters before
proposing/adopting them. Existing policy families remain with their current policy API owner.
A Sortyard seed cannot overwrite or clone an existing family into a second writable authority.

The catalog distinguishes retained source rules, proposed cross-process guarantees and an
unimplemented crash-loop proposal. All are unbound templates, initially record mode; none is
activated by this documentation change. Current source evidence is pinned in the catalog.
Unconfigured parameters and missing consumers are visible. A mandatory authorization, fence,
budget or verification prerequisite cannot become optional because its policy is in record mode.
An unsupported policy is unsupported governance, not an effective guard.

Each policy names a decision point, typed parameter schema, required parameters, consumer
capability/version, absent/unbound behavior and evidence needed for effective coverage. Coverage
means the installed consumer declares and tests the exact parameter semantics. Imported prose,
a policy row, a recognized ID or a live worker is insufficient. Unknown fields are refused at
binding; policy/consumer schema mismatches prevent activation. Adoption previews the diff,
retains operator overrides and uses the owner's proposal/promotion ladder. New template versions
never silently re-enable actors or replace running definitions.

The source assessment found real policy/consumer drift: handback YAML declares max_attempts and
owner_escalation_after_hours while consumers use retries/route plus separate HEAL_LIMIT/STALLED
constants; red-main consumer coverage chiefly recognizes owns_landing. These are migration gaps,
not evidence that all declared fields are enforced. The policy integration must show this coverage
and shape the consumer fix before promising control. Existing proposal substrate-crashloop-heals
has no implementation and must remain unavailable until its owner capability is implemented.

## Equal control and process improvement

Actor registration/configuration/enable/pause/resume/retire and process start/pause/resume/cancel are registered
public actions with typed schemas and UI/REST/MCP/CLI parity. Server-resolved identity, live
delegation, revisions and idempotency apply. Operators and their agents can inspect definitions,
active runs, stage owners, waits, policy coverage, budget spent and evidence through canonical
resource/history links. A UI actor card cannot hide an administrative-only operation.

A failed or ineffective process emits its own owned condition. Proposed changes to skills,
procedures, routing or policy use the ordinary improvement/review/publication/adoption loop.
Actors cannot weaken their own constraints to declare success. Versioned outcome comparisons
can show whether a new process improves recovery, with coverage and confounders retained.

## Delivery

MS2 delivers the actor/process catalog, seed/consumer coverage and read/control contracts over
current owners. MS5 delivers admitted fenced execution and verified repair through those
contracts. Add bounded follow-ons beneath the existing grooming/triage parent; do not replace
or reopen completed work. Qualification is local contract/replica evidence; activation/custody
and migration remain separate owner capabilities. No live policy, actor or cluster is changed here.
