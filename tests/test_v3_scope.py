"""SY-V3-SCOPE-RECORDED: relabelling the requirement catalog as reference dropped nothing.

The owner's 2026-11-23 decision on company/HARNESS-V3.md is recorded as the SY-DEC-005
amendment in DECISIONS.md, and README.md, AGENTS.md and the delivery plan link it at their top.
Those are documentation; under policy tests-prove-the-real-path their wording is validated by
review, not by tests that read Markdown. What runs here is the production behaviour this change
touches: docs/requirements/tools/gen.py, which renders the catalog (now labelled reference and
linking SY-DEC-005) from the unchanged requirements source and, with --check, refuses a catalog
that is not exactly its rendering.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "docs" / "requirements"


def run_check(requirements: pathlib.Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(requirements / "tools" / "gen.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_requirement_catalog_is_the_generators_rendering_of_every_source_requirement() -> None:
    """catalog.md is exactly what gen.py renders from the unchanged requirements source."""
    result = run_check(REQUIREMENTS)
    assert result.returncode == 0, result.stderr


def test_generator_check_refuses_a_catalog_that_drifted_from_the_source(
    tmp_path: pathlib.Path,
) -> None:
    """A catalog that lost its rows fails the generator's check, so the guard above can fail."""
    copy = tmp_path / "requirements"
    shutil.copytree(REQUIREMENTS, copy)
    (copy / "catalog.md").write_text("")
    result = run_check(copy)
    assert result.returncode == 1
    assert "stale generated file catalog.md" in result.stderr
