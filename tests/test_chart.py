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
