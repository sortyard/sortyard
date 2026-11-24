"""Acceptance: one command boots a local replica of the deployment's shape (corpus M1.1, §11).

`replica/replica.sh up` must
- check its prerequisites (tools and minimum versions) before it changes anything;
- deploy the chart itself, so topology, routing (Services) and auth shape (the Postgres
  password Secret, the shadow's read-only Plane API key Secret) are the deployment's own;
- fake only the outside third-party providers (Plane, the production conductor's pass log),
  and fake them faithfully enough that the real adapter (`PlaneSource`) reads them unchanged.

The full boot runs in CI (`slow.yml`, `replica` job, nightly) on a kind cluster; these tests
hold the parts that need no cluster.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
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

from sortyard.shadow import evaluate, sources

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
    assert set(values) <= {"shadow", "postgres", "image", "engine"}
    # The engine is switched on and nothing else: its images, store and settings are the chart's.
    assert values.get("engine", {"enabled": True}) == {"enabled": True}
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


@requires_helm
def test_replica_renders_the_deployment_topology_plus_the_shadow() -> None:
    default = {(d["kind"], d["metadata"]["name"]): d for d in helm_render()}
    replica = {
        (d["kind"], d["metadata"]["name"]): d
        for d in helm_render("-f", str(REPLICA / "values.yaml"), "--set", "image.tag=replica-x")
    }
    assert set(default) < set(replica)
    added = set(replica) - set(default)
    (schema_job,) = [name for kind, name in added if kind == "Job"]
    assert added == {
        ("Deployment", "sortyard-shadow-conductor"),
        ("Deployment", "sortyard-engine"),
        ("Service", "sortyard-engine"),
        ("ConfigMap", "sortyard-engine"),
        ("Job", schema_job),
    }
    # The API Deployment is the deployment's own, image tag aside.
    api_default = default[("Deployment", "sortyard-api")]
    api_replica = replica[("Deployment", "sortyard-api")]
    (c_default,) = api_default["spec"]["template"]["spec"]["containers"]
    (c_replica,) = api_replica["spec"]["template"]["spec"]["containers"]
    assert c_replica["image"] == "ghcr.io/sortyard/sortyard:replica-x"
    c_replica["image"] = c_default["image"]
    # ... and the address of the engine the replica switches on.
    (engine_target,) = [e for e in c_replica["env"] if e["name"] == "SORTYARD_ENGINE_TARGET"]
    assert engine_target["value"] == "sortyard-engine:7233"
    c_replica["env"].remove(engine_target)
    assert api_replica == api_default
    assert replica[("Service", "sortyard-api")] == default[("Service", "sortyard-api")]


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
