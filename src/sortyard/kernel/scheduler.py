"""The scheduler: the owner of `admitted`, the queue (HARNESS-V3 section 3.1).

An item is dispatched when every item it is blocked by is merged and its lane has a free slot.
Among a lane's queued items whose blockers are merged, the one created first goes first; that
is link order, since an item cannot be dispatched before what it is blocked by.

A lane's slot count is `slots` in its capability file. A slot is held from the grant until the
item is merged, except while the item waits on a named need: a wait can last a day, and a lane
does not stand still behind it. So an item that returns from a wait may put the lane one over
its count until something merges; no item is *dispatched* while the lane is at or over it.

The grant is a row (`sortyard.item_slot`), written under a lock on the lane, so answers given
at the same moment by any number of workers cannot both take the last slot, and an answer
given twice is one grant. The scheduler holds nothing in memory. An item it cannot dispatch
yet gets no reply; whoever observes open stays asks again (`sortyard.kernel.observer`).
"""

from __future__ import annotations

from collections.abc import Mapping

from sortyard.kernel.capabilities import Lane
from sortyard.kernel.item import Payload
from sortyard.kernel.states import StateTable, shipped
from sortyard.kernel.store import Connect

SCHEDULER_OWNER = "scheduler"
DISPATCHED: Payload = {"outcome": "dispatched", "detail": {}}

# The lane's queued items that hold no grant and whose blockers are all merged, oldest first.
_READY = (
    "SELECT i.workspace_id, i.id FROM sortyard.item AS i JOIN sortyard.item_spec AS s"
    "   ON (s.workspace_id, s.item_id) = (i.workspace_id, i.id)"
    " WHERE s.lane = %(lane)s AND i.state_kind = 'queue'"
    "   AND NOT EXISTS (SELECT 1 FROM sortyard.item_slot AS g"
    "                   WHERE (g.workspace_id, g.item_id) = (i.workspace_id, i.id))"
    "   AND NOT EXISTS (SELECT 1 FROM sortyard.item_link AS l JOIN sortyard.item AS b"
    "                     ON (b.workspace_id, b.id) = (l.workspace_id, l.blocked_by)"
    "                   WHERE (l.workspace_id, l.item_id) = (i.workspace_id, i.id)"
    "                     AND NOT COALESCE(b.state = ANY(%(merged)s), false))"
    " ORDER BY i.position LIMIT %(free)s"
)
# Grants whose item is neither merged nor waiting on a need.
_HELD = (
    "SELECT count(*) FROM sortyard.item_slot AS g JOIN sortyard.item AS i"
    "   ON (i.workspace_id, i.id) = (g.workspace_id, g.item_id)"
    " WHERE g.lane = %(lane)s AND i.state_kind NOT IN ('terminal', 'need')"
)


class Scheduler:
    def __init__(
        self, connect: Connect, lanes: Mapping[str, Lane], table: StateTable | None = None
    ) -> None:
        self._connect, self._lanes = connect, lanes
        states = (table or shipped()).states.values()
        self._merged = [state.name for state in states if state.lifecycle == "merged"]

    def __call__(self, call: Payload) -> Payload | None:
        """`dispatched` when the item holds a slot or is given one now; else nothing."""
        tenant, item = str(call["tenant"]), str(call["item"])
        with self._connect() as conn:
            row = conn.execute(
                "SELECT lane FROM sortyard.item_spec WHERE workspace_id = %s AND item_id = %s",
                (tenant, item),
            ).fetchone()
            if row is None or row[0] not in self._lanes:
                return None  # not admitted with a spec, or on a lane this service does not run
            lane = self._lanes[row[0]]
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"lane:{lane.name}",))
            granted = conn.execute(
                "SELECT 1 FROM sortyard.item_slot WHERE workspace_id = %s AND item_id = %s",
                (tenant, item),
            ).fetchone()
            if granted is not None:
                return DISPATCHED
            values = {"lane": lane.name, "merged": self._merged}
            held = conn.execute(_HELD, values).fetchone()
            assert held is not None
            free = max(0, lane.slots - int(held[0]))
            if (tenant, item) not in conn.execute(_READY, {**values, "free": free}).fetchall():
                return None
            conn.execute(
                "INSERT INTO sortyard.item_slot (workspace_id, item_id, lane) VALUES (%s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (tenant, item, lane.name),
            )
        return DISPATCHED
