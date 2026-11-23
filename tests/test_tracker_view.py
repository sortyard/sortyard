"""Acceptance (SY-V3-LEDGER-AND-VIEW): the tracker reads the projection, and a change goes to
the workflow as a signal.

The API service, the database, the ledger, the item workflow and the engine (its test server)
are all real. The request test sends an HTTP request to the service, which signals the real
workflow through the engine; only the owners and the decision service are fakes.
"""

from __future__ import annotations

import ast
import asyncio
import functools
import pathlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from sortyard.api import handlers, permissions
from sortyard.engine import Engine, Registry
from sortyard.engine.blocking import BlockingEngine
from sortyard.engine.testing import time_skipping_engine
from sortyard.kernel.item import register, start_item
from sortyard.kernel.ledger import Ledger
from sortyard.kernel.states import shipped
from tests.api_harness import ITEM, OTHER_WS, WS, Api, running_api
from tests.kernel_harness import DEADLINE, SILENT, Owners, until
from tests.pg import requires_postgres

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "sortyard"


@pytest.fixture
def api() -> Iterator[Api]:
    yield from running_api()


def books(api: Api) -> Ledger:
    return Ledger(functools.partial(psycopg.connect, api.conninfo))


def enter(ledger: Ledger, item: str, sequence: int, state: str, entered: datetime) -> None:
    """Record that `item` entered `state` at `entered`, as its workflow would."""
    declared = shipped().state(state)
    ledger.record(
        {
            "item": item,
            "tenant": WS,
            "sequence": sequence,
            "state": state,
            "state_kind": declared.kind,
            "owner": declared.owner,
            "limit": declared.limit.text if declared.limit else None,
            "reason": declared.reason,
            "entered_at": entered.isoformat(),
            "from_state": None if sequence == 1 else "admitted",
            "from_kind": None if sequence == 1 else "queue",
            "cause": "start" if sequence == 1 else "outcome",
        }
    )


@requires_postgres
def test_the_project_queue_lists_items_in_link_order_with_state_owner_and_age(api: Api) -> None:
    """The project queue lists items in link order with state, owner and age."""
    ledger = books(api)
    # Created in this order (after the harness's own unstarted item-1); the links say
    # otherwise: C waits on B, B waits on A. D and item-1 have no links.
    for item, milestone in (
        ("C", "ms-2"),
        ("B", "ms-1"),
        ("A", "ms-1"),
        ("D", None),
        ("DONE", None),
    ):
        ledger.create_item(
            tenant=WS, item=item, project="proj-a", title=f"Item {item}", milestone=milestone
        )
    ledger.create_item(tenant=WS, item="ELSEWHERE", project="proj-b", title="Another project")
    ledger.create_item(tenant=OTHER_WS, item="THEIRS", project="proj-a", title="Another tenant")
    ledger.link(tenant=WS, item="C", blocked_by="B")
    ledger.link(tenant=WS, item="B", blocked_by="A")
    ledger.link(tenant=WS, item="A", blocked_by="DONE")  # a blocker that is done holds nothing
    now = datetime.now(UTC)
    enter(ledger, "A", 1, "admitted", now - timedelta(hours=3))
    enter(ledger, "A", 2, "building", now - timedelta(hours=1))
    enter(ledger, "B", 1, "admitted", now - timedelta(minutes=30))
    enter(ledger, "DONE", 1, "admitted", now - timedelta(days=2))
    enter(ledger, "DONE", 2, "merged", now - timedelta(days=1))

    reply = api.ws("GET", "/projects/proj-a/queue", "viewer")
    assert reply.status == 200, reply.body
    queue = reply.body["items"]
    # Link order: A before B before C. The unlinked items keep their creation order around
    # them; the merged item, the other project's and the other tenant's are not listed.
    assert [row["id"] for row in queue] == [ITEM, "A", "D", "B", "C"]
    by_id = {row["id"]: row for row in queue}
    assert (by_id["A"]["state"], by_id["A"]["owner"], by_id["A"]["reason"]) == (
        "building",
        "executor",
        "build-in-progress",
    )
    assert by_id["A"]["limit"] == "by risk tier: low 30m, medium 1h, high 2h"
    assert (by_id["B"]["state"], by_id["B"]["owner"], by_id["B"]["limit"]) == (
        "admitted",
        "scheduler",
        "none",
    )
    assert (by_id["C"]["state"], by_id["C"]["owner"]) == (None, None)
    assert [by_id[item]["blocked_by"] for item in ("A", "B", "C", "D")] == [[], ["A"], ["B"], []]
    assert [by_id[item]["milestone_id"] for item in ("A", "B", "C", "D")] == [
        "ms-1",
        "ms-1",
        "ms-2",
        None,
    ]
    # Age: the time in the state, to the second the database read it. A is an hour into
    # building, B half an hour into the queue (its limit is none; its age is what is reported).
    assert 3600 <= by_id["A"]["age_seconds"] < 3600 + DEADLINE
    assert 1800 <= by_id["B"]["age_seconds"] < 1800 + DEADLINE
    assert 0 <= by_id["C"]["age_seconds"] < DEADLINE  # not started: since it was created

    # A project-confined agent reads its own project's queue and no other.
    assert api.ws("GET", "/projects/proj-a/queue", "grooming-agent").status == 200
    assert api.ws("GET", "/projects/proj-b/queue", "grooming-agent").status == 403
    assert [
        row["id"] for row in api.ws("GET", "/projects/proj-b/queue", "admin").body["items"]
    ] == ["ELSEWHERE"]

    # The timeline of one item: its events in ledger order.
    timeline = api.ws("GET", "/items/A/timeline", "viewer")
    assert timeline.status == 200, timeline.body
    assert [
        (e["transition"]["from"], e["transition"]["to"], e["facts"]["owner"])
        for e in timeline.body["items"]
    ] == [(None, "admitted", "scheduler"), ("admitted", "building", "executor")]
    assert api.ws("GET", "/items/THEIRS/timeline", "viewer").status == 404
    assert api.ws("GET", "/items/NO-SUCH/timeline", "viewer").status == 404


