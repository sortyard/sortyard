"""sortyard-kernel: the one service that takes an item from admitted to merged.

It runs two things on one engine connection (HARNESS-V3 section 6, phase 1):

- the **engine worker**, with the item workflow and every owner of the shipped state table
  registered (scheduler, capability-checker, need, executor, reviewer, ci-adapter,
  merge-adapter), the decision step on the decision policy, and the ledger recorder. A table
  owner with no function is refused at start, not found out by an item waiting in its state;
- the **observer loop** (`sortyard.kernel.observer`): every interval it reads the open stays
  from Postgres, asks each one's adapter whether the outside work is done, and sends the
  outcome with the stay's dispatch number.

The service keeps nothing in memory that matters. Stopped at any point and started again, the
engine resumes every workflow from its history and the observer reads the open stays, the gap
items and the lane slots back from Postgres.

Configuration, all from the environment and mounted files. Every setting marked required
must be present: the service exits with status 2 and names what is missing. There are no
optional credentials.

  SORTYARD_ENGINE_TARGET            required  host:port of the workflow engine
  SORTYARD_ENGINE_NAMESPACE                   the engine namespace (default "default")
  SORTYARD_DATABASE_HOST            required  Postgres, as for sortyard-api
  SORTYARD_DATABASE_PORT                      (default 5432)
  SORTYARD_DATABASE_NAME            required
  SORTYARD_DATABASE_USER            required
  SORTYARD_DATABASE_PASSWORD        required
  SORTYARD_LANES_DIR                required  directory of lane capability files (*.toml)
  SORTYARD_WORKER_CONFIG            required  the worker configuration file (TOML, below)
  SORTYARD_GITHUB_APP_ID            required  the GitHub App the lanes' tokens come from
  SORTYARD_GITHUB_APP_KEY_FILE      required  path of the App's private key (PEM)
  SORTYARD_GITHUB_API_URL                     (default https://api.github.com)
  SORTYARD_JOBS_NAMESPACE           required  the namespace worker Jobs run in
  SORTYARD_KUBE_URL                           the Kubernetes API; unset, the pod's own service
  SORTYARD_KUBE_TOKEN_FILE                    account is used (in-cluster). Set, the token
  SORTYARD_KUBE_CA_FILE                       file is required and the CA file is for https.
  SORTYARD_DECISION_POLICY                    a decision policy file (default: the shipped one)
  SORTYARD_OBSERVER_INTERVAL_SECONDS          seconds between observer passes (default 15)

The worker configuration file says how workers run in this deployment
(`sortyard.lane.worker.WorkerConfig`):

  git-url = "https://github.com/{repository}.git"   # optional
  command = ["sortyard-worker"]                      # optional
  deadline = 7200                                    # optional, seconds; also ttl, token-age
  [agents]                                           # required: an argv for each
  build = ["agent", "--build"]
  fix = ["agent", "--fix"]
  review = ["agent", "--review"]
  [secrets]                                          # optional: lane secret name -> Secret, key
  DEPLOY_TOKEN = { secret = "deploy", key = "token" }
  [services]                                         # optional: lane service name -> probe URL
  cluster-api = "https://cluster.example/healthz"

The runner-pool probe checks only that the cluster answers this service for Jobs in the
namespace; no port exists yet that exercises a named pool.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import pathlib
import signal
import ssl
import sys
import tomllib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
import psycopg.conninfo

from sortyard.engine import Engine, Registry
from sortyard.kernel import policy
from sortyard.kernel.capabilities import RUNNER_POOL, CapabilityError, Lane, Need
from sortyard.kernel.preflight import Probe, ProbeResult
from sortyard.lane.github import API, HttpGitHub
from sortyard.lane.jobs import Jobs, KubeJobs
from sortyard.lane.runtime import Runtime, build
from sortyard.lane.worker import WorkerConfig
from sortyard.services.api import load_lanes

log = logging.getLogger("sortyard.kernel")

REQUIRED = (
    "SORTYARD_ENGINE_TARGET",
    "SORTYARD_DATABASE_HOST",
    "SORTYARD_DATABASE_NAME",
    "SORTYARD_DATABASE_USER",
    "SORTYARD_DATABASE_PASSWORD",
    "SORTYARD_LANES_DIR",
    "SORTYARD_WORKER_CONFIG",
    "SORTYARD_GITHUB_APP_ID",
    "SORTYARD_GITHUB_APP_KEY_FILE",
    "SORTYARD_JOBS_NAMESPACE",
)
_WORKER_KEYS = {"git-url", "command", "deadline", "ttl", "token-age", "agents", "secrets"}
_WORKER_KEYS |= {"services"}


class SettingsError(Exception):
    """The service cannot start on its configuration. The message names what is wrong and
    never a value that could be a credential."""


def worker_config(text: str) -> WorkerConfig:
    """The worker configuration from its TOML text."""
    try:
        raw = tomllib.loads(text)
        if set(raw) - _WORKER_KEYS:
            raise ValueError(f"unknown keys {sorted(set(raw) - _WORKER_KEYS)}")
        secrets = {
            name: (str(ref["secret"]), str(ref["key"]))
            for name, ref in dict(raw.get("secrets", {})).items()
        }
        options: dict[str, Any] = {
            key.replace("-", "_"): raw[key]
            for key in ("git-url", "command", "deadline", "ttl", "token-age")
            if key in raw
        }
        return WorkerConfig(
            agents={mode: list(argv) for mode, argv in dict(raw.get("agents", {})).items()},
            secrets=secrets,
            services={name: str(url) for name, url in dict(raw.get("services", {})).items()},
            **options,
        )
    except (ValueError, KeyError, TypeError) as error:
        raise SettingsError(f"SORTYARD_WORKER_CONFIG: {type(error).__name__}: {error}") from None


@dataclass(frozen=True)
class Settings:
    engine_target: str
    engine_namespace: str
    conninfo: str
    lanes: Mapping[str, Lane]
    worker: WorkerConfig
    github_app_id: str
    github_app_key: bytes
    github_api_url: str
    jobs_namespace: str
    kube_url: str | None
    kube_token_file: str | None
    kube_ca_file: str | None
    decisions: policy.Policy
    interval: float

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        missing = [name for name in REQUIRED if not env.get(name)]
        kube_url = env.get("SORTYARD_KUBE_URL") or None
        if kube_url and not env.get("SORTYARD_KUBE_TOKEN_FILE"):
            missing.append("SORTYARD_KUBE_TOKEN_FILE")
        if not kube_url and not env.get("KUBERNETES_SERVICE_HOST"):
            missing.append("SORTYARD_KUBE_URL (or run in a cluster)")
        if missing:
            raise SettingsError(f"missing required settings: {', '.join(missing)}")

        def read(name: str) -> bytes:
            try:
                return pathlib.Path(env[name]).read_bytes()
            except OSError as error:
                raise SettingsError(f"{name}: cannot read the file ({error.strerror})") from None

        try:
            lanes = load_lanes(env["SORTYARD_LANES_DIR"])
            decisions = (
                policy.load(read("SORTYARD_DECISION_POLICY").decode())
                if env.get("SORTYARD_DECISION_POLICY")
                else policy.shipped()
            )
            interval = float(env.get("SORTYARD_OBSERVER_INTERVAL_SECONDS", 15))
            port = int(env.get("SORTYARD_DATABASE_PORT", 5432))
        except (CapabilityError, ValueError, OSError) as error:
            raise SettingsError(str(error)) from None
        if not lanes:
            raise SettingsError("SORTYARD_LANES_DIR holds no lane capability file (*.toml)")
        if interval <= 0:
            raise SettingsError("SORTYARD_OBSERVER_INTERVAL_SECONDS must be above 0")
        return cls(
            engine_target=env["SORTYARD_ENGINE_TARGET"],
            engine_namespace=env.get("SORTYARD_ENGINE_NAMESPACE", "default"),
            conninfo=psycopg.conninfo.make_conninfo(
                host=env["SORTYARD_DATABASE_HOST"],
                port=port,
                dbname=env["SORTYARD_DATABASE_NAME"],
                user=env["SORTYARD_DATABASE_USER"],
                password=env["SORTYARD_DATABASE_PASSWORD"],
            ),
            lanes=lanes,
            worker=worker_config(read("SORTYARD_WORKER_CONFIG").decode()),
            github_app_id=env["SORTYARD_GITHUB_APP_ID"],
            github_app_key=read("SORTYARD_GITHUB_APP_KEY_FILE"),
            github_api_url=env.get("SORTYARD_GITHUB_API_URL", API),
            jobs_namespace=env["SORTYARD_JOBS_NAMESPACE"],
            kube_url=kube_url,
            kube_token_file=env.get("SORTYARD_KUBE_TOKEN_FILE") or None,
            kube_ca_file=env.get("SORTYARD_KUBE_CA_FILE") or None,
            decisions=decisions,
            interval=interval,
        )

    def jobs(self) -> Jobs:
        if self.kube_url is None:
            return KubeJobs.in_cluster(self.jobs_namespace)
        token_file = pathlib.Path(str(self.kube_token_file))
        context = (
            ssl.create_default_context(cafile=self.kube_ca_file) if self.kube_ca_file else None
        )
        return KubeJobs(
            self.kube_url,
            self.jobs_namespace,
            token=lambda: token_file.read_text().strip(),
            context=context,
        )


def runner_pool_probe(jobs: Jobs) -> Probe:
    """Passes when the cluster answers this service for Jobs in the lane's namespace. It does
    not exercise the named pool: nothing in the jobs port can yet."""

    def probe(need: Need, lane: Lane) -> ProbeResult:
        jobs.status("sy-runner-pool-probe")  # raises when the cluster refuses or is away
        return ProbeResult(
            True, f"the cluster answers for Jobs (pool {lane.runner_pool!r} is not exercised)"
        )

    return probe


def assemble(settings: Settings) -> Runtime:
    """Every owner of the shipped table on this deployment's database, GitHub App and cluster.
    Nothing is contacted here."""
    try:
        github = HttpGitHub(
            settings.github_app_id, settings.github_app_key, base_url=settings.github_api_url
        )
    except ValueError as error:
        raise SettingsError(f"SORTYARD_GITHUB_APP_KEY_FILE: {error}") from None
    jobs = settings.jobs()
    return build(
        connect=functools.partial(psycopg.connect, settings.conninfo),
        lanes=settings.lanes,
        github=github,
        jobs=jobs,
        config=settings.worker,
        probes={RUNNER_POOL: runner_pool_probe(jobs)},
        policy=settings.decisions,
    )


async def serve(
    settings: Settings,
    *,
    stop: asyncio.Event | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> int:
    """Run the worker and the observer loop until `stop` is set (0) or one of them ends (1)."""
    runtime = assemble(settings)
    registry = Registry()
    runtime.register(registry)  # refuses a table owner with no function
    engine = await Engine.connect(settings.engine_target, namespace=settings.engine_namespace)
    stop = stop or asyncio.Event()
    tasks: list[asyncio.Task[Any]] = [
        asyncio.create_task(engine.run_worker(registry), name="worker"),
        asyncio.create_task(
            runtime.observer(engine).run(settings.interval, sleep), name="observer"
        ),
    ]
    stopping: asyncio.Task[Any] = asyncio.create_task(stop.wait())
    log.info("sortyard-kernel serving lanes %s", sorted(settings.lanes))
    try:
        await asyncio.wait([*tasks, stopping], return_when=asyncio.FIRST_COMPLETED)
        ended = [task for task in tasks if task.done()]
        for task in ended:
            log.error("%s ended: %r", task.get_name(), task.exception())
        return 1 if ended else 0
    finally:
        for task in (*tasks, stopping):
            task.cancel()
        await asyncio.gather(*tasks, stopping, return_exceptions=True)


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] = os.environ) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        settings = Settings.from_env(env)
        assemble(settings)  # a key that cannot be loaded is a setting that is wrong
    except SettingsError as error:
        print(f"sortyard-kernel: {error}", file=sys.stderr)
        return 2

    async def run() -> int:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop.set)
        return await serve(settings, stop=stop)

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
