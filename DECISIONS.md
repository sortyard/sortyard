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
  builders' own `wc -l` measured it. On main at `125e827` that count stood at 4,998, before
  the phase 2 release workflow is written (SY-V3-KERNEL-SIZE).
- **The baseline's count:** 37,797 is raw lines, comments, docstrings and blank lines
  included: `wc -l` over the 144 `.py` files under `control-plane/conductor` of k3s-harness at
  `66a72b6` whose path does not contain `test`. Recounted on 2026-11-24 from that commit
  (`git ls-tree -r`, then `git show` of each file into `wc -l`): 144 files, 37,797 lines.
- **Options:**
  1. Raw lines (`wc -l`) of the `.py` files of `engine`, `kernel` and `lane`. The same count
     as the baseline's, so the two numbers of the criterion compare like for like. It charges
     a line of explanation the same as a line of code.
  2. Budget code lines instead (a blank line, a comment line and a docstring not counted),
     with the raw figure beside it. Explaining why would cost nothing. Considered and not
     taken: it drops the figure from 4,998 to 3,445 on the same commit, which is a change of
     measure and not a reduction, and it would compare a code-line figure with a raw-line
     baseline. The build team does not loosen a win criterion the owner agreed by changing
     how it is measured.
  3. Count fewer packages (the lane adapters out, as "not kernel"). It makes the most room and
     measures the least: the adapters are hand-written and are where failure classes land.
  4. Count the shipped data files (`.toml`) too. It would charge a new state or policy rule
     against the budget, which is the opposite of what the criterion asks for (a table row,
     not a module).
- **Choice:** option 1, decided by the build team's lead.
  - **Counted:** every line of the `.py` files of `src/sortyard/engine`, `src/sortyard/kernel`
    and `src/sortyard/lane`, sub-packages included, as `wc -l` counts them.
  - **The budget:** that figure stays under 5,000. `tests/test_kernel_size.py` fails when it
    does not.
  - **Reported beside it, gating nothing:** code lines, as `code_lines` in that file computes
    them with the standard library (`tokenize`, `ast`): the physical lines that hold a token
    of code. Blank lines, lines holding only a comment and docstrings (the string that opens
    a module, class or function) are left out; any other string is in, SQL included. A
    docstring that is executed (`exec(__doc__)`) would be left out too; nothing does that.
  - **Data files do not count:** `item_states.toml`, `decision_policy.toml` and
    `lane_example.toml` (260 lines today) are not Python and are where the criterion wants a
    new failure class to go. A counted package may hold `.py` and `.toml` files only; any
    other kind of file fails the test, so code cannot sit uncounted in a stub or a script.
  - **One place:** the rule as values (`COUNTED`, `MAY_IMPORT`, `DATA_SUFFIXES`, `BUDGET`) is
    in `tests/test_kernel_size.py`; the test fails when the rows marked counted in the
    tables below are not the packages it counts. `python -m tests.test_kernel_size` prints
    both figures by package.
- **What keeps kernel code inside the count, and what does not:**
  - A counted package may import only the standard library, the project's declared runtime
    dependencies (`pyproject.toml`) and the counted packages. Anything else fails the test:
    another `sortyard` package, a second package beside `sortyard` (and `src/` may hold only
    `sortyard`), `import sortyard` alone, and an `import_module` or `__import__` whose
    argument is not a literal. The list of other packages the kernel may import
    (`MAY_IMPORT`) is empty; an entry needs its reason here.
  - **The limit of that check:** it follows what the kernel imports, not what imports the
    kernel. `src/sortyard/services/kernel.py` imports `engine`, `kernel` and `lane` to start
    them, so kernel logic written in `services` would be counted by nothing and seen by no
    test here. The rule is therefore stated, and held by review: `services` holds wiring and
    entry points only (read settings, build the runtime, run it, exit codes). A state, an
    owner, an adapter, a decision or a retry belongs in a counted package. The same goes
    for `api`, which calls admission and the ledger. The sizes of the uncounted packages are
    given below so that growth there is visible.
  - Nothing is moved out of the counted packages to make room.
- **The figures.** On main at `125e827`, before this change:

  | Package | In the budget | Raw lines (`wc -l`) | Code lines |
  |---|---|---|---|
  | `src/sortyard/engine` | counted | 722 | 438 |
  | `src/sortyard/kernel` | counted | 2,715 | 1,917 |
  | `src/sortyard/lane` | counted | 1,561 | 1,090 |
  | Total counted | | 4,998 | 3,445 |

  After the duplication removed with this record (SY-V3-KERNEL-SIZE), on main at `9b637f1`:

  | Package | In the budget | Raw lines (`wc -l`) | Code lines |
  |---|---|---|---|
  | `src/sortyard/engine` | counted | 718 | 436 |
  | `src/sortyard/kernel` | counted | 2,690 | 1,878 |
  | `src/sortyard/lane` | counted | 1,553 | 1,076 |
  | Total counted | | 4,961 | 3,390 |
  | `src/sortyard/services` | not counted | 1,269 | 873 |
  | `src/sortyard/api` | not counted | 2,740 | 2,173 |
  | `src/sortyard/shadow` | not counted | 1,073 | 773 |
  | `src/sortyard/models` | not counted | 2,541 | 1,775 |

  `models` is 1,936 lines of generated code (`_generated.py`) and 605 hand-written.

  The duplication removed is 37 raw lines (55 code lines): field lists written out twice, a
  typed read repeated per call, one rule kept in three places. No behaviour changed and no
  existing test was edited. It is small because the code repeats little: a scan for any
  three lines repeated anywhere in the counted packages finds only import lines and the method
  signatures that a Protocol and its implementations share.
