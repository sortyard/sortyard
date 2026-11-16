# Sortyard — decision records

Decisions live here as records, not as prose inside other documents (premise policy: a premise that matters gets a decision record with an owner and a date).

## SY-DEC-001 — Tech stack (2026-11-07, decided by Joe)

The persistence portion is amended for future implementation by SY-DEC-004 below.
The current code and deployed release still use the original Postgres backend.

- **Question:** implementation language(s) for the Sortyard backend.
- **Decision:** Python backend (one codebase; the six services as separate entry points; all-in-one single-pod profile for small installs, split services for larger ones). Console in TypeScript + React (Vite SPA, static files served by the API service). Postgres is the only database (state, event ledger, work queue — no Redis, no message broker). Data models generated from the Phase 0 JSON Schemas, so schema and implementation cannot drift. Strict typing enforced. Helm chart deployment; workers are language-agnostic Kubernetes Jobs.
- **Alternative considered:** Go backend. Rejected for v1: the working conductor/dispatcher logic is Python (thousands of proven lines), and Phase 1's shadow-mode comparison against the old conductor is only meaningful if the port stays close to the original; a rewrite risks silent behaviour drift in a language the estate doesn't use. Go's install-story advantages don't outweigh port fidelity for v1; revisit only if install weight demonstrably bites.
- **Source:** Sortyard design draft v6 §4a (~/workspace/harness-reboot/HARNESS-REBOOT-DRAFT-v6.md).

## SY-DEC-004 — Appwrite substrate (2026-11-15)

- **Owner direction:** use the existing Appwrite substrate for persistence and auth unless a
  concrete requirement prevents it.
- **Planning decision:** Appwrite persistence, Auth and Teams are the preferred target; retain
  Sortyard's business authorization, scoped agent credentials and domain invariants. Python,
  React, schema-led models and Kubernetes workers remain the selected implementation stack.
- **Assessment:** no inherent atomicity or human-auth blocker was found in self-hosted2.6.1.
  Native transaction, append-only permission, replay and collaborator-isolation proofs are
  required before replacing the current store. Hybrid Auth+Postgres is an exception for a
  reproducible unsupported requirement, not the default.
- **Alternatives, evidence and migration order:**
  [Appwrite substrate assessment and plan](docs/decisions/appwrite-substrate.md).
- **Current implementation:** Postgres remains authoritative until the reviewed migration;
  this decision provisions no credentials, changes no live data and does not adopt Cloud-only
  OAuth-server features.

## SY-DEC-005 — Composed ecosystem control plane (2026-11-15)

- **Owner direction:** one control plane for the harness ecosystem, with both an operator
  UI and public APIs through which agents act on the operator's behalf.
- **Decision:** formalize scoped, versioned resources and relationships; route UI, REST,
  MCP and CLI through the same authorized actions. Retain each service's authority until
  an explicit single-writer handover. Standing delegation narrows live operator grants.
- **Boundaries:** CortexPlane owns outer goals/processes; Walwarden owns memory; Ranker
  owns ranking; Closer owns commitments. Existing policy families remain with the policy
  engine while Sortyard integrates inspection, evaluation and attributable scoped writes.
- **Alternatives:** a dashboard alone leaves agents and automation fragmented; copying all
  partner data and logic into Sortyard creates competing writers and loses owner semantics.
  A composed API provides one discoverable surface without either limitation.
- **Requirements and contracts:** [consolidated baseline](docs/requirements/README.md).
  Its capability catalog is planned, not evidence that handlers are installed.
- **Delivery:** connected project operations precede native execution replacement; reviewed
  CI/GitOps remains the release path. Appwrite qualification is substrate evidence, not
  authorization to migrate production state or retire meta-harness.

## SY-DEC-006 — First-class operating processes (2026-11-16)

- **Owner direction:** Sortyard goes beyond current Kubernetes harness/conductor/runner and
  meta-harness behavior. Triage/self-heal processes, seeded policies and responsible actors
  are first-class parts of the operator and delegated-agent control plane.
- **Decision:** add OperationalActor, OperationalProcessVersion and OperationalProcessRun,
  linking existing cases, attempts, agent runs, policy decisions and operations. Publish/adopt
  process versions through the existing definition registry; reuse existing controller/lease/
  operation execution machinery. A consumer must declare and test exact policy parameters.
- **Criteria:** visible responsibility and execution history; bounded authority/budgets;
  reproducible source versions; operator/agent parity; compatibility with existing owners.
- **Alternatives considered:** retaining current controller-specific loops with only status
  projections needs less model work but leaves cross-process ownership, configuration and
  budgets implicit. Extending WorkflowVersion alone reuses delivery stages but obscures
  event-driven incident correlation and long owner waits across several chains. The selected
  outer process model keeps delivery workflows and existing runtime components reusable.
- **Consequence:** reviewed seed templates require explicit owner/consumer/parameter binding
  before adoption/activation. They introduce no live policy writes, actor grants or direct
  cluster repair path. Independent review PASS is in the product evidence.
- **Contract:** [governed operating processes](docs/requirements/operating-processes.md).
