"""SY-V3-SCOPE-RECORDED: the repository records the kernel scope the owner decided.

The owner's 2026-11-23 decision on company/HARNESS-V3.md is the SY-DEC-005 amendment in
DECISIONS.md. A build worker reads README.md, AGENTS.md and the delivery plan before any kernel
task, so each must point at that record at its top and none may still present the superseded
plan (Appwrite as the core's default store, the delivery plan as the build order). These are
planning records, so the first two tests read them directly: that is the item's acceptance, and
it is what keeps the records from drifting back. The last two run the production catalog
generator, which this change relabels as reference.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "docs" / "requirements"
POINTING = (ROOT / "README.md", ROOT / "AGENTS.md", REQUIREMENTS / "delivery-plan.md")
# "At their top": before the first second-level heading, within the opening lines.
TOP_LINES = 12
SY_DEC_005_LINK = re.compile(r"\[SY-DEC-005\]\((?:\.\./)*DECISIONS\.md#sy-dec-005\)")
# A sentence that makes Appwrite the default or preferred store, unless it says that this no
# longer holds. Mentions of Appwrite as history, or for product auth, are allowed.
APPWRITE_AS_DEFAULT = re.compile(
    r"appwrite[^.\n]*\b(?:is|are|as|remains?)\s+the\s+(?:default|preferred)"
    r"|(?:default|preferred)[^.\n]*\bappwrite"
    r"|selects\s+appwrite",
    re.IGNORECASE,
)
SUPERSEDED = re.compile(
    r"no longer appl|superseded|were the default|was the default", re.IGNORECASE
)


def top(path: pathlib.Path) -> str:
    lines = path.read_text().splitlines()[:TOP_LINES]
    for index, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[:index])
    return "\n".join(lines)


def amendment() -> str:
    """The text of the 2026-11-23 amendment inside the SY-DEC-005 record."""
    decisions = (ROOT / "DECISIONS.md").read_text()
    record = re.search(r"^## SY-DEC-005\b.*?(?=^## |\Z)", decisions, re.MULTILINE | re.DOTALL)
    assert record, "DECISIONS.md has no SY-DEC-005 record"
    assert "2026-11-23" in record.group(0).splitlines()[0], "SY-DEC-005 is not dated 2026-11-23"
    part = re.search(r"^### Amendment\b.*?(?=^### |\Z)", record.group(0), re.MULTILINE | re.DOTALL)
    assert part, "SY-DEC-005 has no amendment section"
    return " ".join(part.group(0).split())


def names_appwrite_as_default(text: str) -> list[str]:
    """Paragraphs that name Appwrite as the default without saying it no longer applies."""
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]
    return [p for p in paragraphs if APPWRITE_AS_DEFAULT.search(p) and not SUPERSEDED.search(p)]


def test_decisions_holds_sy_dec_005_with_kernel_scope_postgres_only_and_engine_module() -> None:
    """DECISIONS.md holds SY-DEC-005 with the kernel scope, Postgres only and the engine behind
    one module."""
    text = amendment()
    assert "workflow kernel plus the tracker view" in text
    assert "company/HARNESS-V3.md" in text
    assert "Postgres only" in text
    assert "SY-DEC-004 no longer applies to the core" in text
    assert "durable workflow engine is used behind one module instead of a hand-written one" in text
    assert re.search(r"MS1, MS2 and MS6 are deferred until the kernel runs one lane", text)
    # The superseded record itself says so, where a reader of SY-DEC-004 lands.
    decisions = (ROOT / "DECISIONS.md").read_text()
    dec_004 = re.search(r"^## SY-DEC-004\b.*?(?=^## |\Z)", decisions, re.MULTILINE | re.DOTALL)
    assert dec_004 and "No longer applies to the Sortyard core" in dec_004.group(0)


def test_readme_agents_and_delivery_plan_point_at_sy_dec_005_and_none_names_appwrite_default() -> (
    None
):
    """README.md, AGENTS.md and the delivery plan point at SY-DEC-005 and none names Appwrite as
    the core default."""
    for path in POINTING:
        assert SY_DEC_005_LINK.search(top(path)), f"{path.name} does not link SY-DEC-005 at its top"
    for path in (ROOT / "README.md", ROOT / "AGENTS.md"):
        assert names_appwrite_as_default(path.read_text()) == [], path.name
    # The delivery plan stays as reference (its body is unchanged), so its top must carry the
    # deferral note: it is not presented as the current build order.
    plan_top = " ".join(top(REQUIREMENTS / "delivery-plan.md").split())
    assert "not the current build order" in plan_top
    assert "MS1, MS2 and MS6 are deferred" in plan_top
    assert "(reference)" in (REQUIREMENTS / "catalog.md").read_text().splitlines()[0]


def test_the_appwrite_default_guard_catches_the_superseded_wording() -> None:
    """The guard above can fail: it catches the wording this change removed, and lets through
    history and product auth."""
    old_agents = (
        "[SY-DEC-004](docs/decisions/appwrite-substrate.md) selects Appwrite as the preferred "
        "future persistence/auth substrate."
    )
    old_baseline = "Appwrite persistence, Auth and Teams are the default per SY-DEC-004."
    assert names_appwrite_as_default(old_agents)
    assert names_appwrite_as_default(old_baseline)
    assert not names_appwrite_as_default("Products may still use Appwrite for their auth.")
    assert not names_appwrite_as_default(
        "SY-DEC-004 (Appwrite) no longer applies to it; Appwrite was the default until then."
    )


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
