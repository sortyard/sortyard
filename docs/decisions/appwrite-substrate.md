# SY-DEC-004 — Appwrite as the persistence and identity substrate

> **No longer applies to the Sortyard core** (2026-11-23): the
> [SY-DEC-005 amendment](../../DECISIONS.md#sy-dec-005) makes the core Postgres only. This
> assessment is kept as provenance; products may still use Appwrite for their auth.

Date: 2026-11-15. Owner direction: prefer the existing Appwrite substrate unless a concrete
requirement prevents it. Status: approved planning design. Independent technical review: appwrite_auth, 2026-11-15, PASS.

## Decision and scope

Use self-hosted Appwrite as the target for Sortyard's application persistence and human
authentication. Reuse the estate's substrate and operating patterns. Retain Python, schema-led
domain models, the React console and Kubernetes workers. Sortyard's API continues to own its
business transitions and authorization.

This amends the Postgres-only part of SY-DEC-001. The current code, chart, replica and deployed
shadow release still use Postgres. This document changes the plan; it does not migrate data,
provision an Appwrite project/user/key, change a shared service or activate a new backend.
The existing Postgres store remains authoritative until its migration acceptance is complete.

No requirement found in this assessment inherently needs a separate Sortyard SQL database.
Appwrite persistence is the default to implement and qualify. A demonstrated failure of one
of the named invariants below is a concrete reason for a narrowly scoped exception; preference
for an ORM, SQL familiarity or an assumed lack of transactions is not such evidence.

## Alternatives and criteria

| Option | Fit against the requirements | Disposition |
| --- | --- | --- |
| Appwrite persistence + Auth | Reuses the substrate, transactions, sessions and Teams; requires native data mapping and proof of concurrency/history fences | Selected target |
| Appwrite Auth + dedicated Postgres | Preserves the implemented SQL store and triggers, but retains a second application persistence implementation and operating path | Fallback only for a demonstrated invariant or performance limitation |
| Postgres + independent login/session implementation | Preserves today's database but adds identity decisions already handled by the substrate | No concrete justification found |

Criteria are atomic state/ledger changes, bounded concurrent claims, immutable historical
records, permission isolation, attributable human/agent access, portability, maintainability
and compatibility with the current deployment. Production migration is a separate outcome.

## Verified capability baseline

The existing estate runs self-hosted Appwrite **2.6.1**. Its upstream tag resolves to
`a560f9d38c096374a37c6e3c13aabb9119abdf64`. Current Cloud documentation must not be treated as
proof of capabilities on that installation. Version and behavior are pinned in the replica.

- Appwrite supports staged database transactions, ordered atomic commit, read-own-writes and
  conflict detection. Transactional bounded numeric operations provide a possible lane-capacity
  primitive. The inspected release requires affected databases to share a physical database
  instance; keep Sortyard's transactional core in one Appwrite database.
- The inspected self-hosted defaults allow 100 operations per transaction and a 300-second
  transaction lifetime, configurable within supported bounds. Design short, bounded business
  transitions within the default budget; verify actual configured limits when provisioning.
- Account sessions/JWT, external-provider login and Teams membership/invites provide the human
  identity baseline. Authenticate through Appwrite's Account API/SDK; do not export its global
  signing secret to Sortyard. JWTs are session-bound and short-lived.
- Current OAuth-server, rich authorization and installation-token Cloud documentation is not
  an established self-hosted 2.6.1 capability. Those features are optional future integrations,
  not prerequisites for Sortyard's agent interface.

Evidence:
[transactions](https://appwrite.io/docs/products/databases/tablesdb/transactions),
[atomic numeric operations](https://appwrite.io/docs/products/databases/atomic-numeric-operations),
[pinned transaction commit controller](https://github.com/appwrite/appwrite/blob/a560f9d38c096374a37c6e3c13aabb9119abdf64/src/Appwrite/Platform/Modules/Databases/Http/Databases/Transactions/Update.php),
[pinned release constants](https://github.com/appwrite/appwrite/blob/a560f9d38c096374a37c6e3c13aabb9119abdf64/app/init/constants.php),
[pinned JWT route](https://github.com/appwrite/appwrite/blob/a560f9d38c096374a37c6e3c13aabb9119abdf64/app/controllers/api/account.php#L3509),
[Teams](https://appwrite.io/docs/products/auth/teams),
[OAuth-server Cloud announcement](https://appwrite.io/blog/post/announcing-oauth2-server).

This is source/documentation evidence, not a successful live Sortyard-on-Appwrite experiment.

## Persistence design

Use a small native Appwrite adapter behind Sortyard's domain operations. Its supported SDK/API
version is pinned to the chosen server. Reuse existing endpoint, session, retry/conflict and
schema-readiness patterns; keep the model Python rather than introducing a language rewrite.
The adapter implements explicit domain storage operations, not a SQL interpreter or a new ORM.

One dedicated logical Appwrite project holds Sortyard users and application data; it is not
one Appwrite project per delivery project. A Sortyard Project remains a domain resource.
Provisioning must not grant access to other applications' data, users or administrative keys.

Core tables include projects, tasks, lanes, chains/stages, immutable definition versions,
definition assignments, ledger/audit events, operation receipts, leases and integration outbox.
They share the transaction boundary. Long traces, context packets and artifacts use private
Storage objects with hashes and references; large payloads do not inflate every state write.
Blob upload and database commit are not one transaction: stage content first, publish its
reference only after verification, and reconcile abandoned uploads separately.

Preserve public Sortyard IDs and workspace/project scope. Appwrite's shorter physical IDs need
a deterministic, collision-checked mapping keyed by workspace/type/domain ID; store the original
ID as an indexed field. Do not truncate public IDs. Query/index fields are explicit; an opaque
JSON document alone is insufficient for task ordering, policy resolution and scope filtering.
Definitions retain canonical content hashes and immutable versions. Index/schema readiness
must be verified before publishing application readiness.

Every transition writes its mutable state, immutable event/audit records, idempotency receipt
and required outbox entry in one transaction. A request that repeats after a lost response must
return the recorded outcome rather than create a second chain, event or external instruction.
Expected revisions and shared conflict rows fence concurrent updates. Appwrite conflict is an
explicit result; only classified concurrency conflicts get bounded replay of the whole operation.

Claiming work must not use an unlocked count-then-create sequence. A claim transaction touches
the task revision and the shared lane-capacity row, applies a bounded atomic reservation and
creates the chain/lease/events together. Release, expiry and repair use the same capacity
accounting and fencing token. Prove both same-task exclusion and different-task competition for
the last lane slot. Source policy may define a separate urgent lane/reservation; preserve its
actual semantics rather than silently applying the normal cap to urgent work.

Use per-workspace event sequencing within the transaction when a durable ordered stream is
needed. Appwrite Realtime can wake consumers; it is not a durable queue, replay cursor or proof
that an external effect occurred. Outbox consumers use durable cursors and idempotent receipts.

### Append-only and immutable data

The existing Postgres ledger/history protections are real requirements. Generic API keys with
row-write scopes bypass resource permissions and cannot supply an equivalent table ACL fence.
They must not be the ordinary persistence writer for this design.

The candidate native fence uses a dedicated non-admin Appwrite service principal/session or
JWT. Immutable tables grant that principal create/read, without update/delete, and set
`rowSecurity=false` so a caller cannot grant itself row-level update/delete while creating a
record. Mutable tables grant only their required operations. Runtime receives no schema/admin
key and cannot change table permissions or row-security settings. Human/agent clients receive
no direct mutation access to canonical state or history tables.

Explicit empty row permissions remain good hygiene but do not alone establish immutability:
with row security enabled a creator may grant its own role permissions. Table permissions,
rowSecurity=false and absence of runtime administration must be proved together, including
transactional update/upsert/delete and bulk paths. Schema/bootstrap credentials are delivered
only to their separately scoped setup/upgrade job. They remain an administrative trust boundary,
as the database owner is in the existing SQL design.

This native fence is source-backed and **requires replica acceptance** before migration. If it
fails, document the precise failed operation and compare a corrected Appwrite configuration with
the narrow Postgres fallback. Do not silently weaken append-only semantics or retain a second
store by default.

Evidence:
[permissions](https://appwrite.io/docs/advanced/security/permissions),
[table/row permissions](https://appwrite.io/docs/products/databases/tablesdb/permissions),
[server API keys](https://appwrite.io/docs/advanced/platform/api-keys),
[pinned row creation](https://github.com/appwrite/appwrite/blob/a560f9d38c096374a37c6e3c13aabb9119abdf64/src/Appwrite/Platform/Modules/Databases/Http/Databases/Collections/Documents/Create.php).

## Authentication, collaboration and agent authority

Appwrite owns human accounts, login/session lifecycle and invitations. Use a workspace Team
and explicit delivery-project Teams, with one reviewed mapping of their roles into Sortyard
viewer/operator/admin grants. Membership has one authority; RoleBindings link to it or express
domain-specific grants, rather than duplicate an independently editable membership roster.
An Appwrite Team owner does not automatically become a Sortyard installation administrator.

Map identity by Appwrite issuer/project/user ID, not email. The console uses a supported
session integration with secure HttpOnly cookies or short-lived user JWTs, per-request client
context and CSRF protections appropriate to the chosen flow. API authorization resolves current
identity/membership server-side. Appwrite CRUD permissions do not express task claims, policy
promotion, stage ownership or the create-plus-claim exclusion; those remain Sortyard rules.

Agents use narrow, hashed, expiring Sortyard credentials. Preserve conductor, project grooming,
project sensor and stage-bound worker roles. A developer's delegated agent records issuer,
on-behalf-of identity, project, allowed actions, expiry and revocation; its permissions may only
narrow the issuer's grants. It receives neither an Appwrite administrative key nor the person's
full browser session. Serialize issuance so two simultaneous grants cannot accumulate the
forbidden create-and-claim combination. Dedicated autonomous accounts have explicit ownership.

Revocation covers sessions, membership, delegated credentials and open streams. Online checks
or a tested bounded invalidation/cache contract are required; signature-only JWT validation is
insufficient. Search, graph traversal, exports, context and artifact reads enforce the same
scope. Audit records include the domain actor, Appwrite user/membership IDs, delegation and
credential ID, never secret values. Private corpus/Loop Closer data is not shared by membership
in a Sortyard workspace.

Evidence:
[server-side sessions](https://appwrite.io/docs/products/auth/server-side-rendering),
[JWT integration](https://appwrite.io/docs/products/auth/jwt),
[Teams tenancy](https://appwrite.io/docs/products/auth/multi-tenancy),
[Realtime authorization](https://appwrite.io/docs/apis/realtime).

## Required proofs and plan order

These are proposed acceptance journeys for future bounded implementation slices, not assertions
that an Appwrite backend exists. Use a disposable replica of the pinned self-hosted release;
ordinary CI carries the domain/API contracts, while substrate integration runs in the replica
and on substrate/adapter changes according to the repository's current testing placement rules.

1. **Atomic delivery state:** competing claims for the same task and the final lane slot,
   transaction conflict/rollback, lease expiry, duplicated requests and interrupted responses
   preserve one chain, correct capacity and matching ledger/audit/outbox records.
2. **History and identity integrity:** the actual runtime principal can append history but
   cannot mutate/delete it through row, transaction, upsert/bulk or permission/schema changes;
   definition hashes, public-ID mapping and event replay remain consistent across restart.
3. **Collaborator and agent isolation:** an invited colleague can use project A; project B,
   private context/graph/artifacts and privileged transitions remain inaccessible. Revocation
   invalidates delegated access and feeds within the declared bound; concurrent token issuance
   cannot acquire both task creation and claiming.

Updated implementation order:

- Qualify the pinned Appwrite persistence fence and transaction primitives in the replica.
- Implement native schema/provisioning plus the explicit adapter and operation receipts.
- Wire Appwrite human identity/Teams into existing Sortyard authorization; preserve agent roles.
- Build the project console/API against those domain contracts. Read-only views over the
  existing harness can proceed while persistence qualification runs.
- Rehearse import/export and restart/replay using a retained snapshot. Preserve IDs, versions,
  hashes, relationships, actors and history; account explicitly for migration provenance.
- At an approved project/release boundary, stop the old writer, import the final delta, verify
  the new authority and switch one writer. Retain the original Postgres PVC and a tested rollback
  until accepted; no dual-write migration or automatic destructive Helm change.
- Continue the broader platform plan: project controls, collaboration, verified execution
  replacement and the skill improvement lifecycle. Appwrite changes their substrate, not scope.

The existing Postgres backend is a migration source, not a permanent second source of truth.
Setup and release promotion go through the current custody and GitOps mechanisms. Appwrite
unavailability is shown as unavailable with bounded retries; there is no silent writable local
fallback. Isolate the shared substrate's project credentials and resource budgets so a new
installation does not acquire other applications' authority.

## Consequences for the larger plan

Bring concrete Appwrite auth/Teams integration into the collaborator pilot; remove independent
password/session implementation as the default. Replace planned Postgres-specific storage work
with native Appwrite operations while preserving the domain invariants above. Revise the open
requirements draft's SQL triggers, local-auth assumptions and database packaging accordingly.
Its cuts to archetypes, skills, context recipes and the extension registry remain inconsistent
with the owner's November15 platform direction and are not adopted by this decision.

A standalone Sortyard install now has an explicit Appwrite endpoint/project prerequisite or a
documented separately operated Appwrite install. It does not silently deploy a second Appwrite
estate or require Cloud. The first-run flow checks the supported capability/version, required
schema and project grants, and returns actionable setup status. The existing chart's Postgres
defaults remain accurate for the current implementation until the reviewed migration ships.
