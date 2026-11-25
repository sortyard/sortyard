"""Contract tests: spec/openapi.json run against the implementation.

- Static: every operation the API service routes is an operation of the spec with the same
  method, path, roles (``x-sortyard-roles``) and capability; the Phase 1 surface (tasks, lanes,
  policy read paths, decision-log read) is all routed.
- Live: every routed operation is called by every role. A role outside the operation's
  ``x-sortyard-roles`` gets 403; a role inside never gets 401/403 (its token scoped to the
  target). Every response's status is one the spec declares for the operation and its body
  validates against the spec's response schema (the §3 JSON Schemas, by ``$ref``).
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import pytest
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from sortyard.api import permissions
from tests.api_harness import WS, Api, Response, running_api, task
from tests.pg import requires_postgres

SPEC = pathlib.Path(__file__).resolve().parent.parent / "spec"
OPENAPI = json.loads((SPEC / "openapi.json").read_text())
OPENAPI_ID = "https://sortyard.ai/spec/openapi.json"
METHODS = {"get", "post", "patch", "put", "delete"}
PROBLEM = "application/problem+json"
ROLES = ["admin", "operator", "viewer", "conductor", "build-worker", "sensor", "grooming-agent"]

# The Phase 1 surface this task delivers (tasks, lanes, policy read paths, decision-log read),
# plus the operations the §7 matrix names.
PHASE_1 = {
    "listTasks", "createTask", "getTask", "updateTask", "markTaskReady", "claimTask",
    "advanceTask", "handBackTask", "blockTask", "unblockTask", "cancelTask", "requeueTask",
    "listTaskDecisionLog",
    "listLanes", "createLane", "getLane", "updateLane", "deleteLane",
    "listPolicies", "getPolicy", "listPolicyVersions", "getPolicyVersion",
    "listPrioritizationPolicies", "getPrioritizationPolicy",
    "listPrioritizationPolicyVersions", "getPrioritizationPolicyVersion",
    "listSequencingPolicies", "getSequencingPolicy",
    "listSequencingPolicyVersions", "getSequencingPolicyVersion",
    "listDecisionLog", "getDecisionLogEntry",
    "createPolicy", "proposePolicyVersion", "answerDecision",
    "getStageRunContextPacket", "submitStageRunResult", "createAlert", "instructIntegrator",
    "issueServiceAccountToken",
}  # fmt: skip


def spec_operations() -> dict[str, tuple[str, str, dict[str, Any]]]:
    return {
        op["operationId"]: (method.upper(), path, op)
        for path, item in OPENAPI["paths"].items()
        for method, op in item.items()
        if method in METHODS
    }


SPEC_OPS = spec_operations()


def registry() -> Registry[Any]:
    resources = [
        (json.loads(p.read_text())["$id"], json.loads(p.read_text()))
        for p in sorted(SPEC.glob("*.schema.json"))
    ]
    resources.append((OPENAPI_ID, OPENAPI))
    return Registry().with_resources(
        (uri, DRAFT202012.create_resource(doc)) for uri, doc in resources
    )


REGISTRY = registry()


def pointer(*parts: str) -> str:
    return "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def check_response(op_id: str, r: Response) -> None:
    """The status is declared for the operation, and the body matches its schema."""
    method, path, op = SPEC_OPS[op_id]
    assert str(r.status) in op["responses"], f"{op_id}: undeclared status {r.status} {r.body}"
    declared = op["responses"][str(r.status)]
    base = f"{OPENAPI_ID}#/paths/{pointer(path, method.lower(), 'responses', str(r.status))}"
    if "$ref" in declared:
        base = f"{OPENAPI_ID}{declared['$ref']}"
        declared = OPENAPI["components"]["responses"][declared["$ref"].rsplit("/", 1)[1]]
    content = declared.get("content")
    if not content:
        assert r.body is None, f"{op_id}: {r.status} declares no body"
        return
    (media,) = content
    ctype = r.headers.get("Content-Type", "")
    assert ctype == media, f"{op_id}: {r.status} Content-Type {ctype!r}, spec says {media!r}"
    schema = {"$ref": f"{base}/{pointer('content', media, 'schema')}"}
    jsonschema.Draft202012Validator(schema, registry=REGISTRY).validate(r.body)


# --- static ------------------------------------------------------------------------------


def test_every_routed_operation_is_the_spec_operation() -> None:
    for op in permissions.OPERATIONS.values():
        assert op.operation_id in SPEC_OPS, op.operation_id
        method, path, spec_op = SPEC_OPS[op.operation_id]
        assert (op.method, op.path) == (method, path), op.operation_id
        assert op.roles == frozenset(spec_op["x-sortyard-roles"]), op.operation_id
        assert op.capability == spec_op.get("x-sortyard-capability"), op.operation_id


def test_the_phase_1_surface_is_routed() -> None:
    assert set(permissions.OPERATIONS) >= PHASE_1


def test_required_request_bodies_are_the_spec_s() -> None:
    from sortyard.api import routing

    required = {
        op_id
        for op_id in permissions.OPERATIONS
        if SPEC_OPS[op_id][2].get("requestBody", {}).get("required")
    }
    assert required == routing._BODY_REQUIRED


def test_the_response_check_rejects_what_the_spec_does_not_allow() -> None:
    task_doc = task("task-x")
    check_response("getTask", Response(200, task_doc, {"Content-Type": "application/json"}))
    with pytest.raises(jsonschema.ValidationError):
        bad = {**task_doc, "state": "nonsense"}
        check_response("getTask", Response(200, bad, {"Content-Type": "application/json"}))
    with pytest.raises(AssertionError):
        check_response("getTask", Response(418, None))
    with pytest.raises(jsonschema.ValidationError):
        check_response("getTask", Response(403, {"title": "x"}, {"Content-Type": PROBLEM}))


def test_seed_documents_are_schema_valid() -> None:
    from tests.api_harness import seed_rows

    for table, doc in seed_rows():
        stem = table.replace("_", "-")
        uri = f"https://sortyard.ai/spec/{stem}.schema.json"
        jsonschema.Draft202012Validator({"$ref": uri}, registry=REGISTRY).validate(doc)


# --- live ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api() -> Iterator[Api]:
    yield from running_api()


def target(op_id: str, role: str = "admin") -> tuple[str, Any]:
    """A request for ``op_id`` aimed at objects every role's token is scoped to."""
    _, path, _ = SPEC_OPS[op_id]
    ids = {
        "workspace_id": WS,
        "task_id": "task-1",
        "lane_id": "lane-a",
        "policy_id": "pol-1",
        "prioritization_policy_id": "prio-1",
        "sequencing_policy_id": "seqp-1",
        "version": "1.0.0",
        "decision_log_id": "dl-1",
        "decision_id": "dec-1",
        "stage_run_id": "sr-1",
        "integrator_id": "integrator-default",
        "role_binding_id": "rb-sensor",
        "project_id": "proj-a",
        "item_id": "item-1",
    }
    for name, value in ids.items():
        path = path.replace("{" + name + "}", value)
    body: Any = BODIES.get(op_id)
    if op_id == "createTask":
        # A sensor files sensor tasks, a grooming agent grooming tasks (createTask's rule).
        body = {**body, "origin": {"grooming-agent": "grooming"}.get(role, "sensor")}
    return path, body


