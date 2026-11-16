"""Acceptance: the §7 permission matrix is enforced by the API service, account by account.

Design draft §7: a build worker reads its own context packet and submits its own stage result —
nothing else; a sensor files findings/tasks in its project only; a grooming agent creates and
grooms tasks but never claims or merges; the conductor account alone claims, hands back or
instructs the Integrator; operator accounts alone edit Policies/Lanes or answer Decisions; and
no token may both create tasks and claim them — refused at issuance.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import psycopg
import pytest

from sortyard.api import auth, permissions
from tests.api_harness import AGENT_BINDINGS, OTHER_WS, WS, Api, running_api, task
from tests.pg import requires_postgres

# --- the matrix in code (no database) ------------------------------------------------------


def test_no_role_column_holds_both_task_create_and_task_claim() -> None:
    for role in permissions.AGENT_ROLES:
        caps = permissions.capabilities(role)
        assert not {"task.create", "task.claim"} <= caps, role


def test_the_queue_poisoning_combination_is_refused_by_the_issuance_check() -> None:
    with pytest.raises(auth.IssuanceRefused, match="queue-poisoning"):
        auth.check_combination({"task.create"}, {"task.claim", "task.hand_back"})
    with pytest.raises(auth.IssuanceRefused):
        auth.check_combination({"task.create", "task.claim"}, set())
    auth.check_combination({"task.create", "task.groom"}, {"finding.file"})


def test_section_7_columns() -> None:
    assert permissions.capabilities("build-worker") == {"stage_run.submit"}
    assert permissions.capabilities("sensor") == {"task.create", "finding.file"}
    grooming = permissions.capabilities("grooming-agent")
    assert {"task.create", "task.groom"} <= grooming
    assert not grooming & {"task.claim", "task.hand_back", "task.advance", "integrator.instruct"}
    for capability in ("task.claim", "task.hand_back", "integrator.instruct"):
        assert permissions.roles_with(capability) == {"conductor"}, capability
    for capability in ("policy.edit", "lane.edit", "decision.answer"):
        assert permissions.roles_with(capability) == {"admin", "operator"}, capability


# --- enforced by the running service ------------------------------------------------------


@pytest.fixture(scope="module")
def api() -> Iterator[Api]:
    """One running API over one seeded database for the module; tests use distinct objects."""
    yield from running_api()


@requires_postgres
def test_no_token_is_unauthorized(api: Api) -> None:
    r = api.ws("GET", "/tasks")
    assert r.status == 401
    assert r.headers["Content-Type"] == "application/problem+json"
    assert api.call("GET", f"/v1/workspaces/{WS}/tasks", token="sy_not-a-token").status == 401


@requires_postgres
def test_a_token_is_confined_to_its_workspace(api: Api) -> None:
    assert api.call("GET", f"/v1/workspaces/{OTHER_WS}/tasks", "operator").status == 403


@requires_postgres
def test_tokens_are_stored_hashed_and_shown_once(api: Api) -> None:
    issued = api.issue("sensor", project_id="proj-a")
    assert issued.status == 201
    token = issued.body["token"]
    assert issued.body["agent_role"] == "sensor"
    assert issued.body["project_id"] == "proj-a"
    with api.db() as conn:
        rows = conn.execute("SELECT token_sha256 FROM sortyard.api_token").fetchall()
        dump = str(conn.execute("SELECT * FROM sortyard.api_token").fetchall())
    assert hashlib.sha256(token.encode()).hexdigest() in {r[0] for r in rows}
    assert token not in dump


@requires_postgres
def test_an_expired_token_is_unauthorized(api: Api) -> None:
    issued = api.issue("sensor", project_id="proj-a")
    with api.db() as conn:
        conn.execute(
            "UPDATE sortyard.api_token SET expires_at = now() - interval '1 second' "
            "WHERE token_sha256 = %s",
            [hashlib.sha256(issued.body["token"].encode()).hexdigest()],
        )
    r = api.call("POST", f"/v1/workspaces/{WS}/alerts", token=issued.body["token"], body={})
    assert r.status == 401


# build worker: its own context packet and its own stage result, nothing else.


@requires_postgres
def test_build_worker_reads_its_own_context_packet_only(api: Api) -> None:
    own = api.ws("GET", "/stage-runs/sr-1/context-packet", "build-worker")
    assert own.status == 200
    assert own.body["packet_hash"] == api.doc("stage_run", "sr-1")["inputs_packet_hash"]  # type: ignore[index]
    assert api.ws("GET", "/stage-runs/sr-2/context-packet", "build-worker").status == 403


@requires_postgres
def test_build_worker_submits_its_own_result_once(api: Api) -> None:
    result = {"state": "succeeded", "outputs": [{"kind": "patch", "ref": "runs/sr-1.patch"}]}
    assert api.ws("POST", "/stage-runs/sr-2/result", "build-worker", result).status == 403
    first = api.ws("POST", "/stage-runs/sr-1/result", "build-worker", result)
    assert first.status == 200, first.body
    assert first.body["state"] == "succeeded"
    assert api.ws("POST", "/stage-runs/sr-1/result", "build-worker", result).status == 409


@requires_postgres
@pytest.mark.parametrize(
    ("method", "rest", "body"),
    [
        ("GET", "/tasks", None),
        ("GET", "/tasks/task-1", None),
        ("POST", "/tasks", task("task-bw", origin="chain")),
        ("POST", "/tasks/task-1/claim", {"lane_id": "lane-a", "execution_binding_id": "eb-1"}),
        ("GET", "/decision-log", None),
        ("GET", "/lanes", None),
        ("GET", "/policies", None),
        ("POST", "/alerts", {}),
    ],
)
def test_build_worker_can_do_nothing_else(api: Api, method: str, rest: str, body: object) -> None:
    assert api.ws(method, rest, "build-worker", body).status == 403


@requires_postgres
def test_a_build_worker_token_needs_its_stage_run(api: Api) -> None:
    assert api.issue("build-worker").status == 422
    assert api.issue("build-worker", stage_run_id="sr-missing").status == 404


# sensor: findings and tasks in its own project only.


@requires_postgres
def test_sensor_files_tasks_in_its_project_only(api: Api) -> None:
    ok = api.ws("POST", "/tasks", "sensor", task("task-s1", origin="sensor", state="backlog"))
    assert ok.status == 201, ok.body
    other = task("task-s2", project_id="proj-b", origin="sensor", state="backlog")
    assert api.ws("POST", "/tasks", "sensor", other).status == 403
    posing = task("task-s3", origin="human", state="backlog")
    assert api.ws("POST", "/tasks", "sensor", posing).status == 403


@requires_postgres
def test_sensor_files_findings_in_its_project_only(api: Api) -> None:
    def finding(aid: str, project_id: str) -> dict[str, object]:
        return {
            "id": aid,
            "workspace_id": WS,
            "kind": "sensor_finding",
            "summary": "walk found a broken link",
            "subject": {"kind": "project", "ref": project_id},
            "state": "open",
            "detected_at": "2026-11-12T00:00:00Z",
        }

    ok = api.ws("POST", "/alerts", "sensor", finding("alert-s1", "proj-a"))
    assert ok.status == 201, ok.body
    assert ok.body["source"] == {"kind": "agent", "id": "sa-sensor"}
    assert api.ws("POST", "/alerts", "sensor", finding("alert-s2", "proj-b")).status == 403


@requires_postgres
@pytest.mark.parametrize(
    ("method", "rest", "body"),
    [
        ("GET", "/tasks", None),
        ("PATCH", "/tasks/task-1", {"title": "renamed"}),
        ("POST", "/tasks/task-1/claim", {"lane_id": "lane-a", "execution_binding_id": "eb-1"}),
        ("GET", "/stage-runs/sr-1/context-packet", None),
        ("GET", "/decision-log", None),
    ],
)
def test_sensor_can_do_nothing_else(api: Api, method: str, rest: str, body: object) -> None:
    assert api.ws(method, rest, "sensor", body).status == 403


@requires_postgres
def test_a_sensor_token_needs_its_project(api: Api) -> None:
    assert api.issue("sensor").status == 422


# grooming agent: creates and grooms, never claims or merges.


@requires_postgres
def test_grooming_agent_creates_and_grooms(api: Api) -> None:
    created = api.ws(
        "POST", "/tasks", "grooming-agent", task("task-g1", origin="grooming", state="backlog")
    )
    assert created.status == 201, created.body
    patched = api.call(
        "PATCH",
        f"/v1/workspaces/{WS}/tasks/task-g1",
        "grooming-agent",
        {"title": "Groomed title", "labels": ["groomed"]},
        content_type="application/merge-patch+json",
    )
    assert patched.status == 200, patched.body
    assert patched.body["title"] == "Groomed title"
    ready = api.ws("POST", "/tasks/task-g1/ready", "grooming-agent")
    assert ready.status == 200, ready.body
    assert ready.body["state"] == "todo"
    assert api.ws("GET", "/decision-log", "grooming-agent").status == 200


@requires_postgres
def test_grooming_agent_is_confined_to_its_project(api: Api) -> None:
    other = task("task-g2", project_id="proj-b", origin="grooming", state="backlog")
    assert api.ws("POST", "/tasks", "grooming-agent", other).status == 403
    assert api.ws("PATCH", "/tasks/task-b", "grooming-agent", {"title": "x"}).status == 403


@requires_postgres
@pytest.mark.parametrize(
    ("method", "rest", "body"),
    [
        ("POST", "/tasks/task-2/claim", {"lane_id": "lane-a", "execution_binding_id": "eb-2"}),
        ("POST", "/tasks/task-2/advance", {"state": "merging"}),
        (
            "POST",
            "/tasks/task-2/hand-back",
            {"handback_reason": "x", "handback_evidence": ["y"]},
        ),
        (
            "POST",
            "/integrators/integrator-default/landings",
            {"task_id": "task-2", "chain_id": "chain-x"},
        ),
        ("POST", "/stage-runs/sr-2/result", {"state": "succeeded"}),
    ],
)
def test_grooming_agent_never_claims_or_merges(
    api: Api, method: str, rest: str, body: object
) -> None:
    assert api.ws(method, rest, "grooming-agent", body).status == 403


# conductor: the only account that claims, hands back or instructs the Integrator.


@requires_postgres
def test_only_the_conductor_claims_hands_back_and_instructs_the_integrator(api: Api) -> None:
    claim = {"lane_id": "lane-a", "execution_binding_id": "eb-1"}
    for role in ("admin", "operator", "viewer", "build-worker", "sensor", "grooming-agent"):
        assert api.ws("POST", "/tasks/task-1/claim", role, claim).status == 403, role
    chain = api.ws("POST", "/tasks/task-1/claim", "conductor", claim)
    assert chain.status == 201, chain.body
    assert chain.body["task_id"] == "task-1"
    assert chain.body["workflow"] == {"id": "wf-job", "version": "1.0.0"}
    # The lane (max_concurrent_chains 1) is now full.
    full = api.ws(
        "POST",
        "/tasks/task-2/claim",
        "conductor",
        {"lane_id": "lane-a", "execution_binding_id": "eb-2"},
    )
    assert full.status == 409
    assert full.body["reason_code"] == "lane_full"
    claimed = api.doc("task", "task-1")
    assert claimed is not None
    assert (claimed["state"], claimed["chain_id"]) == ("claimed", chain.body["id"])
    log = api.ws("GET", "/tasks/task-1/decision-log", "viewer").body["items"]
    assert "claim" in [entry["decision"] for entry in log]

    for state in ("in_progress", "in_review", "merging"):
        body = {"state": state, "stage": "build"} if state == "in_progress" else {"state": state}
        r = api.ws("POST", "/tasks/task-1/advance", "conductor", body)
        assert r.status == 200, r.body
    landing = {"task_id": "task-1", "chain_id": chain.body["id"]}
    for role in ("admin", "operator", "grooming-agent", "sensor", "build-worker"):
        r = api.ws("POST", "/integrators/integrator-default/landings", role, landing)
        assert r.status == 403, role
    event = api.ws("POST", "/integrators/integrator-default/landings", "conductor", landing)
    assert event.status == 202, event.body
    assert event.body["transition"]["name"] == "landing_instructed"


@requires_postgres
def test_claim_refuses_an_unbound_binding_and_a_full_lane(api: Api) -> None:
    unbound = {"lane_id": "lane-a", "execution_binding_id": "eb-unbound"}
    r = api.ws("POST", "/tasks/task-2/claim", "conductor", unbound)
    assert r.status == 409
    assert r.body["reason_code"] == "unbound"


@requires_postgres
def test_only_the_conductor_hands_back(api: Api) -> None:
    api.insert("task", task("task-hb", state="claimed", lane_id="lane-other"))
    hb = {"handback_reason": "CI log unreadable", "handback_evidence": ["sr-9 transcript"]}
    for role in ("admin", "operator", "grooming-agent", "sensor", "build-worker"):
        assert api.ws("POST", "/tasks/task-hb/hand-back", role, hb).status == 403, role
    r = api.ws("POST", "/tasks/task-hb/hand-back", "conductor", hb)
    assert r.status == 200, r.body
    assert r.body["state"] == "handed_back"
    assert r.body["self_heal_id"]
    assert api.doc("self_heal", r.body["self_heal_id"]) is not None


@requires_postgres
@pytest.mark.parametrize(
    ("method", "rest", "body"),
    [
        ("POST", "/tasks", task("task-c1", origin="chain")),
        ("PATCH", "/lanes/lane-a", {"max_concurrent_chains": 5}),
        ("POST", "/decisions/dec-1/answer", {"resolution": "native"}),
        ("POST", "/stage-runs/sr-2/result", {"state": "succeeded"}),
    ],
)
def test_conductor_cannot_create_tasks_edit_lanes_or_answer(
    api: Api, method: str, rest: str, body: object
) -> None:
    assert api.ws(method, rest, "conductor", body).status == 403


# operators: the only accounts that edit Policies/Lanes or answer Decisions.


@requires_postgres
def test_only_operator_accounts_edit_lanes(api: Api) -> None:
    patch = {"max_concurrent_chains": 3}
    for role in ("viewer", "conductor", "build-worker", "sensor", "grooming-agent"):
        assert api.ws("PATCH", "/lanes/lane-a", role, patch).status == 403, role
    r = api.ws("PATCH", "/lanes/lane-a", "operator", patch)
    assert r.status == 200, r.body
    assert r.body["max_concurrent_chains"] == 3


@requires_postgres
def test_only_operator_accounts_edit_policies(api: Api) -> None:
    pol = dict(api.doc("policy", "pol-1") or {})
    pol["version"] = "1.1.0"
    for role in ("viewer", "conductor", "build-worker", "sensor", "grooming-agent"):
        assert api.ws("POST", "/policies/pol-1/versions", role, pol).status == 403, role
    r = api.ws("POST", "/policies/pol-1/versions", "operator", pol)
    assert r.status == 201, r.body
    assert r.body["content_hash"].startswith("sha256:")
    assert api.ws("GET", "/policies/pol-1", "conductor").body["version"] == "1.1.0"


@requires_postgres
def test_only_operator_accounts_answer_decisions(api: Api) -> None:
    answer = {"resolution": "native"}
    for role in ("viewer", "conductor", "build-worker", "sensor", "grooming-agent"):
        assert api.ws("POST", "/decisions/dec-1/answer", role, answer).status == 403, role
    r = api.ws("POST", "/decisions/dec-1/answer", "operator", answer)
    assert r.status == 200, r.body
    assert r.body["state"] == "answered"
    assert r.body["answered_by"] == {"kind": "operator", "id": "op-operator"}
    assert api.ws("POST", "/decisions/dec-1/answer", "admin", answer).status == 409


# issuance: the create+claim combination is refused; only admins issue.


@requires_postgres
def test_only_admins_issue_tokens(api: Api) -> None:
    rb = AGENT_BINDINGS["sensor"]["id"]
    body = {"agent_role": "sensor", "project_id": "proj-a"}
    for role in ("operator", "viewer", "conductor", "grooming-agent", "sensor", "build-worker"):
        assert api.ws("POST", f"/role-bindings/{rb}/tokens", role, body).status == 403, role


@requires_postgres
def test_tokens_are_issued_only_for_agent_service_accounts(api: Api) -> None:
    assert api.issue("conductor", binding="rb-operator").status == 409


@requires_postgres
def test_no_account_may_hold_create_and_claim(api: Api) -> None:
    # sa-groomer already holds a grooming token (task.create): a conductor token for the same
    # service account would let it create tasks and claim them.
    r = api.issue("conductor", binding=AGENT_BINDINGS["grooming-agent"]["id"])
    assert r.status == 422
    assert r.body["reason_code"] == "create_and_claim"
    r = api.issue("sensor", binding=AGENT_BINDINGS["conductor"]["id"], project_id="proj-a")
    assert r.status == 422
    # And the store itself refuses such a token, whatever wrote it.
    with api.db() as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO sortyard.api_token (id, token_sha256, workspace_id, role_binding_id,"
            " principal, role, capabilities, expires_at) VALUES ('t-x', 'x', %s, 'rb-conductor',"
            " '{}'::jsonb, 'conductor', ARRAY['task.create', 'task.claim'], now())",
            [WS],
        )


@requires_postgres
def test_every_mutation_is_audited_and_ledgered(api: Api) -> None:
    r = api.ws("PATCH", "/lanes/lane-a", "admin", {"heavy_job_cap": 1})
    assert r.status == 200
    with api.db() as conn:
        audit = conn.execute(
            "SELECT doc FROM sortyard.audit_log WHERE doc->'object'->>'id' = 'lane-a'"
        ).fetchall()
        events = conn.execute(
            "SELECT doc FROM sortyard.event WHERE object_kind = 'lane' AND object_id = 'lane-a'"
        ).fetchall()
    assert any(a[0]["actor"] == {"kind": "operator", "id": "op-admin"} for a in audit)
    assert events
