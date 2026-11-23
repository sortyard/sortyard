"""Acceptance: AGENTS.md is a repo brief a zero-context agent can build from (§11, corpus M1.1).

The brief has to stay true as the repo moves, so these tests tie it to the tree: every
service, every package and every top-level directory appears in its architecture map; every
path it names exists; it gives the exact build-loop commands CI runs and the replica command;
and the friction found proving it is filed as findings.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRIEF = ROOT / "AGENTS.md"
FINDINGS = ROOT / "docs" / "findings" / "contributor-foundation.md"


def brief() -> str:
    return BRIEF.read_text()


def section(name: str) -> str:
    text = brief()
    assert f"\n## {name}\n" in text, f"missing section: ## {name}"
    return text.split(f"\n## {name}\n", 1)[1].split("\n## ", 1)[0]


def test_brief_has_its_sections() -> None:
    for name in (
        "Architecture map",
        "Build loop",
        "Local replica",
        "Making a change",
        "Conventions",
        "Known gaps",
    ):
        section(name)


def test_claude_md_points_at_the_brief() -> None:
    assert "AGENTS.md" in (ROOT / "CLAUDE.md").read_text()


def test_architecture_map_names_every_service() -> None:
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    arch = section("Architecture map")
    for script in scripts:
        assert f"`{script}`" in arch, script


def test_architecture_map_covers_every_package_and_top_level_directory() -> None:
    arch = section("Architecture map")
    packages = sorted(
        p.parent.relative_to(ROOT).as_posix()
        for p in (ROOT / "src" / "sortyard").rglob("__init__.py")
    )
    for package in packages:
        assert f"`{package}/`" in arch, package
    # Tracked files plus new, not-ignored ones (a new directory must be mapped before commit).
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    top = {path.split("/", 1)[0] for path in files if "/" in path}
    for directory in sorted(top):
        assert f"`{directory}/" in arch, directory


PATH_LIKE = re.compile(r"`((?:\.?[\w.-]+/)+[\w.-]*|[\w.-]+\.(?:md|py|yaml|yml|toml|sh|sql|json))`")


# Named by the brief precisely because they are missing (its Known gaps section).
KNOWN_MISSING: set[str] = set()


def exists(name: str) -> bool:
    if "NNNN" in name:  # a naming pattern, not a file
        return True
    if "/" not in name.rstrip("/"):  # a bare file name, named next to its directory
        return any(ROOT.rglob(name))
    return (ROOT / name.rstrip("/")).exists()


def test_every_path_the_brief_names_exists() -> None:
    names = set(PATH_LIKE.findall(brief()))
    assert len(names) > 15, "the brief should point at concrete files"
    assert names >= KNOWN_MISSING, "a known gap was fixed: drop it from the brief and here"
    missing = sorted(n for n in names - KNOWN_MISSING if not exists(n))
    assert not missing, f"AGENTS.md names paths that do not exist: {missing}"


def test_build_loop_gives_the_commands_ci_runs() -> None:
    loop = section("Build loop")
    for command in (
        "pip install -e '.[dev]'",
        "ruff check .",
        "ruff format --check .",
        "mypy",
        "pytest tests",
        "python -m sortyard.models.codegen --check",
    ):
        assert command in loop, command
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    for command in ("ruff check .", "ruff format --check .", "mypy", "pytest tests"):
        assert command in ci, command


def test_local_replica_section_gives_the_one_command() -> None:
    replica = section("Local replica")
    for command in (
        "./replica/replica.sh up",
        "./replica/replica.sh smoke",
        "./replica/replica.sh down",
    ):
        assert command in replica, command


def test_readme_points_at_the_brief_and_the_replica() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "AGENTS.md" in readme
    assert "./replica/replica.sh up" in readme


FINDING = re.compile(r"^### (CF-\d{2}) — \S.*$", re.MULTILINE)


def test_friction_is_filed_as_findings() -> None:
    text = FINDINGS.read_text()
    matches = list(FINDING.finditer(text))
    assert matches, "no findings filed"
    ids = [m.group(1) for m in matches]
    assert len(ids) == len(set(ids))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end]
        for field in ("Against", "Severity", "Evidence", "What would fix it"):
            assert re.search(rf"^\*\*{field}:\*\* *\S", body, re.MULTILINE), (m.group(1), field)
        severity = re.search(r"^\*\*Severity:\*\* *(\w+)", body, re.MULTILINE)
        assert severity and severity.group(1) in {"blocker", "major", "minor"}
    assert "docs/findings/contributor-foundation.md" in section("Known gaps")
