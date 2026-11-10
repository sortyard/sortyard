"""Acceptance: CI runs the repo's own checks on every pull request (design draft §9)."""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def load() -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text())
    return data


def all_run_lines() -> str:
    return "\n".join(
        step.get("run", "") for job in load()["jobs"].values() for step in job["steps"]
    )


def test_runs_on_every_pull_request_and_on_main() -> None:
    # PyYAML reads the bare key `on` as boolean True.
    triggers = load()[True]
    assert "pull_request" in triggers
    pr = triggers["pull_request"] or {}
    assert "branches" not in pr and "paths" not in pr, "every PR, not a filtered subset"
    assert triggers["push"]["branches"] == ["main"]


def test_runs_lint_typecheck_tests_chart_and_image() -> None:
    runs = all_run_lines()
    for check in (
        "ruff check",
        "ruff format --check",
        "mypy",
        "pytest",
        "helm lint",
        "helm template",
        "docker build",
    ):
        assert check in runs, check


def test_chart_tests_are_required_in_ci_not_skipped() -> None:
    assert "SORTYARD_REQUIRE_HELM" in WORKFLOW.read_text()
