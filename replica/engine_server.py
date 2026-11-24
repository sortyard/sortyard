"""The chart's workflow engine server, run with docker instead of a cluster.

    python replica/engine_server.py up        # Postgres, the schema Job, the server
    python replica/engine_server.py schema    # run the schema Job again
    python replica/engine_server.py records   # count what the engine has stored in Postgres
    python replica/engine_server.py down      # remove everything `up` made

`up` renders `charts/sortyard` with `engine.enabled=true` and runs what the chart renders: the
Postgres StatefulSet's container, the engine schema Job's containers and the engine Deployment's
containers, each with the image, command, environment, user and read-only root filesystem of its
manifest. Service names become network aliases, Secret references are read from the rendered
Secret (a password made for this run, passed in the environment and never on a command line)
and ConfigMaps are mounted from files. So the server that answers on the printed address
is the chart's: same server image, same schema tool, same settings, on a real Postgres. Nothing
here names an image or a setting of its own.

The slow workflow uses it to run `tests/test_engine_server.py`; the kind replica
(`replica/replica.sh`) is where the same manifests run on a cluster. Needs docker and helm.
Options: --name (prefix of every container, default sortyard-engine), --port (host port of the
engine, default 7233; 0 picks a free one), --memory (limit of each container, default 1g).
"""

from __future__ import annotations

import argparse
import base64
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHART = ROOT / "charts" / "sortyard"
RELEASE = "replica"
COMPONENT = "app.kubernetes.io/component"
ENGINE_PORT = 7233
STEP_TIMEOUT = 600

Manifest = dict[str, Any]


