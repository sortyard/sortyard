"""The kernel's projection in Postgres: items, runs, links and the event ledger.

(company/HARNESS-V3.md section 3.2, SY-V3-LEDGER-AND-VIEW.) The item workflow owns item state.
`Ledger.record` is the workflow's record step: for every transition it writes the item row, the
run rows and one ledger Event in a single database call (`sortyard.record_item_transition`,
migration 0003), so they land together or not at all. The tracker view (`queue`, `timeline`)
reads this projection and nothing else. Nothing here, and no endpoint, writes item state any
other way; the database refuses a direct update.

The tenant identifier is `workspace_id`, on every row.

Each Event also says which harness.lifecycle.v1 kind it is (`lifecycle_kind`), so the measure
job that scores the legacy conductor can score this kernel from the same kinds.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from sortyard.kernel.states import merged_states

Conn = psycopg.Connection[Any]

LIFECYCLE_RECORD_TYPE = "harness.lifecycle.v1"
#: The kinds of harness.lifecycle.v1 (k3s-harness control-plane/conductor/lifecycle_events.py).
LIFECYCLE_KINDS = frozenset(
    {
        "released",
        "merged",
        "handback",
        "readiness_hold",
        "readiness_cleared",
        "refused",
        "main_red",
        "main_green",
        "coverage",
        "completion",
        "release_suspended",
        "tunable_default",
        "secret_repaired",
        "capacity_step",
    }
)
ACTOR = {"kind": "system", "id": "item-workflow"}


class LinkRefused(ValueError):
    """The link would make an item wait on itself, directly or through other items."""


def lifecycle_kind(transition: Mapping[str, Any]) -> str | None:
    """The harness.lifecycle.v1 kind of a transition.

    - into a state the table marks with a lifecycle kind (`lifecycle = "merged"` on the
      shipped table's merged state): that kind. A terminal state the table does not mark,
      such as a cancelled one added later, is not counted as merged.
    - into a decision because the work came back without finishing (an outcome, a passed
      limit): `handback`. A person's request is put to the decision too, and is not a handback.
    - into a wait on a named need: `readiness_hold`; out of one, back to work:
      `readiness_cleared`. A wait that ends at its limit goes to a decision (`handback`); no
      `readiness_cleared` is written for it, because nothing cleared.
    - out of the queue into work: `released`

    harness.lifecycle.v1 has no kind for a move between two work states (building to checking,
    say), for entering the queue, or for a decision's answer. Those return None: the ledger
    keeps the Event, and it has no lifecycle kind to be scored under. `completion` (verified or
    reported-only) is never returned: the kernel has no verifier yet.
    """
    entered, left = transition.get("state_kind"), transition.get("from_kind")
    declared = transition.get("lifecycle")
    if isinstance(declared, str):
        return declared
    if entered == "decision":
        return None if transition.get("cause") == "request" else "handback"
    if entered == "need":
        return "readiness_hold"
    if left == "need" and entered == "work":
        return "readiness_cleared"
    if left == "queue" and entered == "work":
        return "released"
    return None


def _digest(tenant: str, item: str) -> str:
    """One item of one tenant, as 32 hex characters."""
    return hashlib.sha256(f"{len(tenant)}:{tenant}{item}".encode()).hexdigest()[:32]


def _timestamp(value: str) -> str:
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError(f"a transition's entered_at carries its offset: {value!r}")
    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def event_for(transition: Mapping[str, Any]) -> dict[str, Any]:
    """The ledger Event (spec/event.schema.json, less the seq the ledger assigns) of a transition.

    It carries the state left, the state entered, the owner, the limit and the typed reason.
    Its id is fixed by the tenant, the item and the transition's sequence, so recording a
    transition twice appends one Event. The tenant and the item go into the id as a digest: both
    may contain every character an id allows, so no separator could keep two tenants' ids apart.
    """
    tenant, item, sequence = transition["tenant"], transition["item"], transition["sequence"]
    facts = {
        "sequence": sequence,
        "owner": transition.get("owner"),
        "limit": transition.get("limit"),
        "reason": transition["reason"],
        "cause": transition["cause"],
        "outcome": transition.get("outcome"),
        "default": transition.get("default"),
        "action": transition.get("action"),
        "decision": transition.get("decision"),
        "request": transition.get("request"),
        "lifecycle": {"record_type": LIFECYCLE_RECORD_TYPE, "kind": lifecycle_kind(transition)},
    }
    return {
        "id": f"item-{_digest(tenant, item)}-{sequence}",
        "workspace_id": tenant,
        "ts": _timestamp(transition["entered_at"]),
        "actor": ACTOR,
        "object": {"kind": "item", "id": item},
        "transition": {
            "name": transition["cause"],
            "from": transition.get("from_state"),
            "to": transition["state"],
        },
        "facts": facts,
        "refs": [],
    }


class Ledger:
    """Writes to the projection. `connect` opens a connection; each call is one transaction."""

    def __init__(self, connect: Callable[[], Conn]) -> None:
        self._connect = connect

    def create_item(
        self,
        *,
        tenant: str,
        item: str,
        project: str,
        title: str,
        risk_tier: str = "medium",
        milestone: str | None = None,
    ) -> None:
        """Add an item. It has no state until its workflow records the first transition."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sortyard.item"
                " (workspace_id, id, project_id, milestone_id, title, risk_tier)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (tenant, item, project, milestone, title, risk_tier),
            )

    def link(self, *, tenant: str, item: str, blocked_by: str) -> None:
        """Record that `item` is blocked by `blocked_by`. A link that closes a cycle is refused."""
        with self._connect() as conn:
            # One writer of links per tenant at a time, so two links cannot close a cycle
            # between them.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"item_link:{tenant}",))
            cycle = conn.execute(
                "WITH RECURSIVE upstream (id) AS ("
                "    SELECT %(blocked_by)s::text"
                "    UNION"
                "    SELECT l.blocked_by FROM sortyard.item_link AS l"
                "    JOIN upstream AS u ON l.item_id = u.id"
                "    WHERE l.workspace_id = %(tenant)s"
                ") SELECT 1 FROM upstream WHERE id = %(item)s",
                {"tenant": tenant, "item": item, "blocked_by": blocked_by},
            ).fetchone()
            if cycle is not None:
                raise LinkRefused(
                    f"{item} cannot be blocked by {blocked_by}: it would wait on itself"
                )
            conn.execute(
                "INSERT INTO sortyard.item_link (workspace_id, item_id, blocked_by)"
                " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (tenant, item, blocked_by),
            )

    def record(self, transition: Mapping[str, Any]) -> None:
        """The item workflow's record step: the item row, its runs and its Event, together."""
        with self._connect() as conn:
            conn.execute(
                "SELECT sortyard.record_item_transition(%s, %s)",
                (Jsonb(dict(transition)), Jsonb(event_for(transition))),
            )


