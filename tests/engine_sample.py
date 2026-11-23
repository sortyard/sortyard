"""A sample workflow built only on `sortyard.engine` (the engine failure tests' subject).

Every step appends its name to the marks file (`SORTYARD_ENGINE_MARKS`), so a test can count how
often each step's body ran. `tests/test_engine_failure.py` rewrites "-v1" to "-v2" in a copy of
this file to run a worker on changed code: the step bodies and `waits_for_signal`'s own source
both change, as they would in a real deploy.
"""

from __future__ import annotations

import os
import pathlib
import time

from sortyard.engine import step, timer, wait_for_signal, workflow

SEVEN_DAYS = 7 * 24 * 60 * 60


def marks() -> pathlib.Path:
    return pathlib.Path(os.environ["SORTYARD_ENGINE_MARKS"])


def mark(name: str) -> None:
    with marks().open("a") as f:
        f.write(name + "\n")


@step()
def one() -> str:
    mark("one")
    return "one"


@step()
def two() -> str:
    """Holds while the hold file exists, so a test can kill the worker inside this step."""
    mark("two-start")
    while (marks().parent / "hold").exists():
        time.sleep(0.05)
    mark("two-end")
    return "two"


@step()
def three() -> str:
    mark("three")
    return "three"


@workflow
def three_steps() -> list[str]:
    return [one(), two(), three()]


@step()
def before() -> str:
    mark("before-v1")
    return "before-v1"


@step()
def after() -> str:
    mark("after-v1")
    return "after-v1"


@workflow
def waits_for_signal() -> list[str]:
    """Two steps around a wait for "go" (sample revision -v1)."""
    first = before()
    payload = wait_for_signal("go", timeout_seconds=SEVEN_DAYS)
    return [first, str(payload), after()]


@workflow
def seven_day_timer() -> list[str]:
    first = before()
    timer(SEVEN_DAYS)
    return [first, after()]


WORKFLOWS = {
    "three_steps": three_steps,
    "waits_for_signal": waits_for_signal,
    "seven_day_timer": seven_day_timer,
}