BODIES: dict[str, Any] = {
    "admitItem": {
        "id": "item-admitted",
        "project_id": "proj-a",
        "title": "An admitted item",
        "lane": "example",
        "repository": "example/app",
        "needs": ["secret:EXAMPLE_DEPLOY_TOKEN"],
        "blocked_by": ["item-1"],
        "spec": {
            "outcome": "the contract test admits an item",
            "acceptance": [{"test": "tests/test_api_contract.py", "name": "it is admitted"}],
        },
    },
    "requestItemChange": {"answer": "resume", "reason": "the contract test asks"},
    "createTask": task("task-new", origin="sensor", state="backlog"),
    "updateTask": {"title": "Renamed"},
    "claimTask": {"lane_id": "lane-a", "execution_binding_id": "eb-1"},
    "advanceTask": {"state": "in_progress", "stage": "build"},
    "handBackTask": {"handback_reason": "no", "handback_evidence": ["e"]},
    "blockTask": {"blocked_reason": "waiting"},
    "unblockTask": {"reason": "unblocked"},
    "cancelTask": {"reason": "obsolete"},
    "requeueTask": {"reason": "retry"},
    "createLane": {
        "id": "lane-new",
        "workspace_id": WS,
        "name": "new",
        "scope": "dispatcher",
        "max_concurrent_chains": 1,
    },
    "updateLane": {"max_concurrent_chains": 2},
    "createPolicy": {
        "id": "pol-new",
        "workspace_id": WS,
        "version": "1.0.0",
        "scope": "global",
        "kind": "retention",
        "parameters": {},
        "enforcement": "record",
        "absent_state": {"behaviour": "record"},
    },
    "proposePolicyVersion": {
        "id": "pol-1",
        "workspace_id": WS,
        "version": "2.0.0",
        "scope": "global",
        "kind": "merge_gate",
        "parameters": {
            "regime": "conductor_product_pr",
            "review_count": 1,
            "red_never_merges": True,
            "force_merge": False,
        },
        "enforcement": "refuse",
        "absent_state": {"behaviour": "record"},
    },
    "createDecision": {
        "id": "dec-new",
        "workspace_id": WS,
        "project_id": "proj-a",
        "question": "Which?",
        "default": "a",
        "decide_by": "2026-12-01T00:00:00Z",
        "state": "open",
    },
    "answerDecision": {"resolution": "native"},
    "submitStageRunResult": {"state": "succeeded"},
    "createAlert": {
        "id": "alert-new",
        "workspace_id": WS,
        "kind": "sensor_finding",
        "summary": "found",
        "subject": {"kind": "project", "ref": "proj-a"},
        "state": "open",
        "detected_at": "2026-11-12T00:00:00Z",
    },
    "instructIntegrator": {"task_id": "task-1", "chain_id": "chain-x"},
    "issueServiceAccountToken": {"agent_role": "sensor", "project_id": "proj-a"},
    "createRoleBinding": {
        "id": "rb-new",
        "workspace_id": WS,
        "principal": {"kind": "agent", "id": "sa-new"},
        "role": "agent-service-account",
        "scope": {"kind": "workspace"},
    },
}