def queue(
    conn: Conn, tenant: str, project: str, now: datetime | None = None
) -> list[dict[str, Any]]:
    """A project's items that are not done, in link order, each with its state, owner and age.

    Link order: an item comes after every item it is blocked by. Items that no link orders
    keep the order they were created in; a milestone groups items and never orders them. Age
    is the time since the item entered its state (since it was created, for one not started).
    A blocker that ended without merging (withdrawn) still blocks, named in `ended_blockers`.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        if now is None:
            now = cursor.execute("SELECT now() AS now").fetchone()["now"]  # type: ignore[index]
        rows = cursor.execute(
            "SELECT id, title, milestone_id, risk_tier, state, owner, limit_text, reason,"
            "       entered_at, created_at"
            " FROM sortyard.item"
            " WHERE workspace_id = %s AND project_id = %s"
            "   AND state_kind IS DISTINCT FROM 'terminal'"
            " ORDER BY position",
            (tenant, project),
        ).fetchall()
        links = cursor.execute(
            "SELECT l.item_id, l.blocked_by, b.state AS ended FROM sortyard.item_link AS l"
            " JOIN sortyard.item AS i ON i.workspace_id = l.workspace_id AND i.id = l.item_id"
            " LEFT JOIN sortyard.item AS b ON (b.workspace_id, b.id) = (l.workspace_id,"
            "   l.blocked_by) AND b.state_kind = 'terminal' AND NOT b.state = ANY(%s)"
            " WHERE l.workspace_id = %s AND i.project_id = %s",
            (merged_states(), tenant, project),
        ).fetchall()
    waiting_on: dict[str, set[str]] = {row["id"]: set() for row in rows}
    ended: dict[str, dict[str, str]] = {row["id"]: {} for row in rows}
    for link in links:
        # A blocker that is merged, or in another project, no longer holds anything back here.
        if link["item_id"] in waiting_on and link["blocked_by"] in waiting_on:
            waiting_on[link["item_id"]].add(link["blocked_by"])
        elif link["item_id"] in ended and link["ended"]:
            ended[link["item_id"]][link["blocked_by"]] = link["ended"]
    ordered: list[dict[str, Any]] = []
    placed: set[str] = set()
    remaining = list(rows)
    while remaining:
        ready = [row for row in remaining if waiting_on[row["id"]] <= placed]
        # Links cannot form a cycle (Ledger.link refuses one); if rows written some other way
        # do, list what is left in creation order instead of hiding it.
        for row in ready or remaining:
            since = row["entered_at"] or row["created_at"]
            ordered.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "milestone_id": row["milestone_id"],
                    "risk_tier": row["risk_tier"],
                    "state": row["state"],
                    "owner": row["owner"],
                    "limit": row["limit_text"],
                    "reason": row["reason"],
                    "entered_at": row["entered_at"].isoformat() if row["entered_at"] else None,
                    "age_seconds": max(0, int((now - since).total_seconds())),
                    "blocked_by": sorted(waiting_on[row["id"]] | set(ended[row["id"]])),
                    "ended_blockers": ended[row["id"]],
                }
            )
            placed.add(row["id"])
        remaining = [row for row in remaining if row["id"] not in placed]
    return ordered


def timeline(conn: Conn, tenant: str, item: str) -> list[dict[str, Any]] | None:
    """One item's Events in ledger order, or None when the tenant has no such item."""
    known = conn.execute(
        "SELECT 1 FROM sortyard.item WHERE workspace_id = %s AND id = %s", (tenant, item)
    ).fetchone()
    if known is None:
        return None
    rows = conn.execute(
        "SELECT doc FROM sortyard.event"
        " WHERE workspace_id = %s AND object_kind = 'item' AND object_id = %s ORDER BY seq",
        (tenant, item),
    ).fetchall()
    return [row[0] for row in rows]
