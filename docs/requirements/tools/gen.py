#!/usr/bin/env python3
"""Validate the requirements specification and refresh its generated parts.

Usage:
    python3 docs/requirements/tools/gen.py           refresh generated spans and the index
    python3 docs/requirements/tools/gen.py --check   write nothing; exit 1 on any problem

The requirement files are the source of truth. This script reads every ``*.md`` file in the
directory above it and

1. extracts each requirement from its heading and tag line;
2. checks ids, tag lines, acceptance criteria, cross-references, work packages and sizes;
3. rewrites the text between ``<!--gen:KEY-->`` and ``<!--/gen-->`` markers;
4. writes ``requirements.json``.

Edit the requirement files and the plan by hand; never edit the text inside a marker pair.
Only the Python standard library is needed.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = "13-milestones.md"
FINDINGS = "11-coherence.md"
DECISIONS = "15-open-decisions.md"
PARITY = "16-legacy-parity.md"
INDEX = "requirements.json"

AREAS = {
    "TRK": "Work tracking",
    "RDY": "Readiness, preflight, release",
    "GRM": "Grooming and shaping",
    "SCH": "Scheduling",
    "EXE": "Execution",
    "CRD": "Credentials",
    "FLW": "Workflows and chains",
    "MRG": "Landing and merge safety",
    "CIH": "CI and main-branch health",
    "DLV": "Delivery verification",
    "REC": "Recovery and no silent failure",
    "API": "REST API",
    "MCP": "MCP",
    "CLI": "CLI",
    "IAM": "Identity, authorisation, audit",
    "UI": "Console",
    "OBS": "Observability",
    "DEF": "Definitions and configuration",
    "EXT": "Extension points",
    "DEP": "Install, upgrade, operate",
    "MIG": "Migration",
    "QLT": "Quality bar",
}
# Work-package size bands: label, fewest and most one-PR tasks.
BANDS = (("S", 1, 5), ("M", 6, 10), ("L", 11, 18), ("XL", 19, 10**6))

HEAD = re.compile(r"^### ([A-Z]{2,3}-\d{3}) — (.+)$")
TAG = re.compile(
    r"^\*\*(MS\d|LATER)\*\* · (WP\d+\.\d+|—) · "
    r"(MUST|SHOULD|LATER) · (KEEP|FIX|NEW)$"
)
REF = re.compile(r"\b((?:" + "|".join(AREAS) + r")-\d{3})\b")
LINK = re.compile(r"\]\(([0-9A-Za-z_./-]+\.(?:md|json|py))(?:#[^)]*)?\)")
MARK = re.compile(r"<!--gen:([a-z-]+)(?: ([^>]+?))?-->(.*?)<!--/gen-->", re.S)
MS_ROW = re.compile(r"^\| (MS\d) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| (.+) \|$")
WP_ROW = re.compile(r"^\| (WP\d+\.\d+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| (.+) \|$")
SIZE = re.compile(r"^(S|M|L|XL) · (\d+)(?: \(.+\))?$")
DEPENDENCY = re.compile(r"^(WP\d+\.\d+|MS\d gate|all of MS\d|OD-\d+)$")
BLOCK_KEYS = {"areas"}


def band(tasks: int) -> str:
    """Return the size label for an estimated number of tasks."""
    return next(label for label, low, high in BANDS if low <= tasks <= high)


def wp_key(wp: str) -> list[int]:
    """Sort key that orders WP3.10 after WP3.9."""
    return [int(part) for part in wp[2:].split(".")]


def parse_requirements(texts: dict[str, str], errors: list[str]) -> dict[str, dict]:
    """Extract every requirement, in file order, and check its shape."""
    reqs: dict[str, dict] = {}
    for name, text in texts.items():
        lines = text.split("\n")
        for i, line in enumerate(lines):
            head = HEAD.match(line)
            if not head:
                continue
            rid, title = head.group(1), head.group(2).strip()
            tag = TAG.match(lines[i + 1].strip()) if i + 1 < len(lines) else None
            if not tag:
                errors.append(f"{name}:{i + 2}: {rid} has no valid tag line")
                continue
            milestone, wp, priority, origin = tag.groups()
            body: list[str] = []
            for nxt in lines[i + 2 :]:
                if nxt.startswith(("### ", "## ", "# ")) or nxt.strip() == "---":
                    break
                body.append(nxt)
            text_body = "\n".join(body)
            area = rid.split("-")[0]
            if rid in reqs:
                errors.append(f"{name}: duplicate id {rid} (also in {reqs[rid]['file']})")
            if area not in AREAS:
                errors.append(f"{name}: unknown area in {rid}")
            if milestone == "LATER":
                if wp != "—" or priority != "LATER":
                    errors.append(f"{name}: {rid} is LATER and must read '— · LATER'")
            elif priority == "LATER":
                errors.append(f"{name}: {rid} has LATER priority inside {milestone}")
            elif not wp.startswith(f"WP{milestone[2:]}."):
                errors.append(f"{name}: {rid} work package {wp} is not in {milestone}")
            if not text_body.strip() or not text_body.strip().split("\n")[0].strip():
                errors.append(f"{name}: {rid} has no statement")
            if not re.search(r"^- AC1: ", text_body, re.M):
                errors.append(f"{name}: {rid} has no AC1")
            if not re.search(r"^Source: ", text_body, re.M):
                errors.append(f"{name}: {rid} has no Source line")
            criteria = re.findall(r"^- (AC\d+): (.+)$", text_body, re.M)
            source = re.search(r"^Source: (.+)$", text_body, re.M)
            reqs[rid] = {
                "id": rid,
                "title": title,
                "area": area,
                "file": name,
                "milestone": milestone,
                "work_package": None if wp == "—" else wp,
                "priority": priority,
                "origin": origin,
                "statement": re.split(r"^- AC1: ", text_body, maxsplit=1, flags=re.M)[0].strip(),
                "acceptance": [f"{label}: {text.strip()}" for label, text in criteria],
                "source": source.group(1).strip() if source else "",
            }
    return reqs


def check_references(texts: dict[str, str], reqs: dict[str, dict], errors: list[str]) -> None:
    """Every requirement, finding, decision and file named anywhere must exist."""
    findings = set(re.findall(r"^## CF-(\d{2}) ", texts[FINDINGS], re.M))
    decisions = set(re.findall(r"^## OD-(\d+) ", texts[DECISIONS], re.M))
    for name, text in texts.items():
        for n, line in enumerate(text.split("\n"), 1):
            for ref in REF.findall(line):
                if ref not in reqs:
                    errors.append(f"{name}:{n}: unknown requirement {ref}")
            for finding in re.findall(r"\bCF-(\d{2})\b", line):
                if finding not in findings:
                    errors.append(f"{name}:{n}: unknown finding CF-{finding}")
            for decision in re.findall(r"\bOD-(\d+)\b", line):
                if decision not in decisions:
                    errors.append(f"{name}:{n}: unknown decision OD-{decision}")
            for link in LINK.findall(line):
                if not (ROOT / link).is_file() and link != INDEX:
                    errors.append(f"{name}:{n}: link to missing file {link}")
    rows = re.findall(r"^\| (LP-\d{3}) \|", texts[PARITY], re.M)
    repeated = sorted(row for row, count in Counter(rows).items() if count > 1)
    if repeated:
        errors.append(f"{PARITY}: repeated rows {repeated}")


def parse_plan(text: str, reqs: dict[str, dict], errors: list[str]) -> tuple[dict, dict]:
    """Read the milestone table and the work-package tables of the plan."""
    milestones: dict[str, dict] = {}
    packages: dict[str, dict] = {}
    for line in text.split("\n"):
        row = MS_ROW.match(line)
        if row:
            milestones[row.group(1)] = {
                "name": row.group(2).strip(),
                "release": row.group(3).strip(),
                "depends_on": row.group(5).strip(),
                "estimated_tasks": 0,
                "work_packages": [],
                "requirements": [],
            }
            continue
        row = WP_ROW.match(line)
        if not row:
            continue
        wp, name, depends, size = (row.group(n).strip() for n in (1, 2, 3, 4))
        parsed = SIZE.match(size)
        if not parsed:
            errors.append(f"{PLAN}: {wp} size {size!r} is not '<S|M|L|XL> · <tasks>'")
            continue
        label, tasks = parsed.group(1), int(parsed.group(2))
        if band(tasks) != label:
            errors.append(f"{PLAN}: {wp} says {label} for {tasks} tasks; the band is {band(tasks)}")
        needs = [] if depends == "—" else [part.strip() for part in depends.split(",")]
        for need in needs:
            if not DEPENDENCY.match(need):
                errors.append(f"{PLAN}: {wp} depends on {need!r}, which is not a known form")
        packages[wp] = {
            "milestone": f"MS{wp[2:].split('.')[0]}",
            "name": name,
            "depends_on": needs,
            "size": label,
            "estimated_tasks": tasks,
            "requirements": [],
        }
    for req in reqs.values():
        if req["milestone"] in milestones:
            milestones[req["milestone"]]["requirements"].append(req["id"])
        elif req["milestone"] != "LATER":
            errors.append(f"{req['file']}: {req['id']} names {req['milestone']}, not in the plan")
        wp = req["work_package"]
        if wp and wp in packages:
            packages[wp]["requirements"].append(req["id"])
        elif wp:
            errors.append(f"{req['file']}: {req['id']} names {wp}, which the plan does not have")
    for wp, package in packages.items():
        for need in package["depends_on"]:
            if need.startswith("WP") and need not in packages:
                errors.append(f"{PLAN}: {wp} depends on {need}, which the plan does not have")
        if len(package["requirements"]) > package["estimated_tasks"]:
            errors.append(f"{PLAN}: {wp} has more requirements than estimated tasks")
        if package["milestone"] not in milestones:
            errors.append(f"{PLAN}: {wp} belongs to no milestone in the overview table")
            continue
        milestones[package["milestone"]]["work_packages"].append(wp)
        milestones[package["milestone"]]["estimated_tasks"] += package["estimated_tasks"]
    return milestones, packages


def area_table(reqs: dict[str, dict]) -> str:
    """Build the per-area count table for the index page."""
    rows = [
        "| Area | Name | Requirements | MUST | SHOULD | LATER | KEEP | FIX | NEW |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    cols = ("MUST", "SHOULD", "LATER", "KEEP", "FIX", "NEW")
    total: Counter[str] = Counter()
    for area, label in AREAS.items():
        mine = [req for req in reqs.values() if req["area"] == area]
        count = Counter([req["priority"] for req in mine] + [req["origin"] for req in mine])
        total.update(count)
        total["n"] += len(mine)
        cells = " | ".join(str(count[col]) for col in cols)
        rows.append(f"| {area} | {label} | {len(mine)} | {cells} |")
    cells = " | ".join(str(total[col]) for col in cols)
    rows.append(f"| | **Total** | **{total['n']}** | {cells} |")
    return "\n".join(rows)


def main() -> int:
    """Validate, then refresh the generated spans and the index (or compare, with --check)."""
    check_only = "--check" in sys.argv[1:]
    texts = {path.name: path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("*.md"))}
    errors: list[str] = []
    reqs = parse_requirements(texts, errors)
    check_references(texts, reqs, errors)
    milestones, packages = parse_plan(texts[PLAN], reqs, errors)
    later = [req["id"] for req in reqs.values() if req["milestone"] == "LATER"]
    planned = len(reqs) - len(later)
    total_tasks = sum(package["estimated_tasks"] for package in packages.values())
    parity_rows = len(re.findall(r"^\| LP-\d{3} \|", texts[PARITY], re.M))
    used: set[str] = set()

    def value(key: str, arg: str, where: str) -> str:
        if key == "req":
            used.add(arg)
            ids = packages.get(arg, {}).get("requirements", [])
            if not ids:
                errors.append(f"{where}: work package {arg} has no requirements")
            return ", ".join(ids)
        if key == "size" and arg in milestones:
            ids = milestones[arg]["requirements"]
            must = sum(1 for rid in ids if reqs[rid]["priority"] == "MUST")
            tasks = milestones[arg]["estimated_tasks"]
            return f"≈ {tasks} tasks · {len(ids)} req ({must} MUST)"
        if key == "weeks" and arg:
            return str(round(total_tasks / (float(arg) * 7)))
        simple = {
            "later": ", ".join(later),
            "areas": area_table(reqs),
            "total-tasks": str(total_tasks),
            "planned-reqs": str(planned),
            "all-reqs": str(len(reqs)),
            "parity-rows": str(parity_rows),
        }
        if key not in simple:
            errors.append(f"{where}: unknown generated span '{key} {arg}'".rstrip())
            return ""
        return simple[key]

    fresh: dict[str, str] = {}
    for name, text in texts.items():

        def fill(match: re.Match[str], where: str = name) -> str:
            key, arg = match.group(1), match.group(2) or ""
            new = value(key, arg, where)
            if key in BLOCK_KEYS:
                new = f"\n\n{new}\n\n"
            opening = f"<!--gen:{key} {arg}-->" if arg else f"<!--gen:{key}-->"
            return f"{opening}{new}<!--/gen-->"

        fresh[name] = MARK.sub(fill, text)
    for wp in sorted(set(packages) - used, key=wp_key):
        if packages[wp]["requirements"]:
            errors.append(f"{PLAN}: {wp} has requirements but no '<!--gen:req {wp}-->' span")
    index = {
        "generated_by": "docs/requirements/tools/gen.py",
        "count": len(reqs),
        "milestones": {**milestones, "LATER": {"requirements": later}},
        "work_packages": {wp: packages[wp] for wp in sorted(packages, key=wp_key)},
        "requirements": list(reqs.values()),
    }
    fresh[INDEX] = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    stale = [
        name
        for name, text in fresh.items()
        if not (ROOT / name).is_file() or (ROOT / name).read_text(encoding="utf-8") != text
    ]
    per_milestone = ", ".join(f"{ms} {len(m['requirements'])}" for ms, m in milestones.items())
    print(f"requirements: {len(reqs)} ({per_milestone}, LATER {len(later)})")
    print(f"work packages: {len(packages)}; estimated tasks: {total_tasks}")
    print(f"legacy parity rows: {parity_rows}")
    if check_only and stale and not errors:
        errors.append(f"generated content is out of date in {stale}; run without --check")
    if errors:
        print(f"\n{len(errors)} problem(s):")
        for error in errors:
            print(f"  {error}")
        return 1
    if not check_only:
        for name in stale:
            (ROOT / name).write_text(fresh[name], encoding="utf-8")
        print("refreshed: " + (", ".join(stale) if stale else "nothing to change"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
