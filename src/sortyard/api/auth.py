"""Bearer tokens: who is calling, with which role, confined to what (design §7, §3.9).

A token belongs to one RoleBinding of one workspace and is stored only as its SHA-256
(``sortyard.api_token``, migration 0002). Two kinds:

- **Service-account tokens** — issued by an admin through ``issueServiceAccountToken`` for an
  ``agent-service-account`` binding, carrying one §7 agent role: ``conductor``,
  ``build-worker`` (confined to one stage run), ``sensor`` (confined to one project) or
  ``grooming-agent`` (optionally confined to one project). Issuance refuses any token whose
  permissions — together with every live token the same service account already holds —
  would include both task creation and claiming: the queue-poisoning vector (§7). Issuance
  holds a transaction lock on the service account itself (not just the binding), so two
  overlapping issuances through different bindings of one account cannot both pass the check.
  A project-scoped admin issues only tokens confined to its own project.
- **Operator tokens** — the interim operator credential until OIDC sessions land
  (``sortyard-api --issue-operator-token <role-binding>``). The role is always the binding's
  current role (admin, operator or viewer); changing or deleting the binding takes effect on
  the next request. No token is issued for a disabled operator, and an operator's token is
  refused while the operator is disabled.

A binding whose scope is a project names that project (``scope.ref``; the RoleBinding schema
refuses one without it at creation). One stored without it, from before that rule or written
directly, is never read as workspace-wide: no token is issued for it and every token of it is
refused (SY-V3-API-SCOPE-AND-DISABLED).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from sortyard.api import permissions, store
from sortyard.api.store import ApiError, Conn, Doc

DEFAULT_TTL_SECONDS = 24 * 3600
TOKEN_PREFIX = "sy_"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""

    actor: Doc  # {"kind": "operator" | "agent", "id": ...}
    role: str
    workspace_id: str
    project_id: str | None = None
    stage_run_id: str | None = None
    token_id: str = ""

    @property
    def is_agent(self) -> bool:
        return self.role in permissions.AGENT_ROLES


@dataclass(frozen=True)
class Issued:
    token: str
    token_id: str
    role: str
    expires_at: datetime
    project_id: str | None = None
    stage_run_id: str | None = None

    def body(self) -> Doc:
        """The ServiceAccountToken response (components/schemas/ServiceAccountToken)."""
        out: Doc = {
            "token": self.token,
            "agent_role": self.role,
            "expires_at": self.expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        if self.project_id:
            out["project_id"] = self.project_id
        if self.stage_run_id:
            out["stage_run_id"] = self.stage_run_id
        return out


class IssuanceRefused(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(422, "Unprocessable Content", detail, "create_and_claim")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_combination(new: Iterable[str], held: Iterable[str]) -> None:
    """Refuse a token whose capabilities, with those the account already holds, include both
    task.create and task.claim (§7: the queue-poisoning combination)."""
    combined = set(new) | set(held)
    if combined >= permissions.CREATE_AND_CLAIM:
        raise IssuanceRefused(
            "refused at issuance: this token would let one account both create tasks and "
            "claim them (the queue-poisoning combination, design §7)"
        )


def _store_token(
    conn: Conn,
    binding: Doc,
    role: str,
    ttl_seconds: int,
    *,
    project_id: str | None = None,
    stage_run_id: str | None = None,
    issued_by: Doc | None = None,
) -> Issued:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token_id = store.new_id("tok")
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    conn.execute(
        "INSERT INTO sortyard.api_token (id, token_sha256, workspace_id, role_binding_id,"
        " principal, role, capabilities, project_id, stage_run_id, issued_by, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            token_id,
            hash_token(token),
            binding["workspace_id"],
            binding["id"],
            Jsonb(binding["principal"]),
            role,
            sorted(permissions.capabilities(role)),
            project_id,
            stage_run_id,
            Jsonb(issued_by) if issued_by else None,
            expires_at,
        ],
    )
    return Issued(token, token_id, role, expires_at, project_id, stage_run_id)


def _binding(conn: Conn, role_binding_id: str, workspace_id: str | None = None) -> Doc | None:
    if workspace_id is None:
        row = conn.execute(
            "SELECT doc FROM sortyard.role_binding WHERE id = %s", [role_binding_id]
        ).fetchone()
        return None if row is None else dict(row[0])
    return store.get(conn, "role_binding", workspace_id, role_binding_id)


def unnamed_project(binding: Doc) -> bool:
    """A project scope that names no project: confined to nothing known, never workspace-wide."""
    scope = binding.get("scope") or {}
    return scope.get("kind") == "project" and not scope.get("ref")


def operator_disabled(conn: Conn, workspace_id: str, principal: Doc) -> bool:
    operator = store.get(conn, "operator", workspace_id, str(principal.get("id", "")))
    return operator is not None and operator.get("state") != "active"


def issue_operator_token(
    conn: Conn, role_binding_id: str, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> Issued:
    """An operator credential for an admin/operator/viewer RoleBinding (interim, until OIDC)."""
    binding = _binding(conn, role_binding_id)
    if binding is None:
        raise ValueError(f"no role binding {role_binding_id!r}")
    if binding.get("role") not in permissions.HUMAN_ROLES:
        raise ValueError(
            f"role binding {role_binding_id!r} is {binding.get('role')!r}, not an operator "
            "role; service accounts get tokens from issueServiceAccountToken"
        )
    if unnamed_project(binding):
        raise ValueError(
            f"role binding {role_binding_id!r} is scoped to a project but names no project"
        )
    if operator_disabled(conn, binding["workspace_id"], binding["principal"]):
        raise ValueError(
            f"role binding {role_binding_id!r} is for operator "
            f"{binding['principal'].get('id')!r}, which is disabled"
        )
    return _store_token(conn, binding, binding["role"], ttl_seconds)


def lock_principal(conn: Conn, workspace_id: str, principal: Doc) -> None:
    """Serialise token issuance per service account: a transaction-scoped advisory lock on
    (workspace, principal), held until commit, so the capability check and the insert of one
    issuance cannot interleave with another for the same account — whichever binding it
    goes through."""
    key = "sortyard.api_token:" + json.dumps(
        [workspace_id, principal], sort_keys=True, separators=(",", ":")
    )
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def issue_service_account_token(
    conn: Conn,
    workspace_id: str,
    role_binding_id: str,
    request: Doc,
    issued_by: Doc,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    *,
    issuer_project_id: str | None = None,
) -> Issued:
    """issueServiceAccountToken: validate the request against the binding and the issuer's
    scope, refuse the create+claim combination, store the token's hash.

    ``issuer_project_id`` is the project a project-scoped admin is confined to: such an admin
    issues only tokens confined to that project (never a workspace-wide conductor or
    grooming token, never a build-worker token for another project's stage run)."""
    unknown = set(request) - {"agent_role", "project_id", "stage_run_id"}
    if unknown:
        raise store.unprocessable(f"unknown properties: {sorted(unknown)}")
    role = request.get("agent_role")
    if role not in permissions.AGENT_ROLES:
        raise store.unprocessable(f"agent_role must be one of {list(permissions.AGENT_ROLES)}")
    project_id = request.get("project_id")
    stage_run_id = request.get("stage_run_id")
    for name, value in (("project_id", project_id), ("stage_run_id", stage_run_id)):
        if value is not None and not isinstance(value, str):
            raise store.unprocessable(f"{name} must be a string")

    binding = store.get(conn, "role_binding", workspace_id, role_binding_id, lock=True)
    if binding is None:
        raise store.not_found("role binding", role_binding_id)
    if binding.get("role") != "agent-service-account":
        raise store.conflict(
            f"role binding {role_binding_id!r} is {binding.get('role')!r}: service-account "
            "tokens are issued only for agent-service-account bindings",
            "not_a_service_account",
        )
    if unnamed_project(binding):
        raise store.unprocessable(
            f"role binding {role_binding_id!r} is scoped to a project but names no project",
            "out_of_binding_scope",
        )
    scope = binding.get("scope") or {}
    if scope.get("kind") == "project":
        if project_id is None:
            project_id = scope.get("ref")
        elif project_id != scope.get("ref"):
            raise store.unprocessable(
                f"the binding is scoped to project {scope.get('ref')!r}", "out_of_binding_scope"
            )

    if role == "build-worker":
        if stage_run_id is None:
            raise store.unprocessable(
                "a build-worker token is confined to one stage run: stage_run_id is required"
            )
        if project_id is not None:
            raise store.unprocessable("a build-worker token is confined by stage_run_id only")
        if not store.exists(conn, "stage_run", workspace_id, stage_run_id):
            raise store.not_found("stage run", stage_run_id)
    elif stage_run_id is not None:
        raise store.unprocessable("stage_run_id confines build-worker tokens only")
    if role == "sensor" and project_id is None:
        raise store.unprocessable(
            "a sensor token is confined to its project: project_id is required"
        )
    if role == "conductor" and project_id is not None:
        raise store.unprocessable("the conductor token is workspace-wide; omit project_id")
    if project_id is not None and not store.exists(conn, "project", workspace_id, project_id):
        raise store.not_found("project", project_id)
    if issuer_project_id is not None:
        if role == "build-worker":
            confined_to = _stage_run_project(conn, workspace_id, str(stage_run_id))
        else:
            confined_to = project_id
        if confined_to != issuer_project_id:
            raise store.forbidden(
                f"this admin is confined to project {issuer_project_id!r}: it issues only "
                "tokens confined to that project",
                "project_scope",
            )

    lock_principal(conn, workspace_id, binding["principal"])

    held = conn.execute(
        "SELECT coalesce(array_agg(DISTINCT c), '{}') FROM sortyard.api_token,"
        " unnest(capabilities) AS c WHERE workspace_id = %s AND principal = %s"
        " AND revoked_at IS NULL AND expires_at > now()",
        [workspace_id, Jsonb(binding["principal"])],
    ).fetchone()
    check_combination(permissions.capabilities(role), held[0] if held else [])

    issued = _store_token(
        conn,
        binding,
        role,
        ttl_seconds,
        project_id=project_id,
        stage_run_id=stage_run_id,
        issued_by=issued_by,
    )
    summary = {k: v for k, v in issued.body().items() if k != "token"}
    store.record(
        conn,
        workspace_id,
        issued_by,
        "api_token",
        issued.token_id,
        action="create",
        transition="token_issued",
        before=None,
        after={**summary, "role_binding_id": role_binding_id},
    )
    return issued


def _stage_run_project(conn: Conn, workspace_id: str, stage_run_id: str) -> str | None:
    row = conn.execute(
        "SELECT t.project_id FROM sortyard.stage_run AS sr"
        " JOIN sortyard.chain AS c ON c.workspace_id = sr.workspace_id AND c.id = sr.chain_id"
        " JOIN sortyard.task AS t ON t.workspace_id = c.workspace_id AND t.id = c.task_id"
        " WHERE sr.workspace_id = %s AND sr.id = %s",
        [workspace_id, stage_run_id],
    ).fetchone()
    return None if row is None else row[0]


def authenticate(conn: Conn, token: str) -> Principal | None:
    """The principal behind a bearer token; None when unknown, expired, revoked, or its
    binding no longer grants it."""
    row: Any = conn.execute(
        "SELECT t.id, t.workspace_id, t.principal, t.role, t.project_id, t.stage_run_id,"
        " rb.doc FROM sortyard.api_token AS t"
        " JOIN sortyard.role_binding AS rb ON rb.id = t.role_binding_id"
        " WHERE t.token_sha256 = %s AND t.revoked_at IS NULL AND t.expires_at > now()",
        [hash_token(token)],
    ).fetchone()
    if row is None:
        return None
    token_id, workspace_id, principal, role, project_id, stage_run_id, binding = row
    if binding.get("principal") != principal or unnamed_project(binding):
        return None
    if role in permissions.AGENT_ROLES:
        if binding.get("role") != "agent-service-account":
            return None
    else:
        role = binding.get("role")
        if role not in permissions.HUMAN_ROLES:
            return None
        scope = binding.get("scope") or {}
        if scope.get("kind") == "project":
            project_id = scope.get("ref")
        if operator_disabled(conn, workspace_id, principal):
            return None
    return Principal(
        actor=dict(principal),
        role=role,
        workspace_id=workspace_id,
        project_id=project_id,
        stage_run_id=stage_run_id,
        token_id=token_id,
    )
