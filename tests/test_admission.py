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
import os
import pathlib
import shutil
import subprocess
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import psycopg
import psycopg.conninfo

from sortyard.api import handlers
from sortyard.engine import Engine, Registry, WorkflowNotFound
from sortyard.engine.blocking import BlockingEngine
from sortyard.engine.testing import local_engine
from sortyard.kernel.admission import ref_safe
from sortyard.kernel.capabilities import Lane, load
from sortyard.kernel.item import register, start_item, workflow_id
from sortyard.kernel.ledger import Ledger
from sortyard.kernel.states import shipped
from sortyard.kernel.store import Items
from sortyard.services import api as api_service
from tests.api_harness import ITEM, OTHER_WS, WS, Api, project, running_api
from tests.kernel_harness import SILENT, Owners, until
from tests.pg import requires_postgres
from tests.runtime_harness import LANE as LANE_TEXT
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
async def admitting(lanes: list[Lane] | None = None) -> AsyncIterator[tuple[Api, Engine]]:
    """The API service on a fresh database, admitting against the walwarden lane (or the lanes
    given) and starting workflows in a real engine."""
    async with local_engine() as local:
        blocking = BlockingEngine(local.target)

        def start(tenant: str, item: str, risk_tier: str) -> None:
            blocking.call(lambda e: start_item(e, item, tenant=tenant, risk_tier=risk_tier))

        apis = running_api(
            signal_item=blocking.signal,
            kernel=handlers.Kernel({lane.name: lane for lane in lanes or [LANE]}, start),
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
        ("unknown-project", {"project_id": "proj-nowhere"}),
        ("unknown-project", {"project_id": "proj-theirs"}),  # another tenant's project
        ("unknown-milestone", {"milestone_id": "ms-nowhere"}),
        # Ids the API's own pattern allows and git does not, as part of sortyard/<id>.
        ("unsafe-id", {"id": "ITEM:1"}),
        ("unsafe-id", {"id": "ITEM..1"}),
        ("unsafe-id", {"id": "ITEM-1.lock"}),
        ("unsafe-id", {"id": "ITEM-1/"}),
        ("unsafe-id", {"id": "group/.hidden"}),
    ]

    async def scenario() -> None:
        async with admitting() as (api, engine):
            Ledger(functools.partial(psycopg.connect, api.conninfo)).create_item(
                tenant=OTHER_WS, item="THEIRS", project="proj-a", title="Another tenant's"
            )
            theirs = {**project("proj-theirs"), "workspace_id": OTHER_WS}
            api.insert("project", theirs)
            before = rows(api)
            for rule, change in [*refused.items(), *more]:
                assert rules(api.ws("POST", "/items", "operator", body(**change))) == [rule], rule
            # Everything wrong at once: every reason is given, not the first.
            everything = body(
                needs=["secret:NOT_DECLARED", "service:not-declared"],
                blocked_by=["NO-SUCH-ITEM", ITEM],
                spec={"notes": "no outcome, no acceptance"},
                risk_tier="extreme",
                project_id="proj-nowhere",
                milestone_id="ms-nowhere",
                id="ITEM:1",
            )
            assert rules(api.ws("POST", "/items", "admin", everything)) == [
                "no-acceptance-test",
                "no-outcome",
                "undeclared-need",
                "undeclared-need",
                "unknown-milestone",
                "unknown-project",
                "unknown-risk-tier",
                "unresolved-link",
                "unsafe-id",
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
def test_an_item_of_a_project_the_lane_does_not_name_is_refused() -> None:
    """an item of a project the lane does not name is refused

    The walwarden lane names its project, so an item of the canary project is refused on it
    (`unknown-lane-project`) and nothing is created; a lane that names no project takes an item
    of any project of the workspace, as before (SY-DEC-011, fact 3)."""
    bound = load(LANE_TEXT.replace("slots = 2", 'slots = 2\nprojects = ["walwarden"]'))
    unbound = load(LANE_TEXT.replace('lane = "walwarden"', 'lane = "open"'))
    assert (bound.projects, unbound.projects) == (("walwarden",), ())

    async def scenario() -> None:
        async with admitting([bound, unbound]) as (api, engine):
            for pid in ("canary", "walwarden"):
                api.insert("project", project(pid))
            before = rows(api)
            canary = body("CANARY-1", project_id="canary")
            refused = api.ws("POST", "/items", "operator", canary)
            assert rules(refused) == ["unknown-lane-project"]
            assert "'walwarden'" in refused.body["reasons"][0]
            assert rows(api) == before and await unknown(engine, "CANARY-1")
            # Given with other failures, it is one reason among all of them.
            also = api.ws("POST", "/items", "operator", {**canary, "needs": ["secret:NOPE"]})
            assert rules(also) == ["undeclared-need", "unknown-lane-project"]
            # An item of the project the lane names is admitted on it.
            own = api.ws("POST", "/items", "operator", body("WAL-1", project_id="walwarden"))
            assert own.status == 201, own.body
            # A lane that names no project takes the canary item, as every lane did before.
            opened = api.ws("POST", "/items", "operator", {**canary, "lane": "open"})
            assert opened.status == 201, opened.body
            assert rows(api)["item"] == before["item"] + 2

    asyncio.run(scenario())


@requires_postgres
def test_an_admitted_item_has_its_spec_lane_and_needs_stored_and_its_workflow_started() -> None:
    """An admitted item has its spec, lane and needs stored and its workflow started."""

    async def scenario() -> None:
        async with admitting() as (api, engine):
            connect = functools.partial(psycopg.connect, api.conninfo)
            api.insert(
                "milestone",
                {"id": "ms-1", "workspace_id": WS, "project_id": "proj-a", "name": "First"},
            )
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
                # Recorded first, then the queue's owner is asked.
                await until(
                    lambda: asyncio.sleep(0, list(owners.calls)), bool, "the scheduler asked"
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
def test_get_item_returns_the_spec_lane_repository_links_and_state_of_an_item() -> None:
    """getItem returns the spec, lane, repository, links and state of an item: enough to file
    the item again under another id."""

    async def scenario() -> None:
        async with admitting() as (api, engine):
            connect = functools.partial(psycopg.connect, api.conninfo)
            api.insert(
                "milestone",
                {"id": "ms-1", "workspace_id": WS, "project_id": "proj-a", "name": "First"},
            )
            asked = body(
                needs=["secret:MODEL_API_KEY"],
                blocked_by=[ITEM],
                base="release",
                risk_tier="high",
                milestone_id="ms-1",
            )
            assert api.ws("POST", "/items", "operator", asked).status == 201
            second = api.ws("POST", "/items", "operator", body("ITEM-2", blocked_by=["ITEM-1"]))
            assert second.status == 201, second.body
            read = api.ws("GET", "/items/ITEM-1", "viewer")
            assert read.status == 200, read.body
            admitted_with = {
                **asked,
                # The repository is stored as a need too; admitting the list again is the same.
                "needs": ["repository:walwarden/app", "secret:MODEL_API_KEY"],
            }
            assert {key: read.body[key] for key in admitted_with} == admitted_with
            assert (read.body["blocked_by"], read.body["blocks"]) == ([ITEM], ["ITEM-2"])
            assert read.body["workflow_id"] == workflow_id(WS, "ITEM-1")
            # Not started yet: no state. Once its workflow records one, the read shows it,
            # from the projection.
            assert (read.body["state"], read.body["state_kind"], read.body["detail"]) == (
                None,
                None,
                {},
            )
            owners = Owners(script={"admitted": [SILENT, SILENT]})
            registry = Registry()
            by_owner = {s.owner: owners.owner for s in shipped().states.values() if s.owner}
            register(registry, owners=by_owner, decide=owners.decide, record=Ledger(connect).record)
            worker = asyncio.create_task(engine.run_worker(registry))
            try:
                await until(
                    lambda: asyncio.to_thread(Items(connect).open_stays),
                    lambda stays: {stay["item"] for stay in stays} == {"ITEM-1", "ITEM-2"},
                    "both items in the queue",
                )
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            now = api.ws("GET", "/items/ITEM-1", "conductor").body
            table = shipped().state("admitted")
            assert (now["state"], now["state_kind"], now["owner"], now["reason"]) == (
                "admitted",
                "queue",
                table.owner,
                table.reason,
            )
            assert now["limit"] == "none" and now["entered_at"]
            # What was read is what admission takes: the same item is filed under a new id
            # from the read alone, and reads back the same.
            keys = set(asked) - {"id"}
            refiled = {"id": "ITEM-1b", **{key: now[key] for key in keys}}
            assert api.ws("POST", "/items", "operator", refiled).status == 201
            again = api.ws("GET", "/items/ITEM-1b", "viewer").body
            assert {key: again[key] for key in keys} == {key: now[key] for key in keys}
            # An item this workspace does not have is not found, and a role outside the
            # operation's set reads nothing.
            assert api.ws("GET", "/items/NOPE", "viewer").status == 404
            assert api.ws("GET", "/items/ITEM-1", "sensor").status == 403
            assert api.ws("GET", "/items/ITEM-1").status == 401

    asyncio.run(scenario())


def enter(ledger: Ledger, tenant: str, item: str, sequence: int, state: str) -> None:
    """Record that `item` entered `state`, as its workflow would."""
    declared = shipped().state(state)
    ledger.record(
        {
            "item": item,
            "tenant": tenant,
            "sequence": sequence,
            "state": state,
            "state_kind": declared.kind,
            "lifecycle": declared.lifecycle,
            "owner": declared.owner,
            "limit": declared.limit.text if declared.limit else None,
            "reason": declared.reason,
            "entered_at": datetime.now(UTC).isoformat(),
            "from_state": None if sequence == 1 else "admitted",
            "from_kind": None if sequence == 1 else "queue",
            "cause": "start" if sequence == 1 else "outcome",
        }
    )


def listed(api: Api, project: str, role: str = "viewer", query: str = "") -> list[dict[str, Any]]:
    """Every item listItems returns for `project`, page after page."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        after = f"&cursor={cursor}" if cursor else ""
        reply = api.ws("GET", f"/projects/{project}/items?limit=2{query}{after}", role)
        assert reply.status == 200, reply.body
        assert len(reply.body["items"]) <= 2
        items += reply.body["items"]
        cursor = reply.body.get("next_cursor")
        if cursor is None:
            return items


@requires_postgres
def test_list_items_returns_every_item_of_the_project_with_its_state() -> None:
    """listItems returns every item of the project with its state, ended items included, and
    nothing of another project."""

    async def scenario() -> None:
        async with admitting() as (api, _engine):
            ledger = Ledger(functools.partial(psycopg.connect, api.conninfo))
            for item in ("MERGED", "WITHDRAWN", "BUILDING", "WAITING"):
                assert api.ws("POST", "/items", "operator", body(item)).status == 201
            # As their workflows would record them: one merged, one withdrawn, one at work.
            for item, last in (("MERGED", "merged"), ("WITHDRAWN", "withdrawn")):
                enter(ledger, WS, item, 1, "admitted")
                enter(ledger, WS, item, 2, last)
            enter(ledger, WS, "BUILDING", 1, "admitted")
            enter(ledger, WS, "BUILDING", 2, "building")
            # Items of another project and of another workspace, one of them ended too.
            ledger.create_item(tenant=WS, item="ELSEWHERE", project="proj-b", title="Not ours")
            enter(ledger, WS, "ELSEWHERE", 1, "admitted")
            enter(ledger, WS, "ELSEWHERE", 2, "withdrawn")
            ledger.create_item(tenant=OTHER_WS, item="THEIRS", project="proj-a", title="Theirs")
            enter(ledger, OTHER_WS, "THEIRS", 1, "admitted")
            enter(ledger, OTHER_WS, "THEIRS", 2, "merged")

            # The queue leaves the ended items out; the list keeps them.
            queue = api.ws("GET", "/projects/proj-a/queue", "viewer").body["items"]
            assert {row["id"] for row in queue} == {ITEM, "BUILDING", "WAITING"}
            items = listed(api, "proj-a")
            assert [(row["id"], row["state"], row["state_kind"], row["lane"]) for row in items] == [
                (ITEM, None, None, None),  # the harness's item, never admitted with a spec
                ("MERGED", "merged", "terminal", "walwarden"),
                ("WITHDRAWN", "withdrawn", "terminal", "walwarden"),
                ("BUILDING", "building", "work", "walwarden"),
                ("WAITING", None, None, "walwarden"),
            ]
            by_id = {row["id"]: row for row in items}
            assert by_id["WITHDRAWN"]["repository"] == "walwarden/app"
            assert by_id["WITHDRAWN"]["entered_at"] and by_id["WAITING"]["entered_at"] is None
            # Each listed item is the one getItem reads.
            got = api.ws("GET", "/items/WITHDRAWN", "viewer").body
            assert {key: got[key] for key in by_id["WITHDRAWN"]} == by_id["WITHDRAWN"]

            # Only the items that ended, and only those of one other kind.
            assert [row["id"] for row in listed(api, "proj-a", query="&state_kind=terminal")] == [
                "MERGED",
                "WITHDRAWN",
            ]
            assert [row["id"] for row in listed(api, "proj-a", query="&state_kind=work")] == [
                "BUILDING"
            ]
            # Every kind the state table has can be asked for; nothing else can.
            kinds = {state.kind for state in shipped().states.values()}
            assert kinds <= set(handlers.STATE_KINDS)
            bad = api.ws("GET", "/projects/proj-a/items?state_kind=ended", "viewer")
            assert bad.status == 400, bad.body

            # The other project lists its own item alone; the other workspace's is in neither.
            assert [row["id"] for row in listed(api, "proj-b", "admin")] == ["ELSEWHERE"]
            assert listed(api, "no-such-project") == []
            # A project-confined token lists its own project only; roles outside the set none.
            assert len(listed(api, "proj-a", "grooming-agent")) == len(items)
            assert api.ws("GET", "/projects/proj-b/items", "grooming-agent").status == 403
            assert api.ws("GET", "/projects/proj-a/items", "sensor").status == 403
            assert api.ws("GET", "/projects/proj-a/items").status == 401

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


def test_an_item_id_must_be_usable_in_a_branch_name() -> None:
    """`sortyard/<id>` must be a ref name git accepts (git-check-ref-format) and not look like
    an option: admission refuses an id that is not, before a worker finds out at push."""
    for good in ("ITEM-1", "SORTYARD-176", "a", "group/ITEM-1", "v1.2", "a.b/c_d", "x.locked"):
        assert ref_safe(good), good
    for bad in (
        "a:b", "a..b", "a~1", "a^", "a?", "a*", "a[0]", "a\\b", "a b", "a\tb", "a\x7f",
        "a.lock", "a.lock/b", "a/", "/a", "a//b", ".a", "a/.b", "a.", "-a", "a@{b", "",
    ):  # fmt: skip
        assert not ref_safe(bad), bad
    # Held to git itself for the same names, where git is there to ask.
    if shutil.which("git"):
        for name in ("ITEM-1", "group/ITEM-1", "a:b", "a..b", "a.lock", "a/", "a//b", ".a", "a."):
            asked = subprocess.run(
                ["git", "check-ref-format", f"refs/heads/sortyard/{name}"], check=False
            )
            assert (asked.returncode == 0) == ref_safe(name), name


@requires_postgres
def test_the_api_service_admits_on_its_own_configuration(tmp_path: pathlib.Path) -> None:
    """The service built from `Config` alone (an engine target and a lanes directory, as the
    chart sets them) loads the lanes, connects to the engine and admits: the wiring a
    deployment runs, with nothing handed in."""
    (tmp_path / "walwarden.toml").write_text(LANE_TEXT)

    async def scenario() -> None:
        async with local_engine() as local:
            for seeded in running_api(kernel=None):
                config = api_service.Config(
                    host="127.0.0.1",
                    port=0,
                    database_host=os.environ["PGHOST"],
                    database_port=int(os.environ.get("PGPORT", "5432")),
                    database_name=str(psycopg.conninfo.conninfo_to_dict(seeded.conninfo)["dbname"]),
                    database_user=os.environ["PGUSER"],
                    database_password=os.environ["PGPASSWORD"],
                    engine_target=local.target,
                    lanes_dir=str(tmp_path),
                )
                server = api_service.make_server(config)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    api = replace(seeded, base=f"http://127.0.0.1:{server.server_address[1]}")
                    reply = await asyncio.to_thread(api.ws, "POST", "/items", "operator", body())
                    assert reply.status == 201, reply.body
                    assert set(server.kernel.lanes) == {"walwarden"}  # type: ignore[union-attr]
                    recorded = await local.engine.recorded(workflow_id(WS, "ITEM-1"))
                    assert recorded.status == "running"
                    # The same service refuses what the lane file does not declare.
                    undeclared = body("ITEM-2", needs=["secret:NOT_DECLARED"])
                    refused = await asyncio.to_thread(
                        api.ws, "POST", "/items", "operator", undeclared
                    )
                    assert rules(refused) == ["undeclared-need"]
                finally:
                    server.shutdown()
                    server.server_close()

    asyncio.run(scenario())
