# Ecosystem ownership and integration contracts

A single control plane composes owned APIs. It does not relocate every product database or
replace CortexPlane's operator processes. Each resource family has one authoritative owner,
source version and epoch, a registered read/command/event contract and a scoped credential route.

## Ownership and current gaps

| Service/family | Authoritative records | Sortyard control surface | Known gap / rule |
| --- | --- | --- | --- |
| Sortyard | Harness projects, governed definitions after handover, delivery/execution, delegation, operations, provenance links | Native resource/action API and UI | Current Phase1 routes are a subset of the planned model |
| Existing harness and Plane | Current unmigrated tasks, chains, scheduling and operations | Bounded read projections and owner-routed commands | No competing scheduler or local write-through copy |
| Policy engine | Current policy families, versions, variants, lifecycle and resolution | List/effective-policy/history, proposal/edit/promotion, consumer decisions and impact | Current export is not a full migration snapshot; writer auth/actor scope needs explicit bridge support |
| Git/meta-harness | Current definitions, guidance, intended-use, decisions and artifacts | Versioned source refs, proposal/review/adoption routes and conformance inventory | Commit-forward until a family is explicitly transferred; do not archive the whole repository |
| Appwrite | Human accounts/sessions/Teams and Sortyard native persistence | Identity/membership setup and domain-authorized operations | CRUD/backend credentials are not business authority; use qualified runtime permission fences |
| CortexPlane | Operator intents, goals/KRs and outer process orchestration | Scoped goal/process refs and harness actions for CP's delegated agent | Owner processes are not silently absorbed into Sortyard |
| Corpus Ranker | Originals, classifications, scores, rubrics, rankings | Authorized discovery/ranking/explanation links and pursuit proposals | Source serves capture, score and top-N. Qualify the installed owner routes and scope before integration. |
| Loop Closer | Who/what/when commitments, state, supersession, closure | Loop proposal/acceptance/progress/outcome refs tied to improvement work | Production entry point uses Postgres. Qualify the installed API and restart-safe readback before integration. |
| Walwarden | Memory observations, known/replaced facts and supersession | Provenance/context references and authorized supersession queries | Vault/repo/session retrieval is a source, not the memory authority |
| Product Lab | Hypotheses, treatments, baselines and experiments | Experiment/evidence refs linked to decisions and proposals | Advertise only the owner's implemented contracts |
| Notifications | Conditions, delivery, acknowledgement and escalation | Owner-routed attention and acknowledgement views/actions | Use the registered API; no new unaudited send path |
| Rove | Governed browser/external actions and their receipts | Explicit capability/action references | Preserve action-specific approval/authority; no generic outward-action grant |
| Git host/CI/Argo/OpenBao | Change requests, native checks/releases, reconciliation and secret custody | Authorized requests, status/coverage and provider evidence links | Secret references only; native release path, never product-shell deployment fallback |

Some partner records may be exposed through their existing SDK/API rather than a new Sortyard
endpoint per field. Operator/agent discovery remains uniform: typed refs and registered actions
name the owner and normalized request/result schema. Native/partner state never becomes writable
merely because a row was cached in Appwrite.

## Common connection contract

A ServiceConnection identifies trusted service/installation, reviewed contract version,
resource families, source schema/action manifest, credential custody ref, allowed audience,
project/workspace mapping, timeout/rate policy, health/freshness and delivery checkpoint.
The registry is configuration, not a client-supplied URL proxy. Redirects/token forwarding to
unknown services are refused. Credential values never appear in resource data, tools or URLs.

A read returns source identity/version, observation time, coverage and authorized refs. A
mutation names its registered owner action, target/variant, expected owner version/epoch,
idempotency identity, reason and verified caller context. A receipt distinguishes owner
acceptance, source mutation and observed intended effect. Retain source request/response IDs and
normalized hashes; redact secrets. Unsupported, misconfigured, forbidden and unavailable are
separate states. Reconcile ambiguous results before retrying effects.

Cross-service actions are not atomic transactions. Use durable outbox/checkpoints and stable
provider effect IDs, with explicit compensation when supported and authorized. Auth revocation
and access filtering apply on replay and read projection. Optional partner failure produces an
owned wait/unknown coverage without stopping unrelated harness work.

## Policy engine: integrate the API already present

Inspected harness source exposes:

- `GET /policies` with decision_point, project/workflow/stage/corpus/loop context and scope/kind
  filters; `GET /policies/{id}?version=N` for a version.
- `POST /policies/propose`, `/policies/edit`, `/policies/promote` with policy document and why.
  These preserve the source lifecycle, variant resolution and enforcement promotion ladder.
- `GET /policies/export`, protected by the conductor writer credential, for the current export.

The current policy writer is authenticated as the conductor and records that service actor.
It is not a per-user/project delegation API. The bridge must not expose its credential to a
browser/agent or pretend it already provides individual attribution and scoped write isolation.
A dedicated policy-only owner credential/action scope and authenticated gateway context must
be supported before the multi-user write connector is enabled. Owner validation rejects wrong
family/project scope and inappropriate promotion; the gateway additionally validates the live
operator/delegation and records its audit. Source actor attribution identifies whether it is
directly verified or gateway-asserted through an authenticated trusted service. It never trusts
an arbitrary end-user actor header. Read/inspection integration can ship independently.

