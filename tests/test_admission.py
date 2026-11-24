"""Acceptance (SY-V3-LANE-RUNTIME): admission checks an item, creates it and starts its workflow,
or refuses it and creates nothing.

The API service, the database, the admission check and the engine (its development server) are
real: a request goes over HTTP, and an admitted item's workflow is started in the engine through
the same blocking connection the service uses in a deployment. The lane is a capability file
loaded by the real loader.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg

from sortyard.api import handlers
from sortyard.engine import Engine, Registry, WorkflowNotFound
from sortyard.engine.blocking import BlockingEngine
from sortyard.engine.testing import local_engine
from sortyard.kernel.item import register, start_item, workflow_id
from sortyard.kernel.ledger import Ledger
from sortyard.kernel.states import shipped
from sortyard.kernel.store import Items
from tests.api_harness import ITEM, OTHER_WS, WS, Api, running_api
from tests.kernel_harness import SILENT, Owners, until
from tests.pg import requires_postgres
from tests.worker_harness import LANE

SPEC = {
    "outcome": "the widget counts to ten",
    "acceptance": [{"test": "tests/test_widget.py", "name": "the widget counts to ten"}],
    "notes": "anything else in a spec is kept as written",
}


def body(item: str = "ITEM-1", **over: Any) -> dict[str, Any]:
    return {
        "id": item,
        "project_id": "proj-a",
        "title": "Count to ten",
        "lane": "walwarden",
        "repository": "walwarden/app",
        "spec": SPEC,
        **over,
    }


@asynccontextmanager
async def admitting() -> AsyncIterator[tuple[Api, Engine]]:
    """The API service on a fresh database, admitting against the walwarden lane and starting
    workflows in a real engine."""
    async with local_engine() as local:
        blocking = BlockingEngine(local.target)

        def start(tenant: str, item: str, risk_tier: str) -> None:
            blocking.call(lambda e: start_item(e, item, tenant=tenant, risk_tier=risk_tier))

        apis = running_api(
            signal_item=blocking.signal, kernel=handlers.Kernel({LANE.name: LANE}, start)
        )
        try:
            yield next(apis), local.engine
        finally:
            blocking.close()
            next(apis, None)


def rows(api: Api) -> dict[str, int]:
    """How many rows admission could have written."""
    counted = {}
    with psycopg.connect(api.conninfo) as conn:
        for table in ("item", "item_spec", "item_link", "item_slot"):
            found = conn.execute(f"SELECT count(*) FROM sortyard.{table}").fetchone()
            assert found is not None
            counted[table] = found[0]
    return counted


def rules(reply: Any) -> list[str]:
    """The rule each reason of a refusal names."""
    assert reply.status == 422 and reply.body["reason_code"] == "admission", reply.body
    return sorted(reason.split(":")[0] for reason in reply.body["reasons"])


async def unknown(engine: Engine, item: str) -> bool:
    try:
        await engine.recorded(workflow_id(WS, item))
    except WorkflowNotFound:
        return True
    return False


@requires_postgres
def test_admit_item_refuses_what_fails_the_check_and_creates_nothing() -> None:
    """admitItem refuses a spec with an undeclared need, no acceptance test or an unresolved
    link, and creates nothing."""
    refused: dict[str, dict[str, Any]] = {
        "undeclared-need": {"needs": ["secret:NOT_DECLARED"]},
        "no-acceptance-test": {"spec": {"outcome": "it works", "acceptance": []}},
        "unresolved-link": {"blocked_by": ["NO-SUCH-ITEM"]},
    }
    more: list[tuple[str, dict[str, Any]]] = [
        ("no-acceptance-test", {"spec": {"outcome": "it works"}}),
        # A test with no name is not a named acceptance test.
        ("no-acceptance-test", {"spec": {**SPEC, "acceptance": [{"test": "tests/test_x.py"}]}}),
        ("no-outcome", {"spec": {"acceptance": SPEC["acceptance"]}}),
        ("undeclared-need", {"repository": "walwarden/elsewhere"}),
        ("malformed-need", {"needs": ["a-need-of-no-kind"]}),
        ("unknown-lane", {"lane": "no-such-lane"}),
        ("unknown-risk-tier", {"risk_tier": "extreme"}),
        ("unresolved-link", {"blocked_by": ["THEIRS"]}),  # an item of another tenant
        ("unresolved-link", {"blocked_by": ["ITEM-1"]}),  # itself
    ]

    async def scenario() -> None:
        async with admitting() as (api, engine):
            Ledger(functools.partial(psycopg.connect, api.conninfo)).create_item(
                tenant=OTHER_WS, item="THEIRS", project="proj-a", title="Another tenant's"
            )
            before = rows(api)
            for rule, change in [*refused.items(), *more]:
                assert rules(api.ws("POST", "/items", "operator", body(**change))) == [rule], rule
            # Everything wrong at once: every reason is given, not the first.
            everything = body(
                needs=["secret:NOT_DECLARED", "service:not-declared"],
                blocked_by=["NO-SUCH-ITEM", ITEM],
                spec={"notes": "no outcome, no acceptance"},
                risk_tier="extreme",
            )
            assert rules(api.ws("POST", "/items", "operator", everything)) == [
                "no-acceptance-test",
                "no-outcome",
                "undeclared-need",
                "undeclared-need",
                "unknown-risk-tier",
                "unresolved-link",
            ]
            # A body that is not an admission at all is refused before the check.
            for malformed in (
                {**body(), "needs": "secret:MODEL_API_KEY"},
                {**body(), "spec": "do the thing"},
                {**body(), "surprise": 1},
                {key: value for key, value in body().items() if key != "lane"},
                body("not an id"),
            ):
                reply = api.ws("POST", "/items", "operator", malformed)
                assert reply.status == 422 and "reasons" not in reply.body, reply.body
            # Nothing was created: no row, and no workflow in the engine.
            assert rows(api) == before
            assert await unknown(engine, "ITEM-1")

    asyncio.run(scenario())


@requires_postgres
def test_an_admitted_item_has_its_spec_lane_and_needs_stored_and_its_workflow_started() -> None:
    """An admitted item has its spec, lane and needs stored and its workflow started."""

    async def scenario() -> None:
        async with admitting() as (api, engine):
            connect = functools.partial(psycopg.connect, api.conninfo)
            asked = body(
                needs=["secret:MODEL_API_KEY", "service:cluster-api"],
                blocked_by=[ITEM],
                base="release",
                risk_tier="high",
                milestone_id="ms-1",
            )
            reply = api.ws("POST", "/items", "grooming-agent", asked)
            assert reply.status == 201, reply.body
            assert reply.body["workflow_id"] == workflow_id(WS, "ITEM-1")
            stored = Items(connect).spec(WS, "ITEM-1")
            assert (stored.lane, stored.repository, stored.base) == (
                "walwarden",
                "walwarden/app",
                "release",
            )
            # The repository is a need too, so preflight exercises it; then the listed ones.
            assert stored.needs == (
                "repository:walwarden/app",
                "secret:MODEL_API_KEY",
                "service:cluster-api",
            )
            assert stored.spec == SPEC and stored.title == "Count to ten"
            queue = api.ws("GET", "/projects/proj-a/queue", "viewer").body["items"]
            row = next(each for each in queue if each["id"] == "ITEM-1")
            assert (row["blocked_by"], row["risk_tier"], row["milestone_id"], row["state"]) == (
                [ITEM],
                "high",
                "ms-1",
                None,
            )
            # The workflow is started in the engine, with no worker running yet.
            recorded = await engine.recorded(workflow_id(WS, "ITEM-1"))
            assert recorded.status == "running"
            # A worker that comes up finds it and records its first state: the queue.
            owners = Owners(script={"admitted": [SILENT]})
            registry = Registry()
            by_owner = {s.owner: owners.owner for s in shipped().states.values() if s.owner}
            register(registry, owners=by_owner, decide=owners.decide, record=Ledger(connect).record)
            worker = asyncio.create_task(engine.run_worker(registry))
            try:
                await until(
                    lambda: asyncio.to_thread(Items(connect).open_stays),
                    lambda stays: [stay["item"] for stay in stays] == ["ITEM-1"],
                    "ITEM-1 in the queue",
                )
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            (call,) = owners.calls
            assert (call["item"], call["tenant"], call["state"]) == ("ITEM-1", WS, "admitted")
            # Admission is the caller's act: it is in the audit log.
            with connect() as conn:
                audited = conn.execute(
                    "SELECT doc -> 'actor' ->> 'kind', doc -> 'after' ->> 'lane'"
                    " FROM sortyard.audit_log WHERE doc -> 'object' ->> 'kind' = 'item'"
                ).fetchall()
            assert audited == [("agent", "walwarden")]

    asyncio.run(scenario())


@requires_postgres
def test_admitting_the_same_item_again_changes_nothing_and_another_spec_is_refused() -> None:
    """Admission is idempotent on the item id: the same content again answers the item and
    writes nothing; other content under the id is refused, and what is stored stays."""

    async def scenario() -> None:
        async with admitting() as (api, engine):
            first = api.ws("POST", "/items", "operator", body(needs=["secret:MODEL_API_KEY"]))
            assert first.status == 201, first.body
            after = rows(api)
            again = api.ws("POST", "/items", "operator", body(needs=["secret:MODEL_API_KEY"]))
            assert (again.status, again.body) == (200, first.body)
            changes: list[dict[str, Any]] = [
                {"spec": {**SPEC, "outcome": "the widget counts to eleven"}},
                {"needs": []},
                {"title": "Another title"},
                {"blocked_by": [ITEM]},
            ]
            for change in changes:
                other = api.ws(
                    "POST", "/items", "operator", {**body(needs=["secret:MODEL_API_KEY"]), **change}
                )
                assert (other.status, other.body["reason_code"]) == (409, "different_item"), change
            assert rows(api) == after
            stored = Items(functools.partial(psycopg.connect, api.conninfo)).spec(WS, "ITEM-1")
            assert stored.spec == SPEC and stored.title == "Count to ten"
            assert (await engine.recorded(workflow_id(WS, "ITEM-1"))).status == "running"
            # An item that was not admitted (the harness's own, created with no spec) cannot
            # be taken over by admitting its id.
            taken = api.ws("POST", "/items", "operator", body(ITEM))
            assert taken.status == 409, taken.body

    asyncio.run(scenario())


@requires_postgres
def test_admission_is_confined_to_its_roles_and_to_a_tokens_project() -> None:
    for api in running_api():
        assert api.ws("POST", "/items", "viewer", body()).status == 403
        assert api.ws("POST", "/items", "conductor", body()).status == 403
        elsewhere = api.ws("POST", "/items", "grooming-agent", body(project_id="proj-b"))
        assert (elsewhere.status, elsewhere.body["reason_code"]) == (403, "project_scope")


@requires_postgres
def test_an_engine_that_does_not_take_the_start_leaves_no_item_behind() -> None:
    """With no engine to start the workflow in, admission answers 503 and nothing is stored;
    so does a service that runs without a kernel."""
    blocking = BlockingEngine("127.0.0.1:1", timeout_seconds=5.0)  # nothing listens there

    def start(tenant: str, item: str, risk_tier: str) -> None:
        blocking.call(lambda e: start_item(e, item, tenant=tenant, risk_tier=risk_tier))

    try:
        for api in running_api(kernel=handlers.Kernel({LANE.name: LANE}, start)):
            before = rows(api)
            reply = api.ws("POST", "/items", "operator", body())
            assert (reply.status, reply.body["reason_code"]) == (503, "engine"), reply.body
            assert rows(api) == before
    finally:
        blocking.close()
    for api in running_api(kernel=None):
        before = rows(api)
        reply = api.ws("POST", "/items", "operator", body())
        assert (reply.status, reply.body["reason_code"]) == (503, "engine"), reply.body
        assert rows(api) == before
