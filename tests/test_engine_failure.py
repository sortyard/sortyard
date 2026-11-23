"""Acceptance (SY-V3-ENGINE-SURVIVES-FAILURE): the engine survives the four failures.

Every test runs a real engine server (`sortyard.engine.testing`; no cluster, no deployment) and
the sample workflows of `tests/engine_sample.py`, which use `sortyard.engine` only. Workers in
the kill tests are real processes (`tests/engine_worker.py`) stopped with SIGKILL, so nothing a
worker held in memory can carry a workflow across.

No test waits a fixed time for the engine. A worker is killed only after the engine itself
reports the position the test means to kill it at (`Engine.recorded`), and every wait is a poll
with a deadline.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import signal
import subprocess
import sys
from collections.abc import Awaitable, Callable, Iterator
from datetime import timedelta
from typing import TypeVar

import pytest

from sortyard.engine import Engine, Recorded, WorkflowFailed, WorkflowNotFound, engine_version
from sortyard.engine.testing import local_engine, time_skipping_engine
from tests import engine_sample

HERE = pathlib.Path(__file__).resolve().parent
SAMPLE = HERE / "engine_sample.py"
WORKER = HERE / "engine_worker.py"
DEADLINE = 60.0
T = TypeVar("T")


@pytest.fixture(autouse=True)
def marks(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[pathlib.Path]:
    """The marks and hold files, in the environment both this process and its workers read."""
    path = tmp_path / "marks"
    monkeypatch.setenv("SORTYARD_ENGINE_MARKS", str(path))
    monkeypatch.setenv("SORTYARD_ENGINE_HOLD", str(tmp_path / "hold"))
    yield path


async def until(
    read: Callable[[], Awaitable[T]],
    accept: Callable[[T], bool],
    what: str,
    workers: Workers | None = None,
) -> T:
    """Poll `read` until `accept`; fail with the last value read once the deadline passes."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DEADLINE
    while True:
        if workers is not None:
            workers.check()
        value = await read()
        if accept(value):
            return value
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}; last read: {value!r}")
        await asyncio.sleep(0.05)


