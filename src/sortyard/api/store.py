"""Postgres access for the API: the §3 tables (charts/sortyard/migrations/) and the writes every
mutation makes — one AuditLog entry and one ledger Event (spec/openapi.json: "Every mutation
writes an AuditLog entry and ledger Events").

Every row's ``doc`` is the object exactly as its §3 JSON Schema defines it; the other columns
are generated from it. State and config objects are keyed by id; definitions by (id, version),
the newest recorded version being the current one.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

Conn = psycopg.Connection[Any]
Doc = dict[str, Any]

#: The id pattern of common.schema.json#/$defs/id.
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$"


class ApiError(Exception):
    """A refusal, answered as an RFC 9457 problem (components/schemas/Problem)."""

    def __init__(
        self, status: int, title: str, detail: str = "", reason_code: str | None = None
    ) -> None:
        super().__init__(f"{status} {title}: {detail}")
        self.status = status
        self.title = title
        self.detail = detail
        self.reason_code = reason_code

    def problem(self) -> Doc:
        body: Doc = {"type": "about:blank", "title": self.title, "status": self.status}
        if self.detail:
            body["detail"] = self.detail
        if self.reason_code:
            body["reason_code"] = self.reason_code
        return body


def bad_request(detail: str) -> ApiError:
    return ApiError(400, "Bad Request", detail, "malformed")


def forbidden(detail: str, reason_code: str = "out_of_scope") -> ApiError:
    return ApiError(403, "Forbidden", detail, reason_code)


def not_found(kind: str, oid: str) -> ApiError:
    return ApiError(404, "Not Found", f"no {kind} {oid!r} in this workspace", "not_found")


def conflict(detail: str, reason_code: str) -> ApiError:
    return ApiError(409, "Conflict", detail, reason_code)


def unprocessable(detail: str, reason_code: str = "invalid") -> ApiError:
    return ApiError(422, "Unprocessable Content", detail, reason_code)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def content_hash(doc: Mapping[str, Any]) -> str:
    """sha256 over the canonical JSON of a document (its own content_hash excluded)."""
    body = {k: v for k, v in doc.items() if k != "content_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


# --- reads --------------------------------------------------------------------------------


def _table(name: str) -> sql.Composed:
    return sql.SQL("sortyard.{}").format(sql.Identifier(name))


def get(conn: Conn, table: str, workspace_id: str, oid: str, *, lock: bool = False) -> Doc | None:
    """The current document of a state/config object, optionally locked for update."""
    query = sql.SQL("SELECT doc FROM {} WHERE workspace_id = %s AND id = %s{}").format(
        _table(table), sql.SQL(" FOR UPDATE" if lock else "")
    )
    row = conn.execute(query, [workspace_id, oid]).fetchone()
    return None if row is None else dict(row[0])


def get_definition(
    conn: Conn, table: str, workspace_id: str, oid: str, version: str | None = None
) -> Doc | None:
    """A definition version; without ``version``, the newest recorded one (the current)."""
    if version is None:
        latest = sql.SQL(
            "SELECT doc FROM {} WHERE workspace_id = %s AND id = %s "
            "ORDER BY recorded_at DESC, version DESC LIMIT 1"
        ).format(_table(table))
        row = conn.execute(latest, [workspace_id, oid]).fetchone()
    else:
        exact = sql.SQL(
            "SELECT doc FROM {} WHERE workspace_id = %s AND id = %s AND version = %s"
        ).format(_table(table))
        row = conn.execute(exact, [workspace_id, oid, version]).fetchone()
    return None if row is None else dict(row[0])


@dataclass(frozen=True)
class Page:
    """Offset paging behind an opaque cursor."""

    offset: int
    limit: int

    @classmethod
    def parse(cls, query: Mapping[str, str]) -> Page:
        raw_limit = query.get("limit", "50")
        try:
            limit = int(raw_limit)
        except ValueError:
            raise bad_request(f"limit must be an integer, not {raw_limit!r}") from None
        if not 1 <= limit <= 500:
            raise bad_request("limit must be between 1 and 500")
        offset = 0
        if query.get("cursor"):
            try:
                decoded = base64.urlsafe_b64decode(query["cursor"].encode()).decode()
                kind, _, value = decoded.partition(":")
                if kind != "o":
                    raise ValueError(decoded)
                offset = int(value)
            except (ValueError, binascii.Error, UnicodeDecodeError):
                raise bad_request("cursor is not one this API issued") from None
        return cls(offset, limit)

    def cursor_after(self, returned: int, more: bool) -> str | None:
        if not more:
            return None
        return base64.urlsafe_b64encode(f"o:{self.offset + returned}".encode()).decode()


def page(
    conn: Conn,
    table: str,
    workspace_id: str,
    filters: Mapping[str, str | None],
    paging: Page,
    *,
    order: str = "id",
    latest_definitions: bool = False,
    extra: tuple[str, Sequence[Any]] | None = None,
) -> Doc:
    """One page of ``{"items": [...], "next_cursor": ...}``; ``filters`` match generated
    columns. ``latest_definitions`` keeps only the current version of each definition."""
    where: list[sql.Composable] = [sql.SQL("workspace_id = %s")]
    params: list[Any] = [workspace_id]
    for column, value in filters.items():
        if value is not None:
            where.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
            params.append(value)
    if extra is not None:
        where.append(sql.SQL(extra[0]))
        params.extend(extra[1])
    source: sql.Composable = _table(table)
    if latest_definitions:
        source = sql.SQL(
            "(SELECT DISTINCT ON (id) * FROM {} ORDER BY id, recorded_at DESC, version DESC) AS t"
        ).format(_table(table))
    query = sql.SQL("SELECT doc FROM {} WHERE {} ORDER BY {} LIMIT %s OFFSET %s").format(
        source, sql.SQL(" AND ").join(where), sql.SQL(order)
    )
    rows = conn.execute(query, [*params, paging.limit + 1, paging.offset]).fetchall()
    items = [dict(r[0]) for r in rows[: paging.limit]]
    return {
        "items": items,
        "next_cursor": paging.cursor_after(len(items), len(rows) > paging.limit),
    }


# --- writes -------------------------------------------------------------------------------


def insert(conn: Conn, table: str, doc: Doc) -> None:
    conn.execute(sql.SQL("INSERT INTO {} (doc) VALUES (%s)").format(_table(table)), [Jsonb(doc)])


def replace(conn: Conn, table: str, doc: Doc) -> None:
    conn.execute(
        sql.SQL("UPDATE {} SET doc = %s WHERE workspace_id = %s AND id = %s").format(_table(table)),
        [Jsonb(doc), doc["workspace_id"], doc["id"]],
    )


def delete(conn: Conn, table: str, workspace_id: str, oid: str) -> None:
    conn.execute(
        sql.SQL("DELETE FROM {} WHERE workspace_id = %s AND id = %s").format(_table(table)),
        [workspace_id, oid],
    )


def exists(conn: Conn, table: str, workspace_id: str, oid: str) -> bool:
    query = sql.SQL("SELECT 1 FROM {} WHERE workspace_id = %s AND id = %s LIMIT 1")
    return conn.execute(query.format(_table(table)), [workspace_id, oid]).fetchone() is not None


def append_event(
    conn: Conn,
    workspace_id: str,
    actor: Doc,
    kind: str,
    oid: str,
    transition: str,
    *,
    before: str | None = None,
    after: str | None = None,
    facts: Doc | None = None,
    refs: Sequence[str] = (),
) -> Doc:
    """Append one ledger Event; returns it with its assigned ``seq``."""
    event: Doc = {
        "id": new_id("evt"),
        "workspace_id": workspace_id,
        "ts": now(),
        "actor": actor,
        "object": {"kind": kind, "id": oid},
        "transition": {"name": transition, "from": before, "to": after},
        "facts": facts or {},
        "refs": list(refs),
    }
    row = conn.execute("SELECT sortyard.append_event(%s)", [Jsonb(event)]).fetchone()
    assert row is not None
    return {**event, "seq": int(row[0])}


def audit(
    conn: Conn,
    workspace_id: str,
    actor: Doc,
    action: str,
    kind: str,
    oid: str,
    before: Doc | None,
    after: Doc | None,
    reason: str | None = None,
) -> Doc:
    entry: Doc = {
        "id": new_id("audit"),
        "workspace_id": workspace_id,
        "ts": now(),
        "actor": actor,
        "channel": "api",
        "action": action,
        "object": {"kind": kind, "id": oid},
        "before": before,
        "after": after,
    }
    if reason:
        entry["reason"] = reason
    insert(conn, "audit_log", entry)
    return entry


def record(
    conn: Conn,
    workspace_id: str,
    actor: Doc,
    kind: str,
    oid: str,
    *,
    action: str,
    transition: str,
    before: Doc | None,
    after: Doc | None,
    reason: str | None = None,
    facts: Doc | None = None,
    refs: Sequence[str] = (),
) -> Doc:
    """A mutation's paper trail: the AuditLog entry and the ledger Event. Returns the Event."""
    entry = audit(conn, workspace_id, actor, action, kind, oid, before, after, reason)
    return append_event(
        conn,
        workspace_id,
        actor,
        kind,
        oid,
        transition,
        before=_state(before),
        after=_state(after),
        facts=facts,
        refs=[f"audit-log:{entry['id']}", *refs],
    )


def _state(doc: Doc | None) -> str | None:
    if doc is None:
        return None
    state = doc.get("state")
    return state if isinstance(state, str) else None


def last_transition_from(conn: Conn, kind: str, oid: str, transition: str) -> str | None:
    """The ``from`` state of the object's latest ``transition`` event in the ledger."""
    row = conn.execute(
        "SELECT doc -> 'transition' ->> 'from' FROM sortyard.event "
        "WHERE object_kind = %s AND object_id = %s AND transition = %s "
        "ORDER BY seq DESC LIMIT 1",
        [kind, oid, transition],
    ).fetchone()
    return None if row is None else row[0]
