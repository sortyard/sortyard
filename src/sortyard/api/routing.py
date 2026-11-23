"""From an HTTP request to an operation's answer: route, authenticate, authorize, run.

The order is the contract's: an unknown route is 404; a missing or unknown token is 401; a
role outside the operation's ``x-sortyard-roles`` (permissions.OPERATIONS), or a token of
another workspace, is 403 — all before any object is read or the body is looked at. Then the
body is parsed (400 if malformed) and the handler runs inside one transaction; its refusals
are RFC 9457 problems.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, unquote

import psycopg

from sortyard.api import auth, handlers, permissions
from sortyard.api.store import ApiError, Conn

log = logging.getLogger("sortyard.api")

PROBLEM = "application/problem+json"
JSON = "application/json"
BODY_TYPES = {"application/json", "application/merge-patch+json"}


@dataclass(frozen=True)
class Answer:
    status: int
    body: Any = None
    content_type: str = JSON


def match(method: str, path: str) -> tuple[permissions.Operation, dict[str, str]] | None:
    for op in permissions.OPERATIONS.values():
        if op.method != method:
            continue
        found = op.pattern.match(path)
        if found:
            return op, {k: unquote(v) for k, v in found.groupdict().items()}
    return None


def problem(error: ApiError) -> Answer:
    return Answer(error.status, error.problem(), PROBLEM)


def bearer(headers: Mapping[str, str]) -> str | None:
    value = headers.get("Authorization") or headers.get("authorization") or ""
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def parse_body(raw: bytes, content_type: str | None) -> Any:
    if not raw:
        return None
    media = (content_type or JSON).split(";", 1)[0].strip().lower()
    if media not in BODY_TYPES:
        raise ApiError(400, "Bad Request", f"unsupported Content-Type {media!r}", "malformed")
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "Bad Request", f"body is not JSON: {exc}", "malformed") from None


def dispatch(
    method: str,
    target: str,
    headers: Mapping[str, str],
    raw_body: bytes,
    connect: Callable[[], Conn],
    token_ttl_seconds: int = auth.DEFAULT_TTL_SECONDS,
    signal_item: handlers.SignalItem | None = None,
) -> Answer | None:
    """The answer to one request, or None when no operation has this route."""
    path, _, query_string = target.partition("?")
    routed = match(method, path)
    if routed is None:
        return None
    op, params = routed
    token = bearer(headers)
    if token is None:
        return problem(
            ApiError(401, "Unauthorized", "a bearer token is required", "unauthenticated")
        )
    try:
        conn = connect()
    except psycopg.Error as exc:
        log.warning("database unavailable: %s", exc)
        return problem(ApiError(503, "Service Unavailable", "database unavailable", "database"))
    try:
        with conn:
            return _authorized(
                conn,
                op,
                params,
                query_string,
                token,
                headers,
                raw_body,
                token_ttl_seconds,
                signal_item,
            )
    except psycopg.Error as exc:
        log.exception("database error in %s", op.operation_id)
        return problem(ApiError(500, "Internal Server Error", type(exc).__name__, "database"))


def _authorized(
    conn: Conn,
    op: permissions.Operation,
    params: dict[str, str],
    query_string: str,
    token: str,
    headers: Mapping[str, str],
    raw_body: bytes,
    token_ttl_seconds: int,
    signal_item: handlers.SignalItem | None,
) -> Answer:
    principal = auth.authenticate(conn, token)
    if principal is None:
        return problem(ApiError(401, "Unauthorized", "unknown or expired token", "unauthenticated"))
    if principal.role not in op.roles:
        return problem(
            ApiError(
                403,
                "Forbidden",
                f"role {principal.role!r} may not {op.operation_id} "
                f"(permitted: {', '.join(sorted(op.roles))})",
                "role",
            )
        )
    workspace_id = params.pop("workspace_id")
    if principal.workspace_id != workspace_id:
        return problem(
            ApiError(403, "Forbidden", "the token belongs to another workspace", "workspace")
        )
    try:
        body = parse_body(raw_body, headers.get("Content-Type") or headers.get("content-type"))
        request = handlers.Request(
            conn=conn,
            principal=principal,
            workspace_id=workspace_id,
            params=params,
            query=dict(parse_qsl(query_string)),
            body=body,
            token_ttl_seconds=token_ttl_seconds,
            signal_item=signal_item,
        )
        if body is None and method_takes_body(op):
            raise ApiError(400, "Bad Request", "a JSON body is required", "malformed")
        with conn.transaction():
            reply = handlers.HANDLERS[op.operation_id](request)
    except ApiError as error:
        return problem(error)
    return Answer(reply.status, reply.body, JSON)


# Operations whose request body the spec marks required.
def method_takes_body(op: permissions.Operation) -> bool:
    return op.operation_id in _BODY_REQUIRED


_BODY_REQUIRED = {
    "createTask", "updateTask", "claimTask", "advanceTask", "handBackTask", "blockTask",
    "unblockTask", "cancelTask", "requeueTask", "createLane", "updateLane", "createPolicy",
    "proposePolicyVersion", "createDecision", "answerDecision", "submitStageRunResult",
    "createAlert", "instructIntegrator", "createRoleBinding", "issueServiceAccountToken",
    "requestItemChange",
}  # fmt: skip
