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

## SY-DEC-009 — A merge that never happens is decided, not re-armed for ever (2026-11-24)

- **Context:** HARNESS-V3 section 3.1 gives the default of `merging` at its 30-minute limit as
  "update the branch and re-arm", and the state table shipped it as `redispatch`. The merge
  adapter (SY-V3-GITHUB-PORT) waits while checks on the head to merge have not reported. Checks
  that never report therefore made `merging` redispatch every 30 minutes with no end: the one
  wait in the table that nothing bounded (SY-V3-LANE-RUNTIME).
- **Options:**
  1. Leave `redispatch`. Faithful to the section's wording, and an item can stay in `merging`
     for ever with nobody asked.
  2. `retry = N`, then `decision`, keeping the action `update-branch`. Each passed limit still
     updates the branch and re-arms; after N of them the decision step is asked, as it is for
     `building` and `checking`.
  3. Have the merge adapter answer `conflict` after its own count of looks. That puts a
     counter in an adapter that holds no state, and sends an item to `fixing` with nothing to
     fix.
- **Choice:** option 2 with N = 3: `default = { retry = 3, then = "decision", action =
  "update-branch" }` in `src/sortyard/kernel/item_states.toml`. Asked for by the build team's
  lead in the SY-V3-LANE-RUNTIME brief; it carries no owner decision.
- **Consequences:** `merging` is dispatched at most four times (two hours) before a decision.
  The decision's table default is `resume`, which returns the item to `merging`; the same
  question answered the same way a second time waits on a named need, as every repeated
  decision does. The first limits behave as section 3.1 says. The number 3 is the team's and
  provisional: it is one value in the data file, and changing it is a change to that file only.
  `tests/test_item_workflow.py` and `tests/test_state_table.py` hold the behaviour.

## SY-DEC-010 — What the kernel size budget counts (2026-11-24)

- **Context:** win criterion 10 of HARNESS-V3 section 5 is "Size of the hand-written kernel:
  under 5,000 lines, against 37,797 in the conductor; a new failure class adds a table row, not
  a module". Nothing said which files count or whether a comment counts, and nothing but the
  builders' own `wc -l` measured it. On main at `125e827` that count stood at 4,998 before the
  phase 2 release workflow is written, so every line of explanation was competing with code
  for the last two lines (SY-V3-KERNEL-SIZE).
- **Options:**
  1. Raw lines (`wc -l`) of the Python in `engine`, `kernel` and `lane`. It is the count used
     so far and most likely the kind of count behind the conductor's 37,797 (not checked). It
     charges a docstring or a comment that explains why the same as a line of code, so the
     cheapest way to stay under it is to delete explanation.
  2. Code lines of the same packages: a physical line counts when it holds code; a blank line,
     a line holding only a comment and the lines of a docstring do not. The raw figure is
     reported beside it. Explaining why costs nothing; code still costs what it did.
  3. Count fewer packages (the lane adapters out, as "not kernel"). It makes the most room and
     measures the least: the adapters are hand-written and are where failure classes land.
  4. Code lines, with the shipped data files (`.toml`) counted too. It would charge a new
     state or policy rule against the budget, which is the opposite of what the criterion
     asks for (a table row, not a module).
- **Choice:** option 2. A team choice (the build team's proposal, taken as proposed); it
  carries no owner decision.
  - **Counted:** the `.py` files of `src/sortyard/engine`, `src/sortyard/kernel` and
    `src/sortyard/lane`, sub-packages included.
  - **The figure:** code lines, as `code_lines` in `tests/test_kernel_size.py` computes them
    with the standard library (`tokenize`, `ast`): every physical line that holds a token of
    code, so each line of a statement or string that runs over several lines counts, and a
    line of code with a comment after it counts once. Not counted: blank lines, lines holding
    only a comment, and docstrings (the string that opens a module, class or function). Any
    other string counts, SQL included.
  - **The budget:** the figure stays under 5,000. The raw `wc -l` figure is reported beside it
    and has no budget.
  - **Data files do not count:** `item_states.toml`, `decision_policy.toml` and
    `lane_example.toml` (260 lines today) are not Python and are where the criterion wants a
    new failure class to go. A counted package may hold `.py` and `.toml` files only; any
    other kind of file fails the test, so code cannot sit uncounted in a stub or a script.
  - **Not counted:** `api`, `models`, `services`, `shadow`. They are not the kernel, and the
    kernel imports none of them. If it ever does, the test fails until that package is
    counted or put on the short list of packages the kernel may import (`MAY_IMPORT`, empty
    today), with the reason added here.
  - **One place:** the rule as values (`COUNTED`, `MAY_IMPORT`, `DATA_SUFFIXES`, `BUDGET`) is
    in `tests/test_kernel_size.py`; the test fails when the packages in the tables below are
    not the packages it counts. `python -m tests.test_kernel_size` prints both figures.
- **What the change of rule does, and what it does not:** choosing code lines drops the
  figure from 4,998 to 3,445 on the same commit. That is a change of measure, not a
  reduction: not one line of the kernel went away with it. The criterion as it was measured
  until today (raw lines) stands at 4,961 after this change, 38 under 5,000. Against the
  conductor's 37,797 the raw figure is the like-for-like one, if that number was a raw count.

  On main at `125e827`, before this change:

  | Package | Code lines | Raw lines (`wc -l`) |
  |---|---|---|
  | `src/sortyard/engine` | 438 | 722 |
  | `src/sortyard/kernel` | 1,917 | 2,715 |
  | `src/sortyard/lane` | 1,090 | 1,561 |
  | Total | 3,445 | 4,998 |

  After the duplication removed with this record (SY-V3-KERNEL-SIZE):

  | Package | Code lines | Raw lines (`wc -l`) |
  |---|---|---|
  | `src/sortyard/engine` | 436 | 718 |
  | `src/sortyard/kernel` | 1,878 | 2,690 |
  | `src/sortyard/lane` | 1,076 | 1,553 |
  | Total | 3,390 | 4,961 |

  The duplication removed is 55 code lines (37 raw): field lists written out twice, a typed
  read repeated per call, one rule kept in three places. No behaviour changed and no existing
  test was edited. It is small because the code repeats little; the room below comes from the
  rule, not from the refactor.
- **Consequences:**
  - **Room for phase 2.** The budget leaves 1,609 code lines (4,999 less 3,390). The release
    workflow (canary, promote, prober, live marks, leased rollback; HARNESS-V3 section 3.4) is
    not designed yet. The estimate here is 1,000 to 1,500 code lines, from the size of what
    exists: the item workflow is 400, the GitHub port and its adapters 443, the jobs port and
    the worker launcher 480. That fits, with 100 to 600 lines left for the two kernel fixes
    waiting on room and for phases 3 and 4. It is an estimate, and it is tight at the top:
    a release workflow that reuses the state-table loader and the ledger lands low, one that
    brings its own table format lands high.
  - **By raw lines it does not fit,** and no refactor of this code makes it fit: 38 lines are
    left. If the criterion is read as raw lines, phase 2 breaks it. This record does not
    settle that reading; it gives both figures so that it can be judged.
  - A docstring or comment that explains why is free. A docstring that hides code is not
    possible: only the string that opens a body is left out.
  - To reverse: set the rule's values in `tests/test_kernel_size.py` (count raw lines, or
    other packages) and amend this record in the same change.
