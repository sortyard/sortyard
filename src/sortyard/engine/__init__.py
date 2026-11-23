"""The durable workflow engine boundary (HARNESS-V3 section 3.1, SY-V3-ENGINE-SURVIVES-FAILURE).

This package is the only code in the repository that imports the workflow engine SDK
(`tests/test_engine_boundary.py` holds that). The kernel gets four things from it and nothing
else:

- **start a workflow**: `Engine.start` runs a function registered with `Registry.workflow`
  under an id; its position, timers and history survive worker restarts and deploys;
- **a durable timer**: `Context.timer` waits for a duration that is recorded by the engine, not
  held in a worker's memory;
- **a signal from outside**: `Engine.signal` delivers a named payload to a workflow, whether or
  not a worker is running; the workflow reads it with `Context.wait_signal`;
- **a step that is retried and recorded**: `Context.step` runs a function registered with
  `Registry.step`. It is retried when it raises or when its worker dies, and once it has
  finished its result is recorded and it never runs again for that workflow. A step can be
  bounded by a durable timer (`limit`), which raises `LimitPassed` in the workflow.

The engine is Temporal (docs/decisions/workflow-engine.md records why, the versions tested and
the failure-test results). Replacing it changes only this package: the kernel handles no
Temporal type and catches no Temporal exception. Failures cross the boundary as `StepFailed`,
`LimitPassed`, `WorkflowFailed`, `WorkflowNotFound` and `EngineUnavailable`.

Rules for workflow functions. A workflow function is replayed from its recorded history when a
worker restarts, so it must be deterministic: every side effect goes in a step, every wait in
`Context.timer` or `Context.wait_signal`, and the time comes from `Context.now`. Step functions
have no such rule; they may be changed and redeployed freely while workflows are in flight.
Arguments, results and signal payloads are JSON values.
"""

from __future__ import annotations

from sortyard.engine._temporal import (
    ENGINE,
    Context,
    Engine,
    EngineUnavailable,
    LimitPassed,
    Recorded,
    Registry,
    StepFailed,
    StepFunction,
    WorkflowFailed,
    WorkflowFunction,
    WorkflowNotFound,
    engine_version,
)

__all__ = [
    "ENGINE",
    "Context",
    "Engine",
    "EngineUnavailable",
    "LimitPassed",
    "Recorded",
    "Registry",
    "StepFailed",
    "StepFunction",
    "WorkflowFailed",
    "WorkflowFunction",
    "WorkflowNotFound",
    "engine_version",
]
