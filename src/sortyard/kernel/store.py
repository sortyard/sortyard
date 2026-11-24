"""What the lane runtime keeps in Postgres (migration 0004; HARNESS-V3 sections 3.1, 3.3).

Nothing here is held in a process: a kernel service that restarts reads all of it back.

- `Items` reads an admitted item's spec (`ItemSpec`: lane, repository, base branch, needs, the
  spec itself) and the **open stays**: every item that is in a state an owner can move it out
  of, with the dispatch number, action, detail and deadline its workflow recorded on entering.
  That one query is all an observer knows. It is also the preflight's result sink
  (`record_probe`).
- `PgGapRegistry` is `sortyard.kernel.preflight.GapRegistry` on two tables. The rule that a
  need of a lane has at most one open gap item is a unique index, so it holds across
  processes; opening or finding the gap item and linking the work item are one transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from sortyard.kernel.preflight import GapItem, ProbeRecord

Conn = psycopg.Connection[Any]
Connect = Callable[[], Conn]
# The kinds of state an owner moves an item out of (a decision is a pass, not a stay).
OPEN_KINDS = ("queue", "work", "need")


@dataclass(frozen=True)
class ItemSpec:
    """What an item was admitted with."""

    tenant: str
    item: str
    title: str
    lane: str
    repository: str
    base: str
    needs: tuple[str, ...]
    spec: Mapping[str, Any]


class Items:
    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    def spec(self, tenant: str, item: str) -> ItemSpec:
        """The item's spec, or `LookupError` for an item that was not admitted with one."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT i.title, s.lane, s.repository, s.base, s.needs, s.spec"
                " FROM sortyard.item_spec AS s JOIN sortyard.item AS i"
                "   ON (i.workspace_id, i.id) = (s.workspace_id, s.item_id)"
                " WHERE s.workspace_id = %s AND s.item_id = %s",
                (tenant, item),
            ).fetchone()
        if row is None:
            raise LookupError(f"item {item!r} of {tenant!r} has no spec: it was not admitted")
        return ItemSpec(tenant, item, row[0], row[1], row[2], row[3], tuple(row[4]), row[5])

    def open_stays(self) -> list[dict[str, Any]]:
        """Every open stay, oldest item first, shaped as the owner's call was: tenant, item,
        state, owner, dispatch, attempt, action, detail; and `entered_at`, `deadline`."""
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                "SELECT i.workspace_id AS tenant, i.id AS item, i.state, i.owner, r.dispatch,"
                "       r.attempt, r.action, r.detail, r.cause, i.entered_at, r.deadline"
                " FROM sortyard.item AS i JOIN sortyard.item_run AS r"
                "   ON (r.workspace_id, r.item_id, r.sequence) = (i.workspace_id, i.id, i.sequence)"
                " WHERE i.state_kind = ANY(%s) AND r.dispatch IS NOT NULL ORDER BY i.position",
                (list(OPEN_KINDS),),
            ).fetchall()

    def record_probe(self, record: ProbeRecord) -> None:
        """The preflight's result sink: one row per item, dispatch and need."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sortyard.probe_result"
                " (workspace_id, item_id, dispatch, need, lane, passed, output)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (workspace_id, item_id, dispatch, need) DO UPDATE SET"
                " lane = EXCLUDED.lane, passed = EXCLUDED.passed, output = EXCLUDED.output,"
                " recorded_at = now()",
                (
                    record.tenant,
                    record.item,
                    record.dispatch,
                    record.need,
                    record.lane,
                    record.passed,
                    record.output,
                ),
            )

    def probe_results(self, tenant: str, item: str) -> list[ProbeRecord]:
        """Every probe result recorded for the item, by dispatch."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT lane, dispatch, need, passed, output FROM sortyard.probe_result"
                " WHERE workspace_id = %s AND item_id = %s ORDER BY dispatch, recorded_at, need",
                (tenant, item),
            ).fetchall()
        return [ProbeRecord(tenant, item, *row) for row in rows]


_GAP = (
    "SELECT g.id, g.workspace_id, g.lane, g.need, g.resolver, g.output, g.open"
    " FROM sortyard.capability_gap AS g"
)


class PgGapRegistry:
    """`GapRegistry` in Postgres: gap items outlive the process and are shared by every one."""

    def __init__(self, connect: Connect) -> None:
        self._connect = connect

    def _gap(self, conn: Conn, row: tuple[Any, ...]) -> GapItem:
        items = conn.execute(
            "SELECT item_id FROM sortyard.capability_gap_item WHERE gap_id = %s ORDER BY position",
            (row[0],),
        ).fetchall()
        gap_id, tenant, lane, need, resolver, output, is_open = row
        linked = tuple(each[0] for each in items)
        return GapItem(gap_id, tenant, lane, need, resolver, output, linked, is_open)

    def open_or_link(
        self, *, tenant: str, lane: str, need: str, resolver: str, output: str, item: str
    ) -> GapItem:
        with self._connect() as conn:
            # The unique index on open gap items makes the insert find the open one instead.
            row = conn.execute(
                "INSERT INTO sortyard.capability_gap (workspace_id, lane, need, resolver, output)"
                " VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (workspace_id, lane, need) WHERE open"
                " DO UPDATE SET need = EXCLUDED.need"
                " RETURNING id, workspace_id, lane, need, resolver, output, open",
                (tenant, lane, need, resolver, output),
            ).fetchone()
            assert row is not None
            conn.execute(
                "INSERT INTO sortyard.capability_gap_item (gap_id, workspace_id, item_id)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (gap_id, item_id) DO UPDATE SET waiting = true",
                (row[0], tenant, item),
            )
            return self._gap(conn, row)

    def get(self, gap_id: str) -> GapItem:
        with self._connect() as conn:
            row = conn.execute(_GAP + " WHERE g.id = %s", (gap_id,)).fetchone()
            if row is None:
                raise KeyError(gap_id)
            return self._gap(conn, row)

    def close(self, gap_id: str) -> GapItem:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sortyard.capability_gap SET open = false, closed_at = now()"
                " WHERE id = %s AND open",
                (gap_id,),
            )
        return self.get(gap_id)

    def for_item(self, tenant: str, item: str) -> tuple[GapItem, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                _GAP + " JOIN sortyard.capability_gap_item AS l ON l.gap_id = g.id"
                " WHERE l.workspace_id = %s AND l.item_id = %s AND l.waiting ORDER BY l.position",
                (tenant, item),
            ).fetchall()
            return tuple(self._gap(conn, row) for row in rows)

    def settle(self, tenant: str, item: str, keep: Collection[str] = ()) -> None:
        mine = "workspace_id = %s AND item_id = %s AND NOT gap_id = ANY(%s)"
        still_open = "gap_id IN (SELECT id FROM sortyard.capability_gap WHERE open)"
        with self._connect() as conn:
            # An open gap item the item no longer needs loses the link; a closed one keeps it
            # as its record, and the item just stops waiting on it.
            conn.execute(
                f"DELETE FROM sortyard.capability_gap_item WHERE {mine} AND {still_open}",
                (tenant, item, list(keep)),
            )
            conn.execute(
                f"UPDATE sortyard.capability_gap_item SET waiting = false WHERE {mine}",
                (tenant, item, list(keep)),
            )

    def all(self) -> tuple[GapItem, ...]:
        """Every gap item, open and closed, in the order they were opened."""
        with self._connect() as conn:
            rows = conn.execute(_GAP + " ORDER BY g.opened_at, length(g.id), g.id").fetchall()
            return tuple(self._gap(conn, row) for row in rows)
