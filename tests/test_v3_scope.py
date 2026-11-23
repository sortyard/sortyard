"""Drift guard: the planning records a build worker reads point at SY-DEC-005 (2026-11-23).

The owner's decision on company/HARNESS-V3.md is recorded as the 2026-11-23 amendment to
SY-DEC-005 in DECISIONS.md. These tests guard that the amendment states the kernel scope
(workflow kernel plus tracker view), the Postgres-only core with SY-DEC-004 inapplicable, the
durable engine behind one module and the MS1/MS2/MS6 deferral; that README.md, AGENTS.md and the
delivery plan each link the record at their top, the plan carrying the deferral note and the
catalog labelled reference; that none of them (nor the requirements baseline they link) names
Appwrite as the core's default persistence; and that the requirement catalog is still exactly the
production generator's rendering of every requirement in the unchanged source.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "requirements" / "delivery-plan.md"
BASELINE = ROOT / "docs" / "requirements" / "README.md"
CATALOG = ROOT / "docs" / "requirements" / "catalog.md"
DECISIONS = ROOT / "DECISIONS.md"
POINTING_DOCS = (ROOT / "README.md", ROOT / "AGENTS.md", PLAN)
LINK = re.compile(r"\]\((?:\.\./)*DECISIONS\.md#sy-dec-005\)")


def flat(text: str) -> str:
    """Whitespace-normalised text with blockquote markers removed."""
    return " ".join(re.sub(r"^\s*>\s?", "", text, flags=re.M).split())


def top(path: pathlib.Path) -> str:
    """The title and the text before the document's first `## ` section."""
    return path.read_text().split("\n## ", 1)[0]


def sy_dec_005_amendment(text: str) -> str:
    """The flattened 2026-11-23 amendment section of SY-DEC-005, or "" if it is absent."""
    record = re.search(
        r'<a id="sy-dec-005"></a>\s*\n## SY-DEC-005\b(.*?)(?=\n## |\Z)', text, re.S
    )
    if not record:
        return ""
    amendment = re.search(
        r"\n### Amendment\b[^\n]*2026-11-23[^\n]*\n(.*?)(?=\n### |\Z)", record.group(1), re.S
    )
    return flat(amendment.group(1)) if amendment else ""


AMENDMENT_CLAUSES = {
    "supersedes the November 15 decision": r"supersedes the November 15",
    "kernel plus tracker view": r"workflow kernel plus the tracker view described in "
    r"company/HARNESS-V3\.md",
    "ecosystem control surface deferred": r"ecosystem control surface .{0,80}deferred",
    "Postgres-only core": r"core stores to Postgres only",
    "SY-DEC-004 inapplicable": r"SY-DEC-004 no longer applies to the core",
    "durable engine behind one module": r"durable workflow engine is used behind one module "
    r"instead of a hand-written one",
    "MS1/MS2/MS6 deferred until one lane runs": r"MS1, MS2 and MS6 are deferred until the "
    r"kernel runs one lane",
}


def missing_amendment_clauses(text: str) -> list[str]:
    amendment = sy_dec_005_amendment(text)
    return [name for name, pattern in AMENDMENT_CLAUSES.items() if not re.search(pattern, amendment)]


def test_decisions_holds_the_dated_sy_dec_005_kernel_scope_amendment() -> None:
    """DECISIONS.md holds SY-DEC-005 with the kernel scope, Postgres only and the engine behind
    one module."""
    text = DECISIONS.read_text()
    assert sy_dec_005_amendment(text), "DECISIONS.md has no 2026-11-23 SY-DEC-005 amendment"
    assert missing_amendment_clauses(text) == []
    sy_dec_004 = text.split("## SY-DEC-004", 1)[1].split("\n## ", 1)[0]
    assert re.search(r"No longer applies to the Sortyard core", sy_dec_004), (
        "SY-DEC-004 is not marked as no longer applying to the core"
    )


def test_decision_check_rejects_a_record_without_the_amendment() -> None:
    """The record check fails when the amendment or any of its clauses is missing."""
    text = DECISIONS.read_text()
    without = re.sub(r"\n### Amendment\b.*?(?=\n### )", "\n", text, count=1, flags=re.S)
    assert sy_dec_005_amendment(without) == ""
    assert set(missing_amendment_clauses(without)) == set(AMENDMENT_CLAUSES)
    weakened = text.replace("behind one module instead", "in several modules instead", 1)
    assert missing_amendment_clauses(weakened) == ["durable engine behind one module"]


def test_plan_carries_the_deferral_note_and_catalog_is_labelled_reference() -> None:
    plan_top = flat(top(PLAN))
    assert re.search(r"not the current build order", plan_top), "plan lacks the deferral note"
    assert re.search(r"MS1, MS2 and MS6 are deferred until the kernel runs one lane", plan_top)
    catalog_top = top(CATALOG)
    assert catalog_top.startswith("# Requirements catalog (reference)")
    assert LINK.search(catalog_top), "catalog does not link SY-DEC-005 at its top"


def test_readme_agents_and_plan_point_at_sy_dec_005_at_their_top() -> None:
    for path in POINTING_DOCS:
        assert LINK.search(top(path)), f"{path.name} does not link SY-DEC-005 at its top"


def appwrite_default_claims(text: str) -> list[str]:
    """Sentences that present Appwrite as the default, preferred or selected core substrate."""
    claims = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n\s*\n|\n[-|#>]", text):
        s = flat(sentence)
        if "Appwrite" not in s:
            continue
        if not re.search(r"\b(default|preferred|selects?|target)\b", s, re.I):
            continue
        if re.search(r"no longer|not (?:the|a|needed)|superseded|does not apply", s, re.I):
            continue
        claims.append(s)
    return claims


def test_no_pointing_doc_names_appwrite_as_the_core_default() -> None:
    for path in (*POINTING_DOCS, BASELINE):
        assert appwrite_default_claims(path.read_text()) == [], path.name


def test_requirement_catalog_is_the_generators_rendering_of_every_source_requirement() -> None:
    """The production generator's own check: catalog.md is exactly what gen.py renders from the
    unchanged requirements source, so relabelling the catalog dropped no requirement."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "docs" / "requirements" / "tools" / "gen.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
