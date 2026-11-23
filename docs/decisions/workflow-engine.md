# SY-DEC-007 — The durable workflow engine: DBOS Transact on Postgres

Date: 2026-11-23. Item: SY-V3-ENGINE-SURVIVES-FAILURE (HARNESS-V3 §3.1, Phase 0). Status: decided
by the system under the owner's accepted plan; reversible as below.

## What was decided

The kernel's durable workflow engine is **DBOS Transact (Python), with Postgres as its store**,
behind `src/sortyard/engine/`. That package is the only code that imports the SDK
(`tests/test_engine_boundary.py`). It gives the kernel four things: start a workflow
(`Engine.start`), a durable timer (`timer`), a signal from outside (`Client.signal` /
`wait_for_signal`), and a step that is retried and recorded (`step`). The hand-written transition,
schedule, lease and queue code that was planned for native execution is not written.

## Search for an existing answer

Searched `DECISIONS.md` (SY-DEC-001 to SY-DEC-006) and `docs/decisions/` (only
`appwrite-substrate.md`, SY-DEC-004). Neither has a workflow-engine decision. The answer on record
is the owner's acceptance of HARNESS-V3 §3.1, as the item quotes it: "Temporal on Postgres behind
one module, with DBOS as the fallback; the design statements about both engines were from general
knowledge and this task is what verifies them." This record carries out that answer. It does not
open a new question.

## Options considered

| Option | What it would do | Verified on 2026-11-23 |
| --- | --- | --- |
| Temporal (Python SDK) | Workflows run against a Temporal server (here the SDK's local dev or time-skipping test server; Postgres as the server's store in production). A separate server process to deploy and run. | The SDK installs from the package index (`temporalio` 1.36.1). Its local test servers do **not** come from the package index: `WorkflowEnvironment.start_local()` and `start_time_skipping()` both download a server binary at first use from `https://temporal.download/...`. On the build worker that download was refused (`CONNECT tunnel failed, response 403`), and no package on the index ships the server (`temporal-cli`, `temporalio-cli`, `temporal-server`, `temporalio-testserver` and others all return 404). So the tests cannot run with "no network beyond the package index", which the item requires. The failure tests were not run on Temporal for that reason. |
| DBOS Transact (Python) | A library in the worker process. It records workflow status, step results, timer deadlines and messages in a `dbos` schema of a Postgres database, and recovers unfinished workflows when a worker launches. No separate server. | Installs from the package index (`dbos` 3.6.0, MIT; its dependencies are MIT/BSD). All four failure tests pass against Postgres 16 (results below). |
| Hand-written engine (the old native-execution plan) | Sortyard's own transition, schedule, lease and queue code. | Replaced by the owner's §3.1 decision; not reconsidered. |

## Chosen answer and basis

DBOS, the fallback the owner named. Basis: the item's `must_allow` says "the tests running
without an estate cluster or network beyond the package index". Temporal's test server breaks
that, and DBOS passes all four failure tests within it. DBOS also needs no new service to deploy:
it uses the Postgres the chart already runs. No money is involved, since both are open source
with no paid service.

The engine keeps its state in Postgres, not Appwrite. SY-DEC-004 prefers Appwrite for
application persistence, but the item's authority states "Appwrite is not needed for the
harness", and §3.1 places the engine on Postgres.

## Failure test results

Run 2026-11-23 on the build worker: Python 3.11.2, **dbos 3.6.0**, Postgres 16.16
(`postgres:16-alpine`). Command: `pytest tests/test_engine_failure.py tests/test_engine_boundary.py`.
Each test runs real worker processes (`tests/engine_worker.py`) on the sample workflow
`tests/engine_sample.py` against a throwaway database, and stops workers with SIGKILL.

The tests use no fixed sleeps to wait for the engine (a guard test in the same file holds this).
A worker is killed only after the engine has durably recorded the position the test means to
kill it at. `Client.recorded` reads the finished steps and registered waits, and the test polls
it with a deadline. The timer test also has a recovery barrier: the worker's test clock reports
the wait it computed from the recorded deadline. The test asserts that the timer is still pending
only after that report, and checks the reported wait against the deadline recorded before the
kill.

| Test (`tests/test_engine_failure.py`) | Result |
| --- | --- |
| A workflow finishes after its worker is killed mid-step, and finished steps do not run again | **pass.** Step one ran once. The step the worker died in ran twice (once interrupted, once to completion), as expected. Step three ran once. |
| A waiting workflow keeps its position across a worker restart on changed step code | **pass.** The new worker ran a copy whose step bodies and workflow source changed (`-v1` → `-v2`). The finished step was not re-run. The workflow was still waiting, took the signal, and ran the *new* code for the next step. |
| A seven-day timer fires under the test clock | **pass.** A worker with its clock moved forward 1 day resumed the timer from its recorded deadline: the wait it reported was the deadline minus its clock, about 6 days. It left the workflow waiting and recorded nothing new. A worker moved forward 7 days + 60 s finished it at once, without waiting again. |
| A signal sent with no worker running is delivered when a worker starts | **pass.** The signal was sent after the worker was killed, while the workflow was still waiting. The next worker delivered it. |
| `tests/test_engine_boundary.py`: only `src/sortyard/engine` imports the engine SDK | **pass.** It covers `import`, `from … import` and `importlib.import_module` / `__import__` with a literal name, for `dbos` and `temporalio`. |

Each guard was checked by breaking the engine module on purpose. Making `step` a plain call
failed the kill test ("a finished step ran again"). Leaving `version` unpinned failed the
changed-code test. Making `Client.signal` drop the message failed the signal test. Making
`timer` record a deadline of under one day failed the timer test at its recovery barrier: the
resumed worker reported no pending wait and ran the next step.

Facts about DBOS that the boundary encodes:

- **The version is pinned.** By default DBOS derives the application version from a hash of
  the workflow source, and a worker recovers only workflows of its own version. A deploy that
  changes a workflow's source would then strand every waiting workflow. `Engine` sets the
  version explicitly (`version="1"`). Bump it only for a change that existing workflows cannot
  replay.
- **A step the worker died inside runs again.** "Recorded" means a finished step never runs
  twice. A step's side effect must still tolerate a second attempt.
- **Timer deadlines are wall-clock** (recorded epoch time). The test clock is a worker whose
  wall clock is moved forward, and a fleet needs synchronised clocks.

## How to reverse

To change engines (back to Temporal, for example), rewrite `src/sortyard/engine/_dbos.py`
behind the same names in `src/sortyard/engine/__init__.py`, swap the `dbos` dependency in
`pyproject.toml`, and re-run the four failure tests and the boundary test. No other module
imports the SDK. For Temporal, first make its server available without the download: a pinned
binary in the worker image and CI, passed through the SDK's `dev_server_existing_path`. That is
a worker-image change (the HARNESS-3152 class). Workflows that are waiting at the switch do not
migrate between engines; drain them first.
