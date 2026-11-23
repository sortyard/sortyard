"""Acceptance: the workflow engine survives failure (HARNESS-V3 §3.1).

Item: SY-V3-ENGINE-SURVIVES-FAILURE.

A sample workflow built only on `sortyard.engine` (`tests/engine_sample.py`) runs in real worker
processes (`tests/engine_worker.py`) against a throwaway Postgres, and passes four failure tests:

- the worker is killed (SIGKILL) inside a step; a new worker finishes the workflow, and the
  steps that had finished are not run again;
- a workflow waiting for a signal keeps its position when the worker restarts on changed step
  code: the finished step is not re-run and the later step runs the new code;
- a seven-day timer fires under the test clock (a worker whose clock is moved forward), and
  does not fire early;
- a signal sent while no worker runs is delivered when a worker starts.

Results and the engine version are recorded in docs/decisions/workflow-engine.md.
"""

from __future__ import annotations

import ast
import os
import pathlib
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from urllib.parse import quote

import pytest

from sortyard.engine import Client, Recorded
from tests.pg import fresh_database, requires_postgres

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "tests" / "engine_sample.py"
WORKER = ROOT / "tests" / "engine_worker.py"
DAY = 24 * 60 * 60
WAIT = 60.0
WAITING = Recorded("wait")  # a registered wait, whatever its deadline

pytestmark = requires_postgres


def database_url(name: str) -> str:
    user = quote(os.environ.get("PGUSER", "postgres"), safe="")
    password = os.environ.get("PGPASSWORD")
    auth = f"{user}:{quote(password, safe='')}" if password else user
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    return f"postgresql://{auth}@{host}:{port}/{name}"


class Run:
    """One test's database, marks file and worker processes."""

    def __init__(self, url: str, workdir: pathlib.Path) -> None:
        self.url = url
        self.marks = workdir / "marks"
        self.marks.touch()
        self.hold = workdir / "hold"
        self.workers: list[subprocess.Popen[bytes]] = []
        self.client: Client | None = None

    def lines(self) -> list[str]:
        return self.marks.read_text().splitlines()

    def count(self, name: str) -> int:
        return self.lines().count(name)

    def wait_for(self, what: str, check: Callable[[], bool]) -> None:
        deadline = time.monotonic() + WAIT
        while not check():
            for proc in self.workers:
                if proc.poll() not in (None, -signal.SIGKILL):
                    raise AssertionError(f"worker exited {proc.returncode} waiting for {what}")
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out waiting for {what}; marks: {self.lines()}")
            time.sleep(0.05)

    def waits(self) -> list[float]:
        """The long waits the workers' test clocks were asked for (`tests/engine_worker.py`)."""
        return [float(line.split()[1]) for line in self.lines() if line.startswith("wait ")]

    def wait_for_position(self, workflow_id: str, expected: list[Recorded]) -> list[Recorded]:
        """Wait until the engine has durably recorded `expected` for the workflow, and no more.

        A wait matches `WAITING` whatever its deadline. Killing a worker only after this keeps
        the kill from racing the engine's own recording of a step result or a wait.
        """

        def matches(found: list[Recorded]) -> bool:
            return len(found) == len(expected) and all(
                want == (WAITING if got.kind == "wait" else got)
                for got, want in zip(found, expected, strict=True)
            )

        found: list[Recorded] = []

        def reached() -> bool:
            nonlocal found
            found = self.connect().recorded(workflow_id)
            return matches(found)

        self.wait_for(f"{workflow_id} to record {expected}", reached)
        return found

    def worker(
        self,
        sample: pathlib.Path = SAMPLE,
        start: tuple[str, str] | None = None,
        clock_offset: float = 0.0,
    ) -> subprocess.Popen[bytes]:
        """Start a worker and wait until it has launched (and started `start`, if given)."""
        ready = self.count("ready")
        args = [sys.executable, str(WORKER), str(sample), self.url]
        if start:
            args += ["--start", *start]
        if clock_offset:
            args += ["--clock-offset", str(clock_offset)]
        env = {**os.environ, "SORTYARD_ENGINE_MARKS": str(self.marks)}
        proc = subprocess.Popen(args, env=env, cwd=ROOT)
        self.workers.append(proc)
        self.wait_for("worker ready", lambda: self.count("ready") > ready)
        return proc

    def kill(self, proc: subprocess.Popen[bytes]) -> None:
        proc.kill()
        proc.wait(timeout=WAIT)

    def connect(self) -> Client:
        if self.client is None:
            self.client = Client(self.url)
        return self.client

    def close(self) -> None:
        for proc in self.workers:
            if proc.poll() is None:
                self.kill(proc)
        if self.client is not None:
            self.client.close()


@pytest.fixture
def run(tmp_path: pathlib.Path) -> Iterator[Run]:
    for db in fresh_database():
        r = Run(database_url(db.name), tmp_path)
        try:
            yield r
        finally:
            r.close()


