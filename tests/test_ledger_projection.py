"""Acceptance (SY-V3-LEDGER-AND-VIEW): every transition writes its item row and its event
together.

The database is real (a fresh migrated Postgres per test), the ledger is the kernel's own
`Ledger`, and the lifecycle test runs the real item workflow on the engine's test server with
the ledger as its record step. Only the owners and the decision service are fakes.
"""

from __future__ import annotations

import asyncio
import functools
import json
import pathlib
from collections.abc import Iterator
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import psycopg
import psycopg.conninfo
import pytest
from psycopg.types.json import Jsonb
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from sortyard.engine import Registry as StepRegistry
from sortyard.engine.testing import time_skipping_engine
from sortyard.kernel import ledger
from sortyard.kernel.item import register, send_outcome, start_item
from sortyard.kernel.ledger import LIFECYCLE_KINDS, Ledger, LinkRefused, event_for, lifecycle_kind
from sortyard.kernel.states import shipped
from tests.api_harness import INSTALLATION, OTHER_WS, WS
from tests.kernel_harness import DEADLINE, SILENT, Owners, until
from tests.pg import fresh_database, requires_postgres

SPEC = pathlib.Path(__file__).resolve().parent.parent / "spec"
ENTERED = "2026-11-23T10:00:00+00:00"


@pytest.fixture
def connect() -> Iterator[Any]:
    """A fresh migrated database with two tenants; yields how to connect to it."""
    for database in fresh_database():
        proc = database.migrate()
        assert proc.returncode == 0, proc.stderr
        opener = functools.partial(
            psycopg.connect, psycopg.conninfo.make_conninfo(dbname=database.name)
        )
        with opener(autocommit=True) as conn:
            conn.execute(
                "INSERT INTO sortyard.installation (doc) VALUES (%s)", [Jsonb(INSTALLATION)]
            )
            for tenant in (WS, OTHER_WS):
                doc = {"id": tenant, "installation_id": INSTALLATION["id"], "name": tenant}
                conn.execute("INSERT INTO sortyard.workspace (doc) VALUES (%s)", [Jsonb(doc)])
        yield opener


def transition(sequence: int, state: str, **fields: Any) -> dict[str, Any]:
    """A transition event as the item workflow hands it to its record step."""
    table = shipped()
    declared = table.state(state)
    return {
        "item": "ITEM-1",
        "tenant": WS,
        "sequence": sequence,
        "state": state,
        "state_kind": declared.kind,
        "owner": declared.owner,
        "limit": declared.limit.text if declared.limit else None,
        "reason": declared.reason,
        "entered_at": ENTERED,
        "from_state": None,
        "from_kind": None,
        "cause": "start",
        **fields,
    }


def item_row(connect: Any, item: str = "ITEM-1", tenant: str = WS) -> tuple[Any, ...]:
    with connect() as conn:
        row = conn.execute(
            "SELECT state, owner, limit_text, reason, sequence, xmin::text FROM sortyard.item"
            " WHERE workspace_id = %s AND id = %s",
            (tenant, item),
        ).fetchone()
    assert row is not None
    return tuple(row)


def counts(connect: Any) -> tuple[int, int]:
    """How many run rows and ledger events exist."""
    with connect() as conn:
        runs = conn.execute("SELECT count(*) FROM sortyard.item_run").fetchone()
        events = conn.execute("SELECT count(*) FROM sortyard.event").fetchone()
    assert runs is not None and events is not None
    return runs[0], events[0]


@requires_postgres
def test_a_transition_writes_the_item_row_and_its_event_in_one_transaction(connect: Any) -> None:
    """A transition writes the item row and its event in one transaction."""
    books = Ledger(connect)
    books.create_item(tenant=WS, item="ITEM-1", project="proj-a", title="First")
    assert item_row(connect)[:5] == (None, None, None, None, 0)

    books.record(transition(1, "admitted"))
    state, owner, limit, reason, sequence, item_tx = item_row(connect)
    assert (state, owner, limit, reason, sequence) == ("admitted", "scheduler", "none", "queued", 1)
    with connect() as conn:
        run = conn.execute(
            "SELECT state, cause, left_at, event_id, xmin::text FROM sortyard.item_run"
        ).fetchall()
        events = conn.execute(
            "SELECT id, workspace_id, object_kind, object_id, xmin::text FROM sortyard.event"
        ).fetchall()
    assert [row[:4] for row in run] == [("admitted", "start", None, f"item:{WS}:ITEM-1:1")]
    assert [row[:4] for row in events] == [(f"item:{WS}:ITEM-1:1", WS, "item", "ITEM-1")]
    # One transaction wrote all three rows.
    assert item_tx == run[0][4] == events[0][4]

    # The next transition closes the run it leaves and opens the one it enters.
    books.record(
        transition(
            2,
            "preflight",
            from_state="admitted",
            from_kind="queue",
            cause="outcome",
            outcome="dispatched",
            entered_at="2026-11-23T10:05:00+00:00",
        )
    )
    with connect() as conn:
        runs = conn.execute(
            "SELECT sequence, state, from_state, left_at IS NOT NULL FROM sortyard.item_run"
            " ORDER BY sequence"
        ).fetchall()
    assert runs == [(1, "admitted", None, True), (2, "preflight", "admitted", False)]
    assert item_row(connect)[:5] == (
        "preflight",
        "capability-checker",
        "5m",
        "checking-capabilities",
        2,
    )

    # The record step may be delivered twice: the second delivery writes nothing.
    books.record(transition(1, "admitted"))
    books.record(
        transition(
            2,
            "preflight",
            from_state="admitted",
            from_kind="queue",
            cause="outcome",
            outcome="dispatched",
            entered_at="2026-11-23T10:05:00+00:00",
        )
    )
    assert counts(connect) == (2, 2)
    assert item_row(connect)[4] == 2


