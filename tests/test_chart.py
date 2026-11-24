"""Acceptance: one Helm chart, one values file, deploys the API service + Postgres."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from sortyard.engine.testing import local_engine
from sortyard.kernel import policy
from sortyard.lane.jobs import DISPATCH_LABEL, ITEM_LABEL, KubeJobs
from sortyard.lane.worker import WorkerConfig, manifest
from sortyard.services import kernel, red_main
from sortyard.services.api import load_lanes
from tests import pg
from tests.chart_mounts import as_started, container_of, named
from tests.fake_github import PEM
from tests.fake_jobs import CONTRACT, FakeCluster
from tests.runtime_harness import LANE as LANE_TEXT
from tests.worker_harness import LANE, TOKEN

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHART = ROOT / "charts" / "sortyard"
HELM = shutil.which("helm")

if HELM is None:
    if os.environ.get("SORTYARD_REQUIRE_HELM"):
        raise RuntimeError("SORTYARD_REQUIRE_HELM is set but helm is not on PATH")
    pytestmark = pytest.mark.skip(reason="helm not on PATH (CI sets SORTYARD_REQUIRE_HELM)")


def render(*args: str, chart: pathlib.Path = CHART) -> list[dict[str, Any]]:
    assert HELM is not None
    out = subprocess.run(
        [HELM, "template", "sy", str(chart), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


def by_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [d for d in docs if d["kind"] == kind]


def test_one_values_file() -> None:
    assert [p.name for p in CHART.glob("values*.y*ml")] == ["values.yaml"]


def test_chart_lints() -> None:
    assert HELM is not None
    subprocess.run([HELM, "lint", "--strict", str(CHART)], check=True, capture_output=True)


def test_deploys_the_api_service() -> None:
    docs = render()
    (deploy,) = [d for d in by_kind(docs, "Deployment") if d["metadata"]["name"].endswith("-api")]
    (container,) = deploy["spec"]["template"]["spec"]["containers"]
    assert container["command"] == ["sortyard-api"]
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    env = {e["name"]: e for e in container["env"]}
    assert env["SORTYARD_DATABASE_HOST"]["value"] == "sy-sortyard-postgres"
    assert "secretKeyRef" in env["SORTYARD_DATABASE_PASSWORD"]["valueFrom"]
    services = {s["metadata"]["name"]: s for s in by_kind(docs, "Service")}
    assert services["sy-sortyard-api"]["spec"]["ports"][0]["port"] == 8080


def test_deploys_postgres_with_persistent_storage() -> None:
    docs = render()
    (sts,) = by_kind(docs, "StatefulSet")
    assert sts["metadata"]["name"] == "sy-sortyard-postgres"
    (container,) = sts["spec"]["template"]["spec"]["containers"]
    assert container["image"].startswith("postgres:")
    assert sts["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"]
    services = {s["metadata"]["name"]: s for s in by_kind(docs, "Service")}
    assert services["sy-sortyard-postgres"]["spec"]["ports"][0]["port"] == 5432
    (secret,) = by_kind(docs, "Secret")
    assert set(secret["data"]) == {"password"}


def test_deploys_nothing_else_yet() -> None:
    kinds = sorted(d["kind"] for d in render())
    assert kinds == [
        "ConfigMap",
        "Deployment",
        "Job",
        "Secret",
        "Service",
        "Service",
        "StatefulSet",
    ]


def test_external_postgres_drops_the_bundled_one() -> None:
    docs = render(
        "--set",
        "postgres.enabled=false",
        "--set",
        "postgres.external.host=db.example",
        "--set",
        "postgres.auth.existingSecret=pg",
    )
    assert by_kind(docs, "StatefulSet") == []
    assert by_kind(docs, "Secret") == []
    (deploy,) = by_kind(docs, "Deployment")
    env = {e["name"]: e for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["SORTYARD_DATABASE_HOST"]["value"] == "db.example"
    assert env["SORTYARD_DATABASE_PASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "pg"
    (job,) = by_kind(docs, "Job")
    job_env = {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert job_env["PGHOST"]["value"] == "db.example"
    assert job_env["PGPASSWORD"]["valueFrom"]["secretKeyRef"]["name"] == "pg"


def test_image_defaults_to_the_chart_app_version() -> None:
    app_version = yaml.safe_load((CHART / "Chart.yaml").read_text())["appVersion"]
    (deploy,) = by_kind(render(), "Deployment")
    image = deploy["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image == f"ghcr.io/sortyard/sortyard:{app_version}"


IMAGE_REPOSITORY = "registry.example/team/sortyard"
IMAGE_DIGEST = "sha256:" + "0123456789abcdef" * 4


def images(docs: list[dict[str, Any]]) -> dict[tuple[str, str, str], str]:
    """Every container of every rendered workload: (kind, name, container) to its image."""
    found: dict[tuple[str, str, str], str] = {}
    for doc in docs:
        pod = doc.get("spec", {}).get("template", {}).get("spec")
        if not isinstance(pod, dict):
            continue
        for made in [*pod.get("initContainers", []), *pod["containers"]]:
            found[(doc["kind"], doc["metadata"]["name"], made["name"])] = made["image"]
    return found


def test_with_a_digest_every_sortyard_container_is_named_by_it_and_none_by_tag(
    tmp_path: pathlib.Path,
) -> None:
    """Every workload the chart can render (API, shadow conductor, engine, kernel) is on; the
    Sortyard containers are the ones the render without a digest gives the Sortyard image."""
    everything = (
        *kernel_values(tmp_path),
        *SHADOW_SNAPSHOT,
        "--set",
        f"image.repository={IMAGE_REPOSITORY}",
        "--set",
        "image.tag=1.2.3",
    )
    by_tag = images(render(*everything))
    ours = {key for key, image in by_tag.items() if image.startswith(IMAGE_REPOSITORY)}
    assert {by_tag[key] for key in ours} == {f"{IMAGE_REPOSITORY}:1.2.3"}
    assert {(name, container) for _, name, container in ours} >= {
        ("sy-sortyard-api", "api"),
        ("sy-sortyard-kernel", "kernel"),
        ("sy-sortyard-kernel", "wait-engine"),
        ("sy-sortyard-shadow-conductor", "shadow-conductor"),
    }

    by_digest = images(render(*everything, "--set", f"image.digest={IMAGE_DIGEST}"))
    assert set(by_digest) == set(by_tag)
    for key, image in by_digest.items():
        if key in ours:
            assert image == f"{IMAGE_REPOSITORY}@{IMAGE_DIGEST}", key
        else:
            # Another image (Postgres, the engine's) is what it was, and is not ours renamed.
            assert image == by_tag[key] and "sortyard" not in image, key


@pytest.mark.parametrize(
    "digest",
    [
        "0123456789abcdef" * 4,  # no algorithm
        "sha256:" + "0123456789abcdef" * 3,  # short
        "sha256:" + "0123456789ABCDEF" * 4,  # upper case
        "sha256:" + "0123456789abcdef" * 4 + "0",  # long
        "sha512:" + "0123456789abcdef" * 8,
        "1.2.3",  # a tag
    ],
)
def test_a_malformed_image_digest_fails_the_render(digest: str) -> None:
    assert "image.digest" in render_fails("--set-string", f"image.digest={digest}")


@pytest.mark.parametrize("value", ["0", "false", "1", "true"])
def test_an_image_digest_that_is_not_a_string_fails_the_render_and_never_means_no_digest(
    value: str,
) -> None:
    # --set (not --set-string) gives the chart a number or a boolean.
    assert "image.digest" in render_fails("--set", f"image.digest={value}")
    render("--set", "image.digest=null")  # unset is the one other way to say "no digest"


def test_an_empty_image_digest_renders_the_image_by_tag_as_before(tmp_path: pathlib.Path) -> None:
    assert HELM is not None
    assert yaml.safe_load((CHART / "values.yaml").read_text())["image"]["digest"] == ""
    everything = (*kernel_values(tmp_path), *SHADOW_SNAPSHOT)

    def text(*args: str) -> str:
        argv = [HELM, "template", "sy", str(CHART), *everything, *args]
        return subprocess.run(argv, check=True, capture_output=True, text=True).stdout

    plain = text()
    assert text("--set", "image.digest=") == plain
    app_version = yaml.safe_load((CHART / "Chart.yaml").read_text())["appVersion"]
    ours = [image for image in images(render(*everything)).values() if "sortyard" in image]
    assert len(ours) >= 4 and set(ours) == {f"ghcr.io/sortyard/sortyard:{app_version}"}


def test_app_version_matches_the_package() -> None:
    from sortyard import __version__

    assert yaml.safe_load((CHART / "Chart.yaml").read_text())["appVersion"] == __version__


MIGRATIONS = CHART / "migrations"


def test_migrations_run_as_a_hook_job_on_install_and_upgrade() -> None:
    docs = render()
    (job,) = by_kind(docs, "Job")
    assert job["metadata"]["name"] == "sy-sortyard-migrate"
    annotations = job["metadata"]["annotations"]
    assert set(annotations["helm.sh/hook"].split(",")) == {"post-install", "post-upgrade"}
    assert "before-hook-creation" in annotations["helm.sh/hook-delete-policy"]
    pod = job["spec"]["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    (container,) = pod["containers"]
    assert container["image"].startswith("postgres:")
    assert container["command"] == ["sh", "/migrations/migrate.sh", "/migrations"]
    env = {e["name"]: e for e in container["env"]}
    assert env["PGHOST"]["value"] == "sy-sortyard-postgres"
    assert env["PGPORT"]["value"] == "5432"
    assert env["PGDATABASE"]["value"] == "sortyard"
    assert env["PGUSER"]["value"] == "sortyard"
    assert env["PGPASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "sy-sortyard-postgres",
        "key": "password",
    }
    (mount,) = container["volumeMounts"]
    assert mount["mountPath"] == "/migrations"
    (volume,) = pod["volumes"]
    assert volume["configMap"]["name"] == "sy-sortyard-migrations"


def test_the_job_ships_every_migration_verbatim() -> None:
    (cm,) = by_kind(render(), "ConfigMap")
    assert cm["metadata"]["name"] == "sy-sortyard-migrations"
    files = {p.name: p.read_text() for p in MIGRATIONS.iterdir()}
    assert "migrate.sh" in files
    assert any(name.endswith(".sql") for name in files)
    assert cm["data"] == files


SHADOW_SNAPSHOT = ("--set", "shadow.enabled=true", "--set", "shadow.snapshot=http://cp/board.json")


def shadow_deployment(docs: list[dict[str, Any]]) -> dict[str, Any]:
    (deploy,) = [d for d in by_kind(docs, "Deployment") if "shadow" in d["metadata"]["name"]]
    return deploy


def test_shadow_conductor_is_off_by_default() -> None:
    names = [d["metadata"]["name"] for d in by_kind(render(), "Deployment")]
    assert names == ["sy-sortyard-api"]


def test_shadow_conductor_runs_one_read_only_replica() -> None:
    deploy = shadow_deployment(render(*SHADOW_SNAPSHOT))
    assert deploy["metadata"]["name"] == "sy-sortyard-shadow-conductor"
    assert deploy["spec"]["replicas"] == 1
    assert deploy["spec"]["strategy"]["type"] == "Recreate"
    pod = deploy["spec"]["template"]["spec"]
    # No Kubernetes credentials: it touches nothing in the cluster.
    assert pod["automountServiceAccountToken"] is False
    (container,) = pod["containers"]
    assert container["command"] == ["sortyard-conductor", "--shadow", "--interval", "300"]
    env = {e["name"]: e for e in container["env"]}
    assert env["SORTYARD_SHADOW_SOURCE"]["value"] == "snapshot"
    assert env["SORTYARD_SHADOW_SNAPSHOT"]["value"] == "http://cp/board.json"
    assert env["SORTYARD_DATABASE_HOST"]["value"] == "sy-sortyard-postgres"
    assert "secretKeyRef" in env["SORTYARD_DATABASE_PASSWORD"]["valueFrom"]


def test_shadow_conductor_reads_plane_with_a_read_only_key_and_mounted_lanes() -> None:
    deploy = shadow_deployment(
        render(
            "--set",
            "shadow.enabled=true",
            "--set",
            "shadow.source=plane",
            "--set",
            "shadow.plane.url=https://plane.example",
            "--set",
            "shadow.plane.workspace=noncelogic",
            "--set",
            "shadow.plane.projects={p1,p2}",
            "--set",
            "shadow.plane.apiKeySecret=plane-read",
            "--set",
            "shadow.lanes.configMap=conductor-config",
            "--set",
            "shadow.plane.passes=http://cp/passes.json",
        )
    )
    pod = deploy["spec"]["template"]["spec"]
    (container,) = pod["containers"]
    env = {e["name"]: e for e in container["env"]}
    assert env["SORTYARD_SHADOW_PLANE_PROJECTS"]["value"] == "p1,p2"
    assert env["SORTYARD_SHADOW_PLANE_API_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "plane-read",
        "key": "api-key",
    }
    assert env["SORTYARD_SHADOW_LANES"]["value"] == "/lanes/products.json"
    # Plane reads are triggered by the production conductor's pass log.
    assert env["SORTYARD_SHADOW_PASSES"]["value"] == "http://cp/passes.json"
    (mount,) = container["volumeMounts"]
    assert mount == {"name": "lanes", "mountPath": "/lanes", "readOnly": True}
    (volume,) = pod["volumes"]
    assert volume["configMap"]["name"] == "conductor-config"


def test_shadow_conductor_refuses_to_render_without_an_input_path() -> None:
    assert HELM is not None
    proc = subprocess.run(
        [HELM, "template", "sy", str(CHART), "--set", "shadow.enabled=true"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "shadow.snapshot is required" in proc.stderr


# --- the workflow engine server (SY-V3-CHART-ENGINE) -------------------------------------------

ENGINE = ("--set", "engine.enabled=true")
EXTERNAL_ENGINE_DATABASE = (
    *ENGINE,
    "--set",
    "engine.database.host=pg.example",
    "--set",
    "engine.database.username=engine",
    "--set",
    "engine.database.existingSecret=engine-db",
)
# Every setting name the server image reads for a store that is not Postgres.
NO_DIGESTS = ("--set", "engine.image.digest=", "--set", "engine.toolsImage.digest=")


def version(tag: str) -> tuple[str, ...]:
    """The values of a move to another engine version: both tags, and no stale digest."""
    return (
        "--set",
        f"engine.image.tag={tag}",
        "--set",
        f"engine.toolsImage.tag={tag}",
        *NO_DIGESTS,
    )


OTHER_STORES = ("CASSANDRA", "KEYSPACE", "MYSQL", "SQLITE", "ENABLE_ES", "ES_")


def component(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    (doc,) = [
        d
        for d in by_kind(docs, kind)
        if d["metadata"]["labels"]["app.kubernetes.io/component"] == name
    ]
    return doc


def containers(workload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pod = workload["spec"]["template"]["spec"]
    return {c["name"]: c for c in pod.get("initContainers", []) + pod["containers"]}


def env_of(container: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["name"]: e for e in container["env"]}


def render_fails(*args: str) -> str:
    assert HELM is not None
    proc = subprocess.run(
        [HELM, "template", "sy", str(CHART), *args], capture_output=True, text=True
    )
    assert proc.returncode != 0, "rendered"
    return proc.stderr


def test_engine_enabled_renders_the_server_on_postgres_its_schema_job_and_its_service_and_points_the_api_at_it() -> (  # noqa: E501
    None
):
    """engine.enabled renders the server on Postgres, its schema Job and its Service, and
    points the API at it."""
    values = yaml.safe_load((CHART / "values.yaml").read_text())["engine"]
    docs = render(*ENGINE)

    # The server: the pinned upstream image, storing to the chart's Postgres and nothing else.
    server = containers(component(docs, "Deployment", "engine"))
    engine = server["engine"]
    assert engine["image"] == (
        f"temporalio/server:{values['image']['tag']}@{values['image']['digest']}"
    )
    env = env_of(engine)
    assert env["DB"]["value"] == "postgres12"
    assert env["POSTGRES_SEEDS"]["value"] == "sy-sortyard-postgres"
    assert env["DB_PORT"]["value"] == "5432"
    assert env["POSTGRES_USER"]["value"] == "sortyard"
    assert env["POSTGRES_PWD"]["valueFrom"]["secretKeyRef"] == {
        "name": "sy-sortyard-postgres",
        "key": "password",
    }
    assert env["DBNAME"]["value"] != env["VISIBILITY_DBNAME"]["value"]
    assert engine["securityContext"]["readOnlyRootFilesystem"] is True

    # One Service, in front of the server, and the API pointed at it.
    (service,) = [s for s in by_kind(docs, "Service") if "engine" in s["metadata"]["name"]]
    assert service["metadata"]["name"] == "sy-sortyard-engine"
    (port,) = service["spec"]["ports"]
    assert port["port"] == 7233
    assert port["targetPort"] in [p["name"] for p in engine["ports"] if p["containerPort"] == 7233]
    pod_labels = component(docs, "Deployment", "engine")["spec"]["template"]["metadata"]["labels"]
    assert service["spec"]["selector"].items() <= pod_labels.items()
    api = env_of(containers(component(docs, "Deployment", "api"))["api"])
    assert api["SORTYARD_ENGINE_TARGET"]["value"] == "sy-sortyard-engine:7233"

    # The schema Job: the upstream schema tool of the same version, against the same databases.
    job = component(docs, "Job", "engine-schema")
    steps = containers(job)
    schema = steps["schema"]
    assert schema["image"] == (
        f"temporalio/admin-tools:{values['toolsImage']['tag']}@{values['toolsImage']['digest']}"
    )
    assert values["toolsImage"]["tag"] == values["image"]["tag"]
    assert schema["command"] == ["sh", "/engine/setup.sh", "schema"]
    schema_env = env_of(schema)
    assert schema_env["SQL_HOST"]["value"] == env["POSTGRES_SEEDS"]["value"]
    assert schema_env["SQL_PASSWORD"]["valueFrom"] == env["POSTGRES_PWD"]["valueFrom"]
    assert schema_env["SORTYARD_ENGINE_DATABASE"]["value"] == env["DBNAME"]["value"]
    assert (
        schema_env["SORTYARD_ENGINE_VISIBILITY_DATABASE"]["value"]
        == env["VISIBILITY_DBNAME"]["value"]
    )
    # The script the Job runs is the chart's file, byte for byte.
    config = component(docs, "ConfigMap", "engine")
    assert config["data"]["setup.sh"] == (CHART / "engine" / "setup.sh").read_text()
    (volume,) = [v for v in job["spec"]["template"]["spec"]["volumes"] if "configMap" in v]
    assert volume["configMap"]["name"] == config["metadata"]["name"]


def test_the_engine_stores_to_postgres_only() -> None:
    """must_catch: an engine store other than Postgres rendered."""
    for args in (ENGINE, EXTERNAL_ENGINE_DATABASE):
        docs = render(*args)
        workloads = [
            component(docs, "Deployment", "engine"),
            component(docs, "Job", "engine-schema"),
        ]
        for workload in workloads:
            for container in containers(workload).values():
                names = set(env_of(container))
                assert not [n for n in names if n.startswith(OTHER_STORES)], names
                assert not names & {"VISIBILITY_POSTGRES_SEEDS", "VISIBILITY_DB_PORT"}
        env = env_of(containers(component(docs, "Deployment", "engine"))["engine"])
        # One plugin serves both stores: persistence and visibility are the same Postgres.
        assert env["DB"]["value"] == "postgres12"
    script = (CHART / "engine" / "setup.sh").read_text()
    assert "--plugin postgres12" in script
    assert "cassandra" not in script and "elasticsearch" not in script


def test_the_engine_server_waits_for_the_schema_job_of_its_own_version() -> None:
    """must_catch: the server rendered without its schema Job, or the Job not safe to run
    twice (that it is safe on a real Postgres is the slow workflow's to show)."""
    docs = render(*ENGINE, *version("9.9.9"))
    assert component(docs, "Job", "engine-schema")["metadata"]["name"].startswith(
        "sy-sortyard-engine-schema-"
    )
    server = containers(component(docs, "Deployment", "engine"))
    assert server["engine"]["image"] == "temporalio/server:9.9.9"
    assert containers(component(docs, "Job", "engine-schema"))["schema"]["image"] == (
        "temporalio/admin-tools:9.9.9"
    )
    # The server's pod starts with a wait for the record the Job writes for this version.
    assert list(server) == ["wait-schema", "engine"]
    wait = server["wait-schema"]
    assert wait["command"] == ["sh", "/engine/setup.sh", "wait-schema"]
    job = component(docs, "Job", "engine-schema")
    schema = containers(job)["schema"]
    assert (
        env_of(wait)["SORTYARD_ENGINE_SERVER_VERSION"]["value"]
        == env_of(schema)["SORTYARD_ENGINE_SERVER_VERSION"]["value"]
        == "9.9.9"
    )
    assert (
        env_of(wait)["PGDATABASE"]["value"] == env_of(schema)["SORTYARD_ENGINE_DATABASE"]["value"]
    )
    assert "'9.9.9'" in component(docs, "ConfigMap", "engine")["data"]["mark.sql"]
    # An ordinary Job, not a hook: `helm upgrade --wait` waits for the server, which waits for
    # the Job, so a hook that runs after the wait would never start.
    assert "helm.sh/hook" not in job["metadata"].get("annotations", {})
    assert job["spec"]["template"]["spec"]["restartPolicy"] == "Never"
    # Named by what it does: a new server version is a new Job (a Job cannot be changed in
    # place), and an upgrade that changes nothing of the engine's leaves it alone.
    name = job["metadata"]["name"]
    same = render(*ENGINE, *version("9.9.9"), "--set", "api.replicas=2")
    newer = render(*ENGINE, *version("9.9.10"))
    assert component(same, "Job", "engine-schema")["metadata"]["name"] == name
    assert component(newer, "Job", "engine-schema")["metadata"]["name"] != name
    # Nothing in the script drops or overwrites what is there.
    script = (CHART / "engine" / "setup.sh").read_text()
    assert "--overwrite" not in script and "drop" not in script.replace("drops", "")


def test_no_database_password_is_rendered_outside_the_secret() -> None:
    """must_catch: a database password rendered into a manifest instead of a Secret reference."""
    assert HELM is not None
    password = "pw-3f9a7c51d2"
    out = subprocess.run(
        [
            HELM,
            "template",
            "sy",
            str(CHART),
            *ENGINE,
            "--set",
            f"postgres.auth.password={password}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    docs = [doc for doc in yaml.safe_load_all(out) if doc]
    (secret,) = by_kind(docs, "Secret")
    others = yaml.safe_dump_all([d for d in docs if d["kind"] != "Secret"])
    assert password not in others and secret["data"]["password"] not in others
    # Every password setting of an engine container is a reference, never a value.
    for workload in (
        component(docs, "Deployment", "engine"),
        component(docs, "Job", "engine-schema"),
    ):
        for container in containers(workload).values():
            for name, entry in env_of(container).items():
                if "PASSWORD" in name or "PWD" in name:
                    assert set(entry["valueFrom"]) == {"secretKeyRef"}, name


def test_the_engine_takes_an_external_postgres_by_secret_reference() -> None:
    """must_allow: an external Postgres such as an operator-managed cluster."""
    docs = render(*EXTERNAL_ENGINE_DATABASE, "--set", "engine.database.create=false")
    server = containers(component(docs, "Deployment", "engine"))
    job = containers(component(docs, "Job", "engine-schema"))
    env = env_of(server["engine"])
    assert env["POSTGRES_SEEDS"]["value"] == "pg.example"
    assert env["POSTGRES_USER"]["value"] == "engine"
    for container, name in (
        (server["engine"], "POSTGRES_PWD"),
        (server["wait-schema"], "PGPASSWORD"),
        (job["schema"], "SQL_PASSWORD"),
    ):
        assert env_of(container)[name]["valueFrom"]["secretKeyRef"] == {
            "name": "engine-db",
            "key": "password",
        }
    assert env_of(job["schema"])["SQL_HOST"]["value"] == "pg.example"
    # An operator-managed cluster hands out databases; the Job is told not to create them.
    assert env_of(job["schema"])["SORTYARD_ENGINE_CREATE_DATABASES"]["value"] == "false"
    # The API keeps the chart's own Postgres.
    api = env_of(containers(component(docs, "Deployment", "api"))["api"])
    assert api["SORTYARD_DATABASE_HOST"]["value"] == "sy-sortyard-postgres"

    # The other external shape: the whole chart on one external server.
    shared = render(
        *ENGINE,
        "--set",
        "postgres.enabled=false",
        "--set",
        "postgres.external.host=db.example",
        "--set",
        "postgres.auth.existingSecret=pg",
    )
    env = env_of(containers(component(shared, "Deployment", "engine"))["engine"])
    assert env["POSTGRES_SEEDS"]["value"] == "db.example"
    assert env["POSTGRES_PWD"]["valueFrom"]["secretKeyRef"]["name"] == "pg"
    assert by_kind(shared, "Secret") == []


def test_rendering_fails_when_the_external_database_secret_reference_is_missing() -> None:
    """Rendering fails when the external database Secret reference is missing."""
    own = ("--set", "engine.database.host=pg.example", "--set", "engine.database.username=engine")
    assert "engine.database.existingSecret is required" in render_fails(*ENGINE, *own)
    shared = ("--set", "postgres.enabled=false", "--set", "postgres.external.host=db.example")
    assert "postgres.auth.existingSecret is required" in render_fails(*ENGINE, *shared)
    # The same values render once the reference is there, and with the engine off.
    render(*ENGINE, *own, "--set", "engine.database.existingSecret=engine-db")
    render(*ENGINE, *shared, "--set", "postgres.auth.existingSecret=pg")
    render(*shared)


def test_an_engine_image_must_be_pinned_to_a_version() -> None:
    for moving in ("latest", "main", "1.32", ""):
        both = ("--set", f"engine.image.tag={moving}", "--set", f"engine.toolsImage.tag={moving}")
        assert "pinned" in render_fails(*ENGINE, *both, *NO_DIGESTS), moving
    values = yaml.safe_load((CHART / "values.yaml").read_text())["engine"]
    for image in ("image", "toolsImage"):
        assert values[image]["digest"].startswith("sha256:") and len(values[image]["digest"]) == 71


def test_engine_enabled_false_renders_the_same_manifests_as_before() -> None:
    """engine.enabled false renders the same manifests as before."""
    assert HELM is not None

    def text(*args: str) -> str:
        return subprocess.run(
            [HELM, "template", "sy", str(CHART), "--set", "postgres.auth.password=x", *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    default = text()
    assert yaml.safe_load((CHART / "values.yaml").read_text())["engine"]["enabled"] is False
    # With the engine off no engine setting reaches a manifest: the render is the same text
    # whatever they are, so it is what the chart rendered before it had an engine.
    inert = text(
        "--set",
        "engine.enabled=false",
        "--set",
        "engine.image.tag=9.9.9",
        "--set",
        "engine.database.host=pg.example",
        "--set",
        "engine.database.existingSecret=unused",
        "--set",
        "engine.namespace.retention=1d",
        "--set",
        "engine.service.port=1",
    )
    assert inert == default
    # And that render is the manifests the chart had before the engine, with nothing of the
    # engine's in them: the same objects, the same API settings.
    docs = [doc for doc in yaml.safe_load_all(default) if doc]
    assert sorted((d["kind"], d["metadata"]["name"]) for d in docs) == [
        ("ConfigMap", "sy-sortyard-migrations"),
        ("Deployment", "sy-sortyard-api"),
        ("Job", "sy-sortyard-migrate"),
        ("Secret", "sy-sortyard-postgres"),
        ("Service", "sy-sortyard-api"),
        ("Service", "sy-sortyard-postgres"),
        ("StatefulSet", "sy-sortyard-postgres"),
    ]
    (api,) = by_kind(docs, "Deployment")
    assert [e["name"] for e in api["spec"]["template"]["spec"]["containers"][0]["env"]] == [
        "SORTYARD_API_PORT",
        "SORTYARD_DATABASE_HOST",
        "SORTYARD_DATABASE_PORT",
        "SORTYARD_DATABASE_NAME",
        "SORTYARD_DATABASE_USER",
        "SORTYARD_DATABASE_PASSWORD",
    ]
    without_migrations = yaml.safe_dump_all([d for d in docs if d["kind"] != "ConfigMap"])
    assert "engine" not in without_migrations.lower()
    assert "temporal" not in without_migrations.lower()
    # Every object the engine adds is its own; switching it on changes one existing object,
    # the API Deployment, by the one setting that points it at the engine.
    on = {
        (d["kind"], d["metadata"]["name"]): d
        for d in yaml.safe_load_all(text("--set", "engine.enabled=true"))
        if d
    }
    off = {(d["kind"], d["metadata"]["name"]): d for d in docs}
    assert [key for key in off if on[key] != off[key]] == [("Deployment", "sy-sortyard-api")]


def test_whatever_changes_the_schema_job_changes_its_name(tmp_path: pathlib.Path) -> None:
    """A Job's pod template cannot be changed in place, so `helm upgrade` is refused when a
    Job keeps its name and changes its spec. Over every value that reaches the Job, and a chart
    version bump: two renders with the same Job name have the same Job."""
    bumped = tmp_path / "sortyard"
    shutil.copytree(CHART, bumped)
    chart_yaml = yaml.safe_load((bumped / "Chart.yaml").read_text())
    chart_yaml["version"] = "99.0.0"
    (bumped / "Chart.yaml").write_text(yaml.safe_dump(chart_yaml))
    script = tmp_path / "script" / "sortyard"
    shutil.copytree(CHART, script)
    with (script / "engine" / "setup.sh").open("a") as setup:
        setup.write("# changed\n")

    variants: dict[str, list[dict[str, Any]]] = {
        "default": render(*ENGINE),
        "unrelated": render(*ENGINE, "--set", "api.replicas=3", "--set", "engine.replicas=2"),
        "chart version": render(*ENGINE, chart=bumped),
        "script": render(*ENGINE, chart=script),
        "engine version": render(*ENGINE, *version("9.9.9")),
        "external": render(*EXTERNAL_ENGINE_DATABASE),
    }
    for value in (
        "engine.schema.waitSeconds=7",
        "engine.schema.backoffLimit=9",
        "engine.schema.activeDeadlineSeconds=77",
        "engine.schema.ttlSecondsAfterFinished=7",
        "engine.schema.resources.limits.memory=300Mi",
        "engine.schema.resources.requests.cpu=11m",
        "engine.toolsImage.pullPolicy=Always",
        "engine.toolsImage.repository=mirror.example/admin-tools",
        "engine.toolsImage.digest=",
        "imagePullSecrets[0].name=pull",
        "engine.namespace.retention=3d",
        "engine.service.port=7000",
        "engine.database.name=other",
        "engine.database.visibilityName=other_visibility",
        "engine.database.create=false",
        "postgres.auth.username=someone",
    ):
        variants[value] = render(*ENGINE, "--set", value)

    def job(docs: list[dict[str, Any]]) -> tuple[str, dict[str, Any], dict[str, str]]:
        doc = component(docs, "Job", "engine-schema")
        files = component(docs, "ConfigMap", "engine")["data"]
        mounted = {name: files[name] for name in ("setup.sh", "mark.sql")}
        return doc["metadata"]["name"], doc["spec"], mounted

    default_name, default_spec, default_files = job(variants["default"])
    names: dict[str, tuple[dict[str, Any], dict[str, str]]] = {}
    for label, docs in variants.items():
        name, spec, files = job(docs)
        assert names.setdefault(name, (spec, files)) == (spec, files), label
        # Each of these does change the Job or what it runs, so each must have changed the name;
        # the unrelated values change neither.
        changed = (spec, files) != (default_spec, default_files)
        assert changed == (label not in ("default", "unrelated")), label
        assert (name != default_name) == changed, label


def test_a_failed_schema_job_needs_no_hand_to_recover() -> None:
    """A finished Job is removed after its ttl, so the next install or upgrade makes it again,
    and the server's wait for it has a limit, after which the pod fails visibly and retries."""
    docs = render(*ENGINE, "--set", "engine.schema.waitSeconds=120")
    job = component(docs, "Job", "engine-schema")
    assert job["spec"]["ttlSecondsAfterFinished"] > 0
    assert job["spec"]["activeDeadlineSeconds"] > 0
    wait = containers(component(docs, "Deployment", "engine"))["wait-schema"]
    assert env_of(wait)["SORTYARD_ENGINE_WAIT_SECONDS"]["value"] == "120"


@pytest.fixture
def engine_database() -> Iterator[pg.Database]:
    yield from pg.fresh_database()


@pg.requires_postgres
def test_the_server_waits_for_the_schema_record_and_gives_up_at_its_limit(
    engine_database: pg.Database,
) -> None:
    """The init container's command, run for real: it returns once the record the schema Job
    writes for its version is there, and without it fails at its limit instead of waiting on."""
    setup = CHART / "engine" / "setup.sh"
    mark = component(render(*ENGINE), "ConfigMap", "engine")["data"]["mark.sql"]
    tag = yaml.safe_load((CHART / "values.yaml").read_text())["engine"]["image"]["tag"]

    def wait(server_version: str) -> subprocess.CompletedProcess[str]:
        env = {
            **engine_database.env,
            "SORTYARD_ENGINE_SERVER_VERSION": server_version,
            "SORTYARD_ENGINE_WAIT_SECONDS": "2",
        }
        return subprocess.run(
            ["sh", str(setup), "wait-schema"], env=env, capture_output=True, text=True, timeout=60
        )

    started = time.monotonic()
    missing = wait(tag)
    assert missing.returncode != 0 and tag in missing.stderr
    assert time.monotonic() - started < 30
    # The Job's record, written twice (the Job is safe to run again): the wait is over.
    engine_database.run(mark)
    engine_database.run(mark)
    assert engine_database.value("SELECT server_version FROM sortyard_engine_schema") == tag
    assert wait(tag).returncode == 0
    # A record for one version is not a record for the next: an upgraded server still waits.
    assert wait("99.0.0").returncode != 0


def test_the_engine_images_move_together() -> None:
    """The schema tool carries the schema of its own server version, and a digest pins one
    version: a server tag without its tools tag, or a new tag under the old digest, is refused."""
    assert "must be engine.image.tag" in render_fails(
        *ENGINE, "--set", "engine.image.tag=1.33.0", *NO_DIGESTS
    )
    assert "must be engine.image.tag" in render_fails(
        *ENGINE, "--set", "engine.toolsImage.tag=1.33.0", *NO_DIGESTS
    )
    both = ("--set", "engine.image.tag=1.33.0", "--set", "engine.toolsImage.tag=1.33.0")
    for stale in ("engine.toolsImage.digest=", "engine.image.digest="):
        # One digest cleared, the other still the default version's.
        assert "digest" in render_fails(*ENGINE, *both, "--set", stale)
    assert "digest" in render_fails(*ENGINE, *both)
    new = "sha256:" + "ab" * 32
    docs = render(
        *ENGINE,
        *both,
        "--set",
        f"engine.image.digest={new}",
        "--set",
        f"engine.toolsImage.digest={new}",
    )
    server = containers(component(docs, "Deployment", "engine"))["engine"]
    assert server["image"] == f"temporalio/server:1.33.0@{new}"
    render(*ENGINE, *version("1.33.0"))


def test_engine_database_settings_that_would_be_ignored_are_refused() -> None:
    for ignored in ("engine.database.username=engine", "engine.database.existingSecret=engine-db"):
        assert "engine.database.host" in render_fails(*ENGINE, "--set", ignored)


# --- the kernel service (SY-V3-CHART-KERNEL) ----------------------------------------------------

NAMESPACE = "release-ns"
# A fixed password, so that two renders differ only in what the test changes.
RELEASE = ("--namespace", NAMESPACE, "--set", "postgres.auth.password=x")
AGENTS = {
    "build": ["agent", "--build", 'say "hi" <now>'],
    "fix": ["agent", "--fix"],
    "review": ["agent", "--review"],
}
# What a release holds beside the chart: the Secrets its values refer to.
APP_SECRET = {"github-app": {"private-key.pem": PEM.decode()}}
RULE = """version = 1
[[rules]]
state = "building"
outcome = "no-change"
answer = "wait"
reverse = "Send the item a decision request with the answer rebuild."
"""
# The resources the ticket names for the worker Role; it may grant among these and no others.
NAMED_RESOURCES = {
    ("batch", "jobs"),
    ("", "pods"),
    ("", "pods/log"),
    ("", "configmaps"),
    ("", "secrets"),
}


def merged(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        both = isinstance(value, dict) and isinstance(out.get(key), dict)
        out[key] = merged(out[key], value) if both else value
    return out


def kernel_values(tmp_path: pathlib.Path, **over: Any) -> tuple[str, ...]:
    """The arguments of a render with the kernel on: the engine, one lane, the agent commands
    and the GitHub App, with `over` laid on top of the kernel's values (or, for a key that is
    not the kernel's, on the chart's)."""
    top = {key: over.pop(key) for key in list(over) if key in ("postgres", "engine", "shadow")}
    values = {
        "engine": {"enabled": True},
        "kernel": merged(
            {
                "enabled": True,
                "lanes": {"walwarden": LANE_TEXT},
                "worker": {"agents": AGENTS},
                "github": {"appId": "4242", "appKeySecret": "github-app"},
            },
            over,
        ),
    }
    path = tmp_path / f"values-{len(list(tmp_path.glob('values-*')))}.yaml"
    path.write_text(yaml.safe_dump(merged(values, top)))
    return (*RELEASE, "-f", str(path))


def keyed(docs: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(d["kind"], d["metadata"]["name"]): d for d in docs}


def test_kernel_enabled_renders_the_engine_on_postgres_the_kernel_deployment_and_the_worker_role_and_nothing_else_new(  # noqa: E501
    tmp_path: pathlib.Path,
) -> None:
    """kernel.enabled renders the engine on Postgres, the kernel Deployment and the worker Role
    and nothing else new."""
    docs = render(*kernel_values(tmp_path))
    on, engine_only = keyed(docs), keyed(render(*RELEASE, *ENGINE))
    # The engine on Postgres is there, as the chart renders it without the kernel.
    server = env_of(containers(component(docs, "Deployment", "engine"))["engine"])
    assert server["DB"]["value"] == "postgres12"
    assert (
        on[("Deployment", "sy-sortyard-engine")]
        == engine_only[("Deployment", "sy-sortyard-engine")]
    )
    # What the kernel adds: its Deployment and service account, the Role and its binding, and
    # the two ConfigMaps of files. Nothing else is new.
    assert set(on) - set(engine_only) == {
        ("Deployment", "sy-sortyard-kernel"),
        ("ServiceAccount", "sy-sortyard-kernel"),
        ("Role", "sy-sortyard-kernel"),
        ("RoleBinding", "sy-sortyard-kernel"),
        ("ConfigMap", "sy-sortyard-kernel"),
        ("ConfigMap", "sy-sortyard-lanes"),
    }
    assert set(engine_only) <= set(on)
    # One existing object changes: the API, which is given the lane files to admit against.
    assert [key for key in engine_only if on[key] != engine_only[key]] == [
        ("Deployment", "sy-sortyard-api")
    ]

    deploy = on[("Deployment", "sy-sortyard-kernel")]
    assert deploy["spec"]["replicas"] == 1 and deploy["spec"]["strategy"] == {"type": "Recreate"}
    pod = deploy["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "sy-sortyard-kernel"
    assert pod["securityContext"] == {"runAsNonRoot": True, "runAsUser": 10001}
    made = container_of(deploy, "kernel")
    assert made["command"] == ["sortyard-kernel"]
    assert made["image"] == container_of(on[("Deployment", "sy-sortyard-api")], "api")["image"]
    assert made["securityContext"]["readOnlyRootFilesystem"] is True
    # Connected to the engine the chart renders, and to the API's database.
    api = env_of(container_of(on[("Deployment", "sy-sortyard-api")], "api"))
    env = env_of(made)
    assert env["SORTYARD_ENGINE_TARGET"]["value"] == api["SORTYARD_ENGINE_TARGET"]["value"]
    assert env["SORTYARD_ENGINE_TARGET"]["value"] == "sy-sortyard-engine:7233"
    for name in (n for n in api if n.startswith("SORTYARD_DATABASE_")):
        assert env[name] == api[name], name

    # The service starts on what the Deployment gives it: every required setting is there and
    # every file it names is mounted. Read by the service's own settings loader.
    secrets = {**APP_SECRET, "sy-sortyard-postgres": {"password": "a-database-password"}}
    started = as_started(docs, deploy, "kernel", tmp_path, secrets)
    assert set(kernel.REQUIRED) <= set(started)
    in_cluster = {**started, "KUBERNETES_SERVICE_HOST": "10.96.0.1"}  # what a pod is given
    settings = kernel.Settings.from_env(in_cluster)
    kernel.assemble(replace_jobs_free(settings))  # the App key loads
    assert set(settings.lanes) == {"walwarden"} and settings.lanes["walwarden"].slots == 2
    assert settings.worker.agents == AGENTS
    assert settings.engine_target == "sy-sortyard-engine:7233"
    assert settings.jobs_namespace == NAMESPACE and settings.kube_url is None
    assert settings.decisions == policy.shipped() and "SORTYARD_DECISION_POLICY" not in started
    # ... and the API admits against the same lane files.
    api_started = as_started(docs, on[("Deployment", "sy-sortyard-api")], "api", tmp_path, secrets)
    assert load_lanes(api_started["SORTYARD_LANES_DIR"]) == settings.lanes
    # The pod's own token is its cluster access here, and only here.
    assert pod["automountServiceAccountToken"] is True
    assert "SORTYARD_KUBE_URL" not in started


def replace_jobs_free(settings: kernel.Settings) -> kernel.Settings:
    """The settings with a named API server, so that assembling reads no pod files."""
    from dataclasses import replace

    return replace(settings, kube_url="http://kube.invalid", kube_token_file=os.devnull)


def test_the_lane_files_the_decision_policy_and_the_worker_configuration_are_values_mounted_as_files(  # noqa: E501
    tmp_path: pathlib.Path,
) -> None:
    """Every value reaches the service through a mounted file, and a change to one starts a new
    pod."""
    second = LANE_TEXT.replace('lane = "walwarden"', 'lane = "other"')
    over = {
        "lanes": {"walwarden": LANE_TEXT, "other": second},
        "decisionPolicy": RULE,
        "observerIntervalSeconds": 3,
        "worker": {
            "gitUrl": "http://git.test/{repository}.git",
            "command": ["sortyard-worker", "--as-configured"],
            "deadlineSeconds": 900,
            "ttlSeconds": 60,
            "tokenAgeSeconds": 120,
            "secrets": {"MODEL_API_KEY": {"secret": "models", "key": "api-key"}},
            "services": {"cluster-api": "http://cluster-api.test/healthz"},
        },
        "github": {"apiUrl": "http://github.test", "appKeySecretKey": "app.pem"},
    }
    docs = render(*kernel_values(tmp_path, **over))
    deploy = named(docs, "Deployment", "sy-sortyard-kernel")
    secrets = {
        "github-app": {"app.pem": PEM.decode()},
        "sy-sortyard-postgres": {"password": "pw"},
    }
    started = as_started(docs, deploy, "kernel", tmp_path, secrets)
    settings = kernel.Settings.from_env({**started, "KUBERNETES_SERVICE_HOST": "10.96.0.1"})
    assert set(settings.lanes) == {"walwarden", "other"}
    assert settings.decisions == policy.load(RULE) and settings.interval == 3
    assert settings.worker == WorkerConfig(
        agents=AGENTS,
        git_url="http://git.test/{repository}.git",
        secrets={"MODEL_API_KEY": ("models", "api-key")},
        services={"cluster-api": "http://cluster-api.test/healthz"},
        command=["sortyard-worker", "--as-configured"],
        deadline=900,
        ttl=60,
        token_age=120,
    )
    assert settings.github_api_url == "http://github.test"
    assert settings.github_app_key == PEM
    # The files are ConfigMaps of the release, mounted read-only.
    mounts = {m["name"]: m for m in container_of(deploy, "kernel")["volumeMounts"]}
    assert mounts["lanes"]["readOnly"] and mounts["kernel"]["readOnly"]
    assert set(named(docs, "ConfigMap", "sy-sortyard-lanes")["data"]) == {
        "walwarden.toml",
        "other.toml",
    }

    # A pod reads its files once: a changed file is a changed pod template, for the kernel and
    # for the API that admits against the lanes.
    def stamps(rendered: list[dict[str, Any]]) -> tuple[str, str]:
        both = [
            named(rendered, "Deployment", name)["spec"]["template"]["metadata"]["annotations"]
            for name in ("sy-sortyard-kernel", "sy-sortyard-api")
        ]
        return both[0]["checksum/files"], both[1]["checksum/lanes"]

    base = stamps(docs)
    assert stamps(render(*kernel_values(tmp_path, **over))) == base
    lane_changed = {**over, "lanes": {"walwarden": LANE_TEXT.replace("slots = 2", "slots = 3")}}
    assert all(
        a != b
        for a, b in zip(stamps(render(*kernel_values(tmp_path, **lane_changed))), base, strict=True)
    )
    for changed in ({"decisionPolicy": ""}, {"worker": {"deadlineSeconds": 901}}):
        kernel_stamp, api_stamp = stamps(render(*kernel_values(tmp_path, **merged(over, changed))))
        assert kernel_stamp != base[0] and api_stamp == base[1], changed


def test_rendering_fails_when_a_required_secret_reference_is_missing(
    tmp_path: pathlib.Path,
) -> None:
    """Rendering fails when a required Secret reference is missing."""
    # must_catch: the kernel rendered with a missing required Secret reference. Its three
    # credentials: the GitHub App key, the database password, the worker cluster's access.
    missing: dict[str, dict[str, Any]] = {
        "kernel.github.appKeySecret is required": {"github": {"appKeySecret": ""}},
        "kernel.github.appKeySecretKey is required": {"github": {"appKeySecretKey": ""}},
        "postgres.auth.existingSecret is required": {
            "postgres": {"enabled": False, "external": {"host": "db.example"}},
            # The engine on its own database, so that only the kernel's reference is missing.
            "engine": {
                "enabled": True,
                "database": {"host": "pg.example", "username": "e", "existingSecret": "engine-db"},
            },
        },
        "kernel.workers.clusterSecret is required": {"workers": {"sameCluster": False}},
    }
    for message, over in missing.items():
        assert message in render_fails(*kernel_values(tmp_path, **over)), message
    # Each renders once its reference is there.
    render(*kernel_values(tmp_path, github={"appKeySecretKey": "key.pem"}))
    external = merged(
        missing["postgres.auth.existingSecret is required"],
        {"postgres": {"auth": {"existingSecret": "pg"}}},
    )
    docs = render(*kernel_values(tmp_path, **external))
    password = env_of(container_of(named(docs, "Deployment", "sy-sortyard-kernel"), "kernel"))[
        "SORTYARD_DATABASE_PASSWORD"
    ]
    assert password["valueFrom"]["secretKeyRef"] == {"name": "pg", "key": "password"}
    render(*kernel_values(tmp_path, workers={"sameCluster": False, "clusterSecret": "lanes"}))

    # No credential is optional, and none is a value: in every render above that succeeds, each
    # Secret the kernel pod uses is named, and nothing marks one optional.
    for over in (
        {},
        external,
        {"workers": {"sameCluster": False, "clusterSecret": "lanes"}},
    ):
        deploy = named(render(*kernel_values(tmp_path, **over)), "Deployment", "sy-sortyard-kernel")
        pod = deploy["spec"]["template"]["spec"]
        refs = [v["secret"] for v in pod["volumes"] if "secret" in v]
        refs += [
            entry["valueFrom"]["secretKeyRef"]
            for made in [*pod["initContainers"], *pod["containers"]]
            for entry in made["env"]
            if "valueFrom" in entry
        ]
        assert len(refs) >= 2
        for ref in refs:
            assert (ref.get("secretName") or ref.get("name")) and "optional" not in ref, ref
        text = yaml.safe_dump(deploy)
        assert "PRIVATE KEY" not in text
        for name, entry in env_of(container_of(deploy, "kernel")).items():
            if re.search("PASSWORD|TOKEN|KEY|KUBE_URL", name):
                is_file = name.endswith("_FILE") and entry["value"].startswith("/var/run/sortyard/")
                assert is_file or set(entry["valueFrom"]) == {"secretKeyRef"}, name


def test_the_kernel_needs_the_engine_a_lane_the_agent_commands_and_the_app() -> None:
    """What the service cannot start without is refused at render, with the value named: the
    service would exit 2 on it, and a pod that restarts for ever is found later."""
    base = (
        "--set",
        "kernel.enabled=true",
        "--set",
        "kernel.github.appId=1",
        "--set",
        "kernel.github.appKeySecret=app",
        "--set-json",
        f"kernel.worker.agents={json.dumps(AGENTS)}",
    )
    lane = ("--set", "kernel.lanes.one=version = 1")
    render(*ENGINE, *base, *lane)
    assert "requires engine.enabled=true" in render_fails(*base, *lane)
    assert "kernel.lanes is required" in render_fails(*ENGINE, *base)
    with_lane = (*base, *lane)
    refused = {
        "kernel.lanes.one is empty": ("--set", "kernel.lanes.one="),
        "is not a file name": ("--set", "kernel.lanes.Bad_Name=x"),
        "kernel.worker.agents.review is required": ("--set-json", "kernel.worker.agents.review=[]"),
        "kernel.github.appId is required": ("--set", "kernel.github.appId="),
        "kernel.workers.clusterSecret applies only": ("--set", "kernel.workers.clusterSecret=x"),
    }
    for message, args in refused.items():
        assert message in render_fails(*ENGINE, *with_lane, *args), message


WATCHED: dict[str, Any] = {
    "lane": "walwarden",
    "project": "proj-app",
    "roleBinding": "rb-red-main",
    "since": "2026-11-24T22:00:00Z",
}
RED_MAIN: dict[str, Any] = {
    "enabled": True,
    "workspace": "ws-estate",
    "lanes": [WATCHED],
}


def red_main_values(tmp_path: pathlib.Path, **over: Any) -> tuple[str, ...]:
    """A render with the kernel and the red-main observer on, `over` laid on redMain."""
    args = kernel_values(tmp_path)
    values = yaml.safe_load(pathlib.Path(args[-1]).read_text())
    values["redMain"] = merged(RED_MAIN, over)
    path = tmp_path / f"red-main-{len(list(tmp_path.glob('red-main-*')))}.yaml"
    path.write_text(yaml.safe_dump(values))
    return (*args[:-1], str(path))


def test_red_main_enabled_renders_the_observer_and_nothing_else_new(tmp_path: pathlib.Path) -> None:
    """redMain.enabled renders the observer's Deployment and its watch file, and changes nothing
    else; the service starts on what the Deployment gives it."""
    docs = render(*red_main_values(tmp_path))
    on, kernel_only = keyed(docs), keyed(render(*kernel_values(tmp_path)))
    assert set(on) - set(kernel_only) == {
        ("Deployment", "sy-sortyard-red-main"),
        ("ConfigMap", "sy-sortyard-red-main"),
    }
    assert all(on[key] == kernel_only[key] for key in kernel_only)
    deploy = on[("Deployment", "sy-sortyard-red-main")]
    assert deploy["spec"]["replicas"] == 1 and deploy["spec"]["strategy"] == {"type": "Recreate"}
    pod = deploy["spec"]["template"]["spec"]
    # No Kubernetes access: no service account token, no Role.
    assert pod["automountServiceAccountToken"] is False and "serviceAccountName" not in pod
    made = container_of(deploy, "red-main")
    assert made["command"] == ["sortyard-red-main"]
    assert made["image"] == container_of(on[("Deployment", "sy-sortyard-api")], "api")["image"]
    assert made["securityContext"]["readOnlyRootFilesystem"] is True
    env = env_of(made)
    api = env_of(container_of(on[("Deployment", "sy-sortyard-api")], "api"))
    for name in (n for n in api if n.startswith("SORTYARD_DATABASE_")):
        assert env[name] == api[name], name
    assert env["SORTYARD_API_URL"]["value"] == "http://sy-sortyard-api:8080"
    secrets = {**APP_SECRET, "sy-sortyard-postgres": {"password": "a-database-password"}}
    started = as_started(docs, deploy, "red-main", tmp_path, secrets)
    assert set(red_main.REQUIRED) <= set(started)
    assert pod["enableServiceLinks"] is False
    # Even given the link variables Kubernetes sets for the API Service of a release named
    # sortyard (as on the estate, where the first start failed on it), the service starts.
    started = {**started, "SORTYARD_API_PORT": "tcp://10.0.100.229:8080"}
    observer, interval = red_main.build(started)  # the App key loads, the watch file parses
    assert interval == 60
    (watch,) = observer.watches
    assert (watch.lane, watch.project, watch.role_binding) == (
        "walwarden",
        "proj-app",
        "rb-red-main",
    )
    assert watch.repositories == tuple(
        sorted(load_lanes(started["SORTYARD_LANES_DIR"])["walwarden"].repositories)
    )
    # Off, nothing of it is rendered.
    assert not [
        d
        for d in render(*red_main_values(tmp_path, enabled=False))
        if "red-main" in d["metadata"]["name"]
    ]


def test_red_main_needs_the_kernel_a_workspace_and_watched_lanes_the_kernel_declares(
    tmp_path: pathlib.Path,
) -> None:
    """What the observer cannot start on is refused at render, with the value named."""
    assert "requires kernel.enabled=true" in render_fails(
        *RELEASE, *ENGINE, "--set", "redMain.enabled=true", "--set", "redMain.workspace=ws"
    )
    refused: dict[str, dict[str, Any]] = {
        "redMain.workspace is required": {"workspace": ""},
        "redMain.lanes is required": {"lanes": []},
        'lane "nowhere" is not one of kernel.lanes': {"lanes": [{**WATCHED, "lane": "nowhere"}]},
        "is not an RFC 3339 time with its offset": {
            "lanes": [{**WATCHED, "since": "2026-11-24 22:00"}]
        },
        "redMain.lanes[].roleBinding is required": {"lanes": [{**WATCHED, "roleBinding": ""}]},
    }
    for message, over in refused.items():
        assert message in render_fails(*red_main_values(tmp_path, **over)), message


def test_kernel_enabled_false_renders_the_same_manifests_as_before(tmp_path: pathlib.Path) -> None:
    """kernel.enabled false renders the same manifests as before."""
    assert HELM is not None
    assert yaml.safe_load((CHART / "values.yaml").read_text())["kernel"]["enabled"] is False

    def text(*args: str) -> str:
        return subprocess.run(
            [HELM, "template", "sy", str(CHART), "--set", "postgres.auth.password=x", *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    # With the kernel off no kernel value reaches a manifest: the render is the same text
    # whatever they are, with the engine off and with it on, so it is what the chart rendered
    # before it had a kernel. (The pull request that added the kernel compared these two
    # renders with the ones of the commit before it: the same text.)
    inert = kernel_values(tmp_path, enabled=False, decisionPolicy=RULE)
    values = yaml.safe_load(pathlib.Path(inert[-1]).read_text())
    del values["engine"]
    off = tmp_path / "off.yaml"
    off.write_text(yaml.safe_dump(values))
    for others in ((), ENGINE, SHADOW_SNAPSHOT):
        assert text(*others, "-f", str(off)) == text(*others), others
    # ... and nothing of the kernel's is in it: no object of its own, and the API as it was.
    for others in ((), ENGINE):
        docs = [doc for doc in yaml.safe_load_all(text(*others)) if doc]
        kinds = {d["kind"] for d in docs}
        assert not kinds & {"Role", "RoleBinding", "ClusterRole", "ServiceAccount"}
        assert not [d["metadata"]["name"] for d in docs if "kernel" in d["metadata"]["name"]]
        api = named(docs, "Deployment", "sy-sortyard-api")
        made = container_of(api, "api")
        assert "SORTYARD_LANES_DIR" not in env_of(made)
        assert "volumeMounts" not in made and "volumes" not in api["spec"]["template"]["spec"]
        assert "annotations" not in api["spec"]["template"]["metadata"]
        rest = yaml.safe_dump_all([d for d in docs if d["kind"] != "ConfigMap"])
        assert "kernel" not in rest.lower() and "lanes" not in rest.lower()


def exercised_port() -> set[tuple[str, str, str]]:
    """Every call the jobs port makes, as (API group, resource, verb): the real client run
    through each of its methods against the fake API server, and its requests read back."""
    config = WorkerConfig(agents={"build": ["a"], "fix": ["a"], "review": ["a"]})

    def job(name: str, dispatch: int) -> dict[str, Any]:
        labels = {ITEM_LABEL: "one", DISPATCH_LABEL: str(dispatch)}
        return manifest(name, LANE, config, 1800, labels)

    with FakeCluster() as cluster:
        # The Secrets the lane's worker pods mount, there before any Job, as in a cluster.
        cluster.add_secret("deploy-token", {"DEPLOY_TOKEN": "v"})
        cluster.add_secret("model-api-key", {"MODEL_API_KEY": "v"})
        jobs = KubeJobs(cluster.url, cluster.namespace, token=lambda: cluster.token)
        jobs.launch(job("sy-one-1", 1), brief="{}", token=lambda: TOKEN, stamp="1")
        jobs.launch(job("sy-one-1", 1), brief="{}", token=lambda: TOKEN, stamp="1")
        jobs.status("sy-one-1")
        jobs.secret_minted("sy-one-1")
        jobs.refresh_secret("sy-one-1", TOKEN, "2")
        jobs.launch(job("sy-one-2", 2), brief="{}", token=lambda: TOKEN, stamp="1")
        jobs.delete_earlier("one", 2)
        cluster.finish("sy-one-2", "{}")
        jobs.status("sy-one-2")
        jobs.delete_secret("sy-one-2")
        jobs.delete("sy-one-2")
        assert cluster.violations == []
        exchanges = list(cluster.exchanges)
    # That was the whole port: every operation its contract fragment holds was made.
    vendored = {
        operation["operationId"]
        for methods in json.loads(CONTRACT.read_text())["paths"].values()
        for operation in methods.values()
    }
    assert {exchange.operation for exchange in exchanges} == vendored
    verbs = {"POST": "create", "PATCH": "patch", "PUT": "update"}
    calls = set()
    for exchange in exchanges:
        found = re.fullmatch(
            r"/(?:api/v1|apis/(?P<group>[^/]+)/v1)/namespaces/(?P<namespace>[^/]+)"
            r"/(?P<resource>[^/]+)(?P<name>/[^/]+)?(?P<sub>/.+)?",
            exchange.path,
        )
        assert found and found["namespace"] == cluster.namespace, exchange.path
        named_one = bool(found["name"])
        verb = (
            verbs.get(exchange.method)
            or {
                ("GET", True): "get",
                ("GET", False): "list",
                ("DELETE", True): "delete",
                ("DELETE", False): "deletecollection",
            }[exchange.method, named_one]
        )
        calls.add((found["group"] or "", found["resource"] + (found["sub"] or ""), verb))
    return calls


def granted(role: dict[str, Any]) -> set[tuple[str, str, str]]:
    grants = set()
    for rule in role["rules"]:
        assert set(rule) == {"apiGroups", "resources", "verbs"}, rule  # no resourceNames, no URLs
        for group in rule["apiGroups"]:
            for resource in rule["resources"]:
                for verb in rule["verbs"]:
                    grants.add((group, resource, verb))
    return grants


def test_the_worker_role_grants_what_the_jobs_port_calls_in_the_worker_namespace_and_no_more(
    tmp_path: pathlib.Path,
) -> None:
    """must_catch: a Role that grants more than the worker namespace resources named."""
    calls = exercised_port()
    for over, namespace in (({}, NAMESPACE), ({"workers": {"namespace": "lanes"}}, "lanes")):
        docs = render(*kernel_values(tmp_path, **over))
        role = named(docs, "Role", "sy-sortyard-kernel")
        grants = granted(role)
        # Exactly what the port calls: nothing it needs is missing, nothing more is granted.
        assert grants == calls
        assert not [grant for grant in grants if "*" in grant]
        assert {(group, resource) for group, resource, _ in grants} <= NAMED_RESOURCES
        # In the worker namespace only: a Role there, bound to the kernel's service account
        # and to no one else, and nothing cluster-wide.
        assert role["metadata"]["namespace"] == namespace
        binding = named(docs, "RoleBinding", "sy-sortyard-kernel")
        assert binding["metadata"]["namespace"] == namespace
        assert binding["roleRef"] == {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": "sy-sortyard-kernel",
        }
        assert binding["subjects"] == [
            {"kind": "ServiceAccount", "name": "sy-sortyard-kernel", "namespace": NAMESPACE}
        ]
        kinds = [d["kind"] for d in docs]
        assert kinds.count("Role") == 1 and kinds.count("RoleBinding") == 1
        assert not {"ClusterRole", "ClusterRoleBinding"} & set(kinds)
        deploy = named(docs, "Deployment", "sy-sortyard-kernel")
        env = env_of(container_of(deploy, "kernel"))
        assert env["SORTYARD_JOBS_NAMESPACE"]["value"] == namespace
        # No other pod of the release holds that service account, or any cluster token.
        for other in by_kind(docs, "Deployment") + by_kind(docs, "StatefulSet"):
            if other is not deploy:
                pod = other["spec"]["template"]["spec"]
                assert pod.get("serviceAccountName") != "sy-sortyard-kernel"


def test_worker_jobs_on_another_cluster_are_reached_through_a_secret_reference(
    tmp_path: pathlib.Path,
) -> None:
    """must_allow: worker Jobs on another cluster reached through a Secret reference."""
    over = {
        "workers": {"sameCluster": False, "clusterSecret": "lane-cluster", "namespace": "lanes"}
    }
    docs = render(*kernel_values(tmp_path, **over))
    # Nothing is granted in the release's own cluster, and the pod holds no token of it.
    assert not by_kind(docs, "Role") and not by_kind(docs, "RoleBinding")
    deploy = named(docs, "Deployment", "sy-sortyard-kernel")
    assert deploy["spec"]["template"]["spec"]["automountServiceAccountToken"] is False
    env = env_of(container_of(deploy, "kernel"))
    assert env["SORTYARD_KUBE_URL"]["valueFrom"]["secretKeyRef"] == {
        "name": "lane-cluster",
        "key": "server",
    }
    # The service, started on what the Deployment gives it, reaches that cluster: its jobs
    # port, built from its settings, talks to the API server the Secret names with the
    # Secret's token.
    with FakeCluster(namespace="lanes") as cluster:
        secrets = {
            **APP_SECRET,
            "sy-sortyard-postgres": {"password": "pw"},
            "lane-cluster": {
                "server": cluster.url,
                "token": cluster.token + "\n",
                "ca.crt": "unused for http",
            },
        }
        started = as_started(docs, deploy, "kernel", tmp_path, secrets)
        assert "KUBERNETES_SERVICE_HOST" not in started
        settings = kernel.Settings.from_env(started)
        assert settings.kube_url == cluster.url and settings.jobs_namespace == "lanes"
        assert pathlib.Path(str(settings.kube_ca_file)).read_text() == "unused for http"
        # http here, so the CA is not used; over https it is what the server is verified with.
        jobs = kernel.Settings.from_env(
            {k: v for k, v in started.items() if k != "SORTYARD_KUBE_CA_FILE"}
        ).jobs()
        job = manifest("sy-far-1", LANE, settings.worker, 600, {ITEM_LABEL: "far"})
        assert jobs.launch(job, brief="{}", token=lambda: TOKEN, stamp="1") is True
        assert cluster.names("job") == ["sy-far-1"] and cluster.violations == []
    # A server whose certificate the image's trust store verifies needs no CA in the Secret.
    public = merged(over, {"workers": {"clusterCA": False}})
    deploy = named(render(*kernel_values(tmp_path, **public)), "Deployment", "sy-sortyard-kernel")
    assert "SORTYARD_KUBE_CA_FILE" not in env_of(container_of(deploy, "kernel"))
    (volume,) = [v for v in deploy["spec"]["template"]["spec"]["volumes"] if v["name"] == "cluster"]
    assert [item["key"] for item in volume["secret"]["items"]] == ["token"]


def test_the_kernel_pod_waits_for_the_engine_and_gives_up_at_its_limit(
    tmp_path: pathlib.Path,
) -> None:
    """The init container's command, run for real: it returns once the engine answers for its
    namespace, and without an engine fails at its limit instead of waiting on."""
    docs = render(*kernel_values(tmp_path, engineWaitSeconds=1))
    deploy = named(docs, "Deployment", "sy-sortyard-kernel")
    assert [c["name"] for c in deploy["spec"]["template"]["spec"]["initContainers"]] == [
        "wait-engine"
    ]
    wait = container_of(deploy, "wait-engine")
    started = as_started(docs, deploy, "wait-engine", tmp_path, {})
    assert started["SORTYARD_ENGINE_TARGET"] == "sy-sortyard-engine:7233"
    assert started["SORTYARD_ENGINE_WAIT_SECONDS"] == "1"
    # The script the pod runs is the chart's file, as mounted.
    mount = next(m for m in wait["volumeMounts"] if m["name"] == "kernel")
    assert wait["command"] == ["python", f"{mount['mountPath']}/wait_engine.py"]
    script = tmp_path / "wait-engine" / "kernel" / "wait_engine.py"
    assert script.read_text() == (CHART / "kernel" / "wait_engine.py").read_text()

    def run(target: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **started, "SORTYARD_ENGINE_TARGET": target}
        return subprocess.run(
            [sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=120
        )

    async def against_an_engine() -> subprocess.CompletedProcess[str]:
        async with local_engine() as local:
            return await asyncio.to_thread(run, local.target)

    answered = asyncio.run(against_an_engine())
    assert answered.returncode == 0, answered.stderr
    began = time.monotonic()
    nothing = run("127.0.0.1:9")  # the discard port: nothing answers there
    assert nothing.returncode != 0 and "127.0.0.1:9" in nothing.stderr
    assert time.monotonic() - began < 60
