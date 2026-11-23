"""Acceptance: one Helm chart, one values file, deploys the API service + Postgres."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
from typing import Any

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHART = ROOT / "charts" / "sortyard"
HELM = shutil.which("helm")

if HELM is None:
    if os.environ.get("SORTYARD_REQUIRE_HELM"):
        raise RuntimeError("SORTYARD_REQUIRE_HELM is set but helm is not on PATH")
    pytestmark = pytest.mark.skip(reason="helm not on PATH (CI sets SORTYARD_REQUIRE_HELM)")


def render(*args: str) -> list[dict[str, Any]]:
    assert HELM is not None
    out = subprocess.run(
        [HELM, "template", "sy", str(CHART), *args],
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
    docs = render(*ENGINE, "--set", "engine.image.tag=9.9.9", "--set", "engine.image.digest=")
    assert component(docs, "Job", "engine-schema")["metadata"]["name"].startswith(
        "sy-sortyard-engine-schema-"
    )
    server = containers(component(docs, "Deployment", "engine"))
    assert server["engine"]["image"] == "temporalio/server:9.9.9"
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
    no_digest = ("--set", "engine.image.digest=")
    same = render(*ENGINE, "--set", "engine.image.tag=9.9.9", *no_digest, "--set", "api.replicas=2")
    newer = render(*ENGINE, "--set", "engine.image.tag=9.9.10", *no_digest)
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
    for image in ("image", "toolsImage"):
        assert "pinned" in render_fails(*ENGINE, "--set", f"engine.{image}.tag=latest")
        assert "pinned" in render_fails(*ENGINE, "--set", f"engine.{image}.tag=")
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