@requires_postgres
def test_a_failed_event_write_leaves_the_item_row_unchanged(connect: Any) -> None:
    """A failed event write leaves the item row unchanged."""
    books = Ledger(connect)
    books.create_item(tenant=WS, item="ITEM-1", project="proj-a", title="First")
    books.record(transition(1, "admitted"))
    before = item_row(connect)

    # The ledger refuses the next event: its id is already taken by a different event.
    moving = transition(2, "preflight", from_state="admitted", from_kind="queue", cause="outcome")
    taken = {**event_for(moving), "facts": {"planted": True}}
    with connect() as conn:
        conn.execute("SELECT sortyard.append_event(%s)", [Jsonb(taken)])
    with pytest.raises(psycopg.errors.UniqueViolation, match="already appended with different"):
        books.record(moving)
    assert item_row(connect) == before
    assert counts(connect) == (1, 2)  # no run row for the refused transition

    # And the other way: when the item row cannot take the transition, no event is written.
    with pytest.raises(psycopg.Error, match="is at transition 1, cannot record 5"):
        books.record(transition(5, "building"))
    with pytest.raises(psycopg.Error, match="no item NO-SUCH-ITEM"):
        books.record({**transition(1, "admitted"), "item": "NO-SUCH-ITEM"})
    with pytest.raises(psycopg.Error, match="no item ITEM-1 in workspace"):
        books.record({**transition(1, "admitted"), "tenant": OTHER_WS})
    assert item_row(connect) == before
    assert counts(connect) == (1, 2)


@requires_postgres
def test_item_state_is_written_by_the_workflows_transition_and_nothing_else(connect: Any) -> None:
    books = Ledger(connect)
    books.create_item(tenant=WS, item="ITEM-1", project="proj-a", title="First")
    books.record(transition(1, "admitted"))
    before = item_row(connect)
    for statement in (
        "UPDATE sortyard.item SET state = 'merged'",
        "UPDATE sortyard.item SET owner = 'me', sequence = 9",
        "INSERT INTO sortyard.item (workspace_id, id, project_id, title, risk_tier, state)"
        f" VALUES ('{WS}', 'ITEM-2', 'proj-a', 'Forged', 'low', 'merged')",
        "DELETE FROM sortyard.item_run",
    ):
        with pytest.raises(psycopg.errors.FeatureNotSupported), connect() as conn:
            conn.execute(statement)
    assert item_row(connect) == before
    # What is not state can be edited: a title, a milestone.
    with connect() as conn:
        conn.execute("UPDATE sortyard.item SET title = 'Renamed', milestone_id = 'ms-1'")
    assert item_row(connect)[:5] == before[:5]


@requires_postgres
def test_every_row_carries_a_tenant_identifier(connect: Any) -> None:
    books = Ledger(connect)
    books.create_item(tenant=WS, item="ITEM-1", project="proj-a", title="First")
    books.create_item(tenant=WS, item="ITEM-2", project="proj-a", title="Second")
    books.record(transition(1, "admitted"))
    books.link(tenant=WS, item="ITEM-2", blocked_by="ITEM-1")
    with connect() as conn:
        for table in ("item", "item_run", "item_link"):
            missing = conn.execute(
                f"SELECT count(*) FROM sortyard.{table} WHERE workspace_id IS NULL"
            ).fetchone()
            assert missing == (0,)
            nullable = conn.execute(
                "SELECT is_nullable FROM information_schema.columns WHERE table_schema ="
                " 'sortyard' AND table_name = %s AND column_name = 'workspace_id'",
                (table,),
            ).fetchone()
            assert nullable == ("NO",), table
    for statement in (
        "INSERT INTO sortyard.item (id, project_id, title, risk_tier)"
        " VALUES ('ITEM-3', 'proj-a', 'No tenant', 'low')",
        "INSERT INTO sortyard.item (workspace_id, id, project_id, title, risk_tier)"
        " VALUES ('ws-nowhere', 'ITEM-3', 'proj-a', 'Unknown tenant', 'low')",
        "INSERT INTO sortyard.item_link (item_id, blocked_by) VALUES ('ITEM-1', 'ITEM-2')",
    ):
        with pytest.raises(psycopg.errors.IntegrityError), connect() as conn:
            conn.execute(statement)
    # The same item id in another tenant is another item.
    books.create_item(tenant=OTHER_WS, item="ITEM-1", project="proj-a", title="Theirs")
    assert item_row(connect, tenant=OTHER_WS)[:5] == (None, None, None, None, 0)
    assert item_row(connect)[0] == "admitted"

    # A link cannot make an item wait on itself, directly or round a loop.
    for blocked_by in ("ITEM-2", "ITEM-1"):
        with pytest.raises(LinkRefused):
            books.link(tenant=WS, item="ITEM-1", blocked_by=blocked_by)
    with pytest.raises(psycopg.errors.IntegrityError):
        books.link(tenant=WS, item="ITEM-1", blocked_by="NO-SUCH-ITEM")