class Workers:
    """Worker processes of one test; whatever is still running is killed at the end."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.processes: list[subprocess.Popen[bytes]] = []
        self.killed: list[subprocess.Popen[bytes]] = []

    def start(self, sample: pathlib.Path = SAMPLE) -> subprocess.Popen[bytes]:
        process = subprocess.Popen([sys.executable, str(WORKER), str(sample), self.target])
        self.processes.append(process)
        return process

    def kill(self, process: subprocess.Popen[bytes]) -> None:
        """SIGKILL: no shutdown hook runs, nothing is flushed, the worker is just gone."""
        self.killed.append(process)
        process.send_signal(signal.SIGKILL)
        assert process.wait(timeout=DEADLINE) == -signal.SIGKILL

    def kill_all(self) -> None:
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=DEADLINE)

    def check(self) -> None:
        """A worker that exited by itself is a failure now, not a timeout later."""
        for process in self.processes:
            if process not in self.killed and process.poll() is not None:
                raise AssertionError(f"a worker exited by itself with {process.returncode}")

    def alive(self) -> list[subprocess.Popen[bytes]]:
        return [process for process in self.processes if process.poll() is None]


def changed_sample(directory: pathlib.Path) -> pathlib.Path:
    """A copy of the sample whose step code changed: new version tag, new step two body."""
    source = SAMPLE.read_text()
    changed = source.replace('VERSION = "v1"', 'VERSION = "v2"').replace(
        'return f"two-{VERSION}"', 'return f"two-{VERSION}-changed"'
    )
    assert changed.count("v2") == 2 and changed.count("-changed") == 1, "the sample moved"
    path = directory / "engine_sample_v2.py"
    path.write_text(changed)
    return path


def test_a_workflow_finishes_after_its_worker_is_killed_mid_step_and_finished_steps_do_not_run_again(  # noqa: E501
    marks: pathlib.Path,
) -> None:
    """A workflow finishes after its worker is killed mid-step and finished steps do not run
    again."""

    async def scenario() -> None:
        hold = pathlib.Path(os.environ["SORTYARD_ENGINE_HOLD"])
        hold.touch()
        async with local_engine() as local:
            engine, workers = local.engine, Workers(local.target)
            try:
                first = workers.start()
                await engine.start("three-steps", "kill-mid-step")
                # Kill only once step one is recorded as finished and the worker is inside the
                # held step: the engine says the first, the step's own mark says the second.
                await until(
                    lambda: engine.recorded("kill-mid-step"),
                    lambda r: r.finished_steps == ("one",),
                    "step one recorded",
                    workers,
                )
                await until(
                    lambda: asyncio.sleep(0, engine_sample.marks()),
                    lambda m: "held-started" in m,
                    "the worker entering the held step",
                    workers,
                )
                workers.kill(first)
                assert engine_sample.marks() == ["one-v1", "held-started"]

                hold.unlink()
                workers.start()
                result = await asyncio.wait_for(engine.result("kill-mid-step"), DEADLINE)
                recorded = await engine.recorded("kill-mid-step")
            finally:
                workers.kill_all()

        assert result == ["one-v1", "held", "two-v1"]
        assert recorded.status == "completed"
        assert recorded.finished_steps == ("one", "held", "two")
        seen = engine_sample.marks()
        assert seen.count("one-v1") == 1, "the finished step ran again"
        # The step the worker died in ran twice: once interrupted, once to its end. Its own
        # timeout is 30 minutes, so the rerun came from the engine noticing the dead worker.
        assert seen.count("held-started") == 2
        assert seen.count("held-finished") == 1
        assert seen.count("two-v1") == 1

    asyncio.run(scenario())


def test_a_waiting_workflow_keeps_its_position_across_a_worker_restart_on_changed_step_code(
    tmp_path: pathlib.Path,
) -> None:
    """A waiting workflow keeps its position across a worker restart on changed step code."""

    async def scenario() -> None:
        async with local_engine() as local:
            engine, workers = local.engine, Workers(local.target)
            try:
                first = workers.start()
                await engine.start("wait-then-step", "keeps-position")
                waiting = await until(
                    lambda: engine.recorded("keeps-position"), lambda r: r.idle, "the wait", workers
                )
                assert waiting.finished_steps == ("one",)
                workers.kill(first)

                workers.start(changed_sample(tmp_path))
                await engine.signal("keeps-position", "go", "now")
                result = await asyncio.wait_for(engine.result("keeps-position"), DEADLINE)
                recorded = await engine.recorded("keeps-position")
            finally:
                workers.kill_all()

        # Step one's result is the one recorded before the restart; the step after the wait ran
        # on the new code.
        assert result == {"before": "one-v1", "signal": "now", "after": "two-v2-changed"}
        assert recorded.finished_steps == ("one", "two")
        assert engine_sample.marks() == ["one-v1", "two-v2"]

    asyncio.run(scenario())


def test_a_seven_day_timer_fires_under_the_test_clock() -> None:
    """A seven-day timer fires under the test clock."""

    async def scenario() -> None:
        async with time_skipping_engine() as skipping:
            engine, clock = skipping.engine, skipping.clock
            worker = asyncio.create_task(engine.run_worker(engine_sample.REGISTRY))
            try:
                started = await clock.now()
                await engine.start("week", "seven-days")

                def timer_pending(recorded: Recorded) -> bool:
                    return recorded.pending_timers == (engine_sample.WEEK,)

                await until(lambda: engine.recorded("seven-days"), timer_pending, "the timer")

                # One day short of the week: the timer has not fired.
                await clock.advance(timedelta(days=6))
                early = await engine.recorded("seven-days")
                assert early.status == "running" and timer_pending(early)

                # The seventh day passes: it fires, and the workflow finishes.
                await clock.advance(timedelta(days=1))
                await until(
                    lambda: engine.recorded("seven-days"),
                    lambda r: r.pending_timers == (),
                    "the timer firing",
                )
                waited = await asyncio.wait_for(engine.result("seven-days"), DEADLINE)
                fired = await engine.recorded("seven-days")
                finished = await clock.now()
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

        # Seven days by the engine's clock, and by the test clock: no more than the two
        # advances, which the real seconds of this test cannot stretch to an eighth day.
        assert waited >= engine_sample.WEEK.total_seconds()
        assert fired.status == "completed" and fired.pending_timers == ()
        assert engine_sample.WEEK <= finished - started < timedelta(days=8)

    asyncio.run(scenario())


def test_a_signal_sent_with_no_worker_running_is_delivered_when_a_worker_starts() -> None:
    """A signal sent with no worker running is delivered when a worker starts."""

    async def scenario() -> None:
        async with local_engine() as local:
            engine, workers = local.engine, Workers(local.target)
            try:
                first = workers.start()
                await engine.start("wait-then-step", "signal-no-worker")
                await until(
                    lambda: engine.recorded("signal-no-worker"),
                    lambda r: r.idle,
                    "the wait",
                    workers,
                )
                workers.kill(first)
                assert workers.alive() == []

                await engine.signal("signal-no-worker", "go", {"n": 7})
                accepted = await engine.recorded("signal-no-worker")
                # Accepted and kept by the engine, and not yet acted on: nobody is there to.
                assert accepted.signals == ("go",)
                assert accepted.status == "running" and accepted.finished_steps == ("one",)
                assert not accepted.idle

                workers.start()
                result = await asyncio.wait_for(engine.result("signal-no-worker"), DEADLINE)
            finally:
                workers.kill_all()

        assert result == {"before": "one-v1", "signal": {"n": 7}, "after": "two-v1"}
        assert engine_sample.marks() == ["one-v1", "two-v1"]

    asyncio.run(scenario())


def test_a_workflow_started_and_signalled_before_any_worker_exists_runs_when_one_starts() -> None:
    """Start and signal are the engine's records, not a worker's: both wait for the first one."""

    async def scenario() -> None:
        async with local_engine() as local:
            engine, workers = local.engine, Workers(local.target)
            try:
                await engine.start("wait-then-step", "nobody-home")
                await engine.signal("nobody-home", "go", "early")
                workers.start()
                result = await asyncio.wait_for(engine.result("nobody-home"), DEADLINE)
            finally:
                workers.kill_all()
        assert result == {"before": "one-v1", "signal": "early", "after": "two-v1"}

    asyncio.run(scenario())


def test_a_step_that_raises_is_retried_and_its_result_recorded_once() -> None:
    async def scenario() -> tuple[object, Recorded]:
        async with time_skipping_engine() as skipping:
            engine = skipping.engine
            worker = asyncio.create_task(engine.run_worker(engine_sample.REGISTRY))
            try:
                await engine.start("retried", "retried")
                result = await asyncio.wait_for(engine.result("retried"), DEADLINE)
                return result, await engine.recorded("retried")
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    result, recorded = asyncio.run(scenario())
    assert result == "flaky"
    assert engine_sample.marks() == ["flaky-attempt", "flaky-attempt"]
    assert recorded.finished_steps == ("flaky",)


def test_a_step_out_of_attempts_fails_the_workflow_and_a_signal_wait_can_time_out() -> None:
    async def scenario() -> tuple[Recorded, object]:
        async with time_skipping_engine() as skipping:
            engine = skipping.engine
            worker = asyncio.create_task(engine.run_worker(engine_sample.REGISTRY))
            try:
                await engine.start("gives-up", "gives-up")
                with pytest.raises(WorkflowFailed):
                    await asyncio.wait_for(engine.result("gives-up"), DEADLINE)
                await engine.start("recovers", "recovers")
                assert await asyncio.wait_for(engine.result("recovers"), DEADLINE) == "carried on"
                await engine.start("impatient", "impatient")
                with pytest.raises(ValueError, match="already used"):
                    await engine.start("impatient", "impatient")
                await until(
                    lambda: engine.recorded("impatient"),
                    lambda r: r.pending_timers == (timedelta(hours=1),),
                    "the signal wait's timeout",
                )
                await skipping.clock.advance(timedelta(hours=1))
                impatient = await asyncio.wait_for(engine.result("impatient"), DEADLINE)
                return await engine.recorded("gives-up"), impatient
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    recorded, impatient = asyncio.run(scenario())
    assert recorded.status == "failed" and recorded.finished_steps == ()
    assert engine_sample.marks() == ["doomed-attempt"] * 4
    assert impatient == "timed out"


def test_a_step_bounded_by_a_limit_is_abandoned_when_the_durable_timer_fires_first() -> None:
    """On the development server, in real time: the test server does not move its clock while
    a step is running, so a limit that beats a running step cannot be shown on the test clock."""

    async def scenario() -> tuple[Recorded, Recorded, object]:
        hold = pathlib.Path(os.environ["SORTYARD_ENGINE_HOLD"])
        hold.touch()
        async with local_engine() as local:
            engine = local.engine
            worker = asyncio.create_task(engine.run_worker(engine_sample.REGISTRY))
            try:
                await engine.start("bounded", "bounded", 1)
                # A step that finished inside its limit leaves the workflow idle at its wait.
                in_time = await until(
                    lambda: engine.recorded("bounded"), lambda r: r.idle, "the first wait"
                )
                await engine.signal("bounded", "first")
                # So does a step abandoned at its limit, though its one attempt still runs.
                abandoned = await until(
                    lambda: engine.recorded("bounded"),
                    lambda r: r.idle and r.signals == ("first",),
                    "the second wait",
                )
                await engine.start("overruns", "overruns", 1)
                with pytest.raises(WorkflowFailed, match="did not finish within"):
                    await asyncio.wait_for(engine.result("overruns"), DEADLINE)
                await engine.signal("bounded", "second", "done")
                return (
                    in_time,
                    abandoned,
                    await asyncio.wait_for(engine.result("bounded"), DEADLINE),
                )
            finally:
                hold.unlink()
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    in_time, abandoned, result = asyncio.run(scenario())
    assert in_time.finished_steps == ("one",) and in_time.pending_timers == ()
    assert abandoned.finished_steps == ("one",) and abandoned.pending_timers == ()
    assert result == ["one-v1", "limit passed", "done"]
    assert engine_sample.marks() == ["one-v1", "stuck-started", "stuck-started"]


def test_a_defect_in_workflow_code_keeps_the_workflow_and_is_reported() -> None:
    async def scenario() -> Recorded:
        async with time_skipping_engine() as skipping:
            engine = skipping.engine
            worker = asyncio.create_task(engine.run_worker(engine_sample.REGISTRY))
            try:
                await engine.start("defective", "defective")
                return await until(
                    lambda: engine.recorded("defective"),
                    lambda r: r.defect is not None,
                    "the failed pass",
                )
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    recorded = asyncio.run(scenario())
    assert recorded.status == "running" and recorded.finished_steps == ("one",)
    assert recorded.defect is not None and "a bug in the workflow function" in recorded.defect
    assert engine_sample.marks() == ["one-v1"]


def test_calls_on_an_unknown_or_ended_workflow_raise_the_boundarys_own_error() -> None:
    async def scenario() -> None:
        async with time_skipping_engine() as skipping:
            engine = skipping.engine
            worker = asyncio.create_task(engine.run_worker(engine_sample.REGISTRY))
            try:
                with pytest.raises(WorkflowNotFound):
                    await engine.signal("nobody", "go")
                with pytest.raises(WorkflowNotFound):
                    await engine.recorded("nobody")
                with pytest.raises(WorkflowNotFound):
                    await engine.result("nobody")
                await engine.start("retried", "ended")
                await asyncio.wait_for(engine.result("ended"), DEADLINE)
                with pytest.raises(WorkflowNotFound):
                    await engine.signal("ended", "go")
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(scenario())


def test_the_engine_reports_its_version() -> None:
    assert isinstance(Engine, type)
    assert engine_version().split(".")[0].isdigit()