Expose Policy and PolicyVersion with family, variant `(id, scope, scope_ref)`, source version,
status, enforcement, absent-state and consumer support. A proposal does not silently activate or
jump record/warn/refuse. Effective-policy responses record exactly which variant won; registered DefinitionAssignment
records describe owner-supported definition assignments, not an invented second policy authority. PolicyDecision records consumer, input snapshot, actual source versions, conflict/fallback
and verdict. An existing policy with no supported consumer is visibly not an active guard.

Ordinary lookup/export is insufficient for full policy migration. The current export omits
other variant/version bodies and import rows. A future owner snapshot contract must include all
historical bodies, variants, history, import provenance, a consistent checkpoint/hash and epoch.
Then freeze old writes, validate/apply the snapshot, replay retained resolutions and explicitly
rebind one writer/epoch. A failed/missing migration capability blocks migration only; proxying
the existing source remains valid. Rollback restores one writer, never dual authority.

Policies for scoring/loop behavior that belong to Ranker/Closer remain their owned families;
show them alongside governance policy using the registry. Do not coerce different provider
schemas into one writable policy body or migrate them just to make the menu look unified.

## Definitions and source proposals

Git-locked content remains source-owned until an explicit family migration. UI and agent use
one proposal operation that creates/links normal bounded work and reviewed source changes;
accepted publication is observed before materialization/adoption. Changes are not applied by
editing a mirrored row. Recipe/role/skill/archetype versions and local overrides resolve with
provenance and scope. Meta-harness stays commit-forward for current records, including this
planning handoff; task state stays in Plane until its project transfers.

## Improvement and outer-loop integration

Provider evidence checked November 17, 2026 (New York time):

- The existing policy engine's routes are present in [the deployed harness source](https://github.com/noncelogic/k3s-harness/blob/9577e8d1cfeddd6368f61d35d3124e68e529d0f0/control-plane/api.py).
  The k3s control-plane Deployment reported one available replica at that source. Sortyard still
  needs to qualify effective-policy reads and attributable authority for owner actions.
- [Ranker source](https://github.com/noncelogic/corpus-ranker/blob/b8abc1043a8f6afedc1346ea97eb7cf9450cff11/src/server.ts)
  serves capture, score and top-N using Postgres, with S3-compatible storage for captured originals.
  Search, explanation and
  the rest of its published OpenAPI surface still need route-level qualification.
- [Closer's production entry point](https://github.com/noncelogic/loop-closer/blob/565ffdd71b281874550c055ce37fc9ff302a0aa4/src/main.ts)
  constructs a Postgres graph store. Its in-memory entry path is explicitly for tests.
- No Ranker or Closer Deployment or Service was found in the inspected `aks-obs-01` and harness
  k3s clusters. The source observations establish implementation progress. Installed endpoint
  availability, scoped credentials, and a complete cross-service loop remain unverified.

Capture -> classify/rank for project/archetype/stage -> ImprovementProposal -> authorized
pursuit -> Closer intake plus bounded harness task -> reviewed published version -> project
adoption -> actual binding/run usage -> OutcomeObservation. Stable effect IDs make duplicate
pursuit create one intended loop/task. Ranking creates no commitment by itself. A merge does
not prove adoption; adoption does not prove effect. Measurements retain policy/rubric versions,
coverage and confounders. An accepted loop closes against its declared outcome, not a guessed
success inferred from a task label.

CortexPlane under its operator owns the intent/goal/KR process and consumes the same Sortyard
API as another delegated agent. Improvement work can link to an authorized KR without moving
that goal's authority. Walwarden stores what was learned and replaced, with provenance; the
vault remains an ingest source. Private loops/corpora/knowledge stay private despite graph
links or shared project membership. Missing partner API/durability is a real capability gap,
not an empty result or permission to write a replacement store.

## Provider contract dependency

Each unavailable required capability has a Need with owner, target contract/version and
satisfaction evidence. Owner-side work belongs on that product's board; Sortyard adapter tests
use the declared provider contract and report the capability unavailable until deployed.
Cross-project references in prose are not scheduling gates. Deployment/integration acceptance
tracks actual capability needs separately from a feature's local/CI contract acceptance.

## Inspected source checkpoints

The observations above are source facts, not live-health acceptance. Policy API/store inspection
was pinned to [harness02da860](https://github.com/noncelogic/k3s-harness/tree/02da860211215825099db8072f82a6e8ec0977d2/control-plane)
(`api.py`, `policy_store.py`); Ranker server shape to
[Rankerc4a58bf](https://github.com/noncelogic/corpus-ranker/blob/c4a58bfa3c66bc74d584a1255a7359a106361a27/src/server.ts);
Closer default persistence to [Closer5e238ce](https://github.com/noncelogic/loop-closer/tree/5e238ce8bb069372e6241ff6d75e7b8f35e17c4e/src)
(`server.ts`, `main.ts`). Runtime capability discovery and deployed receipts must confirm an
owner's current API before advertising a callable integration.
