"""The scheduler: the owner of `admitted`, the queue (HARNESS-V3 section 3.1).

An item is dispatched when every item it is blocked by is merged and its lane has a free slot.
Among a lane's queued items whose blockers are merged, the one admitted first goes first; that
is link order, since an item cannot be dispatched before what it is blocked by.

Admission order is `position`, which admission writes with the item, not the order the items'
workflows record `admitted`: those run apart and record in any order, so an item whose record
is still to come keeps its place (for FIRST_RECORD_WINDOW), and a later one waits for it.
`position` is taken at insert, not commit: an item whose admission has not committed is not
seen, and is not admitted yet. For admissions whose transactions overlap, `position` may
differ from the order they were answered in; it is the rule, since both were asked for at the
same moment (SORTYARD-190).

A lane's slot count is `slots` in its capability file. A slot is held from the grant until the
item ends (merged or withdrawn), a wait on a need and a decision included; only a merge clears
a link, so what a withdrawn item blocks stays queued.
So a lane never has more than `slots` items out of the queue: a need that fails for the whole
lane parks at most that many and the rest stay queued, and no build starts beside them. The
cost is that an item waiting on a need of its own keeps one slot until its wait ends.

The grant is a row (`sortyard.item_slot`), written under a lock on the lane, so answers given
at the same moment by any number of workers cannot both take the last slot, and an answer
given twice is one grant. The scheduler holds nothing in memory. An item it cannot dispatch
yet gets no reply; whoever observes open stays asks again (`sortyard.kernel.observer`).
"""

from __future__ import annotations

from collections.abc import Mapping

from sortyard.kernel.capabilities import Lane
from sortyard.kernel.item import STEP_TIMEOUT, Payload
from sortyard.kernel.states import StateTable, merged_states
from sortyard.kernel.store import Connect

SCHEDULER_OWNER = "scheduler"
DISPATCHED: Payload = {"outcome": "dispatched", "detail": {}}

# How long an admitted item with no state yet keeps its place: its workflow, started in
# admission's transaction, first records `admitted`, a step bounded by STEP_TIMEOUT a try;
# two tries cover one that timed out. Past that the item is taken as stuck (no workflow, or a
# dead one), so it cannot hold its lane: it no longer counts until it records.
FIRST_RECORD_WINDOW = 2 * STEP_TIMEOUT
# The lane's queued items that hold no grant and whose blockers are all merged, oldest first;
# an admitted item that has not recorded its first state within the window counts as queued.
_READY = (
    "SELECT i.workspace_id, i.id FROM sortyard.item AS i JOIN sortyard.item_spec AS s"
    "   ON (s.workspace_id, s.item_id) = (i.workspace_id, i.id)"
    " WHERE s.lane = %(lane)s AND (i.state_kind = 'queue'"
    "        OR i.state IS NULL AND i.created_at > now() - %(window)s)"
    "   AND NOT EXISTS (SELECT 1 FROM sortyard.item_slot AS g"
    "                   WHERE (g.workspace_id, g.item_id) = (i.workspace_id, i.id))"
    "   AND NOT EXISTS (SELECT 1 FROM sortyard.item_link AS l JOIN sortyard.item AS b"
    "                     ON (b.workspace_id, b.id) = (l.workspace_id, l.blocked_by)"
    "                   WHERE (l.workspace_id, l.item_id) = (i.workspace_id, i.id)"
    "                     AND NOT COALESCE(b.state = ANY(%(merged)s), false))"
    " ORDER BY i.position LIMIT %(free)s"
)
# Grants whose item has not ended: a merged item and a withdrawn one both free their slot.
_HELD = (
    "SELECT count(*) FROM sortyard.item_slot AS g JOIN sortyard.item AS i"
    "   ON (i.workspace_id, i.id) = (g.workspace_id, g.item_id)"
    " WHERE g.lane = %(lane)s AND i.state_kind IS DISTINCT FROM 'terminal'"
)


class Scheduler:
    def __init__(
        self, connect: Connect, lanes: Mapping[str, Lane], table: StateTable | None = None
    ) -> None:
        self._connect, self._lanes, self._merged = connect, lanes, merged_states(table)

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
            values = {"lane": lane.name, "merged": self._merged, "window": FIRST_RECORD_WINDOW}
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
