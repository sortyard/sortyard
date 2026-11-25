"""Acceptance (SY-V3-API-SCOPE-AND-DISABLED): a project scope with no project named is never
read as the whole workspace, and a disabled operator holds no credential (design §7, §3.9).

- A RoleBinding whose scope is ``{"kind": "project"}`` with no ``ref`` is refused when it is
  created (422, nothing stored). One that already exists (written before the refusal, or
  directly) gets no token, operator or service-account, and a token already issued for it is
  refused (401) on every request: it is never treated as workspace-wide, so it cannot act on
  another project.
- A token whose operator is disabled is refused (401) on every operation, admitting and
  withdrawing an item included, and no operator token is issued for a disabled operator.
- A workspace-scoped binding still acts on every project of its workspace.

Every request goes through the real API service over HTTP, on a real Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from sortyard.api import auth
from tests.api_harness import ITEM, WS, Api, role_binding, running_api
from tests.pg import requires_postgres

UNNAMED = {"kind": "project"}  # a project scope that names no project


def operator(oid: str) -> dict[str, Any]:
    return {
        "id": oid,
        "workspace_id": WS,
        "subject": f"oidc|{oid}",
        "display_name": oid,
        "state": "active",
    }


def decision(did: str, project_id: str) -> dict[str, Any]:
    return {
        "id": did,
        "workspace_id": WS,
        "project_id": project_id,
        "question": "Which way?",
        "options": ["left", "right"],
        "default": "left",
        "decide_by": "2026-12-01T00:00:00Z",
        "state": "open",
    }


def admission(iid: str) -> dict[str, Any]:
    return {
        "id": iid,
        "project_id": "proj-b",
        "title": "An item",
        "lane": "example",
        "repository": "example/app",
        "spec": {
            "outcome": "it is admitted",
            "acceptance": [{"test": "tests/test_api_auth.py", "name": "it is admitted"}],
        },
    }


def drop_ref(api: Api, rbid: str) -> None:
    """Make a stored binding's project scope name no project, as one written before creation
    refused it would be."""
    with api.db() as conn:
        conn.execute(
            "UPDATE sortyard.role_binding SET doc = doc #- '{scope,ref}' WHERE id = %s", [rbid]
        )


def set_state(api: Api, oid: str, state: str) -> None:
    """An operator's state, written as the store holds it (the API has no updateOperator
    handler yet; the bootstrap declaration can also create an operator disabled)."""
    with api.db() as conn:
        conn.execute(
            "UPDATE sortyard.operator SET doc = jsonb_set(doc, '{state}', to_jsonb(%s::text))"
            " WHERE id = %s",
            [state, oid],
        )


def answer(api: Api, did: str, token: str) -> Any:
    return api.call(
        "POST",
        f"/v1/workspaces/{WS}/decisions/{did}/answer",
        body={"resolution": "left"},
        token=token,
    )


def items(api: Api) -> set[str]:
    with psycopg.connect(api.conninfo) as conn:
        return {r[0] for r in conn.execute("SELECT id FROM sortyard.item").fetchall()}


@pytest.fixture(scope="module")
def api() -> Iterator[Api]:
    for handle in running_api():
        for did, project_id in (("dec-a", "proj-a"), ("dec-b", "proj-b"), ("dec-b2", "proj-b")):
            handle.insert("decision", decision(did, project_id))
        yield handle


@requires_postgres
def test_a_project_scope_with_no_project_named_is_refused_and_never_read_as_the_whole_workspace(
    api: Api,
) -> None:
    """A project scope with no project named is refused and never read as the whole
    workspace."""
    # Refused when it is created, for an operator and for a service account; nothing stored.
    api.insert("operator", operator("op-unnamed"))
    for rb in (
        {**role_binding("rb-new-op", "operator", "op-unnamed", "operator"), "scope": UNNAMED},
        {
            **role_binding("rb-new-sa", "agent", "sa-unnamed", "agent-service-account"),
            "scope": UNNAMED,
        },
    ):
        created = api.ws("POST", "/role-bindings", "admin", rb)
        assert created.status == 422, created.body
        assert api.doc("role_binding", rb["id"]) is None
    # A binding that names its project is created as before.
    named = {
        **role_binding("rb-named", "operator", "op-unnamed", "operator"),
        "scope": {"kind": "project", "ref": "proj-a"},
    }
    assert api.ws("POST", "/role-bindings", "admin", named).status == 201

    # One that already exists: an operator token issued while it named proj-a, then its ref
    # gone. The token is refused on every request; it never acts on another project.
    api.insert(
        "role_binding",
        {
            **role_binding("rb-old-op", "operator", "op-unnamed", "operator"),
            "scope": {"kind": "project", "ref": "proj-a"},
        },
    )
    with api.db() as conn:
        held = auth.issue_operator_token(conn, "rb-old-op").token
    assert answer(api, "dec-a", held).status == 200  # confined to proj-a, it acts there
    assert answer(api, "dec-b", held).status == 403
    drop_ref(api, "rb-old-op")
    for method, path, body in (
        ("POST", f"/v1/workspaces/{WS}/decisions/dec-b/answer", {"resolution": "left"}),
        ("GET", f"/v1/workspaces/{WS}/decisions?project_id=proj-b", None),
        ("GET", f"/v1/workspaces/{WS}/decisions", None),
        ("POST", f"/v1/workspaces/{WS}/items", admission("item-unnamed")),
    ):
        reply = api.call(method, path, body=body, token=held)
        assert reply.status == 401, (method, path, reply.body)
    assert (api.doc("decision", "dec-b") or {})["state"] == "open"
    assert "item-unnamed" not in items(api)
    # And no operator token is issued for it.
    with api.db() as conn, pytest.raises(ValueError, match="names no project"):
        auth.issue_operator_token(conn, "rb-old-op")

    # A service account bound to a project scope with no project named: no token is issued
    # (it would be workspace-wide), and one issued before is refused.
    api.insert(
        "role_binding",
        {
            **role_binding("rb-old-sa", "agent", "sa-unnamed", "agent-service-account"),
            "scope": UNNAMED,
        },
    )
    issued = api.issue("grooming-agent", "rb-old-sa")
    assert issued.status == 422, issued.body
    api.insert(
        "role_binding",
        {
            **role_binding("rb-old-sa2", "agent", "sa-unnamed2", "agent-service-account"),
            "scope": {"kind": "project", "ref": "proj-a"},
        },
    )
    issued = api.issue("grooming-agent", "rb-old-sa2")
    assert issued.status == 201, issued.body
    drop_ref(api, "rb-old-sa2")
    reply = api.call("GET", f"/v1/workspaces/{WS}/tasks", token=issued.body["token"])
    assert reply.status == 401, reply.body

    # A workspace-scoped binding acts on every project of its workspace.
    assert answer(api, "dec-b2", api.tokens["operator"]).status == 200
    listed = api.ws("GET", "/decisions", "viewer")
    assert listed.status == 200
    assert {"proj-a", "proj-b"} <= {d["project_id"] for d in listed.body["items"]}


@requires_postgres
def test_a_disabled_operators_token_is_refused_and_none_is_issued_for_it(api: Api) -> None:
    """A disabled operator's token is refused and none is issued for it."""
    api.insert("operator", operator("op-leaving"))
    rb = role_binding("rb-leaving", "operator", "op-leaving", "operator")
    assert api.ws("POST", "/role-bindings", "admin", rb).status == 201
    with api.db() as conn:
        token = auth.issue_operator_token(conn, "rb-leaving").token
    # Active, it admits an item and may ask for the seeded one's withdrawal.
    admitted = api.call(
        "POST", f"/v1/workspaces/{WS}/items", body=admission("item-ok"), token=token
    )
    assert admitted.status == 201, admitted.body

    set_state(api, "op-leaving", "disabled")
    for method, path, body in (
        ("POST", f"/v1/workspaces/{WS}/items", admission("item-refused")),
        (
            "POST",
            f"/v1/workspaces/{WS}/items/{ITEM}/requests",
            {"answer": "withdraw", "reason": "a disabled operator asks"},
        ),
        ("GET", f"/v1/workspaces/{WS}/items/{ITEM}", None),
        ("GET", f"/v1/workspaces/{WS}/decisions", None),
    ):
        reply = api.call(method, path, body=body, token=token)
        assert reply.status == 401, (method, path, reply.body)
    assert "item-refused" not in items(api)
    with psycopg.connect(api.conninfo) as conn:
        asked = conn.execute(
            "SELECT count(*) FROM sortyard.audit_log WHERE doc -> 'object' ->> 'kind' ="
            " 'item_request'"
        ).fetchone()
    assert asked == (0,)

    # No token is issued for a disabled operator.
    with api.db() as conn, pytest.raises(ValueError, match="disabled"):
        auth.issue_operator_token(conn, "rb-leaving")
    with api.db() as conn:
        held = conn.execute(
            "SELECT count(*) FROM sortyard.api_token WHERE role_binding_id = 'rb-leaving'"
        ).fetchone()
    assert held == (1,)

    # Enabled again, its token is honoured again.
    set_state(api, "op-leaving", "active")
    assert api.call("GET", f"/v1/workspaces/{WS}/decisions", token=token).status == 200
