"""The engine boundary on Temporal. Import `sortyard.engine`, not this module.

How the four primitives map (docs/decisions/workflow-engine.md):

- a registered workflow function runs inside one generic Temporal workflow, chosen by the
  workflow type name, so the kernel never declares a Temporal workflow class;
- a step is a Temporal activity, chosen the same way by its activity type name; its timeout is
  required because a step whose worker died is only rerun once that timeout has passed;
- a timer is a Temporal timer; a signal is a Temporal signal, buffered by the server until a
  worker reads it.

The generic workflow runs unsandboxed. Temporal's import sandbox exists to catch
non-deterministic workflow code; it would also re-import the kernel's modules inside every
workflow, which a registry of plain functions cannot survive. The determinism rule is stated in
`sortyard.engine` instead, and a broken rule surfaces as a replay error, not as silent drift.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import deque
from collections.abc import Awaitable, Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from importlib.metadata import version
from typing import Any, Protocol

from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType, PendingActivityState
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.common import RawValue, RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

ENGINE = "temporal"
DEFAULT_TASK_QUEUE = "sortyard"
# A running step reports in to the engine by itself. A step whose worker has died stops
# reporting, and the engine reruns it after this long, however long the step's own timeout is.
DEAD_WORKER_AFTER = timedelta(seconds=10)


def engine_version() -> str:
    """The engine SDK version in use, for the decision record and for diagnostics."""
    return version("temporalio")


class WorkflowFailed(Exception):
    """A workflow ended without a result.

    It let `StepFailed`, `LimitPassed` or a signal wait's `TimeoutError` through, or it was
    cancelled or terminated. Any other exception in a workflow function is treated as a defect
    in its code: the workflow stays running, the engine retries the pass until fixed code is
    deployed, and `Recorded.defect` carries the error.
    """


class WorkflowNotFound(LookupError):
    """No workflow has this id, or (for a signal) the workflow has already ended."""


class EngineUnavailable(Exception):
    """The engine service could not be reached or refused the call."""


class LimitPassed(Exception):
    """A step did not finish within the limit its caller gave it."""


class StepFailed(Exception):
    """A step ran out of attempts. A workflow that does not catch this fails."""


class Context(Protocol):
    """What a workflow function may do. Everything else belongs in a step."""

    @property
    def workflow_id(self) -> str: ...

    def now(self) -> datetime:
        """The engine's clock, the same on replay. Never read the wall clock in a workflow."""
        ...

    async def step(self, name: str, arg: Any = None, limit: timedelta | None = None) -> Any:
        """Run the registered step `name`; return its recorded result if it already finished.

        With a `limit`, a durable timer runs beside the step, retries included. If the timer
        fires first the step is abandoned and `LimitPassed` is raised.
        """
        ...

    async def timer(self, duration: timedelta) -> None:
        """Wait for `duration`. The deadline is the engine's, so it survives any worker."""
        ...

    async def wait_signal(self, name: str, timeout: timedelta | None = None) -> Any:
        """The payload of the next signal `name`, in arrival order.

        Signals sent before the workflow asked are kept. With a `timeout`, raises `TimeoutError`
        if none arrived in time.
        """
        ...


WorkflowFunction = Callable[[Context, Any], Awaitable[Any]]
StepFunction = Callable[[Any], Any]


@dataclass(frozen=True)
class _Step:
    function: StepFunction
    timeout: timedelta
    max_attempts: int
    retry_after: timedelta


