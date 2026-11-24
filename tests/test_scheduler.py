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
def test_a_wait_on_a_need_frees_the_slot_and_a_full_lane_dispatches_no_one(
    connect: Connect,
) -> None:
    """A slot is held from dispatch until the item is merged, except while the item waits on a
    named need; an item back from a wait counts again, and nothing is dispatched while the
    lane is at or over its count."""
    scheduler = Scheduler(connect, LANES)
    queued(connect, "A", "B", "C", "D")
    assert [ask(scheduler, item) for item in "ABC"] == [True, True, False]
    for item in "AB":
        enter(connect, item, "preflight")
    # A waits on a capability gap: its slot goes to C.
    enter(connect, "A", "waiting")
    assert [ask(scheduler, item) for item in "DC"] == [False, True]
    enter(connect, "C", "preflight")
    # A returns: three items are in work on a lane of two. No one is dispatched until two
    # of them are done.
    enter(connect, "A", "preflight")
    assert not ask(scheduler, "D")
    enter(connect, "B", "merged")
    assert not ask(scheduler, "D")
    # A decision is a pass through, not a wait: the slot stays held.
    enter(connect, "A", "decision")
    assert not ask(scheduler, "D")
    enter(connect, "C", "merged")
    assert ask(scheduler, "D")


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
    assert ask(scheduler, "Y") and not ask(scheduler, "LATER")


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
