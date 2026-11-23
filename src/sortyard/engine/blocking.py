"""The engine for callers that are not async: the API service's request threads.

`BlockingEngine` keeps one event loop on its own thread and one connection to the engine,
made on first use, and runs each call there to completion. It adds nothing to what `Engine`
does and imports no SDK.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from sortyard.engine._temporal import DEFAULT_TASK_QUEUE, Engine

T = TypeVar("T")


class BlockingEngine:
    def __init__(
        self,
        target: str,
        *,
        namespace: str = "default",
        task_queue: str = DEFAULT_TASK_QUEUE,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._target = target
        self._namespace = namespace
        self._task_queue = task_queue
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._engine: Engine | None = None

    def _run(self, call: Coroutine[Any, Any, T]) -> T:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(
                    target=self._loop.run_forever, name="sortyard-engine", daemon=True
                ).start()
            loop = self._loop
        return asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(call, self._timeout), loop
        ).result()

    async def _connected(self) -> Engine:
        if self._engine is None:
            self._engine = await Engine.connect(
                self._target, namespace=self._namespace, task_queue=self._task_queue
            )
        return self._engine

    def signal(self, workflow_id: str, name: str, payload: Any = None) -> None:
        """Deliver a signal to a workflow; raises what `Engine.signal` raises, or TimeoutError."""

        async def send() -> None:
            await (await self._connected()).signal(workflow_id, name, payload)

        self._run(send())

    def close(self) -> None:
        with self._lock:
            loop, self._loop, self._engine = self._loop, None, None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
