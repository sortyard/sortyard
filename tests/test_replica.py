"""Acceptance: one command boots a local replica of the deployment's shape (corpus M1.1, §11).

`replica/replica.sh up` must
- check its prerequisites (tools and minimum versions) before it changes anything;
- deploy the chart itself, so topology, routing (Services) and auth shape (the Postgres
  password Secret, the shadow's read-only Plane API key Secret) are the deployment's own;
- fake only the outside third-party providers (Plane, the production conductor's pass log),
  and fake them faithfully enough that the real adapter (`PlaneSource`) reads them unchanged.

Acceptance (SY-V3-CHART-KERNEL): the replica boots the engine on Postgres and the kernel, admits
one item against the fake GitHub and a Job that runs a scripted agent, and sees it merged; then
deletes the kernel pod mid-item and sees the next item merged. GitHub is the one more outside
provider faked for that (`replica/fakes/fake_github_host.py`: the tests' strict fake of the API,
and git over HTTP on a bare repository), faithfully enough that the real GitHub client and the
real worker entry point use it unchanged.

The full boot runs in CI (`slow.yml`, `replica` job, nightly) on a kind cluster, and the one
test that needs that cluster (`SORTYARD_REPLICA_CLUSTER` names it) runs there; the other tests
hold the parts that need no cluster.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
import yaml

from sortyard.kernel import capabilities
from sortyard.lane.github import HttpGitHub
from sortyard.lane.worker import Work, WorkerConfig, brief
from sortyard.services import api as api_service
from sortyard.services import kernel
from sortyard.services.api import load_lanes
from sortyard.shadow import evaluate, sources
from tests.api_harness import running_api
from tests.chart_mounts import as_started, container_of, named
from tests.fake_github import APP_ID, KEY, PEM
from tests.pg import requires_postgres
from tests.worker_harness import DIGEST, run_worker

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPLICA = ROOT / "replica"
SCRIPT = REPLICA / "replica.sh"
CHART = ROOT / "charts" / "sortyard"
HELM = shutil.which("helm")
TOOLS = ("docker", "kind", "kubectl", "helm", "curl")

requires_helm = pytest.mark.skipif(
    HELM is None and not os.environ.get("SORTYARD_REQUIRE_HELM"),
    reason="helm not on PATH (CI sets SORTYARD_REQUIRE_HELM)",
)


# --- the entry point ----------------------------------------------------------------------


def test_one_executable_entry_point() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK), "replica/replica.sh must be executable"
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def bare_path(tmp_path: pathlib.Path, stubs: dict[str, str] | None = None) -> str:
    """A PATH with everything the host has except the replica's tools, plus `stubs`
    (name -> shell script body)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for directory in os.environ["PATH"].split(os.pathsep):
        d = pathlib.Path(directory)
        if not d.is_dir():
            continue
        for entry in d.iterdir():
            target = bin_dir / entry.name
            if entry.name in TOOLS or target.exists() or target.is_symlink():
                continue
            target.symlink_to(entry)
    for name, body in (stubs or {}).items():
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
    return str(bin_dir)


def run_script(path: str, *args: str) -> subprocess.CompletedProcess[str]:
    # BASH_ENV would let a startup file put the real tools back on PATH.
    env = {k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "ENV")}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env={**env, "PATH": path},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_missing_tools_are_named_with_versions_and_install_links(tmp_path: pathlib.Path) -> None:
    proc = run_script(bare_path(tmp_path), "check")
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    for tool in TOOLS:
        assert f"{tool}: not found" in out, tool
    for tested in ("v0.25.0", "v1.31.4", "v3.16.3"):
        assert tested in out, tested
    assert "https://kind.sigs.k8s.io" in out
    assert "nothing was changed" in out


