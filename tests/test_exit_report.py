"""Acceptance (SY-V3-PHASE1-EXIT): the exit report reads the ledger and counts the run.

The database is real (a fresh migrated Postgres per test), the transitions are recorded by the
kernel's own `Ledger` as the item workflow's record step writes them, operator acts go into the
audit log through the API's own `store.audit`, and the report is the shipped command.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from sortyard.api import store
from sortyard.kernel.ledger import Ledger
from sortyard.report.exit_report import main, render, report
from tests.api_harness import OTHER_WS, WS
from tests.kernel_db import PROJECTS, Connect, database, enter
from tests.pg import requires_postgres

PROJECT = PROJECTS[WS]
START = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
WINDOW = (START, START + timedelta(days=2))

# Paths through the shipped table: (state, the fields its transition carries beyond the
# default of `enter`, cause "outcome").
STRAIGHT: list[tuple[str, dict[str, Any]]] = [
    ("preflight", {}),
    ("building", {}),
    ("checking", {}),
    ("reviewing", {}),
    ("merging", {}),
    ("merged", {}),
]
# Fix rounds: red checks, a fix, review findings, another fix; a limit passed and a decision
# the table answered. No person anywhere.
FIX_ROUNDS: list[tuple[str, dict[str, Any]]] = [
    ("preflight", {}),
    ("building", {}),
    ("checking", {}),
    ("fixing", {"outcome": "red"}),
    ("checking", {"outcome": "fixed"}),
    ("decision", {"cause": "limit", "default": "retry once, then decision"}),
    ("checking", {"cause": "decision", "decision": {"answer": "retry", "source": "table"}}),
    ("reviewing", {"outcome": "green"}),
    ("fixing", {"outcome": "findings"}),
    ("checking", {"outcome": "fixed"}),
    ("reviewing", {}),
    ("merging", {}),
    ("merged", {}),
]
# A capability gap that closed without a person: preflight finds the gap, the item waits on
# the need, the need is met and work goes on.
GAP_CLOSED: list[tuple[str, dict[str, Any]]] = [
    ("preflight", {}),
    ("waiting", {"outcome": "gap", "detail": {"need": "runner-pool"}}),
    ("building", {"outcome": "met"}),
    ("checking", {}),
    ("reviewing", {}),
    ("merging", {}),
    ("merged", {}),
]
_REQUEST = {"id": "req-1", "answer": "go-on", "reason": "unstick it", "by": {"id": "op-joe"}}
# A person asked: the request goes to the decision, whose answer sends the item back.
REQUESTED: list[tuple[str, dict[str, Any]]] = [
    ("preflight", {}),
    ("building", {}),
    ("decision", {"cause": "request", "request": _REQUEST}),
    (
        "building",
        {
            "cause": "decision",
            "decision": {"question": {"cause": "request"}, "answer": "go-on", "source": "policy"},
        },
    ),
    ("checking", {}),
    ("reviewing", {}),
    ("merging", {}),
    ("merged", {}),
]
WITHDRAWN: list[tuple[str, dict[str, Any]]] = [
    ("preflight", {}),
    ("building", {}),
    ("decision", {"cause": "request", "request": {**_REQUEST, "answer": "withdraw"}}),
    ("withdrawn", {"cause": "decision", "decision": {"answer": "withdraw", "source": "policy"}}),
]


OPERATOR = {"kind": "operator", "id": "op-joe"}


@pytest.fixture
def connect() -> Iterator[Connect]:
    yield from database()


class Clock:
    """Hands out transition times a minute apart, so the items end in the order made."""

    def __init__(self, start: datetime = START) -> None:
        self.at = start

    def next(self) -> str:
        self.at += timedelta(minutes=1)
        return self.at.isoformat()


def through(
    connect: Connect,
    clock: Clock,
    item: str,
    path: list[tuple[str, dict[str, Any]]],
    *,
    tenant: str = WS,
    project: str = PROJECT,
) -> None:
    """Admit `item` and record it along `path`, as its workflow's record step would."""
    Ledger(connect).create_item(tenant=tenant, item=item, project=project, title=f"Item {item}")
    enter(connect, item, "admitted", tenant=tenant, entered_at=clock.next())
    for state, fields in path:
        enter(connect, item, state, tenant=tenant, entered_at=clock.next(), **fields)


