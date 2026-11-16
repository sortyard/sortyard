# Operator control through UI and agents

The [planned public contract](contracts/operator-api.openapi.json), [action registry](contracts/action-catalog.json)
and [resource catalog](contracts/resource-catalog.json) specify the shared surface. These are
future additive contracts, not the runtime served OpenAPI. Existing194 declared operations and
44 routed handlers remain separately inventoried until capability discovery is implemented.

## Equal authority across interfaces

An operator UI, embedded concierge, MCP client, CLI and CortexPlane acting for an operator are
clients of the same business commands. A supported operator action has both a discoverable API
path and a UI control. Compound agent tools expose child operation refs and cannot add rights.
Small domain tool packs and paginated generic discovery preserve complete authorized reach.

Resolve identities server-side: authority principal, executor, delegation, applicable approver
and system executor are separate. An operator's standing delegation narrows current membership,
resources, actions, audience, expiry and operational limits. Child delegation is denied unless
explicitly allowed and further narrowed. Ordinary in-scope actions execute directly; being an
agent is not a reason to ask for fresh confirmation. A model-driven worker still cannot claim
its own work, act as the controller/integrator, self-widen a grant or bypass independent gates.

Appwrite owns human identity/session and Teams membership per SY-DEC-004. Workflow RoleDefinition
is not an IAM role. Appwrite CRUD scopes are not task/merge/policy authority. Stage grants bind
to one attempt/chain epoch. Delegation and all token issuance are serialized against forbidden
capability accumulation; a raw client-supplied on_behalf_of or system actor is never trusted.
Revocation applies to subsequent requests, active streams, search/graph/export and cached
capabilities within the declared tested bound. No global Appwrite signing/admin key reaches a
browser or worker. Private Ranker/Closer/knowledge data is not implied by project membership.

## Resources, discovery and navigation

Resource envelopes carry stable typed refs, revision, owner/epoch, schema, observation coverage,
authorized actions and canonical UI/API/history links. Timeline events, policy versions, graph
edges and traces have anchors. URLs come from configured trusted origins with encoded IDs;
links contain no bearer tokens and grant no access. Physical storage ID changes and renames do
not break logical resource identity. Batch lookup returns only accessible resources.

Capability discovery separates implemented, installed, configured, operational, authorized and
valid-in-current-state. Missing provider support is different from no records or forbidden.
A planned action never appears callable because a design spec names it. Discovery is bound to
the running revision/principal and is not itself authorization; execution rechecks everything.

## Commands and errors

A command names a registered action, target ref, schema-validated arguments, reason, request/
correlation identity and, where required, expected revision. The server resolves authority and
owner. Generic action dispatch is not arbitrary HTTP proxying or shell execution. Patch actions
accept only the registered user-editable field schema, excluding state, actor, ownership and
historical fields. Named state transitions retain their domain guards.

The action registry gives request/result schemas, target kinds, roles, risk, owner, expected-
revision/idempotency requirements and UI/REST/MCP/CLI parity. Installed connector actions are
registered from pinned reviewed owner contracts; they cannot install client-supplied handlers.
Policy evaluation is a read-only snapshot endpoint, not a queued mutation or lane reservation.

Common failures are401 unauthenticated;403 forbidden (or consistent404 for inaccessible refs);
409 domain/capacity/authority-epoch/idempotency conflict;412 stale revision;428 missing required
precondition;422 invalid domain/schema;429 scoped rate/resource limit;503 required owner
unavailable. Retention gaps are410 with an authorized resync link. Responses are structured
problem documents with request ID and reason/retryability; provider credentials are redacted.
Appwrite bound violations actually returned400 attribute_limit_exceeded in qualification; the
adapter must translate classified errors to the domain result rather than promise native409.

Idempotency keys bind stable authority/workspace/action to normalized payload, targets and
preconditions. Same key/payload recovers the same operation after current authorization checks;
different content returns conflict. Retention is explicit. Recover an existing operation before
retrying an uncertain external effect; no indefinite exactly-once promise follows deleting keys.

A preview records normalized arguments, exact revisions, policy versions, impact/coverage, hash
and expiry without changing delivery state. Approval is required only by the action's standing
policy. An approval-required plan creates a Decision with decision_kind=action_plan_approval;
ActionPlan.approval_ref points to it. The Decision inherits the exact plan workspace and optional
project binding; a workspace-level membership/connection action does not invent a delivery
project, and project-only authority cannot approve that workspace action. The immutable Decision binding contains plan_ref, plan hash,
plan revision and expiry. The ordinary decision.answer action takes approve/reject plus the exact
binding; it atomically approves/rejects the plan only after checking the current approver
authority, Decision and plan revisions, hash and expiry. A Decision default never approves it.
Preparing a replacement through prepareActionPlan with the prior plan_ref atomically supersedes
the old plan and invalidates its approval; the new normalized plan needs approval only when its
policy requires it. Editing or expiry therefore cannot reuse an earlier approval. Execution rechecks authority,
state and policy. A stronger approver authorizes that exact action, not a quiet expansion of the
proposer's standing grant. Routine decision defaults cannot authorize premise-class acts.

## Operations, events and audit

An accepted asynchronous command returns202, Location and an Operation ref. States distinguish
accepted, running, waiting_external, waiting_verification, succeeded, failed and cancelled.
Commit state is independently not_committed, committed or unknown. Acceptance is not proof of
an external mutation or intended outcome. Cancellation is a request with stated actual effect;
compensation is a separately authorized operation, not an implied undo.

Owner-local mutation, immutable event/audit, receipt and outbox share a transaction. Cross-service
calls use at-least-once delivery, stable effect IDs and reconciliation. Events have owner/
workspace cursor, subject/causality, time, type and authorized data. A disconnected consumer may
receive duplicates; stable event IDs allow deduplication. Expired cursors produce a retention
gap and snapshot resync. Provider Realtime is a wakeup hint, not the durable event ledger.

Audit records authority, executor, issuer/delegation, approver, action, target revision, owner
route, request/operation and verified receipts, with protected fields redacted. An older owner
API that only records a service actor does not magically gain individual attribution: the
connector records the operator-side audit and source receipt separately, exposes that coverage
gap, and requires an owner-contract enhancement before promising complete propagated identity.

The minimum pilot journey is: invite a colleague, grant one project and a narrow agent, inspect
an effective policy/blocker, perform an authorized action, follow the operation and evidence
links, then revoke access and verify every transport/feed loses the grant at the tested bound.

## Retained operator capability coverage

`action-catalog.json` contains operator_capability_coverage mapping the retained CLI/UI inventory
to registered public actions, read operations or explicit compound sequences. This is checked
against each requirement's public_capabilities list; transport labels on existing actions alone
do not prove that retained capabilities remain reachable. Job requests use job.run, which creates
one job task and requests guarded release. Project pause/resume affect new admission through the
registered owner, with current attempts shown separately. Chain stop/resume request fenced owner
control and report the actual observed effect. Need discharge requires owner-verified evidence.
Exports are permission-filtered; backup requests remain native provider operations and unavailable
unless that owner contract is installed. None of these is an arbitrary shell or HTTP escape.

Grant actions and scope are nonempty typed lists, authority/executor/audience/expiry are explicit,
and recognized operational limits are closed schema fields. Immutable definition and approval
content hashes remain canonical hashes. Array fields such as policy reason_codes retain arrays
from accepted commands through their persisted resource representation.
