"""Shared pieces of the kernel tests: scripted fake owners, and polling with a deadline."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

DEADLINE = 60.0
T = TypeVar("T")
Reply = Mapping[str, Any] | None

# What every owner answers when nothing goes wrong, by state. "waiting" has no entry: the
# need's owner takes the wait and reports when the need closes.
HAPPY: dict[str, Reply] = {
    "admitted": {"outcome": "dispatched"},
    "preflight": {"outcome": "ready"},
    "building": {"outcome": "built"},
    "checking": {"outcome": "green"},
    "reviewing": {"outcome": "approved"},
    "fixing": {"outcome": "fixed"},
    "merging": {"outcome": "merged"},
}
SILENT: Reply = None  # the owner took the work; its outcome will arrive as an input


async def until(read: Callable[[], Awaitable[T]], accept: Callable[[T], bool], what: str) -> T:
    """Poll `read` until `accept`; fail with the last value read once the deadline passes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DEADLINE
    while True:
        value = await read()
        if accept(value):
            return value
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}; last read: {value!r}")
        await asyncio.sleep(0.02)


@dataclass
class Owners:
    """Scripted owners and a scripted decision service.

    `script[state]` (or `script["ITEM/state"]` for one item) is the list of replies the
    state's owner gives, one per call; when it runs out (or a state has none) the owner gives
    the happy reply. `decisions` are the decision service's answers, one per question; when
    they run out it has no answer.
    """

    script: dict[str, list[Reply]] = field(default_factory=dict)
    decisions: list[Any] = field(default_factory=list)
    calls: list[Mapping[str, Any]] = field(default_factory=list)
    questions: list[Mapping[str, Any]] = field(default_factory=list)

    def owner(self, call: Mapping[str, Any]) -> Reply:
        self.calls.append(call)
        scripted = self.script.get(f"{call['item']}/{call['state']}") or self.script.get(
            call["state"], []
        )
        return scripted.pop(0) if scripted else HAPPY.get(call["state"])

    def decide(self, question: Mapping[str, Any]) -> Reply:
        self.questions.append(question)
        answer = self.decisions.pop(0) if self.decisions else None
        if isinstance(answer, Exception):
            raise answer
        reply: Reply = answer
        return reply

    def calls_for(self, state: str) -> list[Mapping[str, Any]]:
        return [call for call in self.calls if call["state"] == state]