def exit_report(connect: Connect, since: datetime = WINDOW[0]) -> dict[str, Any]:
    with connect() as conn:
        return report(conn, WS, PROJECT, since, WINDOW[1])


@requires_postgres
def test_the_report_counts_the_longest_run_of_merged_items_with_no_request_and_breaks_the_run_at_an_item_with_one(  # noqa: E501
    connect: Connect,
) -> None:
    """the report counts the longest run of merged items with no request and breaks the run at
    an item with one"""
    clock = Clock()
    # Five hands-off items, then one with a request, then ten hands-off: the run is the ten.
    # Fix rounds and a capability gap closed without a person are in the ten (must_allow).
    paths = [STRAIGHT] * 5 + [REQUESTED] + [STRAIGHT, FIX_ROUNDS, GAP_CLOSED] + [STRAIGHT] * 7
    names = [f"w-{index:02d}" for index in range(len(paths))]
    for name, path in zip(names, paths, strict=True):
        through(connect, clock, name, path)
    # Not this project, not this tenant: neither counts nor breaks anything.
    through(connect, clock, "elsewhere", REQUESTED, project="proj-b")
    through(connect, clock, "theirs", REQUESTED, tenant=OTHER_WS, project=PROJECTS[OTHER_WS])
    # Still open: listed by count only.
    through(connect, clock, "open", STRAIGHT[:3])

    with connect() as conn:
        # Admitting an item is how it starts, not a hand.
        store.audit(conn, WS, OPERATOR, "create", "item", "w-03", None, {"id": "w-03"})
        # A person's request in another tenant, naming an item id this tenant also has.
        store.audit(
            conn, OTHER_WS, OPERATOR, "create", "item_request", "req-x", None, {"item_id": "w-03"}
        )
    found = exit_report(connect)
    by_item = {entry["item"]: entry for entry in found["items"]}
    assert by_item["w-03"]["hands_off"] and not by_item["w-03"]["operator_acts"]
    assert list(by_item) == names
    assert found["still_open"] == 1
    # must_catch: an item whose timeline holds a transition caused by a request is not
    # hands-off, though it merged.
    asked = by_item["w-05"]
    assert asked["merged"] and asked["requested"] and not asked["hands_off"]
    assert [move["requested"] for move in asked["transitions"]].count(True) == 2
    # must_allow: fix rounds, a decision the table answered, a capability gap closed by itself.
    for name in ("w-07", "w-08"):
        assert by_item[name]["hands_off"], name
    # must_catch: no run counted across the item with a hand: 10, not 16.
    run = found["longest_hands_off_run"]
    assert run == {"length": 10, "items": names[6:]}

    # The ledger is append-only, so a break in the middle is made the way it happens: a hand
    # on an item. A run from w-06 to w-late is 11; an operator act on w-10 (an audit entry of
    # a request the workflow never put to a decision) breaks it into 4 and 6.
    through(connect, clock, "w-late", STRAIGHT)
    assert exit_report(connect)["longest_hands_off_run"]["length"] == 11
    with connect() as conn:
        store.audit(
            conn,
            WS,
            {"kind": "operator", "id": "op-joe"},
            "create",
            "item_request",
            "req-2",
            None,
            {"item_id": "w-10", "answer": "go-on"},
            "a request the workflow never put to a decision",
        )
    found = exit_report(connect)
    hand = next(entry for entry in found["items"] if entry["item"] == "w-10")
    assert hand["operator_action"] and not hand["requested"] and not hand["hands_off"]
    assert found["longest_hands_off_run"] == {"length": 6, "items": [*names[11:], "w-late"]}

    # Any other act of a person on the item after admitting it is a hand too.
    with connect() as conn:
        store.audit(conn, WS, OPERATOR, "update", "item", "w-13", None, {"title": "renamed"})
    found = exit_report(connect)
    acted = next(entry for entry in found["items"] if entry["item"] == "w-13")
    assert acted["operator_action"] and not acted["hands_off"]
    assert [act["action"] for act in acted["operator_acts"]] == ["update item"]
    # The ten are now 4, 2 and 3; the longest run left is the first five.
    assert found["longest_hands_off_run"] == {"length": 5, "items": names[:5]}

    # An item that ended without merging (withdrawn on a request) breaks the run too, and is
    # never counted as merged.
    through(connect, clock, "w-withdrawn", WITHDRAWN)
    for index in range(7):
        through(connect, clock, f"w-after-{index}", STRAIGHT)
    found = exit_report(connect)
    withdrawn = next(entry for entry in found["items"] if entry["item"] == "w-withdrawn")
    assert not withdrawn["merged"] and not withdrawn["hands_off"]
    assert found["longest_hands_off_run"]["length"] == 7
    assert found["longest_hands_off_run"]["items"][0] == "w-after-0"

    # The window: items that ended before it are not read.
    later = exit_report(connect, since=clock.at - timedelta(minutes=20))
    assert [entry["item"] for entry in later["items"]][-1] == "w-after-6"
    assert "w-00" not in {entry["item"] for entry in later["items"]}


