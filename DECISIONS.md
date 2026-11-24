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

## SY-DEC-011 — What the Walwarden lane move accepts, and what guards a walwarden merge (2026-11-24)

- **Context:** declaring the estate walwarden lane (SORTYARD-197, noncelogic/estate-gitops
  pull request 5) left gaps between what the lane says and what really checks a change. Facts 1
  and 2 and the probe gap are in estate-gitops `sortyard-kernel/README.md` under "Known gaps";
  fact 3 is in SORTYARD-197's report on SORTYARD-179. The move of the lane (SORTYARD-179) needs
  each one either accepted for the move or fixed first. Facts, read 2026-11-24:
  1. The kernel requires `images.ci` to equal `images.worker` (`worker-image-is-ci-image`,
     `src/sortyard/kernel/capabilities.py`), so the lane repeats the worker image (Node 24) as
     its CI image. The real CI is not an image: the required check `gate1` of
     noncelogic/walwarden-context (strict) runs on `[self-hosted, aks]` runners with
     `setup-node` Node 22 and pnpm 10.28.2. Tests that need Docker, a database or a browser run
     in neither the worker nor `gate1`.
  2. noncelogic/walwarden has no branch protection and no pull-request CI. Its only workflow,
     `deploy.yml`, runs on every push to `main`. Its first job
     (`classifyProductionDeploymentScope.sh`) skips the rest when every changed path is on the
     repository's trusted canary list; otherwise it deploys production:
     - a gate job runs `npm run test:deploy`, `npm run test:deploy:azure` and `npm run typecheck`;
     - after the gate, `migrate` (`prisma migrate deploy` on the production database) runs
       beside the image build and **before** promote, with no rollback;
     - promote switches both sites, rolling the sites (not the database) back on a failed
       promote;
     - a live proof runs after promote; its failure rolls nothing back.

     The lane declares `checks = []` for walwarden, so the kernel merges a walwarden pull
     request on review alone. So does the legacy driver today: pull request 1166 of walwarden,
     merged by the conductor on 2026-11-23, carries only the old Vercel statuses, and the legacy
     pipeline is `PR ─▶ one review ─▶ auto-merge` (meta-harness `operations/task-pickup.md`,
     section 1). The lane sets `workflow-files = true`, so a pull request can also change
     `deploy.yml` itself, which the push then runs.
  3. The kernel does not tie a lane to a project. Admission checks that the lane exists and
     that the item's repository is one of the lane's (`src/sortyard/kernel/admission.py`), so
     an operator of another project could admit an item on the walwarden lane. Nothing does.
  4. The runner-pool probe checks only that the worker cluster answers for Jobs, not that a
     runner of the `aks` pool is there.
- **Options:** for the walwarden merge guard (fact 2), the one that decides whether the move
  can break the product:
  1. The lane waits on a check. There is no pull-request check to wait on; a declared check
     that never reports leaves every walwarden item in `merging` until its decision
     (SY-DEC-009). It needs a pull-request workflow in walwarden first.
  2. The review state is the guard, as under the legacy driver, with the deploy workflow after
     the merge as it is. This rests on the review verdict being the reviewer's own. The
     independent review of the estate worker image showed that code run during a review can
     write the verdict file (SORTYARD-194, SY-V3-REVIEW-ANSWER-SEALED), so a pull request
     could approve itself and go straight to the production database and sites, its own
     `deploy.yml` changes included.
  3. Hold the walwarden repository out of the lane (walwarden-context only). That splits the
     board across two systems, which section 6 of HARNESS-V3 and the brief rule out (a lane
     lives on one system at a time).
- **Choice:**
  - **Fact 2: option 2, gated on SORTYARD-194.** The walwarden lane is not moved to the kernel
    (`to-kernel --apply`) until SORTYARD-194 is Done. With the verdict sealed, the kernel's
    guard on a walwarden merge equals the legacy driver's: one independent review, which is
    also the only guard on a migration, on a change to `deploy.yml`, and on a change that
    passes the deploy gate but breaks the live sites. The stronger guard, option 1, is filed
    as WALWARDEN-189 (WW-PR-DEPLOY-GATE: the deploy gate, and the migrations on a throwaway
    database, run on every pull request). When it lands, the lane's walwarden entry declares
    that check by a reviewed estate-gitops change. It is not a precondition of the move,
    because it would hold the move for a guard the legacy driver does not have either.
  - **Fact 1: accepted for the move.** The image is not what gates a walwarden-context merge;
    `gate1` is, and GitHub requires it, so it runs on the same runners with Node 22 whichever
    system drives the item. A change that passes in the Node 24 worker but fails on Node 22
    turns `gate1` red and goes back to fixing; it cannot merge. The cost is a fix round, not a
    broken product. Filed as SORTYARD-201 (SY-V3-LANE-CI-NOT-AN-IMAGE), so the lane file stops
    stating a CI image it does not have.
  - **Fact 3: accepted for the move.** Only operators admit items, and the move tool admits
    under the project `walwarden`. Filed as SORTYARD-202 (SY-V3-LANE-PROJECT-BOUND).
  - **Fact 4: accepted for the move.** If the `aks` runners are gone, `gate1` never reports and
    walwarden-context items wait in `merging` until their decision (SY-DEC-009): a stall, not a
    broken product, and the same `gate1` stalls the legacy driver.
  - These are the build team's choices under the brief ("PLEASE PLEASE STOP BREAKING
    PRODUCTS", the owner, 2026-11-24); they carry no other owner decision.
