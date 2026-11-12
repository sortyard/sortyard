"""Acceptance: project scope is enforced throughout authorization, documents are validated
against their full §3 JSON Schemas before they are stored, and token issuance is serialised per
service account.

- A project-scoped operator account acts in its project only: it cannot read or answer another
  project's Decision, read another project's DecisionLog or stage runs, or edit workspace-wide
  objects (Lanes, non-project Policies). A project-scoped admin grants only within its project:
  no workspace-wide role binding, no workspace-wide (conductor) token, no token for another
  project.
- The generated models check structure only; the API refuses (422) what the full schema
  refuses — a Lane with ``max_concurrent_chains: -1``, a merge-gate Policy with
  ``review_count: 0`` or ``force_merge: true`` — and stores nothing.
- Two overlapping issuances for one service account through different RoleBindings cannot both
  pass the create+claim check.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from sortyard.api import auth
from tests.api_harness import WS, Api, role_binding, running_api
from tests.pg import requires_postgres


def project_binding(rbid: str, principal: str, role: str, project: str) -> dict[str, Any]:
    doc = role_binding(rbid, "operator", principal, role)
    doc["scope"] = {"kind": "project", "ref": project}
    return doc


@pytest.fixture(scope="module")
def api() -> Iterator[Api]:
    for handle in running_api():
        # Project-scoped operator accounts, confined to proj-a.
        for role in ("admin", "operator", "viewer"):
            handle.insert(
                "operator",
                {
                    "id": f"op-a-{role}",
                    "workspace_id": WS,
                    "subject": f"oidc|a-{role}",
                    "display_name": f"a-{role}",
                    "state": "active",
                },
            )
            rb = project_binding(f"rb-a-{role}", f"op-a-{role}", role, "proj-a")
            handle.insert("role_binding", rb)
            with handle.db() as conn:
                handle.tokens[f"a-{role}"] = auth.issue_operator_token(conn, rb["id"]).token
        handle.insert(
            "decision",
            {
                "id": "dec-b",
                "workspace_id": WS,
                "project_id": "proj-b",
                "question": "Which way for B?",
                "options": ["left", "right"],
                "default": "left",
                "decide_by": "2026-12-01T00:00:00Z",
                "state": "open",
            },
        )
        handle.insert(
            "decision",
            {
                "id": "dec-a2",
                "workspace_id": WS,
                "project_id": "proj-a",
                "question": "Which way for A?",
                "options": ["left", "right"],
                "default": "left",
                "decide_by": "2026-12-01T00:00:00Z",
                "state": "open",
            },
        )
        handle.insert(
            "decision_log",
            {
                "id": "dl-b",
                "workspace_id": WS,
                "ts": "2026-11-12T00:00:00Z",
                "conductor_pass_id": "pass-1",
                "decision": "skip",
                "task_id": "task-b",
                "reason_codes": ["lane full"],
                "inputs": {"policy_versions": [], "queue_snapshot_hash": "sha256:" + "2" * 64},
            },
        )
        handle.insert(
            "role_binding", role_binding("rb-sa-b", "agent", "sa-b", "agent-service-account")
        )
        yield handle


# --- project scope ---------------------------------------------------------------------------


@requires_postgres
def test_project_operator_cannot_answer_another_projects_decision(api: Api) -> None:
    answer = {"resolution": "left"}
    r = api.ws("POST", "/decisions/dec-b/answer", "a-operator", answer)
    assert r.status == 403, r.body
    assert r.body["reason_code"] == "project_scope"
    assert (api.doc("decision", "dec-b") or {})["state"] == "open"
    assert api.ws("GET", "/decisions/dec-b", "a-viewer").status == 403
    r = api.ws("POST", "/decisions/dec-a2/answer", "a-operator", answer)
    assert r.status == 200, r.body


@requires_postgres
def test_project_accounts_list_only_their_projects_decisions_and_log(api: Api) -> None:
    listed = api.ws("GET", "/decisions", "a-viewer")
    assert listed.status == 200
    assert {d["project_id"] for d in listed.body["items"]} == {"proj-a"}
    assert api.ws("GET", "/decisions?project_id=proj-b", "a-viewer").status == 403
    log = api.ws("GET", "/decision-log", "a-viewer")
    assert log.status == 200
    assert "dl-b" not in {e["id"] for e in log.body["items"]}
    assert api.ws("GET", "/decision-log/dl-b", "a-viewer").status == 403
    assert api.ws("GET", "/decision-log/dl-b", "viewer").status == 200


@requires_postgres
def test_project_operator_cannot_reach_a_stage_run_outside_its_project(api: Api) -> None:
    # sr-1's chain is not a chain of any proj-a task.
    r = api.ws("GET", "/stage-runs/sr-1/context-packet", "a-viewer")
    assert r.status == 403
    assert api.ws("GET", "/stage-runs/sr-1/context-packet", "viewer").status == 200


@requires_postgres
def test_project_operator_cannot_edit_workspace_wide_objects(api: Api) -> None:
    r = api.ws("PATCH", "/lanes/lane-a", "a-operator", {"heavy_job_cap": 2})
    assert r.status == 403
    assert r.body["reason_code"] == "project_scope"
    assert api.ws("DELETE", "/lanes/lane-a", "a-admin").status == 403
    pol = dict(api.doc("policy", "pol-1") or {})
    pol["version"] = "9.0.0"
    assert api.ws("POST", "/policies/pol-1/versions", "a-operator", pol).status == 403
    assert api.doc("policy", "pol-1") is not None
    own = {**pol, "id": "pol-a", "scope": "project", "scope_ref": "proj-a", "version": "1.0.0"}
    other = {**own, "id": "pol-b", "scope_ref": "proj-b"}
    assert api.ws("POST", "/policies", "a-operator", other).status == 403
    r = api.ws("POST", "/policies", "a-operator", own)
    assert r.status == 201, r.body


@requires_postgres
def test_project_operator_cannot_reversion_a_policy_outside_its_project(api: Api) -> None:
    # The existing Policy's scope is authorized, not only the proposed version's: a proj-a
    # operator cannot take over a proj-b or global Policy by submitting it re-scoped to proj-a.
    pol = dict(api.doc("policy", "pol-1") or {})
    theirs = {**pol, "id": "pol-theirs", "scope": "project", "scope_ref": "proj-b"}
    theirs.pop("content_hash", None)
    theirs.pop("source", None)
    r = api.ws("POST", "/policies", "operator", theirs)
    assert r.status == 201, r.body
    for pid, current in (("pol-theirs", theirs), ("pol-1", pol)):
        hijack = {**current, "scope": "project", "scope_ref": "proj-a", "version": "8.0.0"}
        hijack.pop("content_hash", None)
        r = api.ws("POST", f"/policies/{pid}/versions", "a-operator", hijack)
        assert r.status == 403, (pid, r.body)
        assert r.body["reason_code"] == "project_scope"
        assert (api.doc("policy", pid) or {})["version"] == current["version"]
        assert api.ws("GET", f"/policies/{pid}/versions/8.0.0", "viewer").status == 404

    # A proj-a Policy is versioned by the proj-a operator, and the proposed scope is still
    # checked: it cannot be re-scoped out of proj-a.
    own = {**theirs, "id": "pol-mine", "scope_ref": "proj-a", "version": "1.0.0"}
    assert api.ws("POST", "/policies", "a-operator", own).status == 201
    moved = {**own, "scope_ref": "proj-b", "version": "2.0.0"}
    r = api.ws("POST", "/policies/pol-mine/versions", "a-operator", moved)
    assert r.status == 403, r.body
    widened = {**own, "scope": "global", "version": "2.0.0"}
    widened.pop("scope_ref")
    assert api.ws("POST", "/policies/pol-mine/versions", "a-operator", widened).status == 403
    r = api.ws("POST", "/policies/pol-mine/versions", "a-operator", {**own, "version": "2.0.0"})
    assert r.status == 201, r.body


@requires_postgres
def test_project_admin_grants_only_within_its_project(api: Api) -> None:
    # No workspace-wide token: a conductor token is workspace-wide by definition.
    r = api.call(
        "POST",
        f"/v1/workspaces/{WS}/role-bindings/rb-sa-b/tokens",
        "a-admin",
        {"agent_role": "conductor"},
    )
    assert r.status == 403, r.body
    assert r.body["reason_code"] == "project_scope"
    path = f"/v1/workspaces/{WS}/role-bindings/rb-sa-b/tokens"
    for body in (
        {"agent_role": "sensor", "project_id": "proj-b"},
        {"agent_role": "grooming-agent"},  # unconfined: workspace-wide
        {"agent_role": "build-worker", "stage_run_id": "sr-2"},  # not a proj-a stage run
    ):
        r = api.call("POST", path, "a-admin", body)
        assert r.status == 403, (body, r.body)
    with api.db() as conn:
        held = conn.execute(
            "SELECT count(*) FROM sortyard.api_token WHERE role_binding_id = 'rb-sa-b'"
        ).fetchone()
    assert held == (0,)
    r = api.call("POST", path, "a-admin", {"agent_role": "sensor", "project_id": "proj-a"})
    assert r.status == 201, r.body

    # Nor a workspace-wide role binding, or one for another project.
    wide = role_binding("rb-wide", "operator", "op-x", "admin")
    assert api.call("POST", f"/v1/workspaces/{WS}/role-bindings", "a-admin", wide).status == 403
    other = project_binding("rb-other", "op-x", "admin", "proj-b")
    assert api.call("POST", f"/v1/workspaces/{WS}/role-bindings", "a-admin", other).status == 403
    own = project_binding("rb-own", "op-x", "viewer", "proj-a")
    r = api.call("POST", f"/v1/workspaces/{WS}/role-bindings", "a-admin", own)
    assert r.status == 201, r.body


# --- full schema validation -----------------------------------------------------------------


@requires_postgres
def test_a_lane_the_schema_refuses_is_not_stored(api: Api) -> None:
    lane = {
        "id": "lane-neg",
        "workspace_id": WS,
        "name": "neg",
        "scope": "conductor",
        "max_concurrent_chains": -1,
    }
    r = api.ws("POST", "/lanes", "operator", lane)
    assert r.status == 422, r.body
    assert "max_concurrent_chains" in r.body["detail"]
    assert api.doc("lane", "lane-neg") is None
    r = api.ws("PATCH", "/lanes/lane-a", "operator", {"max_concurrent_chains": -1})
    assert r.status == 422
    assert (api.doc("lane", "lane-a") or {})["max_concurrent_chains"] >= 0


@requires_postgres
@pytest.mark.parametrize(
    "parameters",
    [{"review_count": 0}, {"force_merge": True}, {"review_count": 0, "force_merge": True}],
)
def test_a_policy_version_the_schema_refuses_is_not_stored(
    api: Api, parameters: dict[str, Any]
) -> None:
    pol = dict(api.doc("policy", "pol-1") or {})
    pol.pop("content_hash", None)
    pol["version"] = "7.0.0"
    pol["parameters"] = {**pol["parameters"], **parameters}
    r = api.ws("POST", "/policies/pol-1/versions", "operator", pol)
    assert r.status == 422, r.body
    assert r.body["reason_code"] == "schema"
    with api.db() as conn:
        row = conn.execute(
            "SELECT count(*) FROM sortyard.policy WHERE id = 'pol-1' AND version = '7.0.0'"
        ).fetchone()
    assert row == (0,)


# --- issuance is serialised per service account ----------------------------------------------


@requires_postgres
def test_overlapping_issuance_through_two_bindings_of_one_account_is_serialised(
    api: Api,
) -> None:
    # sa-dual has two agent-service-account bindings; a conductor token through one and a
    # sensor token through the other, issued concurrently, must not both succeed.
    api.insert(
        "role_binding", role_binding("rb-dual-1", "agent", "sa-dual", "agent-service-account")
    )
    api.insert(
        "role_binding", role_binding("rb-dual-2", "agent", "sa-dual", "agent-service-account")
    )
    admin = {"kind": "operator", "id": "op-admin"}
    outcome: dict[str, Any] = {}

    first = psycopg.connect(api.conninfo)
    try:
        auth.issue_service_account_token(first, WS, "rb-dual-1", {"agent_role": "conductor"}, admin)

        def second() -> None:
            with psycopg.connect(api.conninfo) as conn:
                try:
                    auth.issue_service_account_token(
                        conn,
                        WS,
                        "rb-dual-2",
                        {"agent_role": "sensor", "project_id": "proj-a"},
                        admin,
                    )
                    outcome["second"] = "issued"
                except auth.IssuanceRefused:
                    outcome["second"] = "refused"

        thread = threading.Thread(target=second)
        thread.start()
        thread.join(timeout=1.0)
        # The second issuance waits on the account while the first is uncommitted.
        assert thread.is_alive()
        first.commit()
    finally:
        first.close()
    thread.join(timeout=10)
    assert outcome == {"second": "refused"}
    with api.db() as conn:
        roles = conn.execute(
            "SELECT array_agg(role) FROM sortyard.api_token"
            ' WHERE principal = \'{"kind": "agent", "id": "sa-dual"}\'::jsonb'
        ).fetchone()
    assert roles == (["conductor"],)
