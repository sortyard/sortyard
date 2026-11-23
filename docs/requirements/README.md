# Sortyard ecosystem requirements baseline (reference)

> **Reference, not the current build order.** [SY-DEC-005](../../DECISIONS.md#sy-dec-005)
> (2026-11-23 amendment) makes Sortyard the workflow kernel plus the tracker view, stored to
> Postgres only, and defers increments MS1, MS2 and MS6 until the kernel runs one lane. This
> baseline, its catalog and its plan stay as requirement reference; no requirement or plan row changed.

Status: approved. The [operating-process extension review](evidence/operating-process-review.md)
and [prior baseline review](evidence/technical-review.md) are preserved. It was the consolidated planning baseline until SY-DEC-005's amendment. It replaced
PR7's November12 draft assumptions and incorporates the owner's November15 operator/agent,
meta-harness domain and Appwrite directions, plus the current company ownership map (source date
November16). The existing product is still the Phase1 implementation; this baseline declares
requirements, not runtime support or migration authority.

Sortyard is the single human and agent control plane for the ecosystem around the delivery
harness. An operator, the concierge, CortexPlane or the operator's own agent can inspect the same
resources and request the same authorized operations. Domain services retain one authoritative
owner. CortexPlane owns the operator's goals and outer processes; Walwarden owns memory and
supersession; Ranker owns ranking; Closer owns commitments; the policy service owns its current
families. Sortyard formalizes harness governance, delivery and the relationships between them.

## Read and schedule from one baseline

| Document | Purpose |
| --- | --- |
| [Requirements catalog](catalog.md) / [machine index](requirements.json) | Every retained requirement ID, explicit amendment and new requirement, with acceptance/provenance |
| [Domain model](domain-model.md) | Meta-harness artifacts as typed resources; fields, scope, lifecycle, inheritance and graph |
| [API and delegation](operator-api.md) | Equal UI/agent action surface, standing delegation, revisions, events and evidence |
| [Operating processes](operating-processes.md) | First-class triage/self-heal actors, versioned processes, seeds and consumer coverage |
| [Service integrations](integrations.md) | Policy engine and partner ownership, contracts, gaps and authority handover |
| [Delivery plan](delivery-plan.md) / [machine plan](plan.json) | Dependency-ordered increments and their acceptance; no calendar/task-count estimates |
| [Legacy reconciliation](reconciliation.json) | All original333 IDs retained or explicitly amended; none silently removed |
| [Qualification evidence](evidence/README.md) | Real local Appwrite primitive results and their limits |
| [Contract artifacts](contracts/resource-catalog.json) | Typed resources, lifecycles and edges; [domain schemas](contracts/resource-schemas.json), [public API](contracts/operator-api.openapi.json), [actions](contracts/action-catalog.json) |

The original draft is preserved under [history/2026-11-12](history/2026-11-12/ARCHIVE.md) for
provenance. Its cuts, schedules, task counts, proposed statuses and ownership assumptions do not
govern current work. Stable requirement IDs are preserved so evidence and board links survive.
The original legacy behavior inventory remains source evidence; every affected capability must
be retained, improved or explicitly dispositioned by its owner before a dependent cutover.

`requirements-source.json` is the authored active requirement record. `tools/gen.py` validates
IDs, coverage, plan dependencies, resource/action contracts and references, and renders
`requirements.json`, `catalog.md` and `reconciliation.json`. Run:

```sh
python3 docs/requirements/tools/gen.py
python3 docs/requirements/tools/gen.py --check
```

No generated file is runtime capability discovery. Only installed, authenticated handlers of the
running revision advertise callable operations. The current aspirational194-operation spec and
44-route implementation must be reconciled by the capability-discovery slice.

## Governing changes

- Appwrite persistence, Auth and Teams were the default per [SY-DEC-004](../decisions/appwrite-substrate.md);
  that no longer applies to the core, which is Postgres only per SY-DEC-005.
- Archetypes, roles/personas, skills, recipes, contracts, requirements, guidance and extension
  registrations are first-class resources with source ownership and versioned adoption.
- UI, REST, MCP and CLI are equal clients of the same public domain operations. Delegation
  narrows an operator's live grants; it does not require a new confirmation for every routine act.
- Existing policy authority is integrated, not duplicated. Full historical/variant migration is
  a separate capability; current-only export cannot certify it.
- Meta-harness stays commit-forward and Plane stays the task authority for unmigrated work.
  Sortyard transfers resource families/projects only after explicit single-writer acceptance.
- Task completion and observed deployment outcome are separate. Native reviewed CI/GitOps owns
  releases; no administrative merge bypass or product-shell deployment is inferred from an old
  draft or an agent request.
- Premise-class spending/identity/public/irreversible choices retain explicit authority. Routine
  defaults cannot manufacture that authority. Public release/governance is distinct from a
  private colleague pilot.

Board execution state, ordering and blocked-by relations live in Plane. A requirement or a
package in this document is not automatically one PR. Groom only the next tranche into bounded
one-PR tasks with named tests and its approved design reference; retain the rest as requirements
under their existing parent scope. Do not cancel Done/in-progress work or queue hundreds of
speculative tasks from an estimated total.
