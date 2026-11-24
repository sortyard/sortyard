"""Acceptance (SY-V3-LANE-RUNTIME): the scheduler dispatches in link order, within the lane's
slot count.

The scheduler, admission and the ledger are real, on a fresh Postgres; items move as their
workflow would move them (the record step's own database call). Nothing is faked: the
scheduler's only inputs are rows.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from sortyard.kernel.capabilities import CapabilityError, Lane, example_text, load
from sortyard.kernel.ledger import queue
from sortyard.kernel.scheduler import Scheduler
from tests.api_harness import OTHER_WS, WS
from tests.kernel_db import Connect, admitted, database, enter
from tests.pg import requires_postgres
from tests.worker_harness import LANE

TWO = replace(LANE, slots=2)
OTHER = replace(LANE, name="other", slots=1)
LANES = {TWO.name: TWO, OTHER.name: OTHER}


@pytest.fixture
def connect() -> Iterator[Connect]:
    yield from database()


def queued(
    connect: Connect, *items: str, lane: str = TWO.name, tenant: str = WS, **more: Any
) -> None:
    for item in items:
        admitted(connect, LANES, item, lane=lane, tenant=tenant, **more)
        enter(connect, item, "admitted", tenant=tenant)


def ask(scheduler: Scheduler, item: str, tenant: str = WS) -> bool:
    """Whether the scheduler dispatches the item when asked now."""
    reply = scheduler({"tenant": tenant, "item": item, "state": "admitted", "dispatch": 1})
    assert reply is None or reply["outcome"] == "dispatched"
    return reply is not None


def granted(connect: Connect) -> list[str]:
    with connect() as conn:
        rows = conn.execute("SELECT item_id FROM sortyard.item_slot ORDER BY item_id").fetchall()
    return [row[0] for row in rows]


@requires_postgres
def test_items_dispatch_in_link_order_within_the_lane_slot_count(connect: Connect) -> None:
    """Items dispatch in link order within the lane slot count."""
    scheduler = Scheduler(connect, LANES)
    queued(connect, "A")
    queued(connect, "B", blocked_by=("A",))
    queued(connect, "C", "D")
    queued(connect, "E", blocked_by=("B", "D"))
    # Asked last to first. Two slots: A, and C, the next one that nothing holds back. B
    # waits on A although it was created before C; D and E wait for a slot.
    assert [ask(scheduler, item) for item in "EDCBA"] == [False, False, True, False, True]
    assert granted(connect) == ["A", "C"]
    # Asked again, the answer is the same and nothing more is granted.
    assert [ask(scheduler, item) for item in "ABCDE"] == [True, False, True, False, False]
    assert granted(connect) == ["A", "C"]
    for item in "AC":
        enter(connect, item, "preflight")
    # A is in work, not merged: B stays blocked, and both slots are held.
    enter(connect, "A", "building")
    assert not any(ask(scheduler, item) for item in "BDE")
    # A merges. One slot is free, and it goes to B: created before D, and no longer blocked.
    enter(connect, "A", "merged")
    assert [ask(scheduler, item) for item in "EDB"] == [False, False, True]
    enter(connect, "B", "preflight")
    # C merges: D. E is blocked by B and D until both are merged, whatever is free.
    enter(connect, "C", "merged")
    assert [ask(scheduler, item) for item in "ED"] == [False, True]
    enter(connect, "D", "preflight")
    enter(connect, "B", "merged")
    assert not ask(scheduler, "E")
    enter(connect, "D", "merged")
    assert ask(scheduler, "E")
    assert granted(connect) == list("ABCDE")


@requires_postgres
def test_ten_items_asked_for_at_once_take_two_slots_and_no_more(connect: Connect) -> None:
    """Ten items admitted at once on a lane with two slots: however many workers ask at the
    same moment, the two created first are dispatched and no third."""
    items = [f"ITEM-{number:02d}" for number in range(1, 11)]
    queued(connect, *items)

    def asked_by_a_worker(item: str) -> bool:
        return ask(Scheduler(connect, LANES), item)  # its own scheduler: nothing is shared

    with ThreadPoolExecutor(20) as pool:
        answers = list(pool.map(asked_by_a_worker, [*reversed(items), *items]))
    assert granted(connect) == items[:2]
    assert sum(answers) >= 2  # each of the two was told at least once
    # As the lane drains, each freed slot goes to the next one created, one at a time.
    scheduler = Scheduler(connect, LANES)
    for done, following in zip(items, items[2:], strict=False):
        enter(connect, done, "preflight")
        enter(connect, done, "merged")
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(asked_by_a_worker, reversed(items)))
        assert granted(connect)[-1] == following and ask(scheduler, following)
        assert len(granted(connect)) == items.index(following) + 1


@requires_postgres
def test_more_waiters_than_slots_never_puts_more_than_the_slot_count_out_of_the_queue(
    connect: Connect,
) -> None:
    """A slot is held from dispatch until the item is merged, a wait on a need and a decision
    included: with more waiters than slots, exactly `slots` items are out of the queue, before
    the need closes and after."""
    scheduler = Scheduler(connect, LANES)
    items = [f"ITEM-{number}" for number in range(1, 9)]
    queued(connect, *items)

    def out_of_the_queue() -> list[str]:
        with connect() as conn:
            rows = conn.execute(
                "SELECT id FROM sortyard.item WHERE state_kind NOT IN ('queue', 'terminal')"
                " ORDER BY position"
            ).fetchall()
        return [row[0] for row in rows]

    def offer_everyone() -> list[str]:
        """Every queued item is asked, as a pass of the observer does; whoever is dispatched
        goes to preflight and fails the lane-wide need: it waits."""
        moved = []
        for item in reversed(items):
            if item not in out_of_the_queue() and item not in merged and ask(scheduler, item):
                enter(connect, item, "preflight")
                enter(connect, item, "waiting", detail={"need": "secret:X"})
                moved.append(item)
        return moved

    merged: list[str] = []
    # A need the whole lane fails: the first two wait on it, and however often the rest are
    # offered, they stay in the queue. Eight items do not drain into the gap.
    assert sorted(offer_everyone()) == items[:2]
    for _ in range(3):
        assert offer_everyone() == []
    assert out_of_the_queue() == items[:2] and granted(connect) == items[:2]
    # The gap closes: the two return to preflight. Still two out of the queue, never more.
    for item in items[:2]:
        enter(connect, item, "preflight")
    assert offer_everyone() == [] and out_of_the_queue() == items[:2]
    # A decision holds the slot too.
    enter(connect, items[0], "decision")
    assert offer_everyone() == [] and out_of_the_queue() == items[:2]
    # Each merge frees one slot, for the next item created, and the bound holds throughout.
    for done, following in zip(items, items[2:], strict=False):
        enter(connect, done, "merged")
        merged.append(done)
        assert offer_everyone() == [following]
        assert len(out_of_the_queue()) == 2
        assert offer_everyone() == []


@requires_postgres
def test_a_withdrawn_item_releases_its_slot_and_the_next_queued_item_is_dispatched(
    connect: Connect,
) -> None:
    """A withdrawn item releases its slot and the next queued item is dispatched. What it
    blocks stays queued, and the queue says it is blocked by a withdrawn item."""
    scheduler = Scheduler(connect, LANES)
    queued(connect, "A", "B", "C")
    queued(connect, "D", blocked_by=("A",))
    queued(connect, "E", blocked_by=("B",))
    queued(connect, "F")
    assert [ask(scheduler, item) for item in "ABCDEF"] == [True, True, False, False, False, False]
    for item in "AB":
        enter(connect, item, "preflight")
        enter(connect, item, "building")
    assert not any(ask(scheduler, item) for item in "CDEF")  # both slots are held
    # A is withdrawn mid-build (through the decision, as its workflow goes). Its slot is free
    # at once and goes to C, the next one created; then no further: one slot, one item.
    enter(connect, "A", "decision")
    assert not any(ask(scheduler, item) for item in "CDEF")  # a decision holds the slot
    enter(connect, "A", "withdrawn")
    assert [ask(scheduler, item) for item in "FEDC"] == [False, False, False, True]
    enter(connect, "C", "preflight")
    assert not any(ask(scheduler, item) for item in "DEF")
    # B merges. E, blocked by the merged B, is dispatched. D is blocked by the withdrawn A
    # and is not, although it is older than F and a slot is free: only a merge clears a link.
    enter(connect, "B", "merged")
    assert [ask(scheduler, item) for item in "DE"] == [False, True]
    enter(connect, "E", "preflight")
    enter(connect, "C", "merged")
    assert [ask(scheduler, item) for item in "DF"] == [False, True]
    enter(connect, "F", "preflight")
    enter(connect, "E", "merged")
    enter(connect, "F", "merged")
    assert not ask(scheduler, "D")  # every slot free, and D still waits
    assert granted(connect) == list("ABCEF")
    # The queue shows D, alone, still queued, and names what holds it: A, withdrawn. A itself
    # is not in the queue.
    with connect() as conn:
        (row,) = queue(conn, WS, "proj-a")
    assert (row["id"], row["state"], row["blocked_by"]) == ("D", "admitted", ["A"])
    assert row["ended_blockers"] == {"A": "withdrawn"}
    # An item withdrawn from the queue itself held no slot, takes none, and is never offered
    # one.
    queued(connect, "G", lane=OTHER.name)
    queued(connect, "H", lane=OTHER.name)
    enter(connect, "G", "decision")
    enter(connect, "G", "withdrawn")
    assert [ask(scheduler, item) for item in "GH"] == [False, True]
    assert granted(connect) == list("ABCEFH")


@requires_postgres
def test_slots_are_counted_per_lane_and_an_item_without_a_spec_is_not_dispatched(
    connect: Connect,
) -> None:
    scheduler = Scheduler(connect, LANES)
    queued(connect, "A", "B", "C")
    queued(connect, "X", "Y", lane=OTHER.name)
    queued(connect, "THEIRS", tenant=OTHER_WS)
    # The other lane has one slot of its own; another tenant's item on the same lane queues
    # behind the lane's two, since a lane's slots are its workers, whoever's items they run.
    assert [ask(scheduler, item) for item in "ABCXY"] == [True, True, False, True, False]
    assert not ask(scheduler, "THEIRS", OTHER_WS)
    # An item of a lane this service does not run, and an id that was never admitted.
    assert not ask(Scheduler(connect, {TWO.name: TWO}), "Y")
    assert not ask(scheduler, "NEVER-ADMITTED")
    # A blocker is merged only in the state the table marks merged.
    queued(connect, "LATER", lane=OTHER.name, blocked_by=("X",))
    enter(connect, "X", "preflight")
    enter(connect, "X", "waiting")
    assert not ask(scheduler, "Y") and not ask(scheduler, "LATER")
    enter(connect, "X", "merged")
    assert ask(scheduler, "Y") and not ask(scheduler, "LATER")  # one slot: Y was first


def test_a_lane_declares_its_slots_and_the_checks_of_a_repository() -> None:
    """`slots` is a whole number above zero, one when left out; `checks` is a list of names,
    and an empty list is not the same as none given."""
    text = example_text()
    example = load(text)
    assert example.slots == 2 and example.repositories["example/app"].checks == ("test",)
    assert example.repositories["example/charts"].checks is None
    assert load(text.replace("slots = 2\n", "")).slots == 1
    assert (
        load(text.replace('checks = ["test"]', "checks = []")).repositories["example/app"].checks
        == ()
    )
    for broken in ("slots = 0", "slots = -1", 'slots = "2"', "slots = 1.5", "slots = true"):
        with pytest.raises(CapabilityError) as refused:
            load(text.replace("slots = 2", broken))
        assert refused.value.rule == "malformed-file"
    for broken in ('checks = "test"', "checks = [1]", 'checks = [""]'):
        with pytest.raises(CapabilityError):
            load(text.replace('checks = ["test"]', broken))
    assert isinstance(example, Lane)
