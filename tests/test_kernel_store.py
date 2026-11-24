"""Acceptance (SY-V3-LANE-RUNTIME): gap items, probe results and open stays live in Postgres.

The registry and the store are real, on a fresh Postgres. The Postgres gap registry is held to
the in-memory one (the reference `sortyard.kernel.preflight` was built and tested on): the same
calls give the same answers, and the one-open-gap-per-need rule holds in the database itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import psycopg
import pytest

from sortyard.kernel.preflight import GapItem, GapRegistry, InMemoryGapRegistry, ProbeRecord
from sortyard.kernel.store import Items, PgGapRegistry
from tests.api_harness import OTHER_WS, WS
from tests.kernel_db import Connect, admitted, database, enter
from tests.pg import requires_postgres
from tests.worker_harness import LANE

LANES = {LANE.name: LANE}


@pytest.fixture
def connect() -> Iterator[Connect]:
    yield from database()


def shape(gap: GapItem, names: dict[str, str]) -> tuple[Any, ...]:
    """A gap item with its id replaced by the order it was first seen in, so two registries
    that number their gap items differently can be compared."""
    name = names.setdefault(gap.id, f"gap#{len(names) + 1}")
    return (name, gap.tenant, gap.lane, gap.need, gap.resolver, gap.output, gap.items, gap.open)


def exercise(gaps: GapRegistry) -> list[Any]:
    """One history of calls; everything the registry answered, with ids made comparable."""
    names: dict[str, str] = {}
    seen: list[Any] = []

    def link(item: str, need: str, tenant: str = WS, lane: str = "walwarden") -> GapItem:
        gap = gaps.open_or_link(
            tenant=tenant,
            lane=lane,
            need=need,
            resolver="platform",
            output=f"{need} failed",
            item=item,
        )
        seen.append(("linked", shape(gap, names)))
        return gap

    def waits(item: str, tenant: str = WS) -> None:
        seen.append((item, [shape(gap, names) for gap in gaps.for_item(tenant, item)]))

    secret = link("A", "secret:X")
    link("B", "secret:X")  # the open gap item is found, not a second one opened
    link("A", "secret:X")  # linked twice is linked once
    service = link("A", "service:y")
    link("A", "secret:X", tenant=OTHER_WS)  # another tenant's need is another gap item
    link("C", "secret:X", lane="other")  # and so is another lane's
    waits("A")
    waits("B")
    # A's preflight ran again and found only the service still failing: it stops waiting on
    # the secret, which loses the link while it is open.
    gaps.settle(WS, "A", keep=[service.id])
    waits("A")
    seen.append(shape(gaps.get(secret.id), names))
    # Closing is recorded once, and a closed gap item keeps the items it held up.
    seen.append(shape(gaps.close(secret.id), names))
    seen.append(shape(gaps.close(secret.id), names))
    waits("B")
    # The need fails again after the gap item closed: a new one is opened.
    link("B", "secret:X")
    waits("B")
    # B passes: it waits on nothing, the closed one keeps its record, the open one lets go.
    gaps.settle(WS, "B")
    waits("B")
    seen.append(shape(gaps.get(secret.id), names))
    for unknown in ("gap-999999", "no-such-gap"):
        for call in (gaps.get, gaps.close):
            with pytest.raises(KeyError):
                call(unknown)
    return seen


@requires_postgres
def test_the_postgres_gap_registry_answers_as_the_in_memory_one_does(connect: Connect) -> None:
    """Behind the `GapRegistry` interface, the Postgres registry gives the answers the
    in-memory reference gives for the same calls."""
    for item in "ABC":
        admitted(connect, LANES, item, lane=LANE.name)
    admitted(connect, LANES, "A", lane=LANE.name, tenant=OTHER_WS)
    reference = exercise(InMemoryGapRegistry())
    assert exercise(PgGapRegistry(connect)) == reference
    assert len(reference) > 15  # the history is the one above, not an empty one


@requires_postgres
def test_a_need_has_one_open_gap_item_however_many_ask_at_once(connect: Connect) -> None:
    """The at-most-one-open-gap rule holds in the database: concurrent opens from separate
    registries make one gap item, and a second open row is refused by Postgres itself."""
    items = [f"ITEM-{number}" for number in range(12)]
    for item in items:
        admitted(connect, LANES, item, lane=LANE.name)

    def open_for(item: str) -> str:
        registry = PgGapRegistry(connect)  # as another process would
        return registry.open_or_link(
            tenant=WS,
            lane="walwarden",
            need="secret:X",
            resolver="platform",
            output="no such secret",
            item=item,
        ).id

    with ThreadPoolExecutor(12) as pool:
        ids = set(pool.map(open_for, items))
    assert len(ids) == 1
    (gap,) = PgGapRegistry(connect).all()
    assert sorted(gap.items) == sorted(items) and gap.open
    with connect() as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO sortyard.capability_gap (workspace_id, lane, need, resolver, output)"
            " VALUES (%s, 'walwarden', 'secret:X', 'platform', 'again')",
            (WS,),
        )
    # Once it is closed the need may fail again, and gets a new gap item.
    PgGapRegistry(connect).close(gap.id)
    assert open_for("ITEM-0") not in ids
    assert [each.open for each in PgGapRegistry(connect).all()] == [False, True]


@requires_postgres
def test_probe_results_are_kept_per_dispatch_and_a_repeat_replaces_its_own(
    connect: Connect,
) -> None:
    admitted(connect, LANES, "A", lane=LANE.name)
    record = ProbeRecord(WS, "A", "walwarden", 2, "secret:X", False, "no such secret")
    sink = Items(connect).record_probe
    sink(record)
    sink(replace(record, need="worker-image", passed=True, output="runs by digest"))
    # The engine retried the step: the same dispatch and need again, with what it saw now.
    sink(replace(record, output="no such secret (second look)"))
    sink(replace(record, dispatch=5, passed=True, output="read"))
    read = Items(connect).probe_results(WS, "A")  # a new object: nothing but rows
    assert [(r.dispatch, r.need, r.passed, r.output) for r in read] == [
        (2, "worker-image", True, "runs by digest"),
        (2, "secret:X", False, "no such secret (second look)"),
        (5, "secret:X", True, "read"),
    ]
    assert all(r.lane == "walwarden" and r.tenant == WS for r in read)
    assert Items(connect).probe_results(OTHER_WS, "A") == []


@requires_postgres
def test_open_stays_are_read_from_the_projection_with_what_the_owner_was_called_with(
    connect: Connect,
) -> None:
    """One query gives every open stay with its dispatch number, action, detail and deadline;
    a decision, a finished item and an item not yet started are not stays."""
    for item in ("QUEUED", "MERGING", "WAITING", "DECIDING", "DONE", "UNSTARTED"):
        admitted(connect, LANES, item, lane=LANE.name)
    admitted(connect, LANES, "THEIRS", lane=LANE.name, tenant=OTHER_WS)
    enter(connect, "QUEUED", "admitted")
    for item in ("MERGING", "WAITING", "DECIDING", "DONE"):
        enter(connect, item, "admitted")
        enter(connect, item, "preflight")
    deadline = "2026-11-23T12:30:00+00:00"
    head = {"head": "ab" * 20}
    enter(connect, "MERGING", "merging", detail=head, deadline=deadline)
    # The limit passed: the same state again, a new stay, told to update the branch.
    again = enter(
        connect, "MERGING", "merging", detail=head, action="update-branch", attempt=2, cause="limit"
    )
    enter(connect, "WAITING", "waiting", detail={"gaps": ["gap-1"], "need": "secret:X"})
    enter(connect, "DECIDING", "decision")
    enter(connect, "DONE", "merged")
    enter(connect, "THEIRS", "admitted", tenant=OTHER_WS)
    # A stay resumed after a request keeps the dispatch number it was first given.
    enter(connect, "QUEUED", "decision", cause="request")
    enter(connect, "QUEUED", "admitted", cause="decision", dispatch=1, resumed=True)

    stays = Items(connect).open_stays()
    assert [(s["tenant"], s["item"], s["state"], s["owner"]) for s in stays] == [
        (WS, "QUEUED", "admitted", "scheduler"),
        (WS, "MERGING", "merging", "merge-adapter"),
        (WS, "WAITING", "waiting", "need"),
        (OTHER_WS, "THEIRS", "admitted", "scheduler"),
    ]
    by_item = {stay["item"]: stay for stay in stays}
    merging = by_item["MERGING"]
    assert (merging["dispatch"], merging["attempt"], merging["action"]) == (
        again,
        2,
        "update-branch",
    )
    assert merging["detail"] == head and merging["deadline"] is None
    assert by_item["WAITING"]["detail"]["gaps"] == ["gap-1"]
    assert by_item["QUEUED"]["dispatch"] == 1
    assert Items(connect).spec(WS, "MERGING").repository == "walwarden/app"
    with pytest.raises(LookupError):
        Items(connect).spec(WS, "NEVER-ADMITTED")