@requires_postgres
def test_the_report_lists_each_item_with_its_transitions_by_owner_and_cause(
    connect: Connect,
) -> None:
    """the report lists each item with its transitions by owner and cause"""
    clock = Clock()
    through(connect, clock, "gap", GAP_CLOSED)
    through(connect, clock, "asked", REQUESTED)

    found = exit_report(connect)
    gap, asked = found["items"]
    assert gap["admitted_at"] == "2026-11-24T09:01:00.000000Z"
    assert gap["ended_at"] == "2026-11-24T09:08:00.000000Z"
    assert [(move["to"], move["owner"], move["cause"]) for move in gap["transitions"]] == [
        ("admitted", "scheduler", "start"),
        ("preflight", "capability-checker", "outcome"),
        ("waiting", "need", "outcome"),
        ("building", "executor", "outcome"),
        ("checking", "ci-adapter", "outcome"),
        ("reviewing", "reviewer", "outcome"),
        ("merging", "merge-adapter", "outcome"),
        ("merged", None, "outcome"),
    ]
    assert [move["from"] for move in gap["transitions"]][:3] == [None, "admitted", "preflight"]
    assert not any(move["requested"] for move in gap["transitions"])
    assert [
        (move["to"], move["cause"], move["requested"], move["decided_by"])
        for move in asked["transitions"][3:5]
    ] == [("decision", "request", True, None), ("building", "decision", True, "policy")]

    text = render(found)
    assert "gap: hands-off" in text
    assert "asked: needed a hand" in text
    assert "from a request: yes; operator action: no" in text
    assert "preflight -> waiting  need  outcome" in text
    assert "building -> decision  decision-service  request  [REQUEST]" in text
    assert text.rstrip().endswith(
        "longest run of merged items with no request and no operator action: 1 (gap)"
    )

    # The command prints the same, from a read-only session.
    # The command's session is read-only: a write on it is refused.
    seen: list[Any] = []

    def recording() -> Any:
        conn = connect()
        seen.append(conn)
        return conn

    printed = io.StringIO()
    with redirect_stdout(printed):
        code = main(
            ["--workspace", WS, "--project", PROJECT, "--since", WINDOW[0].isoformat()],
            connect=recording,
        )
    assert code == 0
    assert seen and seen[0].read_only
    with connect() as conn:
        conn.read_only = True
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("INSERT INTO sortyard.item_link VALUES ('ws-a', 'x', 'y')")
    assert printed.getvalue().split("\n", 1)[1] == text.split("\n", 1)[1]