@dataclass
class Registry:
    """The workflows and steps one worker serves, by name."""

    workflows: dict[str, WorkflowFunction] = field(default_factory=dict)
    steps: dict[str, _Step] = field(default_factory=dict)

    def workflow(self, name: str) -> Callable[[WorkflowFunction], WorkflowFunction]:
        def register(function: WorkflowFunction) -> WorkflowFunction:
            if name in self.workflows:
                raise ValueError(f"workflow {name!r} is already registered")
            self.workflows[name] = function
            return function

        return register

    def step(
        self,
        name: str,
        *,
        timeout: timedelta,
        max_attempts: int = 0,
        retry_after: timedelta = timedelta(seconds=1),
    ) -> Callable[[StepFunction], StepFunction]:
        """Register a step.

        `timeout` bounds one attempt and is required: when a worker dies in a step, the engine
        reruns the step only after this long. `max_attempts` of 0 retries until it succeeds;
        any other number fails the workflow after that many attempts. `retry_after` is the wait
        before the second attempt; later waits double, up to 100 times the first.
        """
        if timeout <= timedelta(0):
            raise ValueError(f"step {name!r} needs a positive timeout")
        if max_attempts < 0:
            raise ValueError(f"step {name!r} has a negative max_attempts")

        def register(function: StepFunction) -> StepFunction:
            if name in self.steps:
                raise ValueError(f"step {name!r} is already registered")
            self.steps[name] = _Step(function, timeout, max_attempts, retry_after)
            return function

        return register


@dataclass(frozen=True)
class Recorded:
    """What the engine has durably recorded for a workflow: where it stands.

    `status` is running, completed, failed, cancelled, terminated or timed_out.
    `finished_steps` are step names in the order they finished. `pending_timers` are the
    durations of timers started and not yet fired. `signals` are the names of signals the
    engine has accepted. `idle` is true when the workflow is running and nothing is in progress
    for it on any worker: no pass of the workflow function is due or under way and no step is
    running (a step abandoned at its limit does not count). It waits on a timer or a signal,
    and its position is recorded. `defect` is the error of the workflow function's last pass
    when that pass failed and the engine is retrying it, else None.
    """

    status: str
    finished_steps: tuple[str, ...]
    pending_timers: tuple[timedelta, ...]
    signals: tuple[str, ...]
    idle: bool
    defect: str | None = None


class _WorkflowContext:
    """`Context` on Temporal. Lives inside one workflow run; rebuilt on every replay."""

    def __init__(self, steps: dict[str, _Step], signals: dict[str, deque[Any]]) -> None:
        self._steps = steps
        self._signals = signals

    @property
    def workflow_id(self) -> str:
        return workflow.info().workflow_id

    def now(self) -> datetime:
        return workflow.now()

    async def step(self, name: str, arg: Any = None, limit: timedelta | None = None) -> Any:
        declared = self._steps.get(name)
        if declared is None:
            raise LookupError(f"step {name!r} is not registered on this worker")
        running = workflow.start_activity(
            name,
            arg,
            start_to_close_timeout=declared.timeout,
            heartbeat_timeout=min(DEAD_WORKER_AFTER, declared.timeout),
            retry_policy=RetryPolicy(
                initial_interval=declared.retry_after, maximum_attempts=declared.max_attempts
            ),
        )
        timer = None if limit is None else asyncio.ensure_future(workflow.sleep(limit))
        if timer is not None:
            await workflow.wait([running, timer], return_when=asyncio.FIRST_COMPLETED)
        if timer is None or running.done():
            if timer is not None:
                timer.cancel()
            try:
                return await running
            except ActivityError as error:
                raise StepFailed(f"step {name!r} failed: {error.cause}") from error
        # The limit passed first. Abandon the step: the engine stops retrying it, and whatever
        # an attempt still running returns is dropped.
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        raise LimitPassed(f"step {name!r} did not finish within {limit}")

    async def timer(self, duration: timedelta) -> None:
        await workflow.sleep(duration)

    async def wait_signal(self, name: str, timeout: timedelta | None = None) -> Any:
        queue = self._signals.setdefault(name, deque())
        try:
            await workflow.wait_condition(lambda: bool(queue), timeout=timeout)
        except TimeoutError:
            raise TimeoutError(f"no signal {name!r} within {timeout}") from None
        return queue.popleft()


# The registry each task queue's worker serves in this process. The generic workflow and step
# below are module-level (the SDK refuses local classes), so they find their registry here, by
# the task queue the engine handed them the work on.
@dataclass(frozen=True)
class _Serving:
    registry: Registry
    threads: ThreadPoolExecutor


_SERVING: dict[str, _Serving] = {}


