"""Shared pieces of the lane runtime tests: one world the kernel service runs in.

Everything of ours is real: the kernel service is built from its environment settings
(`sortyard.services.kernel`), the API service admits items over HTTP, the engine is the engine's
own development server, the ledger is a fresh migrated Postgres. The outside is the two strict
fakes, each over real HTTP and held to its provider's published schema: GitHub
(`tests/fake_github.py`) and the Kubernetes API (`tests/fake_jobs.py`).

`World.turn` plays what the outside does between two looks of the observer, and nothing else:

- the cluster runs the pod of every Job that can start, with the real `sortyard-worker` entry
  point against a git remote on disk and a scripted agent (`tests/worker_harness.py`), and
  keeps the termination message;
- GitHub's hosting side shows what was pushed (the branch head on disk becomes the branch head
  the fake's API serves);
- CI reports the check `test` on the head of every open pull request.

A test may hold any of these back (`held`, `ci_held`) to keep an item mid-build or mid-check.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import psycopg
import psycopg.conninfo

from sortyard.api import handlers
from sortyard.engine import Engine
from sortyard.engine.blocking import BlockingEngine
from sortyard.engine.testing import local_engine
from sortyard.kernel.item import start_item
from sortyard.lane.jobs import BRIEF_KEY, TOKEN_KEY
from sortyard.services import kernel
from sortyard.services.api import load_lanes
from tests.api_harness import WS, Api, Response, running_api
from tests.fake_github import APP_ID, KEY, PEM, FakeGitHub, FakeRepo, serving
from tests.fake_jobs import FakeCluster
from tests.worker_harness import DIGEST, agent_command, make_remote, remote_head, run_worker

REPO = "walwarden/app"
OTHER_REPO = "walwarden/infra"  # declared by the lane; not on GitHub until a test puts it there
CHECK = "test"
DEADLINE = 240.0
LANE = f"""
version = 1
lane = "walwarden"
resolver = "platform"
runner-pool = "walwarden-runners"
slots = 2

[images]
worker = "registry.test/walwarden/worker@{DIGEST}"
ci = "registry.test/walwarden/ci@{DIGEST}"

[[repositories]]
name = "{REPO}"
checks = ["{CHECK}"]

[[repositories]]
name = "{OTHER_REPO}"
workflow-files = true

[[secrets]]
name = "MODEL_API_KEY"

[[services]]
name = "cluster-api"
"""


def spec(outcome: str = "the widget counts to ten") -> dict[str, Any]:
    return {
        "outcome": outcome,
        "acceptance": [{"test": "tests/test_widget.py", "name": "the widget counts to ten"}],
    }


@dataclass
class World:
    api: Api
    engine: Engine
    target: str
    fake: FakeGitHub
    repo: FakeRepo
    cluster: FakeCluster
    root: pathlib.Path
    bare: pathlib.Path
    env: dict[str, str]
    # Items (or "item:mode") whose Jobs the cluster does not run yet, and whether CI is not
    # reporting yet.
    held: set[str] = field(default_factory=set)
    ci_held: bool = False
    # Items whose first head fails the check.
    red_once: set[str] = field(default_factory=set)
    ran: list[dict[str, Any]] = field(default_factory=list)  # the brief of every Job run

    def connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.api.conninfo)

    def settings(self) -> kernel.Settings:
        """The service's settings, read from the environment as a new process would."""
        return kernel.Settings.from_env(self.env)

    def admit(self, item: str, role: str = "operator", **more: Any) -> Response:
        body = {
            "id": item,
            "project_id": "proj-a",
            "title": f"Item {item}",
            "lane": "walwarden",
            "repository": REPO,
            "spec": spec(),
            **more,
        }
        return self.api.ws("POST", "/items", role, body)

    def states(self) -> dict[str, str | None]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, state FROM sortyard.item WHERE workspace_id = %s AND id <> 'item-1'",
                (WS,),
            ).fetchall()
        return dict(rows)

    def timeline(self, item: str) -> list[dict[str, Any]]:
        reply = self.api.ws("GET", f"/items/{item}/timeline", "viewer")
        assert reply.status == 200, reply.body
        events: list[dict[str, Any]] = reply.body["items"]
        return events

    def path(self, item: str) -> list[str]:
        """The states the item entered, in order."""
        return [event["transition"]["to"] for event in self.timeline(item)]

    def _job_ended(self, name: str) -> bool:
        return bool(self.cluster.get("job", name)["status"].get("conditions"))

    async def turn(self) -> None:
        """What the cluster, GitHub's hosting side and CI do between two looks."""
        for name in self.cluster.names("job"):
            try:
                if self._job_ended(name) or self.cluster.unstartable(name):
                    continue  # ended, or its brief or its token is not there yet
                brief = json.loads(self.cluster.get("configmap", name)["data"][BRIEF_KEY])
                token = self.cluster.secret_value(name, TOKEN_KEY)
            except (KeyError, StopIteration):
                continue  # deleted meanwhile: a later dispatch of the item replaced it
            if {brief["item"], f"{brief['item']}:{brief['mode']}"} & self.held:
                continue
            status, text = await asyncio.to_thread(
                run_worker, self.root / "jobs" / name, brief, token
            )
            self.ran.append(brief)
            head = remote_head(self.bare, brief["branch"])
            if head is not None and self.repo.refs.get(f"refs/heads/{brief['branch']}") != head:
                self.fake.push(self.repo, brief["branch"], sha=head)
            with contextlib.suppress(KeyError):  # deleted while its pod ran
                self.cluster.finish(name, text, status)
        if self.ci_held:
            return
        for pull in self.repo.pulls:
            if pull.open and not self.repo.runs.get(pull.head):
                item = pull.branch.removeprefix("sortyard/")
                failing = item in self.red_once
                self.red_once.discard(item)
                self.fake.check(self.repo, pull.head, CHECK, "failure" if failing else "success")

    def verify(self) -> None:
        """Both fakes stayed inside their published contracts, no Secret's data was read, and
        no token GitHub minted is in the ledger."""
        self.fake.verify()
        assert self.cluster.violations == []
        assert self.cluster.secret_data_reads == 0
        with self.connect() as conn:
            row = conn.execute("SELECT coalesce(json_agg(doc), '[]')::text FROM sortyard.event")
            ledger = str(row.fetchone())
        assert all(token not in ledger for token in self.fake.minted())