- **Consequences:**
  - **The room is 38 lines** (4,999 less 4,961). That is enough for small fixes and for
    nothing else. It is **not** enough for the phase 2 release workflow (canary, promote,
    prober, live marks, leased rollback; HARNESS-V3 section 3.4), and no refactor of this
    code makes it enough.
  - **Open, not decided here:** where the release workflow's code lives and whether it counts
    toward criterion 10. Section 3.4 makes it a workflow per product that starts where the
    item workflow ends; whether that is "the kernel" of the criterion is to be settled when
    phase 2 starts. Until then nothing is moved out of the counted packages to make room.
  - A line of explanation costs a line of budget. The answer to that is to remove what
    repeats, not to cut the explanation; a comment or docstring that says why stays.
  - To reverse: set the rule's values in `tests/test_kernel_size.py` and amend this record in
    the same change.

<a id="sy-dec-011"></a>

## SY-DEC-011 — The agent-ended sentinel and the review answer are sealed with a per-Job key (2026-11-24)

- **Context:** A worker Job's `agent` container ran the agent command and left the review
  answer (`agent-output`) and the exit status (`agent-done`) as plain files in the workspace
  volume, where `push` read them. The command, and code it runs (a review may run the
  repository's tests), runs as the same user and can write both. An independent review of the
  estate worker image showed a review whose command answered findings reported as `approved`
  (SY-V3-REVIEW-ANSWER-SEALED). The containers share only volumes; `push` holds the GitHub
  token; the kernel packages are at their size limit.
- **Options:**
  1. The entry point reports through the `agent` container's termination message and the
     launcher's observer combines it with `push`'s. The channel is the kubelet's, which is
     sound, but `push` runs beside `agent` and cannot read it: the verdict, and the decision
     to push, would move into the observer in `src/sortyard/lane`, which has no room, and
     `push` would still need a signal to start that the agent cannot write.
  2. Run the agent command as another user, so file permissions protect the files. The
     entry point runs as non-root user 10001 and the pod sets no security context; changing
     user needs root or a capability in the container, which is what the image avoids.
  3. Hold the answer in memory, kill the command's whole process tree, and only then write
     the files. With nothing of the agent's alive, nothing rewrites them afterwards; but a
     file written *before* the command ends is still read by `push`, which runs beside it,
     so this alone does not stop an early sentinel.
  4. Option 3, and the sentinel carries a digest (HMAC-SHA-256) keyed by a per-Job secret.
     `clone`, which runs before any agent code, makes the key, keeps it in the state volume
     for `push`, and leaves a copy in the workspace; the `agent` entry point reads it, deletes
     the file, and makes itself non-dumpable before the command starts.
- **Choice:** option 4, all of it in `src/sortyard/services/worker.py`, with the answer
  attributed by the kernel. The command's standard output is one end of a Unix socket pair,
  not a pipe: `/proc/<pid>/fd` cannot open a socket again, and with `SO_PASSCRED` every read
  names the process that wrote it, and the kernel never joins two writers' data in one read
  (a writer can claim another's pid only with CAP_SYS_ADMIN over our pid namespace). Only the
  command's own process's output is the answer; output of processes it gave the socket to is
  logged, not heard. Reading stops at what was queued when the command exited (its exit is
  seen without reaping it, so its pid cannot be reused meanwhile). Then every process it left
  is killed, until `waitpid` says the entry point (pid 1, or a child subreaper) has no child.
  The entry point is made non-dumpable, sets no-new-privileges for the command, and refuses
  to run it while holding CAP_SYS_PTRACE or CAP_SYS_ADMIN. The answer is in the sentinel,
  under the digest; `agent-output` is gone. `push` reads the sentinel without following a
  link or blocking, and anything there without the digest is a failed result at once.
  Nothing changes in the Job manifest or the observer.
- **Consequences:** Code the command runs can make a build or review fail (a planted
  sentinel, a full volume, killing or stopping the entry point where it is not the
  container's first process, a process that cannot be killed within 20 seconds); it cannot
  make one succeed or approve by writing files or the answer stream. An agent command must
  write its answer from its own process: a wrapper script `exec`s the agent, or prints the
  answer itself. Residual risk, stated: (a) the command's own process is not protected from
  code it runs: where the node allows same-user ptrace of an ancestor (Yama `ptrace_scope` 0,
  or no Yama), that code can drive the command process and so write its answer; and a command
  that reloads its configuration or code from files the agent's user can write, or that is
  persuaded by what it reads (prompt injection), answers as that content steers it. The
  worker attests who wrote the answer, not why. (b) A planted sentinel fails `push` at once
  while the agent container runs on to the Job's deadline or its own end. (c) When the
  sentinel cannot be written at all (volume full), or the entry point is killed or stopped,
  `push` waits for the Job's deadline. (d) The manifest sets no security context (it is in
  `src/sortyard/lane`, held for the kernel restructure): the refusal above makes a privileged
  agent container a failed result, not a forged one; dropping all capabilities and
  `allowPrivilegeEscalation: false` in the manifest are for a follow-up.
  `tests/test_worker_entry.py` holds the behaviour.
