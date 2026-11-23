"""The durable workflow engine boundary (HARNESS-V3 §3.1; SY-V3-ENGINE-SURVIVES-FAILURE).

This package is the only code that imports the workflow engine SDK; `tests/test_engine_boundary.py`
fails any other module that does. The kernel gets four things from it, in the engine's own
vocabulary:

- `Engine.start`: start a workflow (a function decorated with `workflow`) under a chosen id;
- `timer`: a durable timer, called inside a workflow; the deadline is recorded when it is first
  reached, so a restarted worker waits only for what is left and a passed deadline fires at once;
- `Client.signal` / `wait_for_signal`: a signal from outside, stored durably, so one sent while
  no worker runs is delivered when a worker starts;
- `step`: a function whose result is recorded once it finishes, retried on exception, and never
  run again after it finished, including after the worker is killed;
- `Client.recorded`: what the engine has durably recorded for a workflow (finished steps,
  registered waits and their deadlines), so a caller can tell where a workflow stands.

The engine is DBOS Transact on Postgres (docs/decisions/workflow-engine.md records why, the
versions tested and the failure tests' results). Swapping it for another engine changes only
this package.

Workflow functions must be deterministic: every side effect goes in a `step`, every wait in
`timer` or `wait_for_signal`. A worker (`Engine.launch`) resumes every unfinished workflow of
its `name` and `version`. `version` is pinned explicitly, not derived from the code, so a worker
restarted on changed step code resumes the waiting workflows where they stopped; change it
only to strand the workflows an incompatible code change could not replay.
"""

from __future__ import annotations

from sortyard.engine._dbos import (
    ENGINE,
    Client,
    Engine,
    Recorded,
    WorkflowFailed,
    engine_version,
    step,
    timer,
    wait_for_signal,
    workflow,
)

__all__ = [
    "ENGINE",
    "Client",
    "Engine",
    "Recorded",
    "WorkflowFailed",
    "engine_version",
    "step",
    "timer",
    "wait_for_signal",
    "workflow",
]
