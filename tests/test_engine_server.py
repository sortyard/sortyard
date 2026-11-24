"""Acceptance (SY-V3-CHART-ENGINE): the four failure tests pass against the engine server on
Postgres.

`tests/test_engine_failure.py` runs the four failure tests on the SDK's own test servers, which
keep their state in memory. Here the same four run through `sortyard.engine` against the engine
**server** the chart installs, storing to a real Postgres: `replica/engine_server.py` starts it
with docker from the chart's rendered manifests (same server image, same schema Job, same
settings), and SORTYARD_ENGINE_SERVER_TARGET (host:port) names it. Without that variable these
tests are skipped: the merge gate does not boot the engine server. The slow workflow sets it, so
there they are required.

Three of the four are the test functions of `tests/test_engine_failure.py` themselves, given
this server instead of a development server. The timer test differs, and has to: a real server
has no test clock to move, so it waits out a short real timer and proves instead what a test
clock cannot, that the timer is the server's and fires with every worker dead.

The server is shared by every test and outlives the run, so each test gets its own task queue
and its own workflow ids: nothing a previous test or run left behind can reach it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import shutil
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from types import ModuleType
from typing import Any

import pytest
import yaml

from sortyard.engine import Engine, Recorded
from tests import test_engine_failure as failure
from tests.test_engine_failure import marks  # noqa: F401  (the marks and hold files)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = os.environ.get("SORTYARD_ENGINE_SERVER_TARGET")
needs_server = pytest.mark.skipif(
    not TARGET, reason="SORTYARD_ENGINE_SERVER_TARGET is not set (the slow workflow sets it)"
)
#: Long enough to kill the worker before it fires; short enough to wait out for real.
SHORT_TIMER = timedelta(seconds=8)


class RunScoped:
    """An engine connection whose workflow ids all carry one prefix.

    The failure tests name their workflows with fixed ids, and an id can be used once: on a
    server that outlives the test, the prefix is what lets them run again.
    """

    def __init__(self, engine: Engine, prefix: str) -> None:
        self._engine, self._prefix = engine, prefix

    async def start(self, workflow_name: str, workflow_id: str, arg: Any = None) -> None:
        await self._engine.start(workflow_name, self._prefix + workflow_id, arg)

    async def signal(self, workflow_id: str, name: str, payload: Any = None) -> None:
        await self._engine.signal(self._prefix + workflow_id, name, payload)

    async def result(self, workflow_id: str) -> Any:
        return await self._engine.result(self._prefix + workflow_id)

    async def recorded(self, workflow_id: str) -> Recorded:
        return await self._engine.recorded(self._prefix + workflow_id)


@dataclass(frozen=True)
class ServerEngine:
    """What a failure test takes from `local_engine()`: the connection and the address."""

    engine: RunScoped
    target: str


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], Any]]:
    """Point the failure tests at the engine server: `local_engine` now connects to it."""
    assert TARGET is not None
    target, run = TARGET, uuid.uuid4().hex[:12]
    queue = f"failure-tests-{run}"
    # The worker processes of the failure tests read their task queue from here.
    monkeypatch.setenv("SORTYARD_ENGINE_TASK_QUEUE", queue)

    @asynccontextmanager
    async def server_engine() -> AsyncIterator[ServerEngine]:
        engine = await Engine.connect(target, task_queue=queue)
        yield ServerEngine(RunScoped(engine, f"{run}-"), target)

    monkeypatch.setattr(failure, "local_engine", server_engine)
    yield server_engine


def short_timer_sample(directory: pathlib.Path) -> pathlib.Path:
    """A copy of the sample whose `week` workflow waits SHORT_TIMER instead of seven days."""
    source = failure.SAMPLE.read_text()
    changed = source.replace(
        "WEEK = timedelta(days=7)", f"WEEK = timedelta(seconds={SHORT_TIMER.total_seconds()})"
    )
    assert changed != source, "the sample moved"
    path = directory / "engine_sample_short_timer.py"
    path.write_text(changed)
    return path


def a_timer_fires_on_the_server_with_no_worker_running(
    server_engine: Callable[[], Any], tmp_path: pathlib.Path
) -> None:
    """The long timer of the failure tests, on a server with no test clock: a real, short
    timer is started, its worker is killed, it fires with no worker running, and a new worker
    finishes the workflow."""

    async def scenario() -> None:
        sample = short_timer_sample(tmp_path)
        async with server_engine() as server:
            engine, workers = server.engine, failure.Workers(server.target)
            try:
                first = workers.start(sample)
                await engine.start("week", "short-timer")
                await failure.until(
                    lambda: engine.recorded("short-timer"),
                    lambda r: r.pending_timers == (SHORT_TIMER,) and r.idle,
                    "the timer",
                    workers,
                )
                workers.kill(first)
                assert workers.alive() == []

                # Nobody is serving the workflow; the timer is the server's, and it fires.
                fired = await failure.until(
                    lambda: engine.recorded("short-timer"),
                    lambda r: r.pending_timers == (),
                    "the timer firing with no worker running",
                )
                assert fired.status == "running" and not fired.idle

                workers.start(sample)
                waited = await asyncio.wait_for(engine.result("short-timer"), failure.DEADLINE)
                recorded = await engine.recorded("short-timer")
            finally:
                workers.kill_all()

        assert waited >= SHORT_TIMER.total_seconds()
        assert recorded.status == "completed" and recorded.pending_timers == ()

    asyncio.run(scenario())


def killed_mid_step(server_engine: Callable[[], Any], tmp_path: pathlib.Path) -> None:
    failure.test_a_workflow_finishes_after_its_worker_is_killed_mid_step_and_finished_steps_do_not_run_again(
        pathlib.Path(os.environ["SORTYARD_ENGINE_MARKS"])
    )


def restart_on_changed_step_code(server_engine: Callable[[], Any], tmp_path: pathlib.Path) -> None:
    failure.test_a_waiting_workflow_keeps_its_position_across_a_worker_restart_on_changed_step_code(
        tmp_path
    )


def signal_with_no_worker(server_engine: Callable[[], Any], tmp_path: pathlib.Path) -> None:
    failure.test_a_signal_sent_with_no_worker_running_is_delivered_when_a_worker_starts()


@needs_server
@pytest.mark.parametrize(
    "failure_test",
    [
        killed_mid_step,
        restart_on_changed_step_code,
        a_timer_fires_on_the_server_with_no_worker_running,
        signal_with_no_worker,
    ],
    ids=lambda test: str(test.__name__),
)
def test_the_four_failure_tests_pass_against_the_engine_server_on_postgres(
    failure_test: Callable[[Callable[[], Any], pathlib.Path], None],
    server: Callable[[], Any],
    tmp_path: pathlib.Path,
) -> None:
    """The four failure tests pass against the engine server on Postgres."""
    failure_test(server, tmp_path)


# --- the server those tests run against is the chart's ---------------------------------------

needs_helm = pytest.mark.skipif(
    shutil.which("helm") is None and not os.environ.get("SORTYARD_REQUIRE_HELM"),
    reason="helm not on PATH (CI sets SORTYARD_REQUIRE_HELM)",
)


def launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "engine_server", ROOT / "replica" / "engine_server.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["engine_server"] = module
    spec.loader.exec_module(module)
    return module


@needs_helm
def test_the_server_started_for_these_tests_is_what_the_chart_renders(
    tmp_path: pathlib.Path,
) -> None:
    """Same server image, same schema tool, same settings: the launcher runs the containers
    of the rendered manifests and names no image or setting of its own."""
    engine_server = launcher()
    values = yaml.safe_load((ROOT / "charts" / "sortyard" / "values.yaml").read_text())["engine"]
    docs = engine_server.manifests(engine_server.render())
    (secret,) = [d for d in docs if d["kind"] == "Secret"]

    def command(
        kind: str, component: str, which: str, index: int
    ) -> tuple[list[str], dict[str, str]]:
        pod = engine_server.find(docs, kind, component)["spec"]["template"]["spec"]
        args, env = engine_server.docker_run(
            pod, pod[which][index], docs, name="n", network="net", memory="1g", config=tmp_path
        )
        return list(args), dict(env)

    server, server_env = command("Deployment", "engine", "containers", 0)
    schema, schema_env = command("Job", "engine-schema", "initContainers", 0)
    namespace, _ = command("Job", "engine-schema", "containers", 0)
    wait, _ = command("Deployment", "engine", "initContainers", 0)

    image = f"temporalio/server:{values['image']['tag']}@{values['image']['digest']}"
    tools = f"temporalio/admin-tools:{values['toolsImage']['tag']}@{values['toolsImage']['digest']}"
    assert server[-1] == image, "the server runs the image's own entrypoint"
    assert schema[schema.index(tools) :] == [tools, "sh", "/engine/setup.sh", "schema"]
    assert namespace[namespace.index(tools) :] == [tools, "sh", "/engine/setup.sh", "namespace"]
    assert wait[-3:] == ["sh", "/engine/setup.sh", "wait-schema"]
    # The chart's settings reach the container: Postgres, with the rendered Secret's password
    # in the environment of the docker call and not on its command line.
    assert server_env["DB"] == "postgres12"
    assert server_env["POSTGRES_SEEDS"] == schema_env["SQL_HOST"]
    assert server_env["POSTGRES_PWD"] == schema_env["SQL_PASSWORD"] != ""
    assert secret["data"]["password"]
    for args in (server, schema):
        assert not [arg for arg in args if server_env["POSTGRES_PWD"] in arg]
    # A value only a cluster can give (the pod's IP) is left to the image.
    assert "TEMPORAL_BROADCAST_ADDRESS" not in server_env
    # The manifest's hardening applies outside the cluster too, and the script is the chart's.
    assert "--read-only" in server and "--read-only" in schema
    assert f"{tmp_path / 'replica-sortyard-engine'}:/engine:ro" in schema
    engine_server.write_config_maps(docs, tmp_path)
    assert (tmp_path / "replica-sortyard-engine" / "setup.sh").read_text() == (
        ROOT / "charts" / "sortyard" / "engine" / "setup.sh"
    ).read_text()


def test_the_slow_workflow_requires_the_server_tests_and_the_merge_gate_does_not_run_them() -> None:
    workflows = ROOT / ".github" / "workflows"
    slow = yaml.safe_load((workflows / "slow.yml").read_text())["jobs"]["engine-server"]
    runs = [step.get("run", "") for step in slow["steps"]]
    # The slow job starts the chart's server, names it to the tests (so none is skipped), runs
    # them before and after a second run of the schema Job, and reads the records in Postgres.
    target = slow["env"]["SORTYARD_ENGINE_SERVER_TARGET"]
    assert target.startswith("127.0.0.1:")
    order = [
        "python replica/engine_server.py up",
        "pytest tests/test_engine_server.py",
        "python replica/engine_server.py schema",
        "pytest tests/test_engine_server.py",
        "python replica/engine_server.py records",
    ]
    found = [next((command for command in order if command in run), None) for run in runs]
    assert [command for command in found if command] == order
    assert any("engine_server.py down" in run for run in runs)
    # The merge gate stays one job that never boots the engine server.
    gate = (workflows / "ci.yml").read_text()
    assert "engine_server" not in gate and "SORTYARD_ENGINE_SERVER_TARGET" not in gate
