"""The observer: outside work is seen by polling, and reported with the stay's dispatch number.

There is no webhook receiver, so a build, a check, a review or a merge that finishes outside
the kernel is found by looking. One pass reads every open stay from the projection
(`sortyard.kernel.store.Items.open_stays`) and, for each, asks the state's owner for an outcome
through its `look`: a function from the stay (shaped as the owner's call) to
`{"outcome", "detail"}` or nothing. An outcome is sent to the item's workflow with the dispatch
number that was read with the stay, so one that arrives after the item left that stay is
ignored by the workflow.

The observer holds no state. Everything it knows it read in this pass, so a pass may run
beside another pass or straight after a restart, and what it sends twice is applied once. One
item's look failing is logged and does not stop the pass for the others.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sortyard.engine import Engine, WorkflowNotFound
from sortyard.kernel.item import Payload, send_outcome, workflow_id

log = logging.getLogger("sortyard.kernel.observer")

# From an open stay to its outcome, or nothing while the work is not done.
Look = Callable[[Payload], Payload | None]


class Observer:
    def __init__(
        self, engine: Engine, stays: Callable[[], list[dict[str, Any]]], looks: Mapping[str, Look]
    ) -> None:
        self._engine, self._stays, self._looks = engine, stays, dict(looks)

    async def look(self, stay: Payload) -> str | None:
        """Ask the stay's owner for an outcome and send it on; the outcome sent, if any."""
        look = self._looks.get(str(stay["owner"]))
        reply = None if look is None else await asyncio.to_thread(look, stay)
        if not isinstance(reply, Mapping) or not isinstance(reply.get("outcome"), str):
            return None
        try:
            await send_outcome(
                self._engine,
                workflow_id(str(stay["tenant"]), str(stay["item"])),
                state=str(stay["state"]),
                outcome=reply["outcome"],
                detail=reply.get("detail"),
                dispatch=int(stay["dispatch"]),
            )
        except WorkflowNotFound:
            return None  # the item's workflow ended since the stay was read
        return str(reply["outcome"])

    async def run_pass(self) -> int:
        """Look at every open stay once; how many outcomes were sent."""
        sent = 0
        for stay in await asyncio.to_thread(self._stays):
            try:
                sent += await self.look(stay) is not None
            except Exception as error:
                log.warning(
                    "observing %s of %s in %s failed: %s: %s",
                    stay["item"],
                    stay["tenant"],
                    stay["state"],
                    type(error).__name__,
                    error,
                )
        return sent

    async def run(
        self, interval: float, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep
    ) -> None:
        """Pass after pass until cancelled, `interval` seconds apart by `sleep`."""
        while True:
            try:
                await self.run_pass()
            except Exception as error:  # the projection could not be read: try again next pass
                log.warning("observer pass failed: %s: %s", type(error).__name__, error)
            await sleep(interval)