class Service:
    """The kernel service as its console script runs it (`kernel.serve`), in this process.

    Its observer loop is paced by the test instead of a timer: the loop's sleep returns when
    `run_pass` says so, so a test decides when the service looks. `kill` stops the worker and
    the observer where they stand; a new `Service` shares nothing with the one before it but
    the database and the engine server.
    """

    def __init__(self, world: World) -> None:
        self._passes = 0
        self._go = asyncio.Event()
        self._task = asyncio.create_task(kernel.serve(world.settings(), sleep=self._sleep))

    async def _sleep(self, interval: float) -> None:
        self._passes += 1
        self._go.clear()
        await self._go.wait()

    async def run_pass(self) -> None:
        """Let the observer loop pass once more, and wait for that pass to end."""
        wanted = self._passes + 1
        self._go.set()
        while self._passes < wanted:
            assert not self._task.done(), self._task
            await asyncio.sleep(0.01)

    async def kill(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


async def drive(
    world: World, service: Service, done: Callable[[], bool], what: str, deadline: float = DEADLINE
) -> None:
    """Passes of the observer and turns of the outside world until `done`."""
    loop = asyncio.get_running_loop()
    until = loop.time() + deadline
    while not done():
        assert loop.time() < until, f"timed out waiting for {what}; states: {world.states()}"
        await service.run_pass()
        await world.turn()
        await asyncio.sleep(0.02)


@asynccontextmanager
async def world(tmp_path: pathlib.Path) -> AsyncIterator[World]:
    bare = make_remote(tmp_path)
    fake = FakeGitHub(APP_ID, KEY.public_key())
    lanes = tmp_path / "lanes"
    lanes.mkdir()
    (lanes / "walwarden.toml").write_text(LANE)
    (tmp_path / "app.pem").write_bytes(PEM)
    async with local_engine() as local:
        blocking = BlockingEngine(local.target)

        def start(tenant: str, item: str, risk_tier: str) -> None:
            blocking.call(lambda e: start_item(e, item, tenant=tenant, risk_tier=risk_tier))

        door = handlers.Kernel(load_lanes(str(lanes)), start)
        apis = running_api(signal_item=blocking.signal, kernel=door)
        api = next(apis)
        try:
            with serving(fake) as github_url, FakeCluster() as cluster:
                repo = fake.repo(REPO)
                fake.protect(repo, "main", [CHECK])
                cluster.add_secret("model-api-key", {"MODEL_API_KEY": "the-lane-secret-value"})
                (tmp_path / "kube-token").write_text(cluster.token + "\n")
                agents = {
                    "build": agent_command(tmp_path, "commit:fix.txt", "build"),
                    "fix": agent_command(tmp_path, "commit:repair.txt", "fix"),
                    "review": agent_command(tmp_path, "review", "review"),
                }
                (tmp_path / "worker.toml").write_text(
                    f'git-url = "{tmp_path.as_uri()}/{{repository}}.git"\n'
                    f'[services]\ncluster-api = "{cluster.url}/healthz"\n'
                    "[agents]\n"
                    + "".join(f"{mode} = {json.dumps(argv)}\n" for mode, argv in agents.items())
                )
                database = psycopg.conninfo.conninfo_to_dict(api.conninfo)
                env = {
                    "SORTYARD_ENGINE_TARGET": local.target,
                    # The test Postgres, as tests/pg.py reaches it.
                    "SORTYARD_DATABASE_HOST": os.environ["PGHOST"],
                    "SORTYARD_DATABASE_PORT": os.environ.get("PGPORT", "5432"),
                    "SORTYARD_DATABASE_USER": os.environ["PGUSER"],
                    "SORTYARD_DATABASE_PASSWORD": os.environ["PGPASSWORD"],
                    "SORTYARD_DATABASE_NAME": str(database["dbname"]),
                    "SORTYARD_LANES_DIR": str(lanes),
                    "SORTYARD_WORKER_CONFIG": str(tmp_path / "worker.toml"),
                    "SORTYARD_GITHUB_APP_ID": APP_ID,
                    "SORTYARD_GITHUB_APP_KEY_FILE": str(tmp_path / "app.pem"),
                    "SORTYARD_GITHUB_API_URL": github_url,
                    "SORTYARD_JOBS_NAMESPACE": cluster.namespace,
                    "SORTYARD_KUBE_URL": cluster.url,
                    "SORTYARD_KUBE_TOKEN_FILE": str(tmp_path / "kube-token"),
                }
                made = World(
                    api, local.engine, local.target, fake, repo, cluster, tmp_path, bare, env
                )
                yield made
                made.verify()
        finally:
            blocking.close()
            next(apis, None)  # lets the API harness stop its server and drop its database
