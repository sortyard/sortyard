# SY-DEC-007 — The durable workflow engine: Temporal

Date: 2026-11-23. Item: SY-V3-ENGINE-SURVIVES-FAILURE (SORTYARD-158; company/HARNESS-V3.md
section 3.1, phase 0). Status: decided under the owner's accepted plan; reversible as below.

## What was decided

The kernel's durable workflow engine is **Temporal**, reached only through `src/sortyard/engine/`.
That package is the only code that imports the SDK (`tests/test_engine_boundary.py`). It gives
the kernel four things. The kernel handles no Temporal type and catches no Temporal exception:
failures cross the boundary as the package's own `StepFailed`, `LimitPassed`, `WorkflowFailed`,
`WorkflowNotFound` and `EngineUnavailable`.

| The kernel asks for | `sortyard.engine` | On Temporal |
| --- | --- | --- |
| start a workflow | `Engine.start`, a function registered with `Registry.workflow` | one generic dynamic workflow that runs the registered function its type name selects |
| a durable timer | `Context.timer` | a workflow timer |
| a signal from outside | `Engine.signal`, `Context.wait_signal` | a workflow signal, buffered by the server |
| a step that is retried and recorded | `Context.step`, a function registered with `Registry.step` | one generic dynamic activity with a retry policy |

`Engine.recorded` reads where a workflow stands (finished steps, pending timers, accepted
signals, whether it is idle, and the error of a workflow-code defect the engine is retrying)
from the engine's records, never from a worker.

The hand-written transition, schedule, lease and queue code planned in the native-execution
design (closed pull request 13) is not written.

## The owner's answer this carries out

HARNESS-V3 decision 2: "Engine: Temporal on our Postgres, behind one module; DBOS as fallback",
with "phase 0 still runs the failure tests". Section 3.1 says the statements about both engines
were from general knowledge and that phase 0 verifies them with four failure tests. This record
is that verification for Temporal. It opens no new question.

## Options considered

| Option | Result on 2026-11-23 |
| --- | --- |
| Temporal (Python SDK `temporalio` 1.36.1, MIT) | **Chosen.** All four failure tests pass (below). |
| DBOS Transact (Python) | Not needed as the fallback. The conductor's earlier build of this item (closed pull request 17) reported that `dbos` 3.6.0 passed the same four tests against Postgres 16; that result was not re-run here. That build chose DBOS only because its worker could not download Temporal's test server (HTTP 403 from its egress proxy), which the item says is a worker gap to report, not a reason to change the engine. |
| Hand-written engine | Replaced by the owner's section 3.1 decision; not reconsidered. |

## Failure test results

Command: `pytest tests/test_engine_failure.py tests/test_engine_boundary.py`. Run on a
workstation (Python 3.12.3, Linux x86-64) and by the `test` job of the pull request that added
this record (Python 3.11). Versions: **temporalio 1.36.1**; the development server is pinned to
Temporal CLI v1.10.1, which reports Server 1.32.2; the time-skipping test server is pinned to
v1.36.0 (`sortyard/engine/testing.py` holds both pins).

The kill tests run real worker processes (`tests/engine_worker.py`) on the sample workflows of
`tests/engine_sample.py` and stop them with SIGKILL. A worker is killed only after the engine
itself reports the position the test means to kill it at; no test waits a fixed time.

| Test (`tests/test_engine_failure.py`) | Result |
| --- | --- |
| A workflow finishes after its worker is killed mid-step and finished steps do not run again | **Pass.** Step one ran once. The step the worker died in ran twice (once interrupted, once to its end), although its own timeout is 30 minutes. The last step ran once. |
| A waiting workflow keeps its position across a worker restart on changed step code | **Pass.** The new worker ran a changed copy of the sample. Step one was not run again and its recorded result was reused; the step after the wait ran on the new code. |
| A seven-day timer fires under the test clock | **Pass.** After six days on the test clock the timer was still pending; after the seventh it fired and the workflow finished, having waited seven days by the engine's clock. |
| A signal sent with no worker running is delivered when a worker starts | **Pass.** With every worker dead the engine accepted and kept the signal; a new worker delivered it. A second test starts and signals a workflow before any worker has ever run. |