- **Consequences:**
  - SORTYARD-179's real move waits on SORTYARD-194 and SORTYARD-203 Done, in addition to its
    rehearsal record and the announcement the move tool checks.
  - After the move, a walwarden pull request merges on one sealed review and is checked by the
    deploy workflow only after the merge, as today. A gate failure stops the deploy before the
    migration and promote and leaves `main` red; a bad migration or a live-proof failure is not
    rolled back by the workflow. The kernel has no red-main handling, and the legacy driver's
    `red-main` items are board items without a task spec, which the move tool reports
    `no-spec` and does not move (SORTYARD-203 gives them an owner before the move).
  - To reverse: move the lane back (`to-legacy`, until the day-28 verdict), or declare a check
    for walwarden once WALWARDEN-189 lands.

<a id="sy-dec-012"></a>

## SY-DEC-012 — The agent-ended sentinel and the review answer are sealed with a per-Job key (2026-11-24)

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
  to run it while holding CAP_SYS_PTRACE, CAP_SYS_ADMIN or CAP_DAC_READ_SEARCH, or any
  capability as a user who is not root. The answer is in the sentinel,
  under the digest; `agent-output` is gone. `push` reads the sentinel without following a
  link or blocking, and anything there without the digest is a failed result at once.
  Nothing changes in the Job manifest or the observer.
