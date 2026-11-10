"""Acceptance: the README carries a quickstart a zero-context reader can follow."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_quickstart_reaches_a_running_empty_system() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "## Quickstart" in readme
    quickstart = readme.split("## Quickstart", 1)[1]
    for step in (
        "kind create cluster",
        "docker build -t ghcr.io/sortyard/sortyard:",
        "kind load docker-image",
        "helm install sortyard charts/sortyard",
        "kubectl port-forward",
        "/readyz",
        "pip install -e '.[dev]'",
    ):
        assert step in quickstart, step
