# Native Sortyard execution

Status: proposed architecture. The checkout replay below is the first executable slice. The
existing [requirements baseline](../requirements/README.md) still governs installed APIs and
migration authority. This design proposes how to replace the legacy execution and task owners.

## 1. Ownership and boundaries

Sortyard owns native tasks, the execution state machine, and the relationship between a task and its
runs. Plane's useful ideas are projects, states, dependencies, priority, and ordered queues. Model
those directly. Keep task identity stable, freeze a task revision at admission, and keep attempts,
leases, evidence, and provider state on runs. A task can be complete while a separate deployment
observation is pending. Import a project's external IDs, dependencies, and history at handover with
an explicit source checkpoint and a single writer. Keep the compatibility adapter outside the core.
Retire the Plane dependency after the last handover.

A small coordinator advances typed state transitions. It calls ports for policy decisions, scheduling,
execution, and verification. Provider adapters normalize observations and reconcile external effects.
They never decide task state. The policy decides whether work is eligible or should wait. It receives
facts and returns a decision with a reason, without credentials or external effects. A verifier reads
independent owner evidence. It never trusts a worker's recovery claim as proof. Scale the components
that need different concurrency or isolation. Keep these as module boundaries even when a single
process hosts several components.

Humans and the concierge use the same resource and action contracts. A canonical resource link can
lead from a failed stage to its run, task, policy version, actor, connection, and owning service.
The concierge can inspect any authorized layer and propose, retry, or route an action through that
layer's owner. Its delegation governs every action. Changes to the harness itself use the same
versioned proposal, review, evaluation, and adoption path as other definitions.

## 2. Lifecycle and effects

Start with explicit seams where behavior is expected to vary. Admission binds a task revision and
workflow. Before a stage, resolve context, skills, executor and policy versions. After observation,
classify the outcome. Before retry or repair, resolve a policy against evidence and remaining budget.
After an effect, reconcile its receipt. Verification establishes the outcome from an independent
source, and completion records the terminal reason. Each seam has a typed input and result, owner,
contract version, and explicit behavior for unavailable evidence. Keep coordination and invariants
inside the state machine. Adding a policy or executor should require a new definition or adapter,
with no edit to the coordinator.

Persist task and run transitions with the event record in one transaction. Pin the policy binding
per run and allow a changed policy only on a new run. Wake due work through a persisted schedule.
A wait releases the execution slot. Apply limits at the appropriate scope, such as a provider
installation or credential rather than across all tenants. Fence claims with expiring leases and
reconcile ambiguous effects by stable operation ID before another attempt. Keep external writes
outside the transition transaction. An accepted write survives a lost response, and an unverified
write cannot advance a run to recovered.

## 3. Kubernetes and observability

Use distinct executor contracts for a pod-backed harness, native CI, and ad hoc work. A harness
profile pins the image digest and stage contract. A Kubernetes adapter creates a Job with a bounded
lifetime, explicit resources and namespace, and independently scoped identity. The scheduler owns
lane admission, while Kubernetes owns pod placement and scaling. A CI adapter observes native job
and runner capacity and reports queue time separately from run time. An ad hoc task uses the same
admission and evidence contracts. Pod replacement and runner changes cannot reset the run's budget.
The coordinator receives normalized outcomes and does not call Kubernetes or GitHub itself.

The event ledger records decisions, component versions, waits, effects, and verification evidence.
Project those records into OpenTelemetry spans through an adapter with bounded buffering and export
to SigNoz. Carry trace context through provider and pod boundaries. Measure queue time, scheduled
wait, execution time, and verification lag separately. Keep repository, run, and policy identities
on traces and use bounded dimensions for metrics. Align OTLP transport, naming, and dashboards with
the ongoing observability refactor. A collector outage must not block a transition.

## 4. Improvement and replay

### The improvement flywheel

The purpose of the execution system is to turn observed work into measured improvements. The
first end-to-end flywheel should tie an incident to a candidate change, an owned commitment,
a version used by real work, and the effect of that version. The checkout replay supplies the
first comparison. An opted-in project supplies the later adoption and outcome evidence.

| Owner | Contribution to the loop | Evidence Sortyard links |
| --- | --- | --- |
| Sortyard | Capture a failure or opportunity from a task, run, or stage. Record the baseline and candidate evaluation. | Run and trace IDs, input snapshot, component versions, decision and verification receipts |
| Corpus Ranker | Retain the original evidence, score candidates under a versioned rubric, and surface candidates for pursuit. | Original ID, score event, ranking result, rubric and ranking policy versions |
| Loop Closer | Own the accepted commitment and its outcome criterion. Track who follows through and when. | Loop ID, accepted commitment, responsible owner, due time and close event |
| Existing policy engine | Resolve the effective policy and own proposal, review and promotion within its authority. | Policy family, effective variant/version, promotion receipt and consumer coverage |
| Sortyard | Bind the approved version to opted-in work and measure the actual effect. Feed the result back into the next ranking. | Adoption and run bindings, outcome observation, costs, guardrails and coverage |

The concierge can take a ranked candidate to the responsible owner through the same authorized
actions the operator uses. An accepted pursuit links one Closer loop to one bounded Sortyard task.
Reconcile ambiguous responses with stable operation IDs before trying again. The task delivers a
reviewed component version. The adopter observes the real binding, and the verifier compares
actual results against the loop's original criterion before closure. A missed criterion or missing
coverage remains visible in the loop and becomes evidence for the next decision. The ledger owns
run evidence while SigNoz helps the operator find the trace and measure the delay.

Start with an effective-policy read and a versioned decision receipt. Then prove Ranker capture,
score and retrieval through its owner API, and Closer intake and restart-safe readback through its
owner API. Finally run a single opted-in improvement from evidence capture to verified closure.
Each adapter reports an owned wait when its provider is unavailable, and the execution queue
continues. This work can use the existing execution adapter during the native task transition.
See [the integration baseline and provider evidence](../requirements/integrations.md).

### The first runnable slice

Harness²'s scoped probes and RRSI's constrained selection suggest a practical loop. Pin a baseline
and one candidate component, run both over the same incident corpus and held-out cases, then compare
successful outcomes, effect count, wait time, and behavior on unrelated work. Record the evidence
before proposing adoption. Roll back by changing the assignment for future runs. See the
[Harness² paper](https://arxiv.org/abs/2610.14224) and the [RRSI paper](https://arxiv.org/abs/2609.24972).

The first native chain uses the same coordinator, observation adapter, and verifier for both
policy bindings. The replay adapter serves reviewed checkout evidence and captures requested
retry commands. The verifier matches the reported recovery to that repository and source tree and
requires the complete set of successful checks. The clock and queue are local to this demonstration.
The [incident fixture](../../tests/fixtures/checkout-incident.json) records its source and separates
historical provider evidence from simulation timing and the synthetic unrelated repository.

```sh
python -m sortyard.checkout tests/fixtures/checkout-incident.json --policy owner-first
python -m sortyard.checkout tests/fixtures/checkout-incident.json --policy wait-and-retry
```

The comparison should show an owner wait with zero commands in one run, a seven-tick wait followed
by one failed retry and an owner wait in the other, and independent same-tree recovery in both. Both
runs must finish the unrelated repository at tick one. The issued command is a simulation of the
historical second attempt, so this comparison does not attribute recovery to retry. The incident
establishes checkout access rejection and leaves the backend cause unknown.

Future slices bring the same boundaries to a durable task/run store, a registered profile executing
one pod-backed chain in the local replica, and a rehearsed single-project handover. That progression
keeps the current system available while each native owner earns authority with observable evidence.
