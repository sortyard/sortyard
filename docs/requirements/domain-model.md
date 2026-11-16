# Domain model and meta-harness conformance

The [resource catalog](contracts/resource-catalog.json) and [data schemas](contracts/resource-schemas.json)
are the planned normalized model. Existing served APIs/models remain the implementation baseline.
Each kind names its owning service, identity, scope, fields, immutable-content rule and state
transitions or an explicit external-owner state contract.

## Identity, tenancy and ownership

A ResourceRef identifies a stable logical service namespace, installation, kind and domain ID, plus workspace,
project and immutable version where its kind requires them. Scope is verified from authenticated
membership and stored owner bindings, never trusted from a request header or unverified ref.
Public IDs survive rename and Appwrite physical-ID mapping. The authority service/epoch names
the current physical owner; changing that owner does not change the logical namespace. Retain
source aliases for legacy refs and URLs through migration. Cross-service references include the
registered installation and scope mapping; coincident IDs or email addresses are not identity.

Every resource envelope includes its ref, opaque mutation revision, schema version, authority
service/epoch/mode, redacted data, observation coverage and authorized links/actions. Authority
mode is authoritative, projection or reference. A projection cannot mutate its owner by updating
Appwrite rows. Cross-workspace reads, search, reverse edges and counts require explicit access.
An Appwrite Project partitions the Sortyard installation; it is not a delivery Project.

The first collaboration profile has named operators in one workspace and explicit project Teams.
Independent operations/workspaces require separate storage/query/cache/event/worker/credential
isolation proofs before enablement. This capability is planned, not claimed from a workspace field.

## What becomes first-class

| Meta-harness practice/artifact | Planned domain objects | Identity and behavior |
| --- | --- | --- |
| Project charter, intended use, repo registry | Project, Repository, IntendedUseRecord | Scoped identity; pinned intended use, repository roles and ownership |
| Owner intent and desired end state | Intent/Goal/KeyResult references | CortexPlane owns these; harness work links to the authorized goal/KR |
| Tasks, milestones, dependency/priority/sequence | Task, Milestone, Need | One owner; explicit dependency edges/readiness reasons; no prose citation gates |
| Templates and decided defaults | ArchetypeVersion, DefinitionAssignment | Versioned bundle; project pins/adopts a version and sees inherited overrides |
| Workflow tables and dispatcher stage rules | WorkflowVersion, ExecutionBinding, Chain, StageRun | Declarative transitions and exact pinned inputs; system transitions remain fenced |
| Role/persona guidance | RoleDefinitionVersion | Prompt/context/tool/model definition; distinct from IAM membership and grants |
| Skills and procedural playbooks | SkillVersion, ProcedureVersion, ExtensionRegistration | Artifact/hash/provenance, compatibility, declared capabilities and project adoption |
| Context selection and source packets | ContextRecipeVersion, ContextPacket | Allowlisted composition and budget; immutable packet provenance; no broad vault retrieval |
| Architecture, schemas and named acceptance | Requirement, DesignRecord, ContractVersion, QualityBarVersion | Stable IDs, review/source revisions, schema boundary and evidence coverage |
| Prose rules and policy APIs | Policy, PolicyVersion, PolicyDecision | Registered owner; variants, lifecycle, effective resolution and actual consumer evidence |
| Grooming, triage and self-heal sessions | GroomingPass, TriageCase, RepairAttempt, Mechanism | Fenced project queue, input snapshot, repair budget, owner and observed result |
| Model/worker profiles and running jobs | AgentDefinition, AgentRun | Definition is separate from attempt/runtime; actual authority/binding/outcome visible |
| Git/CI/Argo delivery | DeliveryObservation and native release references | Merged, published, reconciled and verified are separate facts with freshness |
| Research, ranked candidates and follow-through | Discovery, ImprovementProposal, Adoption, OutcomeObservation | Link Ranker/Closer owners; landing, adoption, usage and effect remain distinct |
| Durable knowledge and replaced facts | MemoryObservation, KnowledgeFact references | Walwarden owns provenance/supersession; vault and repo docs are sources |
| Credentials and external services | ServiceConnection, CapabilityGrant, ExternalReference | References and capability scope only; secret values never enter the object UI |
| Agent proposals, requests and audit | ActionPlan, Operation, PolicyDecision | Exact delegated authority, idempotency, revision, source receipts and observed outcome |

Documents that do not yet have a semantic conversion remain typed DocumentArtifacts with source,
version/hash, sensitivity and provenance. Conformance never drops information merely because a
parser cannot yet classify it. Requirement/design bodies remain reviewable artifacts; turning
an artifact into a resource does not remove its prose or force a database copy of Git authority.

## Versions, state machines and inheritance

A published definition version is immutable. A proposal has a separate draft/validation/review/
publication lifecycle. Assignment, activation and project adoption are distinct mutable records.
Publishing the newest version never silently activates it. Git-locked definitions expose the
same change-proposal API to a person and their agent, then use ordinary review/CI/GitOps.

An archetype references workflows, workflow roles, skills/slots, context recipes, quality bars,
contracts and substrate/deploy profiles. A project pins a version and adds explicit local
overrides. Resolution produces a provenance-bearing effective configuration: which source won,
which rule prevents weakening a safety floor, and which required capability is absent. Upgrading
shows affected projects/future bindings and unknown coverage before adoption. Running stages
retain their packet/workflow/skill versions; live policy decisions record their actual current
resolution. Emergency revocation is explicit and separately authorized.

Tasks retain the six board states backlog, todo, in_progress, in_review, done and cancelled.
Queue status is separate: unreleased, released, claimed, parked, handed_back and needs_human.
Named actions change both fields in one owner transaction; a todo/claimed pair is invalid, and
terminal/backlog tasks hold no claim. Park/hand-back/human waits carry reasons; hand-back carries
evidence and human waits carry owner routes. The catalog records both transition sets; source
owner commands enforce the legal combined transitions. Priority preserves urgent/high/medium/
low/none, including medium and unprioritized none in every edit/ordering surface. Only the
controller/integrator performs fenced internal execution transitions; operator commands request
release/requeue/cancel/repair through the same rules. Requirement and
DesignRecord lifecycles preserve superseded history. An agent/persona edit grants no authority.
Triage distinguishes classification, repair, waiting, verified recovery and closure. Repeated
conditions deduplicate; a new condition revision can reopen a case with history intact.

## Graph semantics

Edges are typed, provenance-bearing records: inherits_from, assigns, depends_on, governed_by,
used_by, derived_from, supersedes, pursues, adopts, evidence_for, serves, observes, repairs,
publishes, implements and requires. Their allowed endpoints are in the catalog. Validate both
endpoints, edge authorization and scope on each hop; do not reveal a private node through
counts or existence. Supersession stays same-kind and acyclic; a reference to an absent source
is unknown/unavailable, not a confirmed relationship.

Operational graph data is a bounded indexed projection over authoritative records, not a
second scheduler or a semantic search authority. Cross-service timelines retain source cursors,
causality and observed time; no global transaction/commit order is invented. Graph expansion is
bounded, paged and cycle-aware. Historical knowledge edges from Walwarden and documents remain
sources with their own authorization/supersession, not hidden task prerequisites.

Approval Decisions inherit their ActionPlan's exact workspace and optional project binding.
Ordinary task Decisions retain project scope. Workspace administrative approvals are not filed
under a fabricated project; server authorization checks the actual action target scope.

Grooming queue and lease identity is the server-resolved authority service, installation and
canonical source board/project ID. Two logical project aliases for the same authoritative board
share one queue/fence; only independent source boards may run grooming concurrently.