def stubs_recording_to(log: pathlib.Path, helm_version: str) -> dict[str, str]:
    record = f'echo "$(basename "$0") $*" >> {log}'
    return {
        "docker": f"{record}\n[ \"$1\" = info ] && exit 0\necho 'Docker version 27.5.1'",
        "kind": f"{record}\necho 'kind v0.25.0 go1.22.9 linux/amd64'",
        "kubectl": f"{record}\necho 'Client Version: v1.31.4'",
        "helm": f"{record}\necho '{helm_version}'",
        "curl": f"{record}\necho 'curl 8.5.0 (x86_64-pc-linux-gnu)'",
    }


def test_up_refuses_a_too_old_tool_before_changing_anything(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "calls.log"
    log.touch()
    path = bare_path(tmp_path, stubs_recording_to(log, "v2.17.0+ga690bad"))
    proc = run_script(path, "up")
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "helm v2.17.0 is older than the minimum v3.12.0" in out
    assert "nothing was changed" in out
    calls = log.read_text().splitlines()
    # Only version / daemon probes ran: no cluster created, no image built, nothing installed.
    for call in calls:
        assert call.split()[1] in ("version", "--version", "info"), call


def test_check_passes_with_supported_tools(tmp_path: pathlib.Path) -> None:
    log = tmp_path / "calls.log"
    log.touch()
    proc = run_script(bare_path(tmp_path, stubs_recording_to(log, "v3.16.3+gcfd0749")), "check")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_unknown_command_prints_usage(tmp_path: pathlib.Path) -> None:
    proc = run_script(os.environ["PATH"], "frobnicate")
    assert proc.returncode == 2
    assert "usage" in (proc.stdout + proc.stderr).lower()


def test_cluster_commands_are_pinned_to_the_replica_cluster() -> None:
    """The script never acts on whatever cluster happens to be the current kube-context."""
    text = SCRIPT.read_text()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for word in ("kubectl ", "helm "):
            if stripped.startswith(word) and "version" not in stripped:
                raise AssertionError(f"call {word.strip()} through its pinned wrapper: {line}")
    assert '--context "kind-$CLUSTER"' in text
    # Backgrounded port-forwards exec kubectl, so stopping $! stops kubectl (not just a
    # subshell that would leave it orphaned).
    assert '(exec kubectl --context "kind-$CLUSTER"' in text
    assert 'k port-forward "svc/$1"' not in text
    assert '--kube-context "kind-$CLUSTER"' in text


def test_the_replica_installs_the_chart_itself() -> None:
    text = SCRIPT.read_text()
    assert 'upgrade --install "$RELEASE" "$ROOT/charts/sortyard"' in text
    assert '-f "$ROOT/replica/values.yaml"' in text


def test_kind_node_image_is_pinned_by_digest() -> None:
    config = yaml.safe_load((REPLICA / "kind.yaml").read_text())
    (node,) = config["nodes"]
    assert "@sha256:" in node["image"]


# --- the deployment's shape -----------------------------------------------------------------


def replica_values() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((REPLICA / "values.yaml").read_text())
    return data


def fakes_manifests() -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all((REPLICA / "fakes.yaml").read_text()) if d]


def test_values_override_only_what_the_replica_must() -> None:
    """Routing and auth stay the chart's: no Service type, no Postgres password, no image
    repository is overridden."""
    values = replica_values()
    assert set(values) <= {"shadow", "postgres", "image", "engine", "kernel"}
    # The engine is switched on and nothing else: its images, store and settings are the chart's.
    assert values.get("engine", {"enabled": True}) == {"enabled": True}
    # The kernel is switched on and pointed at the replica's outside (the fake GitHub, the App
    # key Secret, the scripted agent) and nothing else: where its workers run, its Role and its
    # service account are the chart's.
    kernel_values = values["kernel"]
    assert set(kernel_values) == {"enabled", "observerIntervalSeconds", "worker", "github"}
    assert set(kernel_values["worker"]) == {"gitUrl", "agents"}
    assert set(kernel_values["github"]) == {"appId", "appKeySecret", "apiUrl"}
    assert "auth" not in values.get("postgres", {})
    assert "repository" not in values.get("image", {})
    assert "api" not in values


