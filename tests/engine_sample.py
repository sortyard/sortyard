"""The sample workflows of the engine failure tests, built only on `sortyard.engine`.

Each step appends a line to the marks file (SORTYARD_ENGINE_MARKS) when it runs, so a test can
count how many times a step body ran across worker processes. The failure tests also run a
changed copy of this file (`-v1` becomes `-v2`, and the step bodies change) as "the worker
restarted on changed step code".
"""

from __future__ import annotations

import os
import pathlib
import time
from datetime import timedelta
from typing import Any

from sortyard.engine import Context, LimitPassed, Registry

REGISTRY = Registry()
VERSION = "v1"
WEEK = timedelta(days=7)


def mark(text: str) -> None:
    with pathlib.Path(os.environ["SORTYARD_ENGINE_MARKS"]).open("a") as marks:
        marks.write(text + "\n")


def marks() -> list[str]:
    path = pathlib.Path(os.environ["SORTYARD_ENGINE_MARKS"])
    return path.read_text().splitlines() if path.exists() else []


@REGISTRY.step("one", timeout=timedelta(seconds=10))
def one(arg: Any) -> str:
    mark(f"one-{VERSION}")
    return f"one-{VERSION}"


@REGISTRY.step("two", timeout=timedelta(seconds=10))
def two(arg: Any) -> str:
    mark(f"two-{VERSION}")
    return f"two-{VERSION}"


@REGISTRY.step("held", timeout=timedelta(seconds=3))
def held(arg: Any) -> str:
    """A step a test can stop a worker in: it does not finish while the hold file exists."""
    mark("held-started")
    hold = pathlib.Path(os.environ["SORTYARD_ENGINE_HOLD"])
    while hold.exists():
        time.sleep(0.02)
    mark("held-finished")
    return "held"


@REGISTRY.step("stuck", timeout=timedelta(days=30), max_attempts=1)
def stuck(arg: Any) -> str:
    """A step whose one attempt outlasts any limit a test gives it, until the hold is removed."""
    mark("stuck-started")
    hold = pathlib.Path(os.environ["SORTYARD_ENGINE_HOLD"])
    while hold.exists():
        time.sleep(0.02)
    return "stuck"


@REGISTRY.step("flaky", timeout=timedelta(seconds=10), retry_after=timedelta(milliseconds=10))
def flaky(arg: Any) -> str:
    """Fails on its first attempt and succeeds on its second."""
    mark("flaky-attempt")
    if marks().count("flaky-attempt") < 2:
        raise RuntimeError("first attempt fails")
    return "flaky"


@REGISTRY.step("doomed", timeout=timedelta(seconds=10), max_attempts=2)
def doomed(arg: Any) -> str:
    mark("doomed-attempt")
    raise RuntimeError("always fails")


@REGISTRY.workflow("three-steps")
async def three_steps(ctx: Context, arg: Any) -> list[str]:
    return [await ctx.step("one"), await ctx.step("held"), await ctx.step("two")]


@REGISTRY.workflow("wait-then-step")
async def wait_then_step(ctx: Context, arg: Any) -> dict[str, Any]:
    before = await ctx.step("one")
    payload = await ctx.wait_signal("go")
    return {"before": before, "signal": payload, "after": await ctx.step("two")}


@REGISTRY.workflow("week")
async def week(ctx: Context, arg: Any) -> float:
    started = ctx.now()
    await ctx.timer(WEEK)
    return (ctx.now() - started).total_seconds()


@REGISTRY.workflow("retried")
async def retried(ctx: Context, arg: Any) -> str:
    result: str = await ctx.step("flaky")
    return result


@REGISTRY.workflow("gives-up")
async def gives_up(ctx: Context, arg: Any) -> str:
    result: str = await ctx.step("doomed")
    return result


@REGISTRY.workflow("impatient")
async def impatient(ctx: Context, arg: Any) -> str:
    try:
        await ctx.wait_signal("never", timeout=timedelta(hours=1))
    except TimeoutError:
        return "timed out"
    return "signalled"


@REGISTRY.workflow("bounded")
async def bounded(ctx: Context, arg: Any) -> list[str]:
    """A quick step inside its limit, then a stuck step that outlasts a limit of `arg` seconds."""
    quick: str = await ctx.step("one", limit=timedelta(days=1))
    try:
        await ctx.step("stuck", limit=timedelta(seconds=arg))
    except LimitPassed:
        return [quick, "limit passed"]
    return [quick, "finished"]