More tests in the same file cover the rest of the boundary: a step that raises is retried and
recorded once; a step out of attempts fails the workflow unless the workflow catches
`StepFailed`; a signal wait can time out; a workflow id cannot be used twice; a step bounded by
a limit is abandoned when its durable timer fires first, and the workflow is reported idle at
its next wait; a defect in workflow code keeps the workflow running and is reported; calls on
an unknown or ended workflow raise `WorkflowNotFound`.

## What the tests showed about Temporal

These are properties the kernel has to design for. Each was observed in the runs above.

1. **A dead worker is noticed by silence; a hung step by its timeout.** The server does not
   know a worker died. The boundary makes every running step report in (a heartbeat) and tells
   the server to rerun a step that has been silent for 10 seconds, so the kill test's step was
   rerun in seconds although its timeout is 30 minutes. A step that hangs in a live worker keeps
   reporting in, so only its `timeout` ends it: `Registry.step` requires one. This fits the
   kernel rule that every state has a limit.
2. **A step may run more than once.** The interrupted step ran twice. Steps must be safe to
   repeat (at-least-once); only a step that finished is never run again.
3. **A restarted worker picks work up after a short delay.** The kill tests take 10 to 15
   seconds each, most of it the server waiting out the dead worker's task before handing it to
   the new one (about 10 seconds; this matches the SDK's default sticky-queue timeout, which is
   an inference, not something the tests isolate).
4. **Workflow code is replayed.** A restarted worker rebuilds a workflow's position by running
   the workflow function again against the recorded history. Step code may change freely.
   Workflow functions must stay deterministic, and a change to the order of steps, timers and
   waits before a workflow's current position breaks its replay. The kernel's generic workflow
   interprets a state table, so this is a rule for that one function.
5. **The SDK's import sandbox is off.** The SDK refuses workflow classes that are not at module
   level and re-imports workflow modules in a sandbox. The boundary uses one module-level
   dynamic workflow with the unsandboxed runner so the kernel can register plain functions.
   The cost: nothing checks determinism at import time; a broken rule shows as a replay error.
7. **An error in workflow code does not end the workflow.** Temporal treats an unexpected
   exception in a workflow function as a defect to fix and redeploy: the workflow stays running
   and the pass is retried. The boundary keeps that (work in flight survives a bad deploy) and
   reports the error as `Recorded.defect`. Only the boundary's own outcomes that a workflow lets
   through (`StepFailed`, `LimitPassed`, a signal wait's `TimeoutError`) fail the workflow.
6. **The test clock moves only when told, and not while a step runs.** On the time-skipping
   server a timer fires when the test advances the clock (`TestClock.advance`). With a step in
   progress the advance call did not return (it timed out), so a limit that beats a running
   step is tested on the development server in real time.

## Gaps against the item as written

- **Network beyond the package index.** The item allows "the tests running without an estate
  cluster or network beyond the package index". No cluster is needed. The package index is not
  enough: the SDK downloads the development server and the test server on first use from
  `temporal.download` (about 125 MB and 85 MB) and caches them in the system temporary
  directory. No Python package ships them. A build environment that blocks that host cannot run
  the engine tests; that is a declared need of the lane (HARNESS-V3 section 3.3), and the tests
  fail there, they do not skip.
- **"Temporal on our Postgres" is not verified.** The development server keeps its state in
  memory and nothing was deployed. Temporal storing to Postgres is from its documentation, not
  from a test in this repository. The first deployment of a Temporal server (four services, per
  HARNESS-V3 section 3.1) has to prove it, with the same four tests pointed at that server.

## How to reverse

Replace `src/sortyard/engine/_temporal.py` and `testing.py` with another engine's
implementation of the same names, and run the same tests. Nothing outside the package imports
the SDK or handles a Temporal type, and the boundary test fails if that changes. Workflows in
flight do not move between engines: finish or restart them.