def test_the_shadow_reads_the_fakes_the_way_production_reads_plane() -> None:
    shadow = replica_values()["shadow"]
    assert shadow["enabled"] is True
    assert shadow["source"] == "plane"
    plane = shadow["plane"]
    services = {d["metadata"]["name"]: d for d in fakes_manifests() if d["kind"] == "Service"}
    configmaps = {d["metadata"]["name"]: d for d in fakes_manifests() if d["kind"] == "ConfigMap"}
    (fake,) = services
    assert plane["url"] == f"http://{fake}:8080"
    assert plane["passes"].startswith(f"http://{fake}:8080/")
    assert shadow["lanes"]["configMap"] in configmaps
    # The read-only key: a Secret the script creates and the fake checks.
    text = SCRIPT.read_text()
    assert f"API_KEY_SECRET={plane['apiKeySecret']}" in text
    (deploy,) = [d for d in fakes_manifests() if d["kind"] == "Deployment"]
    (container,) = deploy["spec"]["template"]["spec"]["containers"]
    env = {e["name"]: e for e in container["env"]}
    ref = env["FAKE_PLANE_API_KEY"]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": plane["apiKeySecret"], "key": "api-key"}


def helm_render(*args: str) -> list[dict[str, Any]]:
    assert HELM is not None, "helm not on PATH"
    out = subprocess.run(
        [HELM, "template", "sortyard", str(CHART), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


WORKER_IMAGE = f"ghcr.io/sortyard/sortyard-replica-worker@{DIGEST}"


def replica_render(tmp_path: pathlib.Path) -> list[dict[str, Any]]:
    """The chart as replica.sh installs it: the replica's values, an image tag, and the lane
    file with the worker image it loaded."""
    lane = tmp_path / "lane.toml"
    lane.write_text((REPLICA / "lane.toml").read_text().replace("__WORKER_IMAGE__", WORKER_IMAGE))
    return helm_render(
        "--namespace",
        "sortyard",
        "-f",
        str(REPLICA / "values.yaml"),
        "--set",
        "image.tag=replica-x",
        "--set-file",
        f"kernel.lanes.replica={lane}",
    )


@requires_helm
def test_replica_renders_the_deployment_topology_plus_the_shadow_the_engine_and_the_kernel(
    tmp_path: pathlib.Path,
) -> None:
    default = {(d["kind"], d["metadata"]["name"]): d for d in helm_render()}
    replica = {(d["kind"], d["metadata"]["name"]): d for d in replica_render(tmp_path)}
    assert set(default) < set(replica)
    added = set(replica) - set(default)
    (schema_job,) = [name for kind, name in added if kind == "Job"]
    assert added == {
        ("Deployment", "sortyard-shadow-conductor"),
        ("Deployment", "sortyard-engine"),
        ("Service", "sortyard-engine"),
        ("ConfigMap", "sortyard-engine"),
        ("Job", schema_job),
        ("Deployment", "sortyard-kernel"),
        ("ServiceAccount", "sortyard-kernel"),
        ("Role", "sortyard-kernel"),
        ("RoleBinding", "sortyard-kernel"),
        ("ConfigMap", "sortyard-kernel"),
        ("ConfigMap", "sortyard-lanes"),
    }
    # The API Deployment is the deployment's own, image tag aside.
    api_default = default[("Deployment", "sortyard-api")]
    api_replica = replica[("Deployment", "sortyard-api")]
    (c_default,) = api_default["spec"]["template"]["spec"]["containers"]
    (c_replica,) = api_replica["spec"]["template"]["spec"]["containers"]
    assert c_replica["image"] == "ghcr.io/sortyard/sortyard:replica-x"
    c_replica["image"] = c_default["image"]
    # ... and the address of the engine the replica switches on,
    (engine_target,) = [e for e in c_replica["env"] if e["name"] == "SORTYARD_ENGINE_TARGET"]
    assert engine_target["value"] == "sortyard-engine:7233"
    c_replica["env"].remove(engine_target)
    # ... and the lane files of the kernel it switches on, which the API admits against.
    (lanes_dir,) = [e for e in c_replica["env"] if e["name"] == "SORTYARD_LANES_DIR"]
    c_replica["env"].remove(lanes_dir)
    (mount,) = c_replica.pop("volumeMounts")
    assert mount["mountPath"] == lanes_dir["value"]
    (volume,) = api_replica["spec"]["template"]["spec"].pop("volumes")
    assert volume == {"name": mount["name"], "configMap": {"name": "sortyard-lanes"}}
    assert list(api_replica["spec"]["template"]["metadata"].pop("annotations")) == [
        "checksum/lanes"
    ]
    assert api_replica == api_default
    assert replica[("Service", "sortyard-api")] == default[("Service", "sortyard-api")]
    # The worker Jobs run in the release's own namespace, under the chart's Role.
    assert replica[("Role", "sortyard-kernel")]["metadata"]["namespace"] == "sortyard"


# --- the fake providers -----------------------------------------------------------------------


def load_fake() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fake_plane", REPLICA / "fakes" / "fake_plane.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fake_plane"] = module
    spec.loader.exec_module(module)
    return module


class Running:
    def __init__(self, url: str, server: Any) -> None:
        self.url = url
        self.server = server

    def audit(self) -> dict[str, int]:
        with urllib.request.urlopen(f"{self.url}/_fake/audit") as resp:
            data: dict[str, int] = json.load(resp)
        return data


@pytest.fixture
def fake() -> Iterator[Running]:
    module = load_fake()
    fixtures = module.load_fixtures(REPLICA / "fakes" / "fixtures.json")
    server = module.make_server("127.0.0.1", 0, fixtures, api_key="replica-read-key")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield Running(f"http://127.0.0.1:{server.server_address[1]}", server)
    finally:
        server.shutdown()
        server.server_close()


def lanes_file(tmp_path: pathlib.Path) -> str:
    name = replica_values()["shadow"]["lanes"]["configMap"]
    key = replica_values()["shadow"]["lanes"].get("key", "products.json")
    (cm,) = [d for d in fakes_manifests() if d["metadata"]["name"] == name]
    path = tmp_path / key
    path.write_text(cm["data"][key])
    return str(path)


def plane_source(fake: Running, tmp_path: pathlib.Path, api_key: str) -> sources.PlaneSource:
    plane = replica_values()["shadow"]["plane"]
    return sources.PlaneSource(
        base_url=fake.url,
        workspace_slug=plane["workspace"],
        project_ids=plane["projects"],
        api_key=api_key,
        lanes_path=lanes_file(tmp_path),
        passes=plane["passes"].replace(plane["url"], fake.url),
    )


def test_the_real_adapter_reads_the_fakes_unchanged(fake: Running, tmp_path: pathlib.Path) -> None:
    pending = plane_source(fake, tmp_path, "replica-read-key").pending(lambda _pid: False)
    ids = [s.production_pass_id for s in pending.snapshots]
    assert len(ids) >= 2, "the fake pass log retains more than one pass (replay + live)"
    for snap in pending.snapshots:
        decisions = evaluate.evaluate(snap, evaluate.ClaimPolicy())
        assert any(d.claimed for d in decisions)
        assert any(not d.claimed for d in decisions)
    audit = fake.audit()
    assert audit["reads"] > 0
    assert audit["writes"] == 0
    assert audit["unauthorized"] == 0


def test_the_fake_plane_enforces_the_api_key(fake: Running, tmp_path: pathlib.Path) -> None:
    with pytest.raises(sources.SourceError, match="401"):
        plane_source(fake, tmp_path, "wrong-key").pending(lambda _pid: False)
    assert fake.audit()["unauthorized"] >= 1


def test_the_fake_refuses_and_counts_writes(fake: Running) -> None:
    req = urllib.request.Request(f"{fake.url}/api/v1/workspaces/x/", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 405
    assert err.value.headers["Allow"] == "GET"
    assert fake.audit()["writes"] == 1


# --- the kernel half: the lane, the worker image and the fake GitHub -------------------------

REPOSITORY = "replica/app"
CLUSTER = os.environ.get("SORTYARD_REPLICA_CLUSTER")


def github_manifests() -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all((REPLICA / "fake-github.yaml").read_text()) if d]


@requires_helm
def test_the_replicas_kernel_starts_on_what_the_chart_and_the_replica_give_it(
    tmp_path: pathlib.Path,
) -> None:
    """The kernel service's own settings loader reads the rendered Deployment, and what it
    reads names the replica's fake GitHub, its lane and its worker image's agent."""
    docs = replica_render(tmp_path)
    values = replica_values()["kernel"]
    app_secret = values["github"]["appKeySecret"]
    secrets = {
        app_secret: {"private-key.pem": PEM.decode()},
        "sortyard-postgres": {"password": "pw"},
    }
    deploy = named(docs, "Deployment", "sortyard-kernel")
    started = as_started(docs, deploy, "kernel", tmp_path, secrets)
    settings = kernel.Settings.from_env({**started, "KUBERNETES_SERVICE_HOST": "10.96.0.1"})
    lane = settings.lanes["replica"]
    assert set(settings.lanes) == {"replica"} and set(lane.repositories) == {REPOSITORY}
    assert lane.worker_image.reference == WORKER_IMAGE
    assert settings.jobs_namespace == "sortyard"
    # The API admits against the same lane.
    api = as_started(docs, named(docs, "Deployment", "sortyard-api"), "api", tmp_path, secrets)
    assert load_lanes(api["SORTYARD_LANES_DIR"]) == settings.lanes

    # The fake GitHub is the API the kernel calls and the git host its workers clone from.
    (service,) = [d for d in github_manifests() if d["kind"] == "Service"]
    base = f"http://{service['metadata']['name']}:{service['spec']['ports'][0]['port']}"
    assert settings.github_api_url == base
    assert settings.worker.git_url == base + "/git/{repository}.git"
    (fake,) = [d for d in github_manifests() if d["kind"] == "Deployment"]
    args = container_of(fake, "fake-github")["command"]
    assert f"--url={base}" in args and f"--app-id={settings.github_app_id}" in args
    assert [a.split("=", 1)[1] for a in args if a.startswith("--repository=")] == [REPOSITORY]
    # One Secret holds the App key: the kernel signs with it, the fake verifies with it.
    volumes = {v["name"]: v for v in fake["spec"]["template"]["spec"]["volumes"]}
    assert volumes["github-app"]["secret"]["secretName"] == app_secret
    script = SCRIPT.read_text()
    assert f"GITHUB_APP_SECRET={app_secret}" in script
    # The fake's files are the ones the script puts in its ConfigMap: the host, the tests'
    # strict fake and the vendored API description, where the fake looks for them.
    assert f"GITHUB_CONFIGMAP={volumes['fakes']['configMap']['name']}" in script
    paths = {item["key"]: item["path"] for item in volumes["fakes"]["configMap"]["items"]}
    assert paths == {
        "fake_github_host.py": "fake_github_host.py",
        "fake_github.py": "tests/fake_github.py",
        "fragment.json": "tests/contracts/github/fragment.json",
    }
    for source in ("replica/fakes/fake_github_host.py", "tests/fake_github.py"):
        assert f'"$ROOT/{source}"' in script and (ROOT / source).is_file()
    assert '"$ROOT/tests/contracts/github/fragment.json"' in script

    # The agent commands are in the worker image the script builds on the Sortyard image.
    dockerfile = (REPLICA / "worker" / "Dockerfile").read_text()
    assert "ARG BASE" in dockerfile and "FROM ${BASE}" in dockerfile
    for mode, argv in settings.worker.agents.items():
        assert argv[0] == "python" and f"COPY agent.py {argv[1]}" in dockerfile and argv[2] == mode
    assert '--build-arg BASE="$IMAGE_REPO:$TAG"' in script
    # What the script admits is an item of this lane and repository.
    assert f"LANE={lane.name}\n" in script and f"LANE_REPOSITORY={REPOSITORY}\n" in script


def test_up_runs_the_lane_after_the_smoke_test_and_the_lane_checks_both_sides() -> None:
    text = SCRIPT.read_text()
    up = text.split("\nup() {", 1)[1].split("\n}", 1)[0]
    steps = [line.strip() for line in up.splitlines()]
    wanted = ["build_image", "deploy_fakes", "deploy_fake_github", "deploy_chart", "smoke", "lane"]
    assert [step for step in steps if step in wanted] == wanted
    lane = text.split("\nlane() {", 1)[1].split("\n}\n", 1)[0]
    # Both items are waited to `merged` in Sortyard and checked as merged on GitHub; between
    # the second's admission and its merge, the kernel pod is deleted.
    order = [
        'admit "$first"',
        'wait_item "$first" merged',
        'merged_on_github "$first"',
        'admit "$second"',
        # Mid-item is checked, not assumed: in `building` with a worker Job running, or fail.
        "[[ $state == building ]] && ((active > 0)) ||",
        'k delete "$pod"',
        'wait_item "$second" merged',
        'merged_on_github "$second"',
    ]
    at = [lane.index(step) for step in order]
    assert at == sorted(at)


def load_module(name: str, path: pathlib.Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def github(tmp_path: pathlib.Path) -> Iterator[tuple[str, Any]]:
    """The replica's fake GitHub, serving on a free local port: its URL and its host."""
    module = load_module("fake_github_host", REPLICA / "fakes" / "fake_github_host.py")
    server, host = module.make_server(
        "127.0.0.1",
        0,
        app_id=APP_ID,
        public_key=KEY.public_key(),
        root=tmp_path / "git",
        repositories=[REPOSITORY],
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", host
    finally:
        server.shutdown()
        server.server_close()


def get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def test_the_real_github_client_and_the_real_worker_use_the_fake_github_unchanged(
    github: tuple[str, Any], tmp_path: pathlib.Path
) -> None:
    """What the replica's kernel and worker Jobs do against the fake, done here without a
    cluster: the real client mints tokens as the App, the real worker entry point clones,
    runs the replica's scripted agent and pushes over git with such a token, and the pull
    request the client then opens and merges is of the pushed commit."""
    url, host = github
    client = HttpGitHub(APP_ID, PEM, base_url=url)
    lane = capabilities.load(
        (REPLICA / "lane.toml").read_text().replace("__WORKER_IMAGE__", WORKER_IMAGE)
    )
    agent = [sys.executable, str(REPLICA / "worker" / "agent.py")]
    config = WorkerConfig(
        agents={mode: [*agent, mode] for mode in ("build", "fix", "review")},
        git_url=f"{url}/git/{{repository}}.git",
    )
    work = Work(lane, REPOSITORY, {"outcome": "a change is made"})
    runs = iter(range(100))

    def worker(mode: str, item: str, token: str) -> tuple[int, dict[str, Any]]:
        call = {"tenant": "ws", "item": item, "dispatch": 1, "detail": {}}
        made = brief(mode, work, call, config)
        status, text = run_worker(tmp_path / f"job-{next(runs)}", made, token)
        return status, json.loads(text)

    write = client.token(REPOSITORY, {"contents": "write"})
    status, built = worker("build", "R-1", write.value)
    assert status == 0 and built["outcome"] == "built", built
    # GitHub shows what was pushed: the pull request the client opens is of that commit.
    pulls = client.token(REPOSITORY, {"contents": "write", "pull_requests": "write"})
    client.open_pull(pulls, REPOSITORY, branch="sortyard/R-1", base="main", title="R-1", body="")
    pull = client.find_pull(pulls, REPOSITORY, "sortyard/R-1")
    assert pull is not None and pull.open and pull.head == built["head"]
    # A reviewer's token reads; the scripted agent approves the head it was given.
    read = client.token(REPOSITORY, {"contents": "read", "pull_requests": "read"})
    status, reviewed = worker("review", "R-1", read.value)
    assert status == 0 and reviewed == {"outcome": "approved", "head": built["head"]}
    # The git host takes a token as GitHub would: a read token does not push, and a token
    # the App never minted does not even clone.
    status, refused = worker("build", "R-2", read.value)
    assert status == 1 and refused["outcome"] == "failed" and "push" in refused["reason"]
    status, refused = worker("build", "R-3", "ghs_" + "0" * 36)
    assert status == 1 and refused["outcome"] == "failed" and "clone" in refused["reason"]
    assert client.find_pull(pulls, REPOSITORY, "sortyard/R-2") is None

    assert client.merge(pulls, REPOSITORY, pull.number, pull.head, "squash")
    # What the replica's smoke test reads, without a credential.
    report = get_json(f"{url}/_fake/pull?repository={REPOSITORY}&branch=sortyard/R-1")
    assert report["merged"] is True and report["open"] is False and report["pushed"] is True
    assert report["head"] == built["head"]
    with pytest.raises(urllib.error.HTTPError) as missing:
        get_json(f"{url}/_fake/pull?repository={REPOSITORY}&branch=sortyard/R-2")
    assert missing.value.code == 404
    state = get_json(f"{url}/_fake/state")
    assert state["violations"] == [] and state["git"]["pushes"] == 1
    assert state["git"]["refused"] >= 2 and state["tokens"] == 3
    host.fake.verify()


@pytest.fixture
def api() -> Iterator[Any]:
    yield from running_api()


@requires_postgres
def test_the_replicas_admit_script_admits_an_item_through_the_api(
    api: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The replica's declaration (replica/bootstrap.toml) and replica/admit.py, run as the
    replica runs them in the API pod: `sortyard-api --bootstrap` makes the operator, and the
    script admits through the API's own door, which checks the item against its lanes."""
    module = load_module("replica_admit", REPLICA / "admit.py")
    script = SCRIPT.read_text()
    workspace, project, binding = (
        re.search(rf"^{name}=(\S+)$", script, re.MULTILINE).group(1)  # type: ignore[union-attr]
        for name in ("LANE_WORKSPACE", "LANE_PROJECT", "LANE_BINDING")
    )
    database = dict(part.split("=", 1) for part in api.conninfo.split())["dbname"]
    for name, value in {
        "SORTYARD_API_PORT": api.base.rsplit(":", 1)[1],
        "SORTYARD_DATABASE_HOST": os.environ["PGHOST"],
        "SORTYARD_DATABASE_PORT": os.environ.get("PGPORT", "5432"),
        "SORTYARD_DATABASE_NAME": database,
    }.items():
        monkeypatch.setenv(name, value)

    def stored(item: str) -> list[tuple[Any, ...]]:
        with api.db() as conn:
            rows: list[tuple[Any, ...]] = conn.execute(
                "SELECT s.lane, s.repository FROM sortyard.item AS i JOIN sortyard.item_spec AS s"
                " ON (s.workspace_id, s.item_id) = (i.workspace_id, i.id)"
                " WHERE i.workspace_id = %s AND i.id = %s",
                [workspace, item],
            ).fetchall()
        return rows

    def admit(item: str, lane: str = "example") -> int:
        code: int = module.main(
            ["admit.py", item, "example/app", lane, workspace, project, binding]
        )
        return code

    # The script makes no operator: before the bootstrap there is no binding to get a token for.
    with pytest.raises(ValueError):
        admit("replica-1-a")
    declaration = str(REPLICA / "bootstrap.toml")
    assert api_service.main(["--bootstrap", declaration]) == 0
    assert f"created role_binding {binding}" in capsys.readouterr().out.splitlines()
    # The API of the harness runs the shipped example lane.
    assert admit("replica-1-a") == 0
    assert capsys.readouterr().out.startswith("201 ")
    assert stored("replica-1-a") == [("example", "example/app")]
    # Again, as a second `replica.sh lane` does: nothing is made twice.
    assert api_service.main(["--bootstrap", declaration]) == 0
    assert all(line.startswith("unchanged ") for line in capsys.readouterr().out.splitlines())
    assert admit("replica-1-a") == 0
    assert capsys.readouterr().out.startswith("200 ")
    assert admit("replica-1-b") == 0
    # The API refuses what its lanes do not declare, and the script says so.
    assert admit("replica-1-c", "no-such-lane") == 1
    assert capsys.readouterr().out.rsplit("\n", 2)[-2].startswith("422 ")
    assert stored("replica-1-c") == []


def test_the_replica_gets_its_operator_from_the_bootstrap_command() -> None:
    """replica.sh makes the workspace, project and operator with `sortyard-api --bootstrap`
    before it admits, and neither it nor admit.py writes a row for them."""
    script = SCRIPT.read_text()
    lane = script.split("\nlane() {", 1)[1].split("\n}\n", 1)[0]
    assert "sortyard-api --bootstrap -" in script and '<"$ROOT/replica/bootstrap.toml"' in script
    assert re.search(r"^    bootstrap$", lane, re.MULTILINE)
    assert lane.index("\n    bootstrap\n") < lane.index('admit "$first"')
    for source in (script, (REPLICA / "admit.py").read_text()):
        assert "INSERT INTO" not in source and "ensure_workspace" not in source


@pytest.mark.skipif(
    not CLUSTER,
    reason="needs a booted replica: run `replica/replica.sh up`, then set "
    "SORTYARD_REPLICA_CLUSTER to its kind cluster's name (slow.yml does)",
)
def test_the_replica_admits_an_item_on_the_engine_on_postgres_and_sees_it_merged_then_again_after_the_kernel_pod_is_deleted_mid_item() -> (  # noqa: E501
    None
):
    """The replica admits an item on the engine on Postgres and sees it merged, then again
    after the kernel pod is deleted mid-item."""
    assert CLUSTER is not None
    kubectl = ["kubectl", "--context", f"kind-{CLUSTER}", "--namespace", "sortyard"]

    def deployment(name: str) -> dict[str, Any]:
        out = subprocess.run(
            [*kubectl, "get", "deployment", name, "-o", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        found: dict[str, Any] = json.loads(out)
        return found

    # The engine the kernel runs on stores to Postgres, and is the chart's.
    engine = {e["name"]: e for e in container_of(deployment("sortyard-engine"), "engine")["env"]}
    assert engine["DB"]["value"] == "postgres12"
    assert engine["POSTGRES_SEEDS"]["value"] == "sortyard-postgres"
    served = {e["name"]: e for e in container_of(deployment("sortyard-kernel"), "kernel")["env"]}
    assert served["SORTYARD_ENGINE_TARGET"]["value"] == "sortyard-engine:7233"

    done = subprocess.run(
        [str(SCRIPT), "lane"],
        env={**os.environ, "SORTYARD_REPLICA_CLUSTER": CLUSTER},
        capture_output=True,
        text=True,
        timeout=1500,
    )
    out = done.stdout
    assert done.returncode == 0, out[-3000:] + done.stderr[-6000:]
    # Two items, each merged in Sortyard (the script waited for that) and on GitHub, as a
    # pull request of the commit a worker Job pushed.
    merged = re.findall(r"^ +(replica-\d+-[ab]) merged: (\{.*\})$", out, re.MULTILINE)
    assert [item[-1] for item, _ in merged] == ["a", "b"], out
    for item, report in merged:
        told = json.loads(report)
        assert told["branch"] == f"sortyard/{item}"
        assert told["merged"] is True and told["pushed"] is True and told["open"] is False
    # The kernel pod was deleted while the second item was in work, and another pod took over.
    # Mid-item: the script read the item in `building` with its build Job running, then deleted
    # the pod (it fails before deleting otherwise).
    deleted = re.search(
        r"deleted (pod/\S+) with (\S+) in '([\w-]*)' \(worker Jobs running: (\d+)\)", out
    )
    assert deleted is not None, out
    assert deleted[2] == merged[1][0] and deleted[3] == "building" and int(deleted[4]) >= 1
    pods = subprocess.run(
        [*kubectl, "get", "pods", "-l", "app.kubernetes.io/component=kernel", "-o", "name"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.split()
    assert pods and deleted[1] not in pods
    assert "engine: 2 item workflows in Postgres" in out