- **Consequences:** Code the command runs can make a build or review fail (a planted
  sentinel, a full volume, killing or stopping the entry point where it is not the
  container's first process, a process that cannot be killed within 20 seconds); it cannot
  make one succeed or approve by writing files or the answer stream. An agent command must
  write its answer from its own process. A wrapper that prints an answer it got from a program
  it runs is attested only as far as its own channel to that program, and a file or a pipe is
  not one (2026-11-24 review: one `os.rename` by the tests a reviewer ran forged an approval
  through the estate's wrapper, which read Claude Code's output from a file; a pipe is opened
  again through `/proc/<pid>/fd` under Yama `ptrace_scope` 1). So the wrapper `exec`s the
  program, or reads it through `AttestedOutput`, the same socket and `SO_PASSCRED` check as the
  worker's, and makes itself non-dumpable. Residual risk, stated: (a) the command's own process is not protected from
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

## SY-DEC-013 — Who owns the Walwarden board's alert and decision items after the lane move (2026-11-24)

- **Context:** the rehearsal of the Walwarden lane move (SORTYARD-179, estate-gitops pull
  request 8) reported 13 open WALWARDEN items `NOT MOVED`: 11 with no task spec (7, 8, 9, 11,
  13, 14, 15, 32, 148, 176, 187) and 177 and 188, held by a Plane link to 176
  (PREMISE-DECISIONS). After the move the legacy driver is off for the whole lane (`build: off`,
  `tasks: off`). Read 2026-11-24 in noncelogic/k3s-harness `control-plane/conductor` at
  `d3e7f6b`:
  1. plane-sync still projects a board whose driver has build off. Its product sync
     (`plane_sync_sweep._sync`, `plane_sync_sources.source_items`) is not gated on the driver,
     so the alert items `main is red: <workflow>`, `Scheduled run failing: <workflow>` and
     `Health: <repo>` are still opened on a red run and closed on a green one. On the SORTYARD
     board, whose build went off on 2026-11-23 at 09:53Z (meta-harness `0e11baf8`), plane-sync
     updated such items, and its stranded-build item, later that day (85, 86, 87 and 133,
     between 11:53Z and 22:19Z).
  2. The answer to a red run is gated on the driver: `queue_triage` returns at once for a board
     that is not driven (`plane_sync_red_main.py`), so no triage item, no CI-only re-run and no
     fix build follow. The file-verify sweep and the stranded-build ship step are gated the same
     way.
  3. The kernel has no red-main handling (SY-DEC-011).
- **Options:** for the answer to a red main or a failing scheduled run on a moved lane:
  1. Move now, and leave red runs shown on the board and answered by nobody until the kernel
     has red-main handling. A red `main` of walwarden-context turns `gate1` red on every pull
     request brought up to date (reasoning from `gate1` being required and strict, not an
     observed incident), so the whole lane would stall with no owner.
  2. Have the legacy conductor go on answering red runs for a board whose build is off. That is
     two systems driving one lane, which section 6 of HARNESS-V3 and the brief rule out.
  3. The kernel answers red runs on its own lanes (SORTYARD-204, SY-V3-RED-MAIN-OWNED: one triage
     item per red workflow, admitted on the lane, ended by a green run), and the move waits for
     it.
- **Choice:** option 3. The real `to-kernel --apply` of the walwarden lane waits for
  SORTYARD-204 Done, as it waits for SORTYARD-194 (SY-DEC-011). SORTYARD-204 is linked as a
  blocker of SORTYARD-179. Option 1 leaves a state with no owning service, against the owner's
  zero-stall mandate and "PLEASE PLEASE STOP BREAKING PRODUCTS" (2026-11-24). Option 2 breaks the
  one-system-per-lane rule. This is the build team's choice under the brief; it carries no other
  owner decision.
- **The 13 items, as decided on SORTYARD-203 (a board comment on each, 2026-11-24):**
  - 7, 8, 9, 11 and 148 are cancelled as stale: their workflows are no longer in the
    repositories (walwarden has only `deploy.yml`, walwarden-context only `ci.yml`), so they
    could never close themselves.
  - 13 (deploy) is done: three deploy runs on `main` succeeded after the failing hand-started
    run. 14 (a finished build with no pull request) and 187 (an invisible filing) are done: both
    named only WALWARDEN-170, which is cancelled. 32 (sitemap) is done: its live done-test
    passes.
  - 15 (`Health: walwarden`) stays on the board. plane-sync owns its state (fact 1). Its one
    failing line today is the hand-started deploy run of 2026-11-21, which plane-sync counts as
    the scheduled kind; the deploy runs on `main` after it are green, so it is not a red main and
    clears on the next successful hand-started deploy run (not dispatched for this: it deploys
    production). A new red run is answered by SORTYARD-204. 13 stays Done while plane-sync's
    cached copy of it is unchanged; if that cache is lost, it reopens on the same old run, with
    the same reading. The move tool reports 15 `NOT MOVED` (`no-spec`), named on SORTYARD-179
    with these owners. So is any later alert item the sync files.
  - 176 is decided (I42, no owner gates): the access to noncelogic/walwarden is provided by the
    kernel lane, which declares that repository and whose push probe passed (SORTYARD-197). 176 is
    closed. 177 and 188 state the dependency as the capability need
    `repository:noncelogic/walwarden`, which the kernel checks. They wait in Backlog, which the
    legacy release does not pick up; the legacy driver cannot build that repository anyway. The
    Plane link from 177 to 176 is removed. The move admits them.
- **Other open items found on the way:**
  - 174 (not one of the 13; it moved in the rehearsal) is cancelled as superseded by 177, so the
    inventory is built once.
  - 189 (WW-PR-DEPLOY-GATE, filed after the rehearsal) had a spec that did not parse as YAML; it
    is re-serialized unchanged, and the move admits it.
  - 4, 5 and 6 are projected pull requests the owner opened by hand (walwarden 1148, 1096 and
    1034, August 2026). They are not conductor work and stay with their author, but the move
    tool's drain waits for every started item, so it would never end: filed as SORTYARD-206
    (SY-V3-DRAIN-CONDUCTOR-WORK-ONLY). Closing them is not the build team's call.
  - The estate kernel has no project or operator for walwarden, on purpose until the move, so the
    to-kernel plan stops at its first kernel read (HTTP 403). Filed as SORTYARD-205
    (SY-V3-WALWARDEN-OPERATOR), applied as the move's first step.
- **Consequences:**
  - SORTYARD-179's real move waits on SORTYARD-194, 203, 204, 205 and 206 Done (each linked as
    a blocker of 179).
  - The board's alert items are only as current as plane-sync's projection. On 2026-11-24 the
    last five boards in the `repos.yaml` order, WALWARDEN and SORTYARD among them, had not been
    projected since 2026-11-23 about 22:19Z, because each pass spent its budget first. Filed on
    the harness board as HARNESS-4177 (PLANE-SYNC-TAIL-BOARDS-REACHED).
  - To reverse: drop SORTYARD-204 as a blocker of SORTYARD-179 with a new record here, or move
    the lane back (`to-legacy`). After a move back, 177 and 188 come back in Backlog; to build
    them under legacy, register noncelogic/walwarden in its control-plane registry.

