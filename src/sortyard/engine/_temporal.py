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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from importlib.metadata import version
from typing import Any, Protocol

from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.common import RawValue, RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

ENGINE = "temporal"
DEFAULT_TASK_QUEUE = "sortyard"


def engine_version() -> str:
    """The engine SDK version in use, for the decision record and for diagnostics."""
    return version("temporalio")


class WorkflowFailed(Exception):
    """A workflow ended without a result: it raised, was cancelled or was terminated."""


class LimitPassed(Exception):
    """A step did not finish within the limit its caller gave it."""


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
        before the second attempt; later waits double.
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
    engine has accepted. `idle` is true when the workflow is running and has nothing in
    progress on any worker: it waits on a timer or a signal, and its position is recorded.
    """

    status: str
    finished_steps: tuple[str, ...]
    pending_timers: tuple[timedelta, ...]
    signals: tuple[str, ...]
    idle: bool


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
            retry_policy=RetryPolicy(
                initial_interval=declared.retry_after, maximum_attempts=declared.max_attempts
            ),
        )
        if limit is None:
            return await running
        timer = asyncio.ensure_future(workflow.sleep(limit))
        await workflow.wait([running, timer], return_when=asyncio.FIRST_COMPLETED)
        if running.done():
            timer.cancel()
            return running.result()
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
_SERVING: dict[str, Registry] = {}


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
        registry = _SERVING[info.task_queue]
        function = registry.workflows.get(info.workflow_type)
        if function is None:
            raise LookupError(f"workflow {info.workflow_type!r} is not registered on this worker")
        arg = workflow.payload_converter().from_payload(args[0].payload) if args else None
        return await function(_WorkflowContext(registry.steps, self._signals), arg)


@activity.defn(dynamic=True)
async def _sortyard_step(args: Sequence[RawValue]) -> Any:
    """The one Temporal activity: it runs the registered step its type name selects."""
    info = activity.info()
    declared = _SERVING[info.task_queue].steps.get(info.activity_type)
    if declared is None:
        raise LookupError(f"step {info.activity_type!r} is not registered on this worker")
    arg = activity.payload_converter().from_payload(args[0].payload) if args else None
    if inspect.iscoroutinefunction(declared.function):
        return await declared.function(arg)
    return await asyncio.to_thread(declared.function, arg)


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
    `sortyard.engine.testing`. One `task_queue` is one pool of workers.
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
        await self._client.get_workflow_handle(workflow_id).signal(name, payload)

    async def result(self, workflow_id: str) -> Any:
        """Wait for the workflow to end and return its result, or raise `WorkflowFailed`."""
        try:
            return await self._client.get_workflow_handle(workflow_id).result()
        except WorkflowFailureError as error:
            raise WorkflowFailed(f"workflow {workflow_id!r}: {error.cause}") from error

    async def recorded(self, workflow_id: str) -> Recorded:
        """Where the workflow stands, read from the engine's history, not from any worker."""
        handle = self._client.get_workflow_handle(workflow_id)
        description = await handle.describe()
        scheduled: dict[int, str] = {}
        finished: list[str] = []
        timers: dict[int, timedelta] = {}
        signals: list[str] = []
        steps_open = 0
        last = EventType.EVENT_TYPE_UNSPECIFIED
        async for event in handle.fetch_history_events():
            last = event.event_type
            if last == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
                attributes = event.activity_task_scheduled_event_attributes
                scheduled[event.event_id] = attributes.activity_type.name
                steps_open += 1
            elif last == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
                done = event.activity_task_completed_event_attributes
                finished.append(scheduled[done.scheduled_event_id])
                steps_open -= 1
            elif last in (
                EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED,
                EventType.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT,
                EventType.EVENT_TYPE_ACTIVITY_TASK_CANCELED,
            ):
                steps_open -= 1
            elif last == EventType.EVENT_TYPE_TIMER_STARTED:
                started = event.timer_started_event_attributes
                timers[event.event_id] = started.start_to_fire_timeout.ToTimedelta()
            elif last == EventType.EVENT_TYPE_TIMER_FIRED:
                timers.pop(event.timer_fired_event_attributes.started_event_id, None)
            elif last == EventType.EVENT_TYPE_TIMER_CANCELED:
                timers.pop(event.timer_canceled_event_attributes.started_event_id, None)
            elif last == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED:
                signals.append(event.workflow_execution_signaled_event_attributes.signal_name)
        status = _STATUS.get(description.status or WorkflowExecutionStatus.RUNNING, "running")
        # Idle: the last thing recorded is the workflow yielding (its task completed, possibly
        # followed by the timers it started), with no step in progress. Anything newer (a signal,
        # a fired timer, a finished step) means a worker still has work to pick up.
        idle = (
            status == "running"
            and steps_open == 0
            and last
            in (EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED, EventType.EVENT_TYPE_TIMER_STARTED)
        )
        return Recorded(status, tuple(finished), tuple(timers.values()), tuple(signals), idle)

    async def run_worker(self, registry: Registry) -> None:
        """Serve `registry` on this engine's task queue until cancelled.

        A worker holds no state of its own: started on a fresh process, it resumes every
        unfinished workflow from the engine's history.
        """
        if self.task_queue in _SERVING:
            raise RuntimeError(f"this process already serves task queue {self.task_queue!r}")
        _SERVING[self.task_queue] = registry
        try:
            await Worker(
                self._client,
                task_queue=self.task_queue,
                workflows=[_SortyardWorkflow],
                activities=[_sortyard_step],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ).run()
        finally:
            del _SERVING[self.task_queue]
