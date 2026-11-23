"""Engine test servers: a real engine for tests, with no cluster and no deployment.

Both run the engine's own server as a child process on a free local port and stop it on exit:

- `local_engine` is the engine's development server (the real service in one binary, in-memory
  store). Use it for anything about workers: kills, restarts, signals.
- `time_skipping_engine` is the engine's test server with a test clock. Timers do not fire by
  themselves: the clock moves only when `TestClock.advance` moves it, and timers due by then
  fire. Use it for long timers.

The server binaries are not Python packages. The SDK downloads each one on first use (from
temporal.download) and caches it in the system temporary directory; later runs use the cache.
docs/decisions/workflow-engine.md records this as the one network need beyond the package index.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from temporalio.testing import WorkflowEnvironment

from sortyard.engine._temporal import DEFAULT_TASK_QUEUE, Engine


@dataclass(frozen=True)
class LocalEngine:
    """A running development server. `target` is what `Engine.connect` in another process needs."""

    engine: Engine
    target: str


@asynccontextmanager
async def local_engine(task_queue: str = DEFAULT_TASK_QUEUE) -> AsyncIterator[LocalEngine]:
    async with await WorkflowEnvironment.start_local() as environment:
        target = environment.client.service_client.config.target_host
        yield LocalEngine(Engine(environment.client, task_queue), target)


class TestClock:
    """The test server's clock."""

    __test__ = False  # not a pytest class, whatever its name

    def __init__(self, environment: WorkflowEnvironment) -> None:
        self._environment = environment

    async def now(self) -> datetime:
        return await self._environment.get_current_time()

    async def advance(self, duration: timedelta) -> None:
        """Move the clock forward by `duration`; timers due by then fire."""
        await self._environment.sleep(duration)


@dataclass(frozen=True)
class TimeSkippingEngine:
    engine: Engine
    clock: TestClock


@asynccontextmanager
async def time_skipping_engine(
    task_queue: str = DEFAULT_TASK_QUEUE,
) -> AsyncIterator[TimeSkippingEngine]:
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield TimeSkippingEngine(Engine(environment.client, task_queue), TestClock(environment))