@requires_postgres
@pytest.mark.parametrize("op_id", sorted(permissions.OPERATIONS))
def test_roles_outside_the_matrix_are_forbidden(api: Api, op_id: str) -> None:
    method, _, op = SPEC_OPS[op_id]
    path, body = target(op_id)
    for role in ROLES:
        if role in op["x-sortyard-roles"]:
            continue
        r = api.call(method, path, role, body)
        assert r.status == 403, (op_id, role, r.status, r.body)
        check_response(op_id, r)


@requires_postgres
@pytest.mark.parametrize("op_id", sorted(permissions.OPERATIONS))
def test_unauthenticated_calls_are_refused(api: Api, op_id: str) -> None:
    method, _, _ = SPEC_OPS[op_id]
    path, body = target(op_id)
    r = api.call(method, path, None, body)
    assert r.status == 401
    check_response(op_id, r)


# A successful call of every routed operation, in an order the state machines accept; each
# response is checked against the spec. Roles are the matrix's; ``expect`` is the success code.
SCENARIO: list[tuple[str, str, int]] = [
    ("getProjectQueue", "grooming-agent", 200),
    ("listItems", "viewer", 200),
    ("getItem", "conductor", 200),
    ("getItemTimeline", "viewer", 200),
    ("requestItemChange", "operator", 202),
    ("admitItem", "grooming-agent", 201),
    ("listTasks", "viewer", 200),
    ("getTask", "conductor", 200),
    ("createTask", "sensor", 201),
    ("updateTask", "grooming-agent", 200),
    ("markTaskReady", "grooming-agent", 200),
    ("listLanes", "conductor", 200),
    ("getLane", "viewer", 200),
    ("createLane", "operator", 201),
    ("updateLane", "operator", 200),
    ("listPolicies", "conductor", 200),
    ("getPolicy", "viewer", 200),
    ("listPolicyVersions", "viewer", 200),
    ("getPolicyVersion", "conductor", 200),
    ("createPolicy", "operator", 201),
    ("proposePolicyVersion", "admin", 201),
    ("listPrioritizationPolicies", "grooming-agent", 200),
    ("getPrioritizationPolicy", "conductor", 200),
    ("listPrioritizationPolicyVersions", "viewer", 200),
    ("getPrioritizationPolicyVersion", "viewer", 200),
    ("listSequencingPolicies", "grooming-agent", 200),
    ("getSequencingPolicy", "conductor", 200),
    ("listSequencingPolicyVersions", "viewer", 200),
    ("getSequencingPolicyVersion", "viewer", 200),
    ("listDecisionLog", "grooming-agent", 200),
    ("getDecisionLogEntry", "viewer", 200),
    ("listDecisions", "viewer", 200),
    ("getDecision", "conductor", 200),
    ("createDecision", "conductor", 201),
    ("answerDecision", "operator", 200),
    ("getStageRunContextPacket", "build-worker", 200),
    ("submitStageRunResult", "build-worker", 200),
    ("createAlert", "sensor", 201),
    ("createRoleBinding", "admin", 201),
    ("issueServiceAccountToken", "admin", 201),
    ("claimTask", "conductor", 201),
    ("listTaskDecisionLog", "viewer", 200),
    ("advanceTask", "conductor", 200),
    ("blockTask", "grooming-agent", 200),
    ("unblockTask", "conductor", 200),
    ("handBackTask", "conductor", 200),
    ("requeueTask", "operator", 200),
    ("cancelTask", "admin", 200),
    ("deleteLane", "operator", 204),
    ("instructIntegrator", "conductor", 202),  # run last, on a task of its own (below)
]
# Scenario calls aimed elsewhere than target(): only a backlog task is made ready, and the
# lane created above is the one deleted.
RETARGET = {
    "markTaskReady": ("/tasks/task-1/", "/tasks/task-backlog/"),
    "deleteLane": ("/lanes/lane-a", "/lanes/lane-new"),
}