def test_a_workflow_finishes_after_its_worker_is_killed_mid_step_and_finished_steps_dont_rerun(
    run: Run,
) -> None:
    run.hold.touch()
    first = run.worker(start=("three_steps", "kill-mid-step"))
    run.wait_for("step two to start", lambda: run.count("two-start") == 1)
    run.wait_for_position("kill-mid-step", [Recorded("step", "one")])
    run.kill(first)
    assert run.connect().status("kill-mid-step") == "running"

    run.hold.unlink()
    run.worker()

    assert run.connect().result("kill-mid-step", timeout_seconds=WAIT) == ["one", "two", "three"]
    assert run.count("one") == 1, "a finished step ran again after the worker was killed"
    assert run.count("two-start") == 2, "the step the worker died in is run again"
    assert run.count("two-end") == 1
    assert run.count("three") == 1


def test_a_waiting_workflow_keeps_its_position_across_a_worker_restart_on_changed_step_code(
    run: Run, tmp_path: pathlib.Path
) -> None:
    changed = tmp_path / "engine_sample_changed.py"
    source = SAMPLE.read_text()
    assert source.count("-v1") >= 5  # step bodies and the workflow's source
    changed.write_text(source.replace("-v1", "-v2"))

    first = run.worker(start=("waits_for_signal", "waits"))
    run.wait_for_position("waits", [Recorded("step", "before"), WAITING])
    run.kill(first)

    run.worker(sample=changed)
    assert run.connect().status("waits") == "running"
    run.connect().signal("waits", "go", "proceed")

    result = run.connect().result("waits", timeout_seconds=WAIT)
    assert result == ["before-v1", "proceed", "after-v2"]
    assert run.count("before-v1") == 1
    assert run.count("before-v2") == 0, "the restarted worker re-ran a finished step"
    assert run.count("after-v2") == 1


def test_a_seven_day_timer_fires_under_the_test_clock(run: Run) -> None:
    started = time.monotonic()
    first = run.worker(start=("seven_day_timer", "timer"))
    position = run.wait_for_position("timer", [Recorded("step", "before"), WAITING])
    deadline = position[1].deadline
    assert deadline is not None
    run.wait_for("the first worker to wait on the timer", lambda: len(run.waits()) == 1)
    run.kill(first)

    # Recovery barrier: the worker one day ahead reports the wait it computed from the recorded
    # deadline; only then is "still pending" a statement about the evaluated timer.
    before_spawn = time.time()
    early = run.worker(clock_offset=1 * DAY)
    run.wait_for(
        "the resumed timer to be evaluated",
        lambda: len(run.waits()) == 2 or run.count("after-v1") > 0,
    )
    after_wait = time.time()
    assert run.count("after-v1") == 0, "the timer fired after one day"
    left = run.waits()[1]
    assert deadline - DAY - after_wait <= left <= deadline - DAY - before_spawn, (
        f"the resumed timer waits {left}s, not what is left of the recorded deadline one day on"
    )
    assert run.connect().status("timer") == "running", "the timer fired after one day"
    assert run.connect().recorded("timer") == position, "the resumed timer re-recorded its wait"
    run.kill(early)

    run.worker(clock_offset=7 * DAY + 60)
    assert run.connect().result("timer", timeout_seconds=WAIT) == ["before-v1", "after-v1"]
    assert run.count("before-v1") == 1
    assert len(run.waits()) == 2, "the timer waited again once its deadline had passed"
    assert time.monotonic() - started < 4 * WAIT


def test_a_signal_sent_with_no_worker_running_is_delivered_when_a_worker_starts(run: Run) -> None:
    first = run.worker(start=("waits_for_signal", "signalled"))
    run.wait_for_position("signalled", [Recorded("step", "before"), WAITING])
    run.kill(first)

    run.connect().signal("signalled", "go", "sent-while-down")
    assert run.connect().status("signalled") == "running"

    run.worker()
    result = run.connect().result("signalled", timeout_seconds=WAIT)
    assert result == ["before-v1", "sent-while-down", "after-v1"]
    assert run.count("before-v1") == 1


def test_the_failure_tests_synchronise_on_recorded_state_not_on_fixed_sleeps() -> None:
    """A fixed sleep before a kill or an assertion leaves the engine's progress uncontrolled.

    Each test waits for state the engine has recorded (a finished step, a registered wait) or a
    worker has reported (the wait its test clock was asked for), with a deadline (`Run.wait_for`).
    """
    tree = ast.parse(pathlib.Path(__file__).read_text())
    sleeps = [
        f"{fn.name}:{node.lineno}"
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_")
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "sleep"
    ]
    assert sleeps == [], f"fixed sleeps used as synchronisation: {sleeps}"