def event_validator() -> Any:
    resources = [
        (json.loads(path.read_text())["$id"], json.loads(path.read_text()))
        for path in sorted(SPEC.glob("*.schema.json"))
    ]
    registry: Registry[Any] = Registry().with_resources(
        (uri, DRAFT202012.create_resource(doc)) for uri, doc in resources
    )
    schema = {"$ref": "https://sortyard.ai/spec/event.schema.json"}
    return jsonschema.Draft202012Validator(schema, registry=registry)


@requires_postgres
def test_each_event_maps_to_a_harness_lifecycle_v1_kind_with_owner_limit_and_reason(
    connect: Any,
) -> None:
    """Each event maps to a harness.lifecycle.v1 kind with owner, limit and reason."""
    books = Ledger(connect)
    books.create_item(tenant=WS, item="ITEM-1", project="proj-a", title="First")
    # A full life: a capability gap and a wait, a build that comes back for a decision, then
    # through to merged.
    owners = Owners(
        script={
            "preflight": [{"outcome": "gap", "detail": {"need": "secret:deploy-key"}}],
            "waiting": [SILENT],
            "building": [{"outcome": "no-change"}],
        }
    )
    table = shipped()

    async def scenario() -> Any:
        registry = StepRegistry()
        handlers = {s.owner: owners.owner for s in table.states.values() if s.owner}
        register(registry, owners=handlers, decide=owners.decide, record=books.record)
        async with time_skipping_engine() as skipping:
            engine = skipping.engine
            worker = asyncio.create_task(engine.run_worker(registry))
            try:
                identifier = await start_item(engine, "ITEM-1", tenant=WS)
                await until(
                    lambda: engine.recorded(identifier),
                    lambda r: r.idle and item_row(connect)[0] == "waiting",
                    "the wait on the need",
                )
                await send_outcome(engine, identifier, state="waiting", outcome="closed")
                return await asyncio.wait_for(engine.result(identifier), DEADLINE)
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    assert asyncio.run(scenario())["state"] == "merged"
    with connect() as conn:
        events = ledger.timeline(conn, WS, "ITEM-1")
    assert events is not None
    validator = event_validator()
    moves = []
    for event in events:
        validator.validate(event)
        facts, move = event["facts"], event["transition"]
        entered = table.state(move["to"])
        # The state left, the state entered, the owner, the limit and the typed reason.
        assert facts["owner"] == entered.owner
        assert facts["limit"] == (entered.limit.text if entered.limit else None)
        assert facts["reason"] == entered.reason and facts["reason"] in table.reasons
        assert event["workspace_id"] == WS and event["object"] == {"kind": "item", "id": "ITEM-1"}
        lifecycle = facts["lifecycle"]
        assert lifecycle["record_type"] == "harness.lifecycle.v1"
        assert lifecycle["kind"] is None or lifecycle["kind"] in LIFECYCLE_KINDS
        moves.append((move["from"], move["to"], lifecycle["kind"]))
    assert moves == [
        (None, "admitted", None),
        ("admitted", "preflight", "released"),
        ("preflight", "waiting", "readiness_hold"),
        ("waiting", "preflight", "readiness_cleared"),
        ("preflight", "building", None),
        ("building", "decision", "handback"),
        ("decision", "building", None),
        ("building", "checking", None),
        ("checking", "reviewing", None),
        ("reviewing", "merging", None),
        ("merging", "merged", "merged"),
    ]
    assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)
    assert item_row(connect)[:5] == ("merged", None, None, "done", 11)


def test_the_lifecycle_mapping_covers_every_move_of_the_shipped_table() -> None:
    """Every move the shipped table allows has a decided answer: a v1 kind, or none because
    harness.lifecycle.v1 has no kind for it."""
    table = shipped()
    seen: dict[tuple[str, str], str | None] = {}
    for state in table.states.values():
        targets = set(state.next.values()) | ({state.default.to} if state.default else set())
        for target in targets - {None, "@origin"}:
            assert target is not None
            entered = table.state(target)
            kind = lifecycle_kind({"state_kind": entered.kind, "from_kind": state.kind})
            assert kind is None or kind in LIFECYCLE_KINDS
            seen[(state.kind, entered.kind)] = kind
    assert seen == {
        ("queue", "work"): "released",
        ("work", "work"): None,
        ("work", "need"): "readiness_hold",
        ("work", "decision"): "handback",
        ("work", "terminal"): "merged",
        ("need", "work"): "readiness_cleared",
        ("need", "decision"): "handback",
        ("decision", "work"): None,
        ("decision", "need"): "readiness_hold",
    }