## SY-DEC-014 — The red-main observer sits outside the kernel and talks to it through the API (2026-11-24)

- **Context:** SORTYARD-204 (SY-V3-RED-MAIN-OWNED; SY-DEC-013 option 3) asks that a red default
  branch, or a failing scheduled run, of a lane repository be answered by exactly one kernel
  triage item. Win criterion 10 (HARNESS-V3 section 6) keeps the counted kernel (`engine`,
  `kernel`, `lane`) under 5,000 lines; on 2026-11-24 `main` counts 4,981, and those 19 lines are
  SORTYARD-190's. The lead's placement decision on SORTYARD-204 (2026-11-24, origin: harness,
  not an owner ask) puts the observer outside the counted packages.
- **Choice:** `sortyard-red-main` (`src/sortyard/services/red_main.py`), its own Deployment
  (`redMain.enabled`), is a client of the public API, as an operator tool is:
  - It reads GitHub as the App (one token per repository per pass, `actions: read` and
    `contents: read`) through the kernel's GitHub client, and admits triage items with
    `admitItem`, records evidence and withdraws with `requestItemChange`.
  - It owns only "is there an open triage item for this red workflow". The kernel owns the item
    once admitted, as any other. The deduplication key (repository, workflow) is in the item's
    spec (`incident`) and is read back through `getProjectQueue` and `getItem`; it needs no list
    of ended items (SORTYARD-192), since only an open item answers a red run.
  - An item's id is fixed by the run it answers (`red-main-<digest of repository and
    workflow>-<run id>`), so two observers, or one restarted mid-pass, admit one item: the API
    answers 200 to the same admission.
  - Evidence is a request with the answer `resume` and the run in its reason: it is put on the
    item's timeline, the shipped policy has no rule for it, and the decision state's default
    (`resume`) returns the item to the stay it was in, with the same dispatch and deadline
    (held by `tests/test_item_workflow.py`, "a request goes to the decision and the stay it
    interrupted carries on"). It is read back from the timeline, so a restarted observer does
    not record a run twice; a withdrawal is read back the same way, and one not granted (a
    binding whose role is not operator) is reported every pass, not asked again.
  - A failing run re-run green keeps its id and creation time; that run green ends the
    incident too.
  - The verdict is the newest run on the branch, in progress included, and only a run of the
    newest commit speaks for it. The estate drill (2026-11-24) admitted a second item for a red
    run that predated the merged fix while the merge commit's run was still in progress; the
    item was withdrawn as moot when that run went green, and the rule was changed.
  - A red run of a commit the branch has moved past is answered only after the new head has
    gone `HEAD_GRACE_SECONDS` (300) without a run of its own: the second estate drill admitted
    a second item 6 s after a fix merged, before GitHub listed the merge's run. A workflow that
    skips the new head (a path filter) is still answered, after the grace, measured from when
    the observer first read that head; on a repository whose head moves more often than the
    grace, such a red run waits until the head stays put.
  - A newest run that stays queued or waiting (an environment approval) holds the verdict until
    it ends; an open item meanwhile keeps the kernel's own limits. No limit of the observer's
    own ends that wait (review of sortyard/sortyard#42).
  - It gets its API token by issuing itself a short-lived operator token for the watched lane's
    role binding from the database, as `sortyard-api --issue-operator-token` does: it holds the
    database credential the API holds. A long-lived token kept in a Secret was the alternative;
    it would need rotating by hand and live for days.
- **What this changes in the rules:** AGENTS.md says `src/sortyard/services` holds wiring and
  entry points only. This module holds a decision (when a red run gets an item) and is the one
  recorded exception: it holds no item state, writes nothing but through the API, and could run
  anywhere an operator token reaches the API. Moving it into the kernel would cost about 300
  counted lines the budget does not have.
- **Limits, recorded:** the triage attempt limit and the CI-only re-run of CIH-001/002 are not
  in scope (ticket notes). A triage item withdrawn by hand while the run is still the newest red
  one is not admitted again (the API refuses a withdrawn id) until a newer red run. The agent
  that builds the fix gets the run's URL and head, not its log: the worker token cannot read
  Actions logs. A workflow deleted from the default branch leaves its open item to the kernel's
  own limits.
- **To reverse:** set `redMain.enabled=false`; open triage items are withdrawn by request like
  any item.