@workflow.defn(dynamic=True)
class _SortyardWorkflow:
    """The one Temporal workflow: it runs the registered function its type name selects."""

    def __init__(self) -> None:
        self._signals: dict[str, deque[Any]] = {}

    @workflow.signal(dynamic=True)
    def _signal(self, name: str, args: Sequence[RawValue]) -> None:
        payload = workflow.payload_converter().from_payload(args[0].payload) if args else None
        self._signals.setdefault(name, deque()).append(payload)

    @workflow.run
    async def run(self, args: Sequence[RawValue]) -> Any:
        info = workflow.info()
        registry = _SERVING[info.task_queue].registry
        function = registry.workflows.get(info.workflow_type)
        if function is None:
            raise LookupError(f"workflow {info.workflow_type!r} is not registered on this worker")
        arg = workflow.payload_converter().from_payload(args[0].payload) if args else None
        try:
            return await function(_WorkflowContext(registry.steps, self._signals), arg)
        except (StepFailed, LimitPassed, TimeoutError) as error:
            # The workflow function let one of the boundary's own outcomes through: that ends
            # the workflow as failed. Any other exception is a defect in workflow code, and the
            # engine keeps the workflow and retries the pass until fixed code is deployed.
            raise ApplicationError(str(error), type=type(error).__name__) from error


async def _report_in() -> None:
    """Tell the engine this step's worker is alive, for as long as the step runs."""
    while True:
        activity.heartbeat()
        await asyncio.sleep(DEAD_WORKER_AFTER.total_seconds() / 4)


@activity.defn(dynamic=True)
async def _sortyard_step(args: Sequence[RawValue]) -> Any:
    """The one Temporal activity: it runs the registered step its type name selects."""
    info = activity.info()
    serving = _SERVING[info.task_queue]
    declared = serving.registry.steps.get(info.activity_type)
    if declared is None:
        raise LookupError(f"step {info.activity_type!r} is not registered on this worker")
    arg = activity.payload_converter().from_payload(args[0].payload) if args else None
    reporting = asyncio.ensure_future(_report_in())
    try:
        if inspect.iscoroutinefunction(declared.function):
            return await declared.function(arg)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(serving.threads, declared.function, arg)
    finally:
        reporting.cancel()


@contextmanager
def _engine_errors(workflow_id: str) -> Iterator[None]:
    """Turn the SDK's service errors into this package's own."""
    try:
        yield
    except RPCError as error:
        if error.status is RPCStatusCode.NOT_FOUND:
            raise WorkflowNotFound(f"workflow {workflow_id!r}: {error.message}") from error
        raise EngineUnavailable(f"{error.status.name}: {error.message}") from error


_STATUS = {
    WorkflowExecutionStatus.RUNNING: "running",
    WorkflowExecutionStatus.COMPLETED: "completed",
    WorkflowExecutionStatus.FAILED: "failed",
    WorkflowExecutionStatus.CANCELED: "cancelled",
    WorkflowExecutionStatus.TERMINATED: "terminated",
    WorkflowExecutionStatus.TIMED_OUT: "timed_out",
    WorkflowExecutionStatus.CONTINUED_AS_NEW: "running",
}


