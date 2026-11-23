"""Drift guard: the planning records a build worker reads point at SY-DEC-005 (2026-11-23).

The owner's decision on company/HARNESS-V3.md is recorded as the 2026-11-23 amendment to
SY-DEC-005 in DECISIONS.md; that record's wording is reviewed directly, not asserted here. These
tests guard what can drift: README.md, AGENTS.md and the delivery plan each link the record at
their top, none of them (nor the requirements baseline they link) names Appwrite as the core's
default persistence, and the requirement catalog is still exactly the production generator's
rendering of every requirement in the unchanged source.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "requirements" / "delivery-plan.md"
BASELINE = ROOT / "docs" / "requirements" / "README.md"
POINTING_DOCS = (ROOT / "README.md", ROOT / "AGENTS.md", PLAN)
LINK = re.compile(r"\]\((?:\.\./)*DECISIONS\.md#sy-dec-005\)")


def flat(text: str) -> str:
    """Whitespace-normalised text with blockquote markers removed."""
    return " ".join(re.sub(r"^\s*>\s?", "", text, flags=re.M).split())


def top(path: pathlib.Path) -> str:
    """The title and the text before the document's first `## ` section."""
    return path.read_text().split("\n## ", 1)[0]


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
