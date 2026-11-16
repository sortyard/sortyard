#!/usr/bin/env python3
"""Validate the requirements specification and refresh its generated parts.

Usage:
    python3 docs/requirements/tools/gen.py           refresh generated spans and the index
    python3 docs/requirements/tools/gen.py --check   write nothing; exit 1 on any problem

The requirement files are the source of truth. This script reads every ``*.md`` file in the
directory above it and

1. extracts each requirement from its heading and tag line;
2. checks ids, tag lines, acceptance criteria, cross-references, work packages and sizes;
3. checks the two cross-cutting rules (QLT-050, QLT-051): every divergence from the estate has
   a baseline, dimensions and a demonstration, and every measured criterion and milestone exit
   has both a target and a floor;
4. rewrites the text between ``<!--gen:KEY-->`` and ``<!--/gen-->`` markers;
5. writes ``requirements.json``.

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
PRODUCT = "01-product-definition.md"
FINDINGS = "11-coherence.md"
PLAN = "13-milestones.md"
DECISIONS = "15-open-decisions.md"
PARITY = "16-legacy-parity.md"
REGISTER = "18-divergences.md"
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
# Dimensions on which a divergence may claim to be better (18-divergences.md, section 1.3).
DIMENSIONS = (
    "throughput",
    "latency",
    "stall-rate",
    "recovery-time",
    "operator-actions",
    "failure-visibility",
    "safety",
    "install-effort",
    "upgrade-effort",
    "cost",
    "simplicity",
)
# Ways a divergence may be demonstrated, each with the first milestone at which it exists.
METHODS = {
    "replay": "MS2",
    "parity": "MS2",
    "ledger": "MS4",
    "benchmark": "MS1",
    "chaos": "MS2",
    "count": "MS1",
    "drill": "MS3",
    "usage": "MS0",
}
# Verdicts of the divergence register. "shown" entries must demonstrate that they are better;
# "kept" entries must name the requirements that keep the legacy behaviour.
VERDICTS = {
    "diverge": "shown",
    "diverge (reshaped)": "shown",
    "conditional on use": "shown",
    "keep legacy": "kept",
    "keep legacy (cut reversed)": "kept",
    "not a divergence": "kept",
}
# The verdict kind a legacy parity row needs from the entry it cites.
ROW_KIND = {"FIX": "shown", "DROP": "shown", "PACK": "kept", "OUT": "kept"}
STATUS = "**Status.** Default adopted as planning assumption (2026-11-12)."
OPEN_DECISIONS = ("1", "2", "3", "4")
COMPARED_MILESTONES = ("MS2", "MS3", "MS4", "MS5", "MS6", "MS7")

HEAD = re.compile(r"^### ([A-Z]{2,3}-\d{3}) — (.+)$")
TAG = re.compile(
    r"^\*\*(MS\d|LATER)\*\* · (WP\d+\.\d+|—) · "
    r"(MUST|SHOULD|LATER) · (KEEP|FIX|NEW)$"
)
REF = re.compile(r"\b((?:" + "|".join(AREAS) + r")-\d{3})\b")
CRITERION_REF = re.compile(r"\b((?:" + "|".join(AREAS) + r")-\d{3}) (AC\d+)\b")
LINK = re.compile(r"\]\(([0-9A-Za-z_./-]+\.(?:md|json|py))(?:#[^)]*)?\)")
MARK = re.compile(r"<!--gen:([a-z-]+)(?: ([^>]+?))?-->(.*?)<!--/gen-->", re.S)
MS_ROW = re.compile(r"^\| (MS\d) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| (.+) \|$")
WP_ROW = re.compile(r"^\| (WP\d+\.\d+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| (.+) \|$")
SIZE = re.compile(r"^(S|M|L|XL) · (\d+)(?: \(.+\))?$")
DEPENDENCY = re.compile(r"^(WP\d+\.\d+|MS\d gate|all of MS\d|OD-\d+)$")
# A quantity with a unit, a percentage or a percentile: the mark of a measured criterion.
QUANTITY = re.compile(
    r"\b\d[\d,.]*\s?(?:ms|s|sec|seconds?|min|minutes?|h|hours?|days?|weeks?"
    r"|KB|MB|GB|GiB|MiB|CPU)\b|\d\s?%|\bp\d\d\b"
)
POLICY = re.compile(r"\b(?:defaults?|policy)\b")
MEASURED = re.compile(r"^(.+?) Target: (.+?) Floor: (.+)$")
DEMONSTRATION = re.compile(
    r"^Demonstration \(([a-z]+), (MS\d)\) — (.+?) Target: (.+?) Floor: (.+)$"
)
LATER_PART = re.compile(r"^\(WP(\d+)\.\d+\) ")
BASELINE_ID = re.compile(r"\bBL-\d\d\b")
ENTRY_ID = re.compile(r"\bDIV-\d\d\b")
BASELINE_ROW = re.compile(r"^\| (BL-\d\d) \| ([^|]+) \| ([^|]+) \| (.+) \|$")
ENTRY_HEAD = re.compile(r"^### (DIV-\d\d) — (.+)$")
ENTRY_FIELD = re.compile(r"^- \*\*([A-Za-z ]+):\*\* (.+)$")
PARITY_ROW = re.compile(r"^\| (LP-\d{3}) \| (.+) \| (.+) \| ([A-Z]+) \| (.+) \|$")
EXIT_LINE = re.compile(r"^\d+\. ")
BLOCK_KEYS = {"areas", "scorecard", "divergence-index"}


def band(tasks: int) -> str:
    """Return the size label for an estimated number of tasks."""
    return next(label for label, low, high in BANDS if low <= tasks <= high)


def wp_key(wp: str) -> list[int]:
    """Sort key that orders WP3.10 after WP3.9."""
    return [int(part) for part in wp[2:].split(".")]


def sections(text: str, heading: str) -> dict[str, str]:
    """Split a file into the sections whose headings match ``heading`` (one capture group)."""
    found: dict[str, str] = {}
    pieces = re.split(rf"(?m)^(?={heading})", text)
    for piece in pieces[1:]:
        key = re.match(heading, piece)
        if key:
            found[key.group(1)] = piece
    return found


def parse_criterion(req: dict, label: str, text: str, errors: list[str]) -> dict | None:
    """Check one acceptance criterion; return its measured form when it has levels."""
    where = f"{req['file']}: {req['id']} {label}"
    has_target, has_floor = "Target:" in text, "Floor:" in text
    is_demo = text.startswith("Demonstration")
    if has_target != has_floor:
        errors.append(f"{where} has a target without a floor, or a floor without a target")
        return None
    if not has_target:
        if is_demo:
            errors.append(f"{where} is a demonstration with no target and floor")
        elif QUANTITY.search(text) and not POLICY.search(text):
            errors.append(
                f"{where} states a quantity as a bar without Target: and Floor: "
                "(a shipped policy default must say 'default')"
            )
        return None
    if "|" in text:
        errors.append(f"{where} contains '|', which breaks the scorecard table")
    later = LATER_PART.match(text)
    measured = {
        "criterion": label,
        "demonstration": is_demo,
        "method": None,
        "due": f"MS{later.group(1)}" if later else req["milestone"],
        "target": "",
        "floor": "",
        "baselines": sorted(set(BASELINE_ID.findall(text))),
    }
    if is_demo:
        demo = DEMONSTRATION.match(text)
        if not demo:
            errors.append(f"{where} is not 'Demonstration (<method>, MSn) — … Target: … Floor: …'")
            return None
        method, due, _, target, floor = demo.groups()
        if method not in METHODS:
            errors.append(f"{where} uses unknown method '{method}'")
        elif due < METHODS[method]:
            errors.append(f"{where} is due at {due}, before '{method}' exists ({METHODS[method]})")
        if req["milestone"] == "LATER" or due < req["milestone"]:
            errors.append(f"{where} is due at {due}, before its requirement ({req['milestone']})")
        if not measured["baselines"]:
            errors.append(f"{where} is a demonstration that cites no legacy baseline (BL-nn)")
        measured.update(method=method, due=due, target=target, floor=floor)
        return measured
    parts = MEASURED.match(text)
    if not parts:
        errors.append(f"{where} must read '<measure>. Target: <level>. Floor: <level>.'")
        return None
    measured.update(target=parts.group(2), floor=parts.group(3))
    return measured


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
            baseline = re.search(r"^Baseline: (.+)$", text_body, re.M)
            better = re.search(r"^Better on: (.+)$", text_body, re.M)
            req = {
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
                "baseline": baseline.group(1).strip() if baseline else None,
                "better_on": (
                    [part.strip() for part in better.group(1).rstrip(".").split(",")]
                    if better
                    else []
                ),
                "measured": [],
            }
            for label, text in criteria:
                measured = parse_criterion(req, label, text.strip(), errors)
                if measured:
                    req["measured"].append(measured)
            reqs[rid] = req
    return reqs


def check_divergent_requirements(reqs: dict[str, dict], errors: list[str]) -> None:
    """QLT-050 and QLT-051 at the level of one requirement."""
    for req in reqs.values():
        where = f"{req['file']}: {req['id']}"
        prose = "\n".join(line for line in req["statement"].split("\n") if "|" not in line)
        if QUANTITY.search(prose) and not POLICY.search(prose) and not req["measured"]:
            errors.append(
                f"{where} states a quantity in its statement but has no criterion with "
                "Target: and Floor: (a shipped policy default must say 'default')"
            )
        for dimension in req["better_on"]:
            if dimension not in DIMENSIONS:
                errors.append(f"{where} claims to be better on unknown dimension '{dimension}'")
        demos = [m for m in req["measured"] if m["demonstration"]]
        if req["origin"] != "FIX":
            if req["baseline"] or req["better_on"]:
                errors.append(f"{where} has Baseline: or Better on: but its origin is not FIX")
            continue
        if not req["baseline"]:
            errors.append(f"{where} is FIX (a divergence) and has no 'Baseline:' line")
        elif not BASELINE_ID.search(req["baseline"]):
            errors.append(f"{where} Baseline: cites no legacy baseline (BL-nn)")
        if not req["better_on"]:
            errors.append(f"{where} is FIX (a divergence) and has no 'Better on:' line")
        if not demos:
            errors.append(f"{where} is FIX (a divergence) and has no Demonstration criterion")


def parse_register(text: str, errors: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    """Read the legacy baselines and the divergence entries of the register."""
    baselines: dict[str, dict] = {}
    entries: dict[str, dict] = {}
    current: dict | None = None
    for line in text.split("\n"):
        row = BASELINE_ROW.match(line)
        if row:
            if row.group(1) in baselines:
                errors.append(f"{REGISTER}: baseline {row.group(1)} is listed twice")
            cells = [cell.strip() for cell in row.groups()[1:]]
            if not all(cells):
                errors.append(f"{REGISTER}: baseline {row.group(1)} has an empty cell")
            baselines[row.group(1)] = dict(
                zip(("baseline", "capture", "known"), cells, strict=True)
            )
            continue
        head = ENTRY_HEAD.match(line)
        if head:
            if head.group(1) in entries:
                errors.append(f"{REGISTER}: entry {head.group(1)} is listed twice")
            current = {"id": head.group(1), "title": head.group(2).strip(), "fields": {}}
            entries[head.group(1)] = current
            continue
        if line.startswith(("## ", "# ", "---")):
            current = None
        field = ENTRY_FIELD.match(line)
        if field and current is not None:
            current["fields"][field.group(1)] = field.group(2).strip()
    return baselines, entries


def check_register(
    baselines: dict[str, dict],
    entries: dict[str, dict],
    reqs: dict[str, dict],
    texts: dict[str, str],
    errors: list[str],
) -> None:
    """Every entry has the fields its verdict needs; every divergence is registered."""
    demonstrations = {
        (req["id"], m["criterion"])
        for req in reqs.values()
        for m in req["measured"]
        if m["demonstration"]
    }
    cited: set[tuple[str, str]] = set()
    mentioned: set[str] = set()
    for key, entry in entries.items():
        where = f"{REGISTER}: {key}"
        fields = entry["fields"]
        verdict = fields.get("Verdict", "")
        kind = VERDICTS.get(verdict)
        if kind is None:
            errors.append(f"{where} has unknown verdict '{verdict}'")
            continue
        entry["verdict"], entry["kind"] = verdict, kind
        needed = ["Covers", "Legacy baseline", "Sortyard"]
        needed += ["Better on", "Demonstration"] if kind == "shown" else ["Kept by"]
        if verdict == "conditional on use":
            needed.append("If used")
        for field in needed:
            if not fields.get(field):
                errors.append(f"{where} ({verdict}) has no '{field}' field")
        mentioned.update(REF.findall(" ".join(fields.values())))
        if kind == "kept":
            if not REF.search(fields.get("Kept by", "")):
                errors.append(f"{where} 'Kept by' names no requirement")
            continue
        if not BASELINE_ID.search(fields.get("Legacy baseline", "")):
            errors.append(f"{where} 'Legacy baseline' cites no baseline (BL-nn)")
        for dimension in fields.get("Better on", "").rstrip(".").split(","):
            if dimension.strip() not in DIMENSIONS:
                errors.append(f"{where} claims to be better on unknown '{dimension.strip()}'")
        refs = CRITERION_REF.findall(fields.get("Demonstration", ""))
        if not refs:
            errors.append(f"{where} 'Demonstration' names no criterion (REQ-nnn ACn)")
        for ref in refs:
            if ref not in demonstrations:
                errors.append(f"{where} cites {ref[0]} {ref[1]}, which is not a demonstration")
        cited.update(refs)
    for req in reqs.values():
        if req["origin"] == "FIX" and not any(rid == req["id"] for rid, _ in cited):
            errors.append(
                f"{req['file']}: {req['id']} is FIX but no entry of {REGISTER} demonstrates it"
            )
        if req["milestone"] == "LATER" and req["id"] not in mentioned:
            errors.append(
                f"{req['file']}: {req['id']} is deferred past 1.0; no entry of {REGISTER} covers it"
            )
    for ref in sorted(demonstrations - cited):
        errors.append(f"{REGISTER}: demonstration {ref[0]} {ref[1]} belongs to no entry")
    everything = "\n".join(texts.values())
    for key in baselines:
        if len(re.findall(rf"\b{key}\b", everything)) < 2:
            errors.append(f"{REGISTER}: baseline {key} is never used")


def check_citations(texts: dict[str, str], entries: dict[str, dict], errors: list[str]) -> None:
    """Parity rows, cuts and findings that diverge must cite a fitting register entry."""
    kinds = {key: entry.get("kind") for key, entry in entries.items()}
    for line in texts[PARITY].split("\n"):
        if not line.startswith("| LP-"):
            continue
        row = PARITY_ROW.match(line)
        if not row or row.group(4) not in ("KEEP", *ROW_KIND):
            errors.append(f"{PARITY}: malformed row or unknown disposition: {line[:60]}")
            continue
        disposition = row.group(4)
        if disposition == "KEEP":
            continue
        fitting = [
            key for key in ENTRY_ID.findall(row.group(5)) if kinds.get(key) == ROW_KIND[disposition]
        ]
        if not fitting:
            errors.append(
                f"{PARITY}: {row.group(1)} is {disposition} and cites no divergence entry "
                f"whose verdict is of the '{ROW_KIND[disposition]}' kind"
            )
    product = texts[PRODUCT].split("\n## 5. ", 1)[-1].split("\n## 6. ", 1)[0]
    for line in product.split("\n"):
        cells = [cell.strip() for cell in line.strip("|").split(" | ")]
        if not line.startswith("| ") or len(cells) < 3 or set(cells[1]) <= set("-"):
            continue
        if re.search(r"(?i)replaced|dropped|out of the product", cells[1]) and not ENTRY_ID.search(
            line
        ):
            errors.append(
                f"{PRODUCT}: row '{cells[0][:50]}' diverges and cites no divergence entry"
            )
    cut_list = sections(texts[DECISIONS], r"## OD-(\d+) ").get("3", "")
    for line in cut_list.split("\n"):
        if (
            line.startswith("| ")
            and not line.startswith(("| Cut ", "|---"))
            and not ENTRY_ID.search(line)
        ):
            errors.append(f"{DECISIONS}: OD-3 cut '{line[2:50]}' cites no divergence entry")
    for number, section in sections(texts[FINDINGS], r"## CF-(\d\d) ").items():
        found = re.search(r"^\*\*Divergence\.\*\* (.+)$", section, re.M)
        if not found:
            errors.append(f"{FINDINGS}: CF-{number} has no '**Divergence.**' line")
        elif not found.group(1).startswith("None") and not ENTRY_ID.search(found.group(1)):
            errors.append(f"{FINDINGS}: CF-{number} names neither an entry nor 'None'")


def check_decisions(text: str, errors: list[str]) -> None:
    """Every decision carries its status; the irreversible ones stay open with a confirm-by."""
    for number, section in sections(text, r"## OD-(\d+) ").items():
        status = next((line for line in section.split("\n") if line.startswith("**Status.**")), "")
        if not status.startswith(STATUS):
            errors.append(f"{DECISIONS}: OD-{number} lacks '{STATUS}'")
        if number in OPEN_DECISIONS and not (
            "Stays open" in status and re.search(r"confirm by the MS\d gate", status)
        ):
            errors.append(
                f"{DECISIONS}: OD-{number} must say 'Stays open' and 'confirm by the MSn gate'"
            )


def check_references(
    texts: dict[str, str],
    reqs: dict[str, dict],
    baselines: dict[str, dict],
    entries: dict[str, dict],
    errors: list[str],
) -> None:
    """Every requirement, criterion, finding, decision, baseline, entry and file must exist."""
    findings = set(re.findall(r"^## CF-(\d{2}) ", texts[FINDINGS], re.M))
    decisions = set(re.findall(r"^## OD-(\d+) ", texts[DECISIONS], re.M))
    criteria = {
        (req["id"], item.split(":", 1)[0]) for req in reqs.values() for item in req["acceptance"]
    }
    for name, text in texts.items():
        for n, line in enumerate(text.split("\n"), 1):
            for ref in REF.findall(line):
                if ref not in reqs:
                    errors.append(f"{name}:{n}: unknown requirement {ref}")
            for ref in CRITERION_REF.findall(line):
                if ref[0] in reqs and ref not in criteria:
                    errors.append(f"{name}:{n}: {ref[0]} has no {ref[1]}")
            for finding in re.findall(r"\bCF-(\d{2})\b", line):
                if finding not in findings:
                    errors.append(f"{name}:{n}: unknown finding CF-{finding}")
            for decision in re.findall(r"\bOD-(\d+)\b", line):
                if decision not in decisions:
                    errors.append(f"{name}:{n}: unknown decision OD-{decision}")
            for baseline in BASELINE_ID.findall(line):
                if baseline not in baselines:
                    errors.append(f"{name}:{n}: unknown baseline {baseline}")
            for entry in ENTRY_ID.findall(line):
                if entry not in entries:
                    errors.append(f"{name}:{n}: unknown divergence entry {entry}")
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
                "demonstrations": [],
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
        for measured in req["measured"]:
            if not measured["demonstration"]:
                continue
            if measured["due"] in milestones:
                milestones[measured["due"]]["demonstrations"].append(
                    f"{req['id']} {measured['criterion']}"
                )
            else:
                errors.append(
                    f"{req['file']}: {req['id']} demonstration is due at an unknown milestone"
                )
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


def check_exits(text: str, milestones: dict[str, dict], errors: list[str]) -> None:
    """Measured exit criteria have two levels; each exit lists the comparisons due."""
    for ms, section in sections(text, r"## (MS\d) — ").items():
        exit_part = section.split("**Exit criteria", 1)[-1].split("\n| WP |", 1)[0]
        for line in exit_part.split("\n"):
            if not EXIT_LINE.match(line):
                continue
            levels = "Target:" in line and "Floor:" in line
            if QUANTITY.search(line) and not POLICY.search(line) and not levels:
                errors.append(
                    f"{PLAN}: {ms} exit criterion '{line[:48]}…' states a quantity "
                    "without Target: and Floor:"
                )
        due = milestones.get(ms, {}).get("demonstrations", [])
        listed = re.search(rf"\*\*Comparisons\.\*\*.*<!--gen:demos {ms}-->", exit_part)
        if ms in COMPARED_MILESTONES and not due:
            errors.append(f"{PLAN}: {ms} has no demonstration due; MS2 to MS7 must compare")
        if due and not listed:
            errors.append(f"{PLAN}: {ms} exit omits its comparisons ('<!--gen:demos {ms}-->')")


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


def scorecard(reqs: dict[str, dict]) -> str:
    """Build the table of every measured criterion, ordered by the milestone it is due at."""
    rows = [
        "| Criterion | Requirement | Method | Due | Target | Floor |",
        "|---|---|---|---|---|---|",
    ]
    found = [(m["due"], req, m) for req in reqs.values() for m in req["measured"]]
    for due, req, m in sorted(found, key=lambda item: item[0]):
        method = m["method"] or "test"
        target, floor = m["target"].rstrip("."), m["floor"].rstrip(".")
        name = f"{req['id']} {m['criterion']}"
        rows.append(f"| {name} | {req['title']} | {method} | {due} | {target} | {floor} |")
    return "\n".join(rows)


def divergence_index(reqs: dict[str, dict], entries: dict[str, dict]) -> str:
    """Build the table of FIX requirements with their register entries and demonstrations."""
    rows = [
        "| Requirement | Title | Better on | Entry | Demonstrations (due) |",
        "|---|---|---|---|---|",
    ]
    for req in reqs.values():
        if req["origin"] != "FIX":
            continue
        mine = [
            key
            for key, entry in entries.items()
            if any(
                rid == req["id"]
                for rid, _ in CRITERION_REF.findall(entry["fields"].get("Demonstration", ""))
            )
        ]
        demos = ", ".join(
            f"{m['criterion']} ({m['due']})" for m in req["measured"] if m["demonstration"]
        )
        better = ", ".join(req["better_on"])
        rows.append(f"| {req['id']} | {req['title']} | {better} | {', '.join(mine)} | {demos} |")
    return "\n".join(rows)


def main() -> int:
    """Validate, then refresh the generated spans and the index (or compare, with --check)."""
    check_only = "--check" in sys.argv[1:]
    texts = {path.name: path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("*.md"))}
    errors: list[str] = []
    reqs = parse_requirements(texts, errors)
    baselines, entries = parse_register(texts[REGISTER], errors)
    check_references(texts, reqs, baselines, entries, errors)
    check_divergent_requirements(reqs, errors)
    check_register(baselines, entries, reqs, texts, errors)
    check_citations(texts, entries, errors)
    check_decisions(texts[DECISIONS], errors)
    milestones, packages = parse_plan(texts[PLAN], reqs, errors)
    check_exits(texts[PLAN], milestones, errors)
    later = [req["id"] for req in reqs.values() if req["milestone"] == "LATER"]
    planned = len(reqs) - len(later)
    total_tasks = sum(package["estimated_tasks"] for package in packages.values())
    parity_rows = len(re.findall(r"^\| LP-\d{3} \|", texts[PARITY], re.M))
    measured = [m for req in reqs.values() for m in req["measured"]]
    demos = [m for m in measured if m["demonstration"]]
    verdicts = Counter(entry.get("verdict", "unknown") for entry in entries.values())
    verdict_text = f"{len(entries)} entries: " + ", ".join(
        f"{verdicts[verdict]} {verdict}" for verdict in VERDICTS if verdicts[verdict]
    )
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
        if key == "demos" and arg in milestones:
            return ", ".join(milestones[arg]["demonstrations"])
        if key == "weeks" and arg:
            return str(round(total_tasks / (float(arg) * 7)))
        simple = {
            "later": ", ".join(later),
            "areas": area_table(reqs),
            "scorecard": scorecard(reqs),
            "divergence-index": divergence_index(reqs, entries),
            "verdicts": verdict_text,
            "measured": str(len(measured)),
            "demo-count": str(len(demos)),
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
        "baselines": baselines,
        "divergences": [
            {"id": key, "title": entry["title"], "verdict": entry.get("verdict"), **entry["fields"]}
            for key, entry in entries.items()
        ],
        "requirements": list(reqs.values()),
    }
    fresh[INDEX] = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    stale = [
        name
        for name, text in fresh.items()
        if not (ROOT / name).is_file() or (ROOT / name).read_text(encoding="utf-8") != text
    ]
    per_milestone = ", ".join(f"{ms} {len(m['requirements'])}" for ms, m in milestones.items())
    origins = Counter(req["origin"] for req in reqs.values())
    print(f"requirements: {len(reqs)} ({per_milestone}, LATER {len(later)})")
    print(f"work packages: {len(packages)}; estimated tasks: {total_tasks}")
    print(f"legacy parity rows: {parity_rows}; baselines: {len(baselines)}")
    print(f"divergences: {origins['FIX']} FIX requirements; {verdict_text}")
    print(f"measured criteria: {len(measured)}, of which {len(demos)} demonstrations")
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