def test_the_scenario_covers_every_routed_operation() -> None:
    assert {op for op, _, _ in SCENARIO} == set(permissions.OPERATIONS)


@requires_postgres
def test_every_operation_succeeds_as_the_spec_says(api: Api) -> None:
    for op_id, role, expect in SCENARIO:
        method, _, op = SPEC_OPS[op_id]
        assert role in op["x-sortyard-roles"], (op_id, role)
        path, body = target(op_id, role)
        if op_id == "instructIntegrator":
            continue
        if op_id in RETARGET:
            path = path.replace(*RETARGET[op_id])
        r = api.call(method, path, role, body)
        assert r.status == expect, (op_id, r.status, r.body)
        check_response(op_id, r)
    # The landing needs a task that reached merging, on its own chain.
    api.insert("task", task("task-m", state="todo", lane_id="lane-m"))
    api.insert(
        "lane",
        {
            "id": "lane-m",
            "workspace_id": WS,
            "name": "m",
            "scope": "conductor",
            "max_concurrent_chains": 1,
        },
    )
    eb = api.doc("execution_binding", "eb-1") or {}
    api.insert("execution_binding", {**eb, "id": "eb-m", "task_id": "task-m"})
    chain = api.ws(
        "POST",
        "/tasks/task-m/claim",
        "conductor",
        {"lane_id": "lane-m", "execution_binding_id": "eb-m"},
    )
    assert chain.status == 201, chain.body
    for body in (
        {"state": "in_progress", "stage": "build"},
        {"state": "in_review"},
        {"state": "merging"},
    ):
        assert api.ws("POST", "/tasks/task-m/advance", "conductor", body).status == 200
    landing = api.ws(
        "POST",
        "/integrators/integrator-default/landings",
        "conductor",
        {"task_id": "task-m", "chain_id": chain.body["id"]},
    )
    assert landing.status == 202, landing.body
    check_response("instructIntegrator", landing)


@requires_postgres
def test_in_role_calls_are_never_refused_by_the_matrix(api: Api) -> None:
    """Every role inside an operation's x-sortyard-roles gets past authorization (its token is
    scoped to the target); whatever the outcome, it is a status the spec declares."""
    for op_id in sorted(permissions.OPERATIONS):
        method, _, op = SPEC_OPS[op_id]
        for role in op["x-sortyard-roles"]:
            path, body = target(op_id, role)
            r = api.call(method, path, role, body)
            assert r.status not in (401, 403), (op_id, role, r.status, r.body)
            check_response(op_id, r)


@requires_postgres
def test_malformed_and_invalid_bodies(api: Api) -> None:
    r = api.call(
        "POST", f"/v1/workspaces/{WS}/tasks", "operator", None, content_type="application/json"
    )
    assert r.status == 400
    check_response("createTask", r)
    bad = task("task-bad", state="backlog")
    bad["surprise"] = True
    r = api.ws("POST", "/tasks", "operator", bad)
    assert r.status == 422
    check_response("createTask", r)
    r = api.ws("POST", "/tasks", "operator", task("task-bad2", state="merging"))
    assert r.status == 409
    check_response("createTask", r)
    r = api.ws("GET", "/tasks/nope", "operator")
    assert r.status == 404
    check_response("getTask", r)


@requires_postgres
def test_lists_paginate(api: Api) -> None:
    seen: list[str] = []
    cursor = ""
    while True:
        r = api.ws("GET", f"/tasks?limit=2{cursor}", "viewer")
        assert r.status == 200
        check_response("listTasks", r)
        seen += [t["id"] for t in r.body["items"]]
        if r.body.get("next_cursor") is None:
            break
        cursor = f"&cursor={r.body['next_cursor']}"
    assert len(seen) == len(set(seen)) >= 4
    filtered = api.ws("GET", "/tasks?project_id=proj-b", "viewer").body["items"]
    assert {t["project_id"] for t in filtered} == {"proj-b"}
    assert api.ws("GET", "/tasks?limit=0", "viewer").status == 400
