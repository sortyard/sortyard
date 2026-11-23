"""Acceptance: the six §4 services are separate entry points of one Python package (SY-DEC-001)."""

from __future__ import annotations

import importlib
import pathlib
import tomllib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Service name -> console script -> module under sortyard.services.
SIX_SERVICES = {
    "api": "api",
    "conductor": "conductor",
    "context-assembler": "context_assembler",
    "eval-runner": "eval_runner",
    "sensor-runner": "sensor_runner",
    "integrator": "integrator",
}


def scripts() -> dict[str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    result: dict[str, str] = project["scripts"]
    return result


def test_each_service_is_a_console_script_of_the_one_package() -> None:
    expected = {
        f"sortyard-{name}": f"sortyard.services.{module}:main"
        for name, module in SIX_SERVICES.items()
    }
    assert {k: v for k, v in scripts().items() if k in expected} == expected


def test_registry_names_exactly_the_six_services() -> None:
    from sortyard.services import SERVICES

    assert set(SERVICES) == set(SIX_SERVICES)
    for name, module in SIX_SERVICES.items():
        assert SERVICES[name] == f"sortyard.services.{module}"


@pytest.mark.parametrize("name", sorted(SIX_SERVICES))
def test_entry_point_resolves_to_a_callable_main(name: str) -> None:
    target = scripts()[f"sortyard-{name}"]
    module_name, _, attr = target.partition(":")
    main = getattr(importlib.import_module(module_name), attr)
    assert callable(main)


@pytest.mark.parametrize("name", sorted(set(SIX_SERVICES) - {"api"}))
def test_stub_service_runs_one_cycle_and_exits_cleanly(
    name: str, caplog: pytest.LogCaptureFixture
) -> None:
    module = importlib.import_module(f"sortyard.services.{SIX_SERVICES[name]}")
    with caplog.at_level("INFO"):
        assert module.main(["--once"]) == 0
    assert f"{name}: stub service started" in caplog.text
