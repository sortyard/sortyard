#!/usr/bin/env python3
"""Validate and render the current requirements baseline; no network/runtime mutations.

python3 docs/requirements/tools/gen.py [--check]
Historical source is evidence only. Current authored records/contract artifacts drive outputs.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text())


def duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    return {x for x in values if x in seen or seen.add(x)}


def walk_refs(value):
    if isinstance(value, dict):
        if "$ref" in value:
            yield value["$ref"]
        for child in value.values():
            yield from walk_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_refs(child)


def resolve_pointer(document: dict, pointer: str):
    node = document
    for part in pointer.removeprefix("#/").split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def validate(
    source: dict,
    plan: dict,
    catalog: dict,
    actions: dict,
    api: dict,
    schemas: dict,
    legacy: dict,
    coverage: dict,
) -> list[str]:
    errors: list[str] = []
    reqs = source["requirements"]
    ids = [r["id"] for r in reqs]
    for rid in duplicates(ids):
        errors.append(f"duplicate requirement {rid}")
    known = set(ids)
    original = {r["id"] for r in legacy["requirements"]}
    if set(source["legacy_requirement_ids"]) != original:
        errors.append("legacy identity inventory differs from preserved draft")
    if not original <= known:
        errors.append(f"lost legacy requirement IDs: {sorted(original - known)}")
    if set(source["amended_ids"]) != {r["id"] for r in reqs if r["reconciliation"] == "amended"}:
        errors.append("amendment index differs from explicit records")
    milestones = {m["id"]: m for m in plan["milestones"]}
    for mid in duplicates([m["id"] for m in plan["milestones"]]):
        errors.append(f"duplicate milestone {mid}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(mid):
        if mid not in milestones:
            errors.append(f"unknown milestone dependency {mid}")
            return
        if mid in visiting:
            errors.append(f"milestone cycle at {mid}")
            return
        if mid in visited:
            return
        visiting.add(mid)
        for dep in milestones[mid]["depends_on"]:
            visit(dep)
        visiting.remove(mid)
        visited.add(mid)

    for mid, milestone in milestones.items():
        visit(mid)
        if not milestone.get("exit_criteria"):
            errors.append(f"missing exit criteria {mid}")
    packages = {p["id"]: p for p in plan["work_packages"]}
    package_members: list[str] = []
    for package in packages.values():
        if package["milestone"] not in milestones:
            errors.append(f"unknown package milestone {package['id']}")
        for rid in package["requirement_ids"]:
            if rid not in known:
                errors.append(f"unknown package requirement {rid}")
            package_members.append(rid)
    for rid in duplicates(package_members):
        errors.append(f"requirement assigned to multiple packages {rid}")
    for req in reqs:
        rid = req["id"]
        if not re.fullmatch(r"[A-Z]{2,4}-\d{3}", rid):
            errors.append(f"invalid requirement ID {rid}")
        for field in ("title", "statement", "source", "acceptance"):
            if not req.get(field):
                errors.append(f"missing {field} in {rid}")
        if req["reconciliation"] not in ("retained", "amended", "new"):
            errors.append(f"invalid reconciliation {rid}")
        if rid in original and req["reconciliation"] == "new":
            errors.append(f"legacy ID reused as new {rid}")
        if rid not in original and req["reconciliation"] != "new":
            errors.append(f"new ID falsely claims legacy provenance {rid}")
        if req["reconciliation"] == "amended" and not req.get("amendment_reason"):
            errors.append(f"missing amendment reason {rid}")
        if req["milestone"] != "LATER":
            if req["milestone"] not in milestones or rid not in package_members:
                errors.append(f"unassigned requirement {rid}")
            p = packages.get(req.get("work_package"), {})
            if p.get("milestone") != req["milestone"]:
                errors.append(f"wrong package for {rid}")
    kinds = [r["kind"] for r in catalog["resource_types"]]
    for kind in duplicates(kinds):
        errors.append(f"duplicate resource kind {kind}")
    for resource in catalog["resource_types"]:
        kind = resource["kind"]
        if resource["scope"] not in ("installation", "workspace", "project", "external"):
            errors.append(f"unknown scope {kind}")
        if not resource.get("authority") or not resource.get("required_domain_fields"):
            errors.append(f"missing ownership or fields {kind}")
        states = set(resource["lifecycle"])
        transitions = resource.get("transitions", {})
        if resource["immutable"] or resource["external_state_contract"]:
            if transitions:
                errors.append(f"local mutable transition on immutable/external {kind}")
        elif set(transitions) != states:
            errors.append(f"state-machine coverage missing {kind}")
        for before, afters in transitions.items():
            if before not in states or not set(afters) <= states:
                errors.append(f"invalid lifecycle edge {kind}:{before}")
        if "Domain" + kind not in schemas["$defs"]:
            errors.append(f"missing domain data schema {kind}")
    for edge in catalog["edge_types"]:
        if not set(edge["source_kinds"] + edge["target_kinds"]) <= set(kinds):
            errors.append(f"unknown relationship endpoint in {edge['type']}")
    action_ids = [a["id"] for a in actions["actions"]]
    for aid in duplicates(action_ids):
        errors.append(f"duplicate action {aid}")
    api_ops = [op["operationId"] for item in api["paths"].values() for op in item.values()]
    for oid in duplicates(api_ops):
        errors.append(f"duplicate API operation {oid}")
    for path, item in api["paths"].items():
        for operation in item.values():
            if not operation.get("security"):
                errors.append(f"unauthenticated control operation {operation['operationId']}")
            needed = set(re.findall(r"\{([^}]+)\}", path))
            supplied = {
                p["name"]
                for p in operation.get("parameters", [])
                if p["in"] == "path" and p.get("required")
            }
            if needed != supplied:
                errors.append(f"path parameters disagree {operation['operationId']}")
    for action in actions["actions"]:
        if action["target_kind"] not in kinds:
            errors.append(f"unknown target kind {action['id']}")
        for field in ("arguments_schema", "result_schema"):
            if action[field] not in api["components"]["schemas"]:
                errors.append(f"unknown {field} in {action['id']}")
        if set(action["transports"]) != {"ui", "rest", "mcp", "cli"}:
            errors.append(f"transport parity missing {action['id']}")
        if action["api_operation_id"] not in api_ops:
            errors.append(f"unknown public API mapping {action['id']}")
        if not action.get("invariants") or not action.get("authority_owner"):
            errors.append(f"unowned/unguarded action {action['id']}")
    for label, document in (("api", api), ("domain", schemas)):
        for pointer in walk_refs(document):
            if not pointer.startswith("#/"):
                errors.append(f"unregistered external schema reference {label}:{pointer}")
                continue
            try:
                resolve_pointer(document, pointer)
            except (KeyError, TypeError):
                errors.append(f"unresolved schema reference {label}:{pointer}")
    if schemas["$defs"].get("ResourceRef") != api["components"]["schemas"]["ResourceRef"]:
        errors.append("shared ResourceRef schemas drifted")
    for row in coverage["rows"]:
        missing = set(row["requirement_ids"]) - known
        if missing:
            errors.append(f"unknown legacy coverage IDs {row['id']}:{sorted(missing)}")
    errors.extend(validate_semantics(source, catalog, actions, api, schemas))
    return errors


def validate_semantics(
    source: dict, catalog: dict, actions: dict, api: dict, schemas: dict
) -> list[str]:
    """Check cross-contract meaning that valid JSON pointers alone cannot establish."""
    errors = []
    domain = schemas["$defs"]
    wire = api["components"]["schemas"]
    kinds = {r["kind"]: r for r in catalog["resource_types"]}
    task = source["domain_contracts"]["task"]
    props = domain["DomainTask"]["properties"]
    for prop, key in (
        ("state", "board_states"),
        ("queue_status", "queue_statuses"),
        ("priority", "priorities"),
    ):
        if props.get(prop, {}).get("enum") != task[key]:
            errors.append(f"task {prop} conflicts with retained task contract")
    if kinds["Task"]["lifecycle"] != task["board_states"]:
        errors.append("task board lifecycle conflicts with retained task contract")
    queue = kinds["Task"].get("queue_transitions", {})
    if set(queue) != set(task["queue_statuses"]) or any(
        not set(values) <= set(task["queue_statuses"]) for values in queue.values()
    ):
        errors.append("task queue transition coverage missing")
    if wire["EditableTaskFields"]["properties"]["priority"].get("enum") != task["priorities"]:
        errors.append("editable task priority conflicts with retained task contract")
    for name in ("actions", "scope"):
        shape = domain["DomainCapabilityGrant"]["properties"][name]
        if shape.get("type") != "array" or shape.get("minItems") != 1:
            errors.append(f"capability grant {name} must be a nonempty typed list")
    if domain["DomainPolicyDecision"]["properties"]["reason_codes"].get("type") != "array":
        errors.append("policy decision reason_codes must be a list")
    if domain.get("GrantLimits") != wire.get("GrantLimits"):
        errors.append("grant limit shapes drifted between accepted and stored contracts")
    contract = actions.get("approval_contract", {})
    registered = {a["id"]: a for a in actions["actions"]}
    if (
        contract.get("resource_kind") != "Decision"
        or contract.get("answer_action") not in registered
        or registered.get(contract.get("answer_action"), {}).get("target_kind") != "Decision"
        or contract.get("options") != {"approve": "approved", "reject": "rejected"}
    ):
        errors.append("missing guarded public plan approval Decision contract")
    required_guards = {
        "exact_plan_hash",
        "exact_plan_revision",
        "unexpired",
        "current_approver_authority",
        "no_default_approval",
    }
    if not required_guards <= set(contract.get("guards", [])):
        errors.append("plan approval guards missing")
    if "approval" not in wire["DecisionArguments"]["properties"]:
        errors.append("decision answer lacks exact plan approval arguments")
    if "approval_binding" not in domain["DomainDecision"]["properties"]:
        errors.append("approval Decision lacks immutable plan binding")
    rows = actions.get("operator_capability_coverage", [])
    caps = [row["capability"] for row in rows]
    if duplicates(caps):
        errors.append("duplicate operator capability mapping")
    api_ops = {op["operationId"] for item in api["paths"].values() for op in item.values()}
    known_reqs = {r["id"] for r in source["requirements"]}
    for row in rows:
        if not row.get("api_operations") or not set(row["api_operations"]) <= api_ops:
            errors.append(f"unknown public operation in operator capability {row['capability']}")
        if not set(row["action_ids"]) <= set(registered):
            errors.append(f"unknown action in operator capability {row['capability']}")
        if not set(row["requirement_ids"]) <= known_reqs:
            errors.append(f"unknown requirement in operator capability {row['capability']}")
    for req in source["requirements"]:
        for capability in req.get("public_capabilities", []):
            if not any(
                row["capability"] == capability and req["id"] in row["requirement_ids"]
                for row in rows
            ):
                errors.append(f"missing operator capability mapping {req['id']}:{capability}")
    return errors


def render(source: dict, plan: dict) -> dict[str, str]:
    reqs = source["requirements"]
    current = copy.deepcopy(source)
    current.update(
        generated_by="docs/requirements/tools/gen.py",
        count=len(reqs),
        milestones=plan["milestones"],
        work_packages=plan["work_packages"],
    )
    reconciliation = {
        "source_draft_commit": source["source_draft_commit"],
        "legacy_count": len(source["legacy_requirement_ids"]),
        "rows": [
            {
                "id": r["id"],
                "disposition": r["reconciliation"],
                "baseline_ref": r.get("baseline_ref"),
                "reason": r.get("amendment_reason"),
                "milestone": r["milestone"],
            }
            for r in reqs
        ],
    }
    lines = [
        "# Current requirements catalog",
        "",
        "Generated from requirements-source.json; historical draft is provenance only.",
        (
            f"{len(reqs)} requirements; "
            f"{len(source['legacy_requirement_ids'])} original IDs preserved; "
            f"{len(source['amended_ids'])} explicit amendments."
        ),
        "",
        (
            "Implementation status is requirement-only. "
            "Native/runtime capability discovery is separate."
        ),
        "",
    ]
    for r in reqs:
        lines += [
            f'<a id="{r["id"]}"></a>',
            f"## {r['id']} — {r['title']}",
            "",
            f"**{r['milestone']} · {r['priority']} · {r['reconciliation']}**",
            "",
            r["statement"],
            "",
        ]
        lines += ["- " + a for a in r["acceptance"]]
        lines += ["", "Source: " + r["source"], ""]
        if r.get("baseline_ref"):
            lines += [f"Historical text: [{r['id']}]({r['baseline_ref']}).", ""]
    # Retained narrative references continue to their archived source, not missing current files.
    text = "\n".join(lines)
    text = re.sub(
        r"\]\(((?:0[1-9]|1[0-8])-[^/)]+\.md)([^)]*)\)", r"](history/2026-11-12/\1\2)", text
    )
    return {
        "requirements.json": json.dumps(current, indent=2) + "\n",
        "reconciliation.json": json.dumps(reconciliation, indent=2) + "\n",
        "catalog.md": text,
    }


def main() -> int:
    inputs = [
        read(ROOT, name)
        for name in (
            "requirements-source.json",
            "plan.json",
            "contracts/resource-catalog.json",
            "contracts/action-catalog.json",
            "contracts/operator-api.openapi.json",
            "contracts/resource-schemas.json",
            "history/2026-11-12/requirements.json",
            "legacy-coverage.json",
        )
    ]
    errors = validate(*inputs)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    for name, text in render(inputs[0], inputs[1]).items():
        path = ROOT / name
        if "--check" in sys.argv:
            if not path.exists() or path.read_text() != text:
                print(f"stale generated file {name}", file=sys.stderr)
                return 1
        else:
            path.write_text(text)
    print(
        f"Validated {len(inputs[0]['requirements'])} requirements, "
        f"{len(inputs[2]['resource_types'])} kinds, {len(inputs[3]['actions'])} actions "
        f"and {len(inputs[7]['rows'])} legacy behaviors."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
