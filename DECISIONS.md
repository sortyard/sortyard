# Sortyard — decision records

Decisions live here as records, not as prose inside other documents (premise policy: a premise that matters gets a decision record with an owner and a date).

## SY-DEC-001 — Tech stack (2026-11-07, decided by Joe)

Postgres-only persistence stands for the core: the 2026-11-23 amendment to
[SY-DEC-005](#sy-dec-005) records that SY-DEC-004's Appwrite amendment no longer applies to it.

- **Question:** implementation language(s) for the Sortyard backend.
- **Decision:** Python backend (one codebase; the six services as separate entry points; all-in-one single-pod profile for small installs, split services for larger ones). Console in TypeScript + React (Vite SPA, static files served by the API service). Postgres is the only database (state, event ledger, work queue — no Redis, no message broker). Data models generated from the Phase 0 JSON Schemas, so schema and implementation cannot drift. Strict typing enforced. Helm chart deployment; workers are language-agnostic Kubernetes Jobs.
- **Alternative considered:** Go backend. Rejected for v1: the working conductor/dispatcher logic is Python (thousands of proven lines), and Phase 1's shadow-mode comparison against the old conductor is only meaningful if the port stays close to the original; a rewrite risks silent behaviour drift in a language the estate doesn't use. Go's install-story advantages don't outweigh port fidelity for v1; revisit only if install weight demonstrably bites.
- **Source:** Sortyard design draft v6 §4a (~/workspace/harness-reboot/HARNESS-REBOOT-DRAFT-v6.md).

## SY-DEC-004 — Appwrite substrate (2026-11-15)

**No longer applies to the Sortyard core** (2026-11-23, [SY-DEC-005](#sy-dec-005) amendment):
the core stores to Postgres only. The record below is kept as provenance; products may still
use Appwrite for their auth.

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

<a id="sy-dec-005"></a>

## SY-DEC-005 — Composed ecosystem control plane (2026-11-15), amended to the kernel scope (2026-11-23)

The 2026-11-23 amendment below governs. The November 15 decision that follows it is kept as
provenance; where they conflict, the amendment wins.

### Amendment — workflow kernel plus tracker view, Postgres only (2026-11-23)

- **Owner direction:** owner, 2026-11-23, on company/HARNESS-V3.md
  ([section 3.7 and the Decisions section](https://github.com/noncelogic/meta-harness/blob/main/company/HARNESS-V3.md)):
  "agree with all with caveats". That document's decision table applies the answer: Sortyard
  is re-scoped to the kernel plus the tracker view, and Appwrite is not part of the core. The
  owner's words on Appwrite, verbatim: "AppWrite was just a core foundation tech i had in mind
  to "speed up" saas development, it already handles auth, the idea was to minimize our decision
  space for common things any saas product needed. Not sure we needed appwrite for our harness,
  maybe it was just convenient at the time".
- **Decision:** this amendment supersedes the November 15 scope of SY-DEC-005. Sortyard is the
  workflow kernel plus the tracker view described in company/HARNESS-V3.md. The ecosystem
  control surface (the composed control plane over partner services below) is deferred.
- **Persistence:** the core stores to Postgres only. SY-DEC-004 no longer applies to the core;
  SY-DEC-001's Postgres-only rule stands. Products may still use Appwrite for their auth.
- **Engine:** a durable workflow engine is used behind one module instead of a hand-written
  one; the rest of the code reaches it only through that module.
- **Delivery:** delivery-plan increments MS1, MS2 and MS6 are deferred until the kernel runs one
  lane. The [delivery plan](docs/requirements/delivery-plan.md) and the
  [requirement catalog](docs/requirements/catalog.md) stay in the repository as reference,
  with no requirement or plan row changed; they are not the current build order.
- **Options considered:** keep the November 15 ecosystem scope with Appwrite (the superseded
  plan: execution only at MS3, after the resource kernel and connected project control);
  hand-write the workflow engine (owns durability and replay bugs the kernel does not need to
  own); the chosen kernel-first scope on Postgres with an engine behind one module.
- **How to reverse:** a later dated amendment to this record by the owner; the November 15 text
  and SY-DEC-004 remain below as the prior state. This record cancels and moves no board item.

### Original decision (2026-11-15, superseded by the amendment above)

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

## SY-DEC-007 — Durable workflow engine (2026-11-23)

- **Owner direction:** company/HARNESS-V3.md section 3.1 and decision 2, accepted by the owner
  on 2026-11-23 ("agree with all with caveats"): Temporal on Postgres behind one module, DBOS
  as the fallback, with the failure tests run before any kernel code depends on the engine.
- **Decision:** Temporal, behind `src/sortyard/engine/`, the only package that imports the SDK.
  The Temporal Python SDK 1.36.1 passed all four failure tests: a worker killed mid-step, a
  restart on changed step code, a seven-day timer, a signal sent while no worker runs. The
  fallback is not needed.
- **Not yet verified:** Temporal's server storing to our Postgres. The tests run the engine's
  development server (in-memory store) and its time-skipping test server; no server is deployed.
- **Options, results, what the tests showed and how to reverse:**
  [workflow engine record](docs/decisions/workflow-engine.md).

## SY-DEC-008 — Signing the GitHub App token: `cryptography` (2026-11-23)

- **Context:** the GitHub port (`src/sortyard/lane/github.py`, SY-V3-GITHUB-PORT) mints
  installation tokens as a GitHub App. GitHub accepts only a JSON web token signed RS256 with
  the App's RSA key for that, and the Python standard library has no RSA signing.
- **Options:**
  1. `cryptography` for the one signature; the token itself (two base64 JSON parts) is built
     by hand. One audited dependency with wheels for every platform the image builds on.
  2. `PyJWT[crypto]`: builds the token too, but brings `cryptography` anyway, so it is two
     dependencies for about ten lines saved.
  3. RSA PKCS#1 v1.5 written by hand on `pow()` with a hand-written PEM/DER reader: no
     dependency, but hand-written key parsing and signing in the path that holds the
     estate's most powerful credential.
  4. Calling the `openssl` binary: no Python dependency, but the image would need the binary
     and the key would pass through a child process.
- **Choice:** option 1, `cryptography>=42`, imported only by `src/sortyard/lane/github.py`.
- **Consequences:** one more runtime dependency in the image. The tests use the same library
  to make a throwaway key and, in the fake GitHub, to verify the client's signature with the
  public key. To reverse: replace the two `cryptography` calls in `HttpGitHub` (load the key,
  sign); nothing else imports it.
