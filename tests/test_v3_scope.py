"""Acceptance: the repository records the kernel scope the owner decided (SY-DEC-005, 2026-11-23).

The owner's decision on company/HARNESS-V3.md (section 3.7 and its Decisions section) makes
Sortyard the workflow kernel plus the tracker view, stores the core to Postgres only (SY-DEC-004
no longer applies to it), puts a durable workflow engine behind one module, and defers
delivery-plan increments MS1, MS2 and MS6 until the kernel runs one lane. A build worker reads
README.md, AGENTS.md and the delivery plan before any kernel task, so each of them points at that
record at its top, and none of them (nor the baseline they link) names Appwrite as the core's
default persistence. The requirement catalog stays in the repository as labelled reference.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "DECISIONS.md"
PLAN = ROOT / "docs" / "requirements" / "delivery-plan.md"
CATALOG = ROOT / "docs" / "requirements" / "catalog.md"
BASELINE = ROOT / "docs" / "requirements" / "README.md"
POINTING_DOCS = (ROOT / "README.md", ROOT / "AGENTS.md", PLAN)
LINK = re.compile(r"\]\((?:\.\./)*DECISIONS\.md#sy-dec-005\)")


def flat(text: str) -> str:
    """Whitespace-normalised text with blockquote markers removed."""
    return " ".join(re.sub(r"^\s*>\s?", "", text, flags=re.M).split())


def record(text: str, ident: str) -> str:
    match = re.search(rf"^## {ident}\b.*?(?=^## |\Z)", text, re.M | re.S)
    assert match, f"no record {ident}"
    return match.group(0)


def amendment() -> str:
    dec = record(DECISIONS.read_text(), "SY-DEC-005")
    match = re.search(r"^### .*2026-11-23.*?(?=^### |\Z)", dec, re.M | re.S)
    assert match, "SY-DEC-005 has no dated 2026-11-23 amendment"
    return flat(match.group(0))


def top(path: pathlib.Path) -> str:
    """The title and the text before the document's first `## ` section."""
    return path.read_text().split("\n## ", 1)[0]


def test_sy_dec_005_holds_the_kernel_scope_postgres_only_and_engine_behind_one_module() -> None:
    text = DECISIONS.read_text()
    assert '<a id="sy-dec-005"></a>' in text
    # The earlier November 15 decision stays as provenance under the same record.
    dec = record(text, "SY-DEC-005")
    assert "2026-11-15" in dec
    body = amendment()
    for phrase in (
        "company/HARNESS-V3.md",
        "workflow kernel plus the tracker view",
        "Postgres only",
        "SY-DEC-004 no longer applies",
        "durable workflow engine",
        "behind one module",
        "MS1, MS2 and MS6 are deferred until the kernel runs one lane",
        "supersedes",
    ):
        assert phrase in body, phrase
    # Products keep their own choice of Appwrite for auth.
    assert re.search(r"Appwrite for (?:their )?auth", body)


def test_sy_dec_004_and_001_defer_to_the_amendment() -> None:
    text = DECISIONS.read_text()
    assert "SY-DEC-005" in flat(record(text, "SY-DEC-004"))
    assert "SY-DEC-005" in flat(record(text, "SY-DEC-001"))
    substrate = (ROOT / "docs" / "decisions" / "appwrite-substrate.md").read_text()
    assert "SY-DEC-005" in substrate.split("\n## ", 1)[0]


def test_readme_agents_and_plan_point_at_sy_dec_005_at_their_top() -> None:
    for path in POINTING_DOCS:
        assert LINK.search(top(path)), f"{path.name} does not link SY-DEC-005 at its top"


def test_delivery_plan_carries_the_deferral_note_at_its_top() -> None:
    head = flat(top(PLAN))
    assert "MS1, MS2 and MS6 are deferred until the kernel runs one lane" in head
    assert "not the current build order" in head


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


def test_the_check_catches_an_appwrite_default_claim() -> None:
    assert appwrite_default_claims(
        "[SY-DEC-004](x.md) selects Appwrite as the preferred future persistence substrate."
    )
    assert appwrite_default_claims("- Appwrite persistence, Auth and Teams are the default.")
    assert not appwrite_default_claims("SY-DEC-004 (Appwrite default) no longer applies.")


def test_no_pointing_doc_claims_the_baseline_is_the_current_authority() -> None:
    for path in (*POINTING_DOCS, BASELINE):
        text = flat(path.read_text())
        for claim in (
            "current planning authority is the",
            "Current requirements authority",
            "This is the current consolidated planning baseline",
            "for the current delivery sequence",
        ):
            assert claim not in text, f"{path.name}: {claim}"


def test_requirement_catalog_is_kept_and_labelled_reference() -> None:
    catalog = CATALOG.read_text()
    head = flat(catalog.split('<a id="', 1)[0])
    assert head.startswith("# Requirements catalog (reference)")
    assert "SY-DEC-005" in head
    # Contents stay: every requirement is still rendered.
    assert catalog.count('<a id="') >= 384
    assert "SY-DEC-005" in flat(top(BASELINE))
    assert "reference" in flat(top(BASELINE)).lower()
