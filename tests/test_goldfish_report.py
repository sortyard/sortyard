"""Acceptance: the Phase 1 goldfish install + smoke report (corpus M1.14) is filed in the repo.

The report is the deliverable. These tests hold it to the shape the task asks for: it records
the run against every command the README quickstart documents, files each point of friction as
a finding against exactly one of the repo, the docs or the chart, and states a verdict.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "goldfish" / "phase-1-install-smoke.md"

FINDING = re.compile(r"^### (GF1-\d{2}) — \S.*$", re.MULTILINE)
AGAINST = {"repo", "docs", "chart"}
SEVERITY = {"blocker", "major", "minor"}
VERDICTS = {"clean", "findings", "blocked"}


def report() -> str:
    return REPORT.read_text()


def quickstart_commands() -> list[str]:
    """The shell commands of the README quickstart block, comments stripped."""
    readme = (ROOT / "README.md").read_text()
    section = readme.split("## Quickstart", 1)[1]
    block = section.split("```sh", 1)[1].split("```", 1)[0]
    commands: list[str] = []
    for line in block.splitlines():
        command = line.split("#", 1)[0].strip().rstrip("&").strip()
        if command:
            commands.append(command)
    return commands


def findings() -> list[tuple[str, str]]:
    """(id, body) for every finding in the report."""
    text = report()
    matches = list(FINDING.finditer(text))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].split("\n## ", 1)[0]
        out.append((m.group(1), body))
    return out


def field(body: str, name: str) -> str:
    m = re.search(rf"^\*\*{name}:\*\* *(.+)$", body, re.MULTILINE)
    assert m, f"missing **{name}:**"
    return m.group(1).strip()


def test_report_exists_with_its_sections() -> None:
    text = report()
    for heading in ("## Environment", "## Run log", "## Findings", "## Verdict"):
        assert heading in text, heading


def test_run_log_covers_every_quickstart_command() -> None:
    run_log = report().split("## Run log", 1)[1].split("\n## ", 1)[0]
    for command in quickstart_commands():
        assert command in run_log, command


def test_every_finding_is_filed_against_the_repo_the_docs_or_the_chart() -> None:
    found = findings()
    assert found, "a clean run is reportable, but then the verdict must say clean"
    ids = [fid for fid, _ in found]
    assert ids == [f"GF1-{n:02d}" for n in range(1, len(ids) + 1)], ids
    for fid, body in found:
        assert field(body, "Against") in AGAINST, fid
        assert field(body, "Severity") in SEVERITY, fid
        assert field(body, "Evidence"), fid


def test_verdict_is_stated_and_consistent_with_the_findings() -> None:
    verdict_section = report().split("## Verdict", 1)[1]
    verdict = field(verdict_section, "Verdict")
    assert verdict in VERDICTS, verdict
    severities = {field(body, "Severity") for _, body in findings()}
    if verdict == "clean":
        assert not severities
    if "blocker" in severities:
        assert verdict == "blocked"


def test_readme_points_at_the_report() -> None:
    assert "docs/goldfish/" in (ROOT / "README.md").read_text()