class Engine:
    """A connection to the engine: start, signal and read workflows, and run a worker.

    `Engine.connect` is the only way the kernel makes one; the tests get theirs from
    `sortyard.engine.testing`. One `task_queue` is one pool of workers. Calls that name a
    workflow raise `WorkflowNotFound` for an unknown id and `EngineUnavailable` when the
    engine service fails.
    """

    def __init__(self, client: Client, task_queue: str = DEFAULT_TASK_QUEUE) -> None:
        self._client = client
        self.task_queue = task_queue

    @classmethod
    async def connect(
        cls, target: str, *, namespace: str = "default", task_queue: str = DEFAULT_TASK_QUEUE
    ) -> Engine:
        """Connect to the engine service at `target` (host:port)."""
        return cls(await Client.connect(target, namespace=namespace), task_queue)

    async def start(self, workflow_name: str, workflow_id: str, arg: Any = None) -> None:
        """Start the workflow registered as `workflow_name` under `workflow_id`.

        The start is recorded by the engine, so it needs no worker to be running. An id can be
        used once: starting a second workflow under a used id raises `ValueError`.
        """
        try:
            with _engine_errors(workflow_id):
                await self._client.start_workflow(
                    workflow_name,
                    arg,
                    id=workflow_id,
                    task_queue=self.task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
        except WorkflowAlreadyStartedError as error:
            raise ValueError(f"workflow id {workflow_id!r} is already used") from error

    async def signal(self, workflow_id: str, name: str, payload: Any = None) -> None:
        """Deliver signal `name` to a workflow. Accepted and kept even with no worker running."""
        with _engine_errors(workflow_id):
            await self._client.get_workflow_handle(workflow_id).signal(name, payload)

    async def result(self, workflow_id: str) -> Any:
        """Wait for the workflow to end and return its result, or raise `WorkflowFailed`."""
        try:
            with _engine_errors(workflow_id):
                return await self._client.get_workflow_handle(workflow_id).result()
        except WorkflowFailureError as error:
            raise WorkflowFailed(f"workflow {workflow_id!r}: {error.cause}") from error

    async def recorded(self, workflow_id: str) -> Recorded:
        """Where the workflow stands, read from the engine's records, not from any worker."""
        with _engine_errors(workflow_id):
            return await self._recorded(workflow_id)

    async def _recorded(self, workflow_id: str) -> Recorded:
        handle = self._client.get_workflow_handle(workflow_id)
        scheduled: dict[int, str] = {}
        finished: list[str] = []
        timers: dict[int, timedelta] = {}
        signals: list[str] = []
        defect: str | None = None
        async for event in handle.fetch_history_events():
            kind = event.event_type
            if kind == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
                attributes = event.activity_task_scheduled_event_attributes
                scheduled[event.event_id] = attributes.activity_type.name
            elif kind == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
                done = event.activity_task_completed_event_attributes
                finished.append(scheduled[done.scheduled_event_id])
            elif kind == EventType.EVENT_TYPE_TIMER_STARTED:
                started = event.timer_started_event_attributes
                timers[event.event_id] = started.start_to_fire_timeout.ToTimedelta()
            elif kind == EventType.EVENT_TYPE_TIMER_FIRED:
                timers.pop(event.timer_fired_event_attributes.started_event_id, None)
            elif kind == EventType.EVENT_TYPE_TIMER_CANCELED:
                timers.pop(event.timer_canceled_event_attributes.started_event_id, None)
            elif kind == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED:
                signals.append(event.workflow_execution_signaled_event_attributes.signal_name)
            elif kind == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED:
                defect = event.workflow_task_failed_event_attributes.failure.message
            elif kind == EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED:
                defect = None
        # Read after the history, so `idle` is never older than the steps and timers above.
        description = await handle.describe()
        raw = description.raw_description
        status = _STATUS.get(description.status or WorkflowExecutionStatus.RUNNING, "running")
        steps_running = [
            pending
            for pending in raw.pending_activities
            if pending.state != PendingActivityState.PENDING_ACTIVITY_STATE_CANCEL_REQUESTED
        ]
        idle = (
            status == "running" and not raw.HasField("pending_workflow_task") and not steps_running
        )
        if status != "running":
            defect = None
        return Recorded(
            status, tuple(finished), tuple(timers.values()), tuple(signals), idle, defect
        )

    async def run_worker(self, registry: Registry, *, concurrent_steps: int = 32) -> None:
        """Serve `registry` on this engine's task queue until cancelled.

        A worker holds no state of its own: started on a fresh process, it resumes every
        unfinished workflow from the engine's history. It runs at most `concurrent_steps` steps
        at once and takes no more from the engine than it can run.
        """
        if self.task_queue in _SERVING:
            raise RuntimeError(f"this process already serves task queue {self.task_queue!r}")
        threads = ThreadPoolExecutor(concurrent_steps, thread_name_prefix="sortyard-step")
        _SERVING[self.task_queue] = _Serving(registry, threads)
        try:
            await Worker(
                self._client,
                task_queue=self.task_queue,
                workflows=[_SortyardWorkflow],
                activities=[_sortyard_step],
                workflow_runner=UnsandboxedWorkflowRunner(),
                max_concurrent_activities=concurrent_steps,
            ).run()
        finally:
            del _SERVING[self.task_queue]
            # Do not wait for a step still running in a thread: the engine reruns it elsewhere.
            threads.shutdown(wait=False, cancel_futures=True)