def item_state(api: Api) -> tuple[Any, ...]:
    with psycopg.connect(api.conninfo) as conn:
        row = conn.execute(
            "SELECT state, sequence FROM sortyard.item WHERE id = %s", (ITEM,)
        ).fetchone()
    assert row is not None
    return tuple(row)


async def post_request(api: Api, role: str, body: Any) -> Any:
    """POST a change request for the item, off the event loop the worker runs on."""
    return await asyncio.to_thread(api.ws, "POST", f"/items/{ITEM}/requests", role, body)


@requires_postgres
def test_a_state_change_request_reaches_the_workflow_as_a_signal_and_no_endpoint_writes_state_directly() -> (  # noqa: E501
    None
):
    """A state change request reaches the workflow as a signal and no endpoint writes state
    directly."""
    # The executor takes the build and stays silent; the decision service grants what a
    # request asks for.
    owners = Owners(script={"building": [SILENT]})

    def grant(question: Any) -> Any:
        owners.questions.append(question)
        request = question.get("request")
        if request is None:
            return None
        return {"answer": request["answer"], "reverse": "Send the opposite request."}

    async def requested(api: Api, engine: Engine) -> tuple[Any, list[dict[str, Any]], Any]:
        # Asking before the item has a workflow is refused, and writes nothing.
        early = await post_request(api, "operator", {"answer": "wait", "reason": "too early"})
        assert (early.status, early.body["reason_code"]) == (409, "no_workflow")

        identifier = await start_item(engine, ITEM, tenant=WS)
        await until(
            lambda: engine.recorded(identifier),
            lambda r: r.idle and item_state(api) == ("building", 3),
            "the item waiting in building",
        )
        asked = await post_request(
            api, "operator", {"answer": "wait", "reason": "the release is frozen"}
        )
        assert asked.status == 202, asked.body
        # The reply promises delivery, not the change: the row is the workflow's to write.
        await until(
            lambda: engine.recorded(identifier),
            lambda r: r.idle and item_state(api)[0] == "waiting",
            "the workflow acting on the request",
        )
        recorded = await engine.recorded(identifier)
        timeline = await asyncio.to_thread(api.ws, "GET", f"/items/{ITEM}/timeline", "viewer")
        for body in (
            {"answer": "", "reason": "an empty answer"},
            {"reason": "no answer"},
            {"answer": "wait", "reason": "x", "state": "merged"},
        ):
            refused = await post_request(api, "operator", body)
            assert refused.status == 422, refused.body
        viewer = await post_request(api, "viewer", {"answer": "wait", "reason": "a viewer asks"})
        assert viewer.status == 403
        return asked.body, timeline.body["items"], (recorded.signals, item_state(api))

    async def scenario() -> tuple[Any, list[dict[str, Any]], Any]:
        async with time_skipping_engine() as skipping:
            # The service reaches the engine the way it does in production: by its address.
            blocking = BlockingEngine(skipping.target)
            serving = running_api(signal_item=blocking.signal)
            api = next(serving)
            registry = Registry()
            by_owner = {s.owner: owners.owner for s in shipped().states.values() if s.owner}
            register(registry, owners=by_owner, decide=grant, record=books(api).record)
            worker = asyncio.create_task(skipping.engine.run_worker(registry))
            try:
                return await requested(api, skipping.engine)
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
                blocking.close()
                next(serving, None)  # lets the harness stop its server and drop its database

    asked, timeline, (signals, state) = asyncio.run(scenario())
    # It reached the workflow as one signal, and the workflow moved the item.
    assert signals == ("sortyard.item.input",)
    assert state == ("waiting", 5)
    moves = [
        (e["transition"]["from"], e["transition"]["to"], e["transition"]["name"]) for e in timeline
    ]
    assert moves[-2:] == [("building", "decision", "request"), ("decision", "waiting", "decision")]
    request = timeline[-2]["facts"]["request"]
    assert request["id"] == asked["id"]
    assert (request["answer"], request["reason"]) == ("wait", "the release is frozen")
    assert request["by"]["kind"] == "operator"
    decision = timeline[-1]["facts"]["decision"]
    assert (decision["answer"], decision["source"]) == ("wait", "policy")
    assert decision["question"]["request"]["id"] == asked["id"]
    assert owners.questions[-1]["cause"] == "request"


def test_no_endpoint_writes_item_state() -> None:
    """Statically: the only item operation that is not a read is the request, and no API code
    writes the item tables. (The database refuses a direct write as well:
    tests/test_ledger_projection.py.)"""
    item_ops = {
        op.operation_id: op.method
        for op in permissions.OPERATIONS.values()
        if "/items/" in op.path or op.path.endswith("/queue")
    }
    assert item_ops == {
        "getProjectQueue": "GET",
        "getItemTimeline": "GET",
        "requestItemChange": "POST",
    }
    assert set(item_ops) <= set(handlers.HANDLERS)
    writes = re.compile(
        r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+sortyard\.item\b|record_item_transition",
        re.IGNORECASE,
    )
    for path in [*sorted((SRC / "api").glob("*.py")), SRC / "services" / "api.py"]:
        tree = ast.parse(path.read_text())
        strings = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert not [text for text in strings if writes.search(text)], path.name
        # The ledger's writer is not reachable from the API: only its two reads are used.
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        used |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not used & {"Ledger", "create_item", "event_for"}, path.name
