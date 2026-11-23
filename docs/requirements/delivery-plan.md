# Dependency-ordered delivery plan (reference)

> **Deferral note — this is not the current build order.** [SY-DEC-005](../../DECISIONS.md#sy-dec-005)
> (2026-11-23 amendment) makes Sortyard the workflow kernel plus the tracker view, stored to
> Postgres only; SY-DEC-004 (Appwrite) no longer applies to the core, and a durable workflow
> engine is used behind one module. Increments MS1, MS2 and MS6 are deferred until the kernel
> runs one lane. The increments, the first tranche and the Appwrite items below are kept as
> reference for requirement IDs and provenance; they cancel or move no board item.

[plan.json](plan.json) assigns every current requirement to a milestone and area package. Packages
are scope groups, not estimated one-PR tasks. The board holds state/order/blocked-by. There are
no lane-time/calendar estimates or an automatically generated hundreds-task queue.

| Increment | Usable outcome | Dependencies |
| --- | --- | --- |
| MS0 — Contract and qualification | One current requirement/domain/integration baseline; legacy IDs preserved; real Appwrite primitive proof with explicit remaining gaps | None |
| MS1 — Resource and authority kernel | Appwrite-native boundary, canonical refs/capabilities, human membership, standing delegation, actions/operations/events | MS0 |
| MS2 — Connected project control | One colleague and their agent manage task/governance/definitions/triage and inspect delivery through current owner adapters | MS1 |
| MS3 — Bound native execution | Exact context/skill/workflow binding, fenced claims/leases and isolated stages run a complete local chain | MS1, MS2 |
| MS4 — Governed delivery | Review/required checks/landing and native CI/GitOps observations work without bypass or raw product-shell deployment | MS3 |
| MS5 — Unattended operation | Bounded self-heal, serialized grooming, independent freshness and owned notification/repair outcomes | MS2, MS4 |
| MS6 — Measured improvement | Ranker candidate -> Closer pursuit -> reviewed change -> adoption -> actual usage/effect; portfolio/concierge views | MS2; can use the current execution adapter |
| MS7 — Authority handovers | Accepted projects/families transfer one writer at a time with retained history, matched behavior and scoped retirement | MS4, MS5; each consumer's applicable parity |
| MS8 — Independent operation/distribution | Supported Appwrite setup, access/upgrade/recovery and a coherent complete product; public acts remain explicit decisions | MS2, MS4, MS5, MS6 |

MS2 does not wait for the whole engine rewrite. MS6's narrow first loop can use the existing
harness. A colleague pilot is distinct from public distribution, independent-tenant activation
or migrating every existing project. The native engine's takeover does not automatically move
policy, Ranker, Closer, Walwarden, goals or all meta-harness definitions into its store.

## First implementation tranche

Preserve the existing Backlog parent scopes and decompose the next surfaces into small tasks:

1. Canonical resource refs, domain-ID mapping and source/projection ownership.
2. Running-handler capability discovery and typed unavailable/forbidden states.
3. Appwrite schema/index/runtime permission declaration and native transaction boundary.
4. Appwrite identity and Teams membership resolution.
5. Narrow operator delegation and revocation.
6. Durable operation/idempotency contract and authorized event cursors.
7. Existing policy read connector, then scoped/attributable owner write support and adapter.
8. Definition versions, assignments and archetype/context/skill resolution.
9. Project grooming queue and triage case API.
10. Project console controls/agent tool paths against the merged contracts.

Each feature has one repo, one outcome, at most three named tests and the approved design ref.
Deployment/custody/provider-capability setup is separate from feature acceptance. Use declared
blocked-by relations and Needs with source evidence; a quoted board key is not a gate. Do not
split/reopen Done or in-progress work; add residual follow-ups.

Existing original17–66 Backlog items are source scopes to retain/re-scope, not automatic
cancellations from the old draft's mapping. In particular27/51/52/53/54/55/56/57 remain owed
extension/archetype/role/skill/policy/control/proposal capabilities. Early source/API/identity
slices are groomed now; later feature decomposition follows the relevant milestone.

Owner-side policy/Ranker/Closer/other provider work lives on its product board. A Sortyard
adapter can implement against a pinned declared contract and remain visibly unavailable until
the capability exists. Do not disguise a missing provider API or broad source credential as
completed integration. No write is enabled until its custody/scope/preconditions are satisfied.

## Acceptance of this requirements work

- Every original requirement ID remains in the active catalog, with explicit amended text
  where current scope/ownership/Appwrite contradicts it; legacy behavior traceability remains.
- The resource, action, schema and service-owner contracts define equal UI/operator-agent
  control, standing delegation, graph semantics and single-writer integration.
- Current board scopes, first-tranche tasks and native dependencies reflect the approved plan.
- Real Appwrite primitive tests are recorded accurately; missing shipped-adapter/domain proof
  remains visible rather than falsely completing implementation.

Actual implementation, policy migration, identity provisioning and production rollout are
separate outcomes governed by their existing release and authorization controls.

The [operating-process extension](operating-processes.md) makes triage/self-heal actors,
process definitions, policy seeds and effective consumer coverage MS2 control-surface work.
MS5 adds admitted execution and independent recovery verification using the same contracts.
