"""DBOS Transact behind the engine boundary (the one module that imports the SDK).

`sortyard.engine` re-exports what is here; nothing else in the repository may import `dbos`
(`tests/test_engine_boundary.py`). Replacing the engine means rewriting this file to the same
names and signatures.

Public: `workflow`, `step`, `timer`, `wait_for_signal`, `Engine` (a worker: launch, start,
shutdown), `Client` (signal, status, result from any process), `WorkflowFailed`,
`engine_version`, `ENGINE`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from importlib.metadata import version as _dist_version
from typing import Any, Literal, ParamSpec, TypeVar

from dbos import DBOS, DBOSClient, DBOSConfig, SetWorkflowID

P = ParamSpec("P")
R = TypeVar("R")

ENGINE = "dbos"
"""The engine behind the boundary, by its package name on the package index."""

Status = Literal["running", "finished", "failed", "cancelled"]

_STATUS: dict[str, Status] = {
    "PENDING": "running",
    "ENQUEUED": "running",
    "DELAYED": "running",
    "SUSPENDED": "running",
    "SUCCESS": "finished",
    "ERROR": "failed",
    "MAX_RECOVERY_ATTEMPTS_EXCEEDED": "failed",
    "CANCELLED": "cancelled",
}


class WorkflowFailed(Exception):
    """A workflow ended in failure or cancellation, or did not finish within the wait."""


def engine_version() -> str:
    """The installed engine SDK's version (written to the engine decision record)."""
    return f"{ENGINE} {_dist_version(ENGINE)}"


def workflow(fn: Callable[P, R]) -> Callable[P, R]:
    """Register `fn` as a workflow. Register every workflow before `Engine.launch`."""
    return DBOS.workflow(name=fn.__qualname__)(fn)


def step(
    *, retries: int = 3, backoff_seconds: float = 1.0
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """A step: retried up to `retries` attempts on exception, its result recorded once done.

    A recorded step is never run again for that workflow; a step the worker died inside is run
    again, so a step's side effect must tolerate a second attempt.
    """
    if retries < 1:
        raise ValueError("retries counts attempts and must be at least 1")

    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        return DBOS.step(
            name=fn.__qualname__,
            retries_allowed=retries > 1,
            max_attempts=retries,
            interval_seconds=backoff_seconds,
            backoff_rate=2.0,
        )(fn)

    return decorate


def timer(seconds: float) -> None:
    """Wait `seconds` inside a workflow, durably: the deadline survives worker restarts."""
    DBOS.sleep(seconds)


def wait_for_signal(topic: str, timeout_seconds: float) -> Any:
    """Inside a workflow, wait for a signal on `topic`; its payload, or None on timeout.

    The timeout's deadline is durable like `timer`'s.
    """
    return DBOS.recv(topic, timeout_seconds=timeout_seconds)


def _config(database_url: str, name: str, version: str) -> DBOSConfig:
    return {
        "name": name,
        "system_database_url": database_url,
        "application_version": version,
        "log_level": "WARNING",
    }


class Engine:
    """A worker: runs workflows and, on `launch`, resumes every unfinished one of its version.

    One per process (the SDK keeps process-wide state).
    """

    def __init__(self, database_url: str, *, name: str = "sortyard", version: str = "1") -> None:
        self._dbos = DBOS(config=_config(database_url, name, version))

    def launch(self) -> None:
        DBOS.launch()

    def start(self, wf: Callable[P, R], workflow_id: str, *args: P.args, **kwargs: P.kwargs) -> str:
        """Start `wf` under `workflow_id`. Starting an id that exists does not run it twice."""
        with SetWorkflowID(workflow_id):
            handle = DBOS.start_workflow(wf, *args, **kwargs)
        return handle.get_workflow_id()

    def shutdown(self) -> None:
        DBOS.destroy(destroy_registry=False)


class Client:
    """Talks to workflows from any process, with or without a worker running."""

    def __init__(self, database_url: str) -> None:
        self._client = DBOSClient(system_database_url=database_url)

    def signal(self, workflow_id: str, topic: str, payload: Any) -> None:
        """Deliver `payload` on `topic`; stored until the workflow's `wait_for_signal` takes it."""
        self._client.send(workflow_id, payload, topic)

    def status(self, workflow_id: str) -> Status | None:
        """The workflow's status, or None if no workflow has that id."""
        found = self._client.list_workflows(workflow_ids=[workflow_id])
        return _STATUS[found[0].status] if found else None

    def result(self, workflow_id: str, timeout_seconds: float, poll_seconds: float = 0.2) -> Any:
        """Wait for the workflow to finish and return its result."""
        deadline = time.monotonic() + timeout_seconds
        while (status := self.status(workflow_id)) in (None, "running"):
            if time.monotonic() >= deadline:
                raise WorkflowFailed(f"{workflow_id}: still {status} after {timeout_seconds}s")
            time.sleep(poll_seconds)
        if status != "finished":
            raise WorkflowFailed(f"{workflow_id}: {status}")
        return self._client.retrieve_workflow(workflow_id).get_result()

    def close(self) -> None:
        self._client.destroy()