def render() -> str:
    """The chart with the engine on, as `helm template` renders it."""
    return subprocess.run(
        ["helm", "template", RELEASE, str(CHART), "--set", "engine.enabled=true"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout


def manifests(rendered: str) -> list[Manifest]:
    return [doc for doc in yaml.safe_load_all(rendered) if doc]


def find(docs: list[Manifest], kind: str, component: str) -> Manifest:
    (doc,) = [
        d
        for d in docs
        if d["kind"] == kind and d["metadata"].get("labels", {}).get(COMPONENT) == component
    ]
    return doc


def env_of(container: Manifest, docs: list[Manifest]) -> dict[str, str]:
    """A container's environment, with each Secret reference read from the rendered Secret.

    A value taken from the pod itself (its IP) is left out: the image works it out when unset.
    """
    env: dict[str, str] = {}
    for entry in container.get("env", []):
        if "value" in entry:
            env[entry["name"]] = str(entry["value"])
            continue
        source = entry["valueFrom"]
        if "secretKeyRef" in source:
            ref = source["secretKeyRef"]
            (secret,) = [
                d for d in docs if d["kind"] == "Secret" and d["metadata"]["name"] == ref["name"]
            ]
            env[entry["name"]] = base64.b64decode(secret["data"][ref["key"]]).decode()
        elif "fieldRef" not in source:
            raise ValueError(f"cannot give {entry['name']} a value outside a cluster: {source}")
    return env


def write_config_maps(docs: list[Manifest], directory: pathlib.Path) -> None:
    """Every rendered ConfigMap as a directory of files any container user can read."""
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o755)
    for doc in docs:
        if doc["kind"] != "ConfigMap":
            continue
        target = directory / doc["metadata"]["name"]
        target.mkdir(exist_ok=True)
        target.chmod(0o755)
        for name, content in doc["data"].items():
            (target / name).write_text(content)
            (target / name).chmod(0o644)


def docker_run(
    pod: Manifest,
    container: Manifest,
    docs: list[Manifest],
    *,
    name: str,
    network: str,
    memory: str,
    config: pathlib.Path,
) -> tuple[list[str], dict[str, str]]:
    """The `docker run` command that runs one container of a rendered pod the way its manifest
    says, and the environment to run that command in: the container's variables are passed by
    name, so no value (a password among them) is on the command line."""
    args = ["docker", "run", "--name", name, "--network", network, "--memory", memory]
    security = {**pod.get("securityContext", {}), **container.get("securityContext", {})}
    if "runAsUser" in security:
        args += ["--user", str(security["runAsUser"])]
    if security.get("readOnlyRootFilesystem"):
        args.append("--read-only")
    for capability in security.get("capabilities", {}).get("drop", []):
        args += ["--cap-drop", capability]
    env = env_of(container, docs)
    for key in env:
        args += ["--env", key]
    volumes = {volume["name"]: volume for volume in pod.get("volumes", [])}
    for mount in container.get("volumeMounts", []):
        volume = volumes.get(mount["name"], {})
        if "configMap" in volume:
            args += ["--volume", f"{config / volume['configMap']['name']}:{mount['mountPath']}:ro"]
        elif "emptyDir" in volume:
            args += ["--tmpfs", mount["mountPath"]]
        # Anything else is the pod's data volume: the container keeps its data to itself.
    command = [*container.get("command", []), *container.get("args", [])]
    return [*args, container["image"], *command], env


class Stack:
    """The engine's containers under one name prefix."""

    def __init__(self, name: str, memory: str, port: int) -> None:
        self.name, self.memory, self.port = name, memory, port
        self.network = f"{name}-net"
        self.config = pathlib.Path(tempfile.gettempdir()) / f"{name}-config"
        self._docs: list[Manifest] | None = None

    @property
    def docs(self) -> list[Manifest]:
        """What `up` rendered: later commands act on the same manifests and the same Secret."""
        if self._docs is None:
            self._docs = manifests((self.config / "rendered.yaml").read_text())
        return self._docs

    def run(self, kind: str, component: str, which: str, *, detach: bool = False) -> None:
        """Run the `which` (initContainers or containers) of one rendered workload, in order.

        Detached containers get the workload's Service name as their network alias; the others
        run to their end and must succeed.
        """
        workload = find(self.docs, kind, component)
        pod = workload["spec"]["template"]["spec"]
        for container in pod.get(which, []):
            name = f"{self.name}-{component}" + ("" if detach else f"-{container['name']}")
            args, env = docker_run(
                pod,
                container,
                self.docs,
                name=name,
                network=self.network,
                memory=self.memory,
                config=self.config,
            )
            if detach:
                alias = find(self.docs, "Service", component)["metadata"]["name"]
                extra = ["--detach", "--network-alias", alias]
                if component == "engine":
                    extra += ["--publish", f"127.0.0.1:{self.port}:{ENGINE_PORT}"]
            else:
                extra = ["--rm"]
            print(f"engine_server: {kind} {component}: {container['name']}", flush=True)
            subprocess.run(
                [*args[:2], *extra, *args[2:]],
                check=True,
                timeout=STEP_TIMEOUT,
                stdout=subprocess.DEVNULL if detach else None,
                env={**os.environ, **env},
            )

    def wait_ready(self, component: str, kind: str) -> None:
        """Wait until the container passes the readiness probe command of its manifest."""
        (container,) = find(self.docs, kind, component)["spec"]["template"]["spec"]["containers"]
        probe = container["readinessProbe"]["exec"]["command"]
        deadline = time.monotonic() + STEP_TIMEOUT
        while True:
            ready = subprocess.run(
                ["docker", "exec", f"{self.name}-{component}", *probe],
                capture_output=True,
                timeout=60,
            )
            if ready.returncode == 0:
                return
            if time.monotonic() > deadline:
                raise TimeoutError(f"{component} is not ready: {ready.stderr.decode()}")
            time.sleep(1)

    def target(self) -> str:
        out = subprocess.run(
            ["docker", "port", f"{self.name}-engine", str(ENGINE_PORT)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        return out.splitlines()[0].strip()

    def schema(self) -> None:
        """The whole schema Job, start to end (the server must be running for its last step)."""
        self.run("Job", "engine-schema", "initContainers")
        self.run("Job", "engine-schema", "containers")

    def up(self) -> None:
        self.down()
        rendered = render()
        self._docs = manifests(rendered)
        write_config_maps(self.docs, self.config)
        # It holds the rendered Secret: readable by this user only, and mounted nowhere.
        (self.config / "rendered.yaml").touch(mode=0o600)
        (self.config / "rendered.yaml").write_text(rendered)
        subprocess.run(
            ["docker", "network", "create", self.network],
            check=True,
            stdout=subprocess.DEVNULL,
            timeout=60,
        )
        self.run("StatefulSet", "postgres", "containers", detach=True)
        self.wait_ready("postgres", "StatefulSet")
        # The order a cluster settles into: the Job's schema step, the server's wait for it,
        # the server, the Job's namespace step.
        self.run("Job", "engine-schema", "initContainers")
        self.run("Deployment", "engine", "initContainers")
        self.run("Deployment", "engine", "containers", detach=True)
        self.run("Job", "engine-schema", "containers")
        print(self.target(), flush=True)

    def records(self) -> None:
        """Count the workflows of the namespace that the engine has stored in each of its two
        Postgres databases (the server's own system workflows are not counted)."""
        pod = find(self.docs, "Job", "engine-schema")["spec"]["template"]["spec"]
        (postgres,) = find(self.docs, "StatefulSet", "postgres")["spec"]["template"]["spec"][
            "containers"
        ]
        user = env_of(postgres, self.docs)["POSTGRES_USER"]
        schema = env_of(pod["initContainers"][0], self.docs)
        namespace = env_of(pod["containers"][0], self.docs)["SORTYARD_ENGINE_NAMESPACE"]

        base = ["docker", "exec", f"{self.name}-postgres", "psql", "-X", "-tA", "-U", user]

        def psql(database: str, query: str) -> str:
            return subprocess.run(
                [*base, "-v", "ON_ERROR_STOP=1", database, "-c", query],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout.strip()

        main, visibility = (
            schema["SORTYARD_ENGINE_DATABASE"],
            schema["SORTYARD_ENGINE_VISIBILITY_DATABASE"],
        )
        namespace_id = psql(
            main, f"SELECT encode(id, 'hex')::uuid FROM namespaces WHERE name = '{namespace}'"
        )
        counts = {
            f"{main}.executions": psql(
                main,
                "SELECT count(*) FROM executions"
                f" WHERE namespace_id = decode(replace('{namespace_id}', '-', ''), 'hex')",
            ),
            f"{visibility}.executions_visibility": psql(
                visibility,
                f"SELECT count(*) FROM executions_visibility WHERE namespace_id = '{namespace_id}'",
            ),
        }
        for table, count in counts.items():
            print(f"{table}: {count} workflow(s) of namespace {namespace}", flush=True)
            if int(count) == 0:
                raise SystemExit(f"the engine stored nothing in {table}")

    def down(self) -> None:
        listed = subprocess.run(
            ["docker", "ps", "--all", "--quiet", "--filter", f"name=^{self.name}-"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.split()
        if listed:
            subprocess.run(
                ["docker", "rm", "--force", "--volumes", *listed],
                check=True,
                stdout=subprocess.DEVNULL,
                timeout=120,
            )
        subprocess.run(["docker", "network", "rm", self.network], capture_output=True, timeout=60)
        shutil.rmtree(self.config, ignore_errors=True)


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description="The chart's engine server, run with docker.")
    parser.add_argument("command", choices=["up", "schema", "records", "down"])
    parser.add_argument("--name", default="sortyard-engine")
    parser.add_argument("--port", type=int, default=ENGINE_PORT)
    parser.add_argument("--memory", default="1g")
    options = parser.parse_args(argv)
    stack = Stack(options.name, options.memory, options.port)
    getattr(stack, options.command)()


if __name__ == "__main__":
    main(sys.argv[1:])
