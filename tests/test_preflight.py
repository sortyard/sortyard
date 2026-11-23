"""Acceptance (SY-V3-PREFLIGHT-PROBES): no build is dispatched that a failed probe rules out.

The item workflow, the shipped state table, the capability loader, the preflight owners, the
gap registry and the engine are real (the engine's test server, on its test clock). What stands
outside is faked strictly: the probes and the lookup of an item's needs answer only what a test
scripted and report any other call, and the remaining owners, the decision service and the
recorder are plain functions that keep what they were called with. No test waits a fixed time.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any, TypeVar

import pytest

from sortyard.engine import Engine, EngineUnavailable, Recorded, Registry
from sortyard.engine.testing import TestClock, time_skipping_engine
from sortyard.kernel import preflight as preflight_module
from sortyard.kernel.capabilities import KINDS, Lane, Need, load
from sortyard.kernel.item import Owner, register, send_outcome, start_item, workflow_id
from sortyard.kernel.preflight import (
    CHECKER_OWNER,
    PLATFORM_RESOLVER,
    PREFLIGHT_NEED,
    UNKNOWN_LANE,
    GapItem,
    InMemoryGapRegistry,
    ItemsNotSignalled,
    Preflight,
    ProbeRecord,
    ProbeResult,
    TaskNeeds,
    close_gap,
)
from sortyard.kernel.states import shipped

DEADLINE = 60.0
TENANT = "acme"
T = TypeVar("T")
Reply = Mapping[str, Any] | None

DIGEST = "sha256:" + "c3" * 32
LANE = load(
    f"""
version = 1
lane = "walwarden"
resolver = "platform"
gap-limit = "2h"
runner-pool = "walwarden-runners"
defaults = ["repository:walwarden/app"]

[images]
worker = "registry.test/walwarden/worker@{DIGEST}"
ci = "registry.test/walwarden/ci@{DIGEST}"

[[repositories]]
name = "walwarden/app"

[[secrets]]
name = "DEPLOY_TOKEN"

[[secrets]]
name = "REGISTRY_PASSWORD"

[[services]]
name = "cluster-api"
"""
)
DEFAULTS = ["worker-image", "runner-pool", "repository:walwarden/app"]
SECRET = "secret:DEPLOY_TOKEN"
OK = ProbeResult(True, "ok")
DENIED = ProbeResult(False, "secret store answered 403: no read on DEPLOY_TOKEN")

# What the owners this ticket does not build answer, by state.
HAPPY: dict[str, Reply] = {
    "admitted": {"outcome": "dispatched"},
    "building": {"outcome": "built"},
    "checking": {"outcome": "green"},
    "reviewing": {"outcome": "approved"},
    "fixing": {"outcome": "fixed"},
    "merging": {"outcome": "merged"},
}
TO_MERGED = ["building", "checking", "reviewing", "merging", "merged"]


@dataclass
class World:
    """The strict fakes: what each need's probe finds, and which items exist with which needs.

    A probe for a need with no scripted finding, and a lookup of an item that was not
    declared, raise and are kept in `unscripted`; `verify` fails the test for any of them
    (the checker turns a raising probe into a failed result, so raising alone would not).
    """

    findings: dict[str, ProbeResult] = field(default_factory=lambda: dict.fromkeys(DEFAULTS, OK))
    tasks: dict[str, tuple[str, ...]] = field(default_factory=dict)
    probed: list[tuple[str, str]] = field(default_factory=list)
    unscripted: list[str] = field(default_factory=list)
    sunk: list[ProbeRecord] = field(default_factory=list)
    calls: list[Mapping[str, Any]] = field(default_factory=list)
    events: list[Mapping[str, Any]] = field(default_factory=list)
    questions: list[Mapping[str, Any]] = field(default_factory=list)
    # Replies an owner gives instead of the happy one, by state, one per call.
    replies: dict[str, list[Reply]] = field(default_factory=dict)
    # How many dispatches the capability-checker takes without ever answering, before it
    # works. (The engine's test clock does not move while a step is still running, so a
    # checker that is out is one that took the dispatch and has not reported.)
    silent_checks: int = 0

    def probe(self, need: Need, lane: Lane) -> ProbeResult:
        self.probed.append((lane.name, need.text))
        if need.text not in self.findings:
            self.unscripted.append(f"probe {need.text}")
            raise AssertionError(f"no finding scripted for {need.text}")
        return self.findings[need.text]

    def lookup(self, tenant: str, item: str) -> TaskNeeds:
        if tenant != TENANT or item not in self.tasks:
            self.unscripted.append(f"lookup {tenant}/{item}")
            raise AssertionError(f"no task scripted for {tenant}/{item}")
        return TaskNeeds(LANE, self.tasks[item])

    def owner(self, call: Mapping[str, Any]) -> Reply:
        """Every owner but the two under test."""
        self.calls.append(call)
        if call["state"] not in HAPPY:
            self.unscripted.append(f"owner {call['owner']} in {call['state']}")
            raise AssertionError(f"no reply scripted for {call['state']}")
        scripted = self.replies.get(call["state"])
        return scripted.pop(0) if scripted else HAPPY[call["state"]]

    def decide(self, question: Mapping[str, Any]) -> Reply:
        self.questions.append(question)
        return None

    def record(self, event: Mapping[str, Any]) -> None:
        self.events.append(event)

    def verify(self, decisions: int = 0) -> None:
        assert self.unscripted == [], self.unscripted
        assert len(self.questions) == decisions, self.questions

    def states(self, item: str) -> list[str]:
        return [event["state"] for event in self.events if event["item"] == item]

    def builds(self, item: str) -> list[Mapping[str, Any]]:
        """Every dispatch of the executor for the item."""
        return [c for c in self.calls if c["item"] == item and c["owner"] == "executor"]

    def probes_of(self, need: str) -> int:
        return sum(1 for _, probed in self.probed if probed == need)

    def preflight(self, gaps: InMemoryGapRegistry) -> Preflight:
        return Preflight(
            lookup=self.lookup,
            probes=dict.fromkeys(KINDS, self.probe),
            gaps=gaps,
            sink=self.sunk.append,
        )


@dataclass
class Kernel:
    engine: Engine
    clock: TestClock
    world: World
    gaps: InMemoryGapRegistry

    async def start(self, item: str, *needs: str) -> str:
        self.world.tasks[item] = needs
        return await start_item(self.engine, item, tenant=TENANT)

    async def result(self, item: str) -> Any:
        return await asyncio.wait_for(self.engine.result(workflow_id(TENANT, item)), DEADLINE)

    async def idle_in(self, item: str, state: str) -> Recorded:
        """Wait until the item is waiting in `state`, and return what the engine recorded."""

        async def read() -> tuple[Recorded, list[str]]:
            recorded = await self.engine.recorded(workflow_id(TENANT, item))
            return recorded, self.world.states(item)

        recorded, _ = await until(
            read, lambda seen: seen[0].idle and seen[1][-1:] == [state], f"{item} idle in {state}"
        )
        return recorded


async def until(read: Callable[[], Awaitable[T]], accept: Callable[[T], bool], what: str) -> T:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + DEADLINE
    while True:
        value = await read()
        if accept(value):
            return value
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}; last read: {value!r}")
        await asyncio.sleep(0.02)


@asynccontextmanager
async def kernel(world: World, gaps: InMemoryGapRegistry | None = None) -> AsyncIterator[Kernel]:
    """The real workflow on the shipped table: the two preflight owners real, the rest fake."""
    gaps = gaps or InMemoryGapRegistry()
    owners: dict[str, Owner] = {
        state.owner: world.owner for state in shipped().states.values() if state.owner is not None
    }
    real = world.preflight(gaps)

    def checker(call: Mapping[str, Any]) -> Reply:
        if world.silent_checks > 0:
            world.silent_checks -= 1
            return None
        return real.check(call)

    owners.update(real.owners())
    owners[CHECKER_OWNER] = checker
    registry = Registry()
    register(registry, owners=owners, decide=world.decide, record=world.record)
    async with time_skipping_engine() as skipping:
        worker = asyncio.create_task(skipping.engine.run_worker(registry))
        try:
            yield Kernel(skipping.engine, skipping.clock, world, gaps)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


def call(item: str, **over: Any) -> dict[str, Any]:
    """An owner call as the item workflow makes it, for calling an owner directly."""
    made = {
        "item": item,
        "tenant": TENANT,
        "state": "preflight",
        "owner": "capability-checker",
        "dispatch": 2,
        "attempt": 1,
        "cause": "outcome",
        "action": None,
        "detail": {},
    }
    return {**made, **over}


def test_a_failed_probe_dispatches_no_build_and_opens_one_gap_item_with_the_need_and_the_probe_output() -> (  # noqa: E501
    None
):
    """A failed probe dispatches no build and opens one gap item with the need and the probe
    output."""
    world = World()
    world.findings[SECRET] = DENIED

    async def scenario() -> tuple[Recorded, tuple[GapItem, ...]]:
        async with kernel(world) as k:
            await k.start("ITEM-1", SECRET)
            # Idle: the engine has nothing in progress for the item, so no build is on its way.
            return await k.idle_in("ITEM-1", "waiting"), k.gaps.all()

    waiting, gaps = asyncio.run(scenario())
    world.verify()
    # No build was dispatched: the executor was never called and the item never left the wait.
    assert world.builds("ITEM-1") == []
    assert world.states("ITEM-1") == ["admitted", "preflight", "waiting"]
    assert [c["state"] for c in world.calls] == ["admitted"]
    # One gap item, for the resolver the lane declares, naming the need and the probe output.
    assert gaps == (
        GapItem(
            id=gaps[0].id,
            tenant=TENANT,
            lane="walwarden",
            need=SECRET,
            resolver="platform",
            output=DENIED.output,
            items=("ITEM-1",),
            open=True,
        ),
    )
    # One probe per need, the lane's defaults first, and each result recorded: handed to the
    # sink and written into the transition the workflow records.
    assert world.probed == [("walwarden", need) for need in [*DEFAULTS, SECRET]]
    results = [(need, True, "ok") for need in DEFAULTS] + [(SECRET, False, DENIED.output)]
    assert [(r.need, r.passed, r.output) for r in world.sunk] == results
    assert {(r.tenant, r.item, r.lane, r.dispatch) for r in world.sunk} == {
        (TENANT, "ITEM-1", "walwarden", 2)
    }
    entered = world.events[-1]
    assert (entered["state"], entered["from_state"], entered["outcome"]) == (
        "waiting",
        "preflight",
        "gap",
    )
    assert entered["detail"]["probes"] == [
        {"need": need, "passed": passed, "output": output} for need, passed, output in results
    ]
    assert entered["detail"]["need"] == SECRET and entered["detail"]["gaps"] == [gaps[0].id]
    assert entered["detail"]["resolver"] == "platform"
    # The wait is bounded by the limit the need set (the lane's gap-limit), on one timer.
    assert len(waiting.pending_timers) == 1
    limit = timedelta(hours=2)
    assert limit - timedelta(seconds=DEADLINE) < waiting.pending_timers[0] <= limit


def test_a_second_item_with_the_same_failed_need_links_to_the_open_gap_item() -> None:
    """A second item with the same failed need links to the open gap item."""
    world = World()
    world.findings[SECRET] = DENIED
    world.findings["service:cluster-api"] = ProbeResult(False, "connection refused")

    async def scenario() -> tuple[GapItem, ...]:
        async with kernel(world) as k:
            await k.start("ITEM-1", SECRET)
            await k.idle_in("ITEM-1", "waiting")
            first = k.gaps.all()
            assert len(first) == 1 and first[0].items == ("ITEM-1",)
            await k.start("ITEM-2", SECRET)
            await k.idle_in("ITEM-2", "waiting")
            # A different failed need is a different gap item.
            await k.start("ITEM-3", "service:cluster-api")
            await k.idle_in("ITEM-3", "waiting")
            return k.gaps.all()

    gaps = asyncio.run(scenario())
    world.verify()
    assert [(gap.need, gap.items, gap.open) for gap in gaps] == [
        (SECRET, ("ITEM-1", "ITEM-2"), True),
        ("service:cluster-api", ("ITEM-3",), True),
    ]
    # The gap item keeps what opened it; the second item was told which one it waits on.
    assert gaps[0].output == DENIED.output and gaps[0].resolver == "platform"
    waits = {e["item"]: e["detail"]["gaps"] for e in world.events if e["state"] == "waiting"}
    assert waits == {"ITEM-1": [gaps[0].id], "ITEM-2": [gaps[0].id], "ITEM-3": [gaps[1].id]}
    for item in ("ITEM-1", "ITEM-2", "ITEM-3"):
        assert world.builds(item) == []
        assert world.states(item) == ["admitted", "preflight", "waiting"]


def test_waiting_items_return_to_preflight_when_the_gap_item_closes() -> None:
    """Waiting items return to preflight when the gap item closes."""
    world = World()
    world.findings[SECRET] = DENIED

    async def scenario() -> tuple[list[Any], GapItem]:
        async with kernel(world) as k:
            for item in ("ITEM-1", "ITEM-2"):
                await k.start(item, SECRET)
                await k.idle_in(item, "waiting")
            (gap,) = k.gaps.all()
            assert world.probes_of(SECRET) == 2
            assert world.builds("ITEM-1") == world.builds("ITEM-2") == []
            # The resolver grants the read and closes the gap item. Nothing else is done.
            world.findings[SECRET] = OK
            closed = await close_gap(k.engine, k.gaps, gap.id)
            assert closed is not None
            return [await k.result(item) for item in ("ITEM-1", "ITEM-2")], closed

    results, closed = asyncio.run(scenario())
    world.verify()
    assert (closed.open, closed.items) == (False, ("ITEM-1", "ITEM-2"))
    assert [result["state"] for result in results] == ["merged", "merged"]
    for item in ("ITEM-1", "ITEM-2"):
        # Back to preflight from the wait, probed again, and only then built: once.
        assert world.states(item) == ["admitted", "preflight", "waiting", "preflight", *TO_MERGED]
        back = [e for e in world.events if e["item"] == item and e["state"] == "preflight"][1]
        assert (back["from_state"], back["cause"], back["outcome"]) == (
            "waiting",
            "outcome",
            "closed",
        )
        assert back["detail"] == {"closed_gaps": [closed.id]}
        (build,) = world.builds(item)
        assert build["cause"] == "outcome" and build["detail"]["lane"] == "walwarden"
        assert {"need": SECRET, "passed": True, "output": "ok"} in build["detail"]["probes"]
    # Each item's need was exercised twice: the failure, and again after the gap closed.
    assert world.probes_of(SECRET) == 4
    assert sorted((r.item, r.passed) for r in world.sunk if r.need == SECRET) == [
        ("ITEM-1", False),
        ("ITEM-1", True),
        ("ITEM-2", False),
        ("ITEM-2", True),
    ]


def test_a_task_with_no_needs_beyond_the_lane_defaults_passes_preflight() -> None:
    world = World()

    async def scenario() -> tuple[Any, tuple[GapItem, ...]]:
        async with kernel(world) as k:
            await k.start("ITEM-1")
            return await k.result("ITEM-1"), k.gaps.all()

    result, gaps = asyncio.run(scenario())
    world.verify()
    assert result["state"] == "merged" and gaps == ()
    assert world.states("ITEM-1") == ["admitted", "preflight", *TO_MERGED]
    # Only the lane's defaults were exercised, each once, and the build got the results.
    assert world.probed == [("walwarden", need) for need in DEFAULTS]
    (build,) = world.builds("ITEM-1")
    assert build["detail"]["probes"] == [
        {"need": need, "passed": True, "output": "ok"} for need in DEFAULTS
    ]


def test_a_need_that_still_fails_after_its_gap_closed_opens_a_new_gap_and_no_build() -> None:
    world = World()
    world.findings[SECRET] = DENIED

    async def scenario() -> tuple[GapItem, ...]:
        async with kernel(world) as k:
            await k.start("ITEM-1", SECRET)
            await k.idle_in("ITEM-1", "waiting")
            # Closed without the need being met: the item is probed again and waits again.
            await close_gap(k.engine, k.gaps, k.gaps.all()[0].id)
            await until(
                lambda: asyncio.sleep(0, world.states("ITEM-1")),
                lambda states: states.count("waiting") == 2,
                "the second wait",
            )
            await k.idle_in("ITEM-1", "waiting")
            return k.gaps.all()

    gaps = asyncio.run(scenario())
    world.verify()
    assert [(gap.need, gap.open, gap.items) for gap in gaps] == [
        (SECRET, False, ("ITEM-1",)),
        (SECRET, True, ("ITEM-1",)),
    ]
    assert world.builds("ITEM-1") == [] and world.probes_of(SECRET) == 2
    assert world.states("ITEM-1") == ["admitted", "preflight", "waiting", "preflight", "waiting"]


class ClosesAtOnce(InMemoryGapRegistry):
    """A registry whose first gap item is closed the moment the item is linked to it: the
    resolver was faster than the item's move into the wait, so no `closed` can reach it."""

    def __init__(self, world: World) -> None:
        super().__init__()
        self._world = world
        self.closed_early: list[str] = []

    def open_or_link(
        self, *, tenant: str, lane: str, need: str, resolver: str, output: str, item: str
    ) -> GapItem:
        gap = super().open_or_link(
            tenant=tenant, lane=lane, need=need, resolver=resolver, output=output, item=item
        )
        if not self.closed_early:
            self.closed_early.append(gap.id)
            self._world.findings[need] = OK
            self.close(gap.id)
        return gap


def test_a_gap_that_closes_before_the_item_reaches_the_wait_does_not_strand_it() -> None:
    world = World()
    world.findings[SECRET] = DENIED
    gaps = ClosesAtOnce(world)

    async def scenario() -> Any:
        async with kernel(world, gaps) as k:
            await k.start("ITEM-1", SECRET)
            result = await k.result("ITEM-1")
            # Closing again, with the item's workflow ended, is passed over, not an error.
            again = await close_gap(k.engine, k.gaps, gaps.closed_early[0])
            assert again is not None and not again.open
            return result

    assert asyncio.run(scenario())["state"] == "merged"
    world.verify()
    assert world.states("ITEM-1") == ["admitted", "preflight", "waiting", "preflight", *TO_MERGED]
    assert len(gaps.all()) == 1 and len(world.builds("ITEM-1")) == 1


def test_items_that_fail_the_same_need_at_the_same_time_share_one_gap_item() -> None:
    world = World()
    world.findings[SECRET] = DENIED
    items = [f"ITEM-{n}" for n in range(1, 9)]

    async def scenario() -> tuple[GapItem, ...]:
        async with kernel(world) as k:
            await asyncio.gather(*(k.start(item, SECRET) for item in items))
            for item in items:
                await k.idle_in(item, "waiting")
            return k.gaps.all()

    (gap,) = asyncio.run(scenario())
    world.verify()
    assert sorted(gap.items) == sorted(items) and gap.open
    assert all(world.builds(item) == [] for item in items)


def test_concurrent_opens_for_one_need_make_one_gap_item() -> None:
    gaps = InMemoryGapRegistry()
    threads_per_need, needs = 16, [SECRET, "service:cluster-api", "runner-pool"]
    barrier = threading.Barrier(threads_per_need * len(needs))
    returned: list[GapItem] = []
    errors: list[BaseException] = []

    def link(need: str, item: str) -> None:
        try:
            barrier.wait(timeout=DEADLINE)
            returned.append(
                gaps.open_or_link(
                    tenant=TENANT,
                    lane="walwarden",
                    need=need,
                    resolver="platform",
                    output=f"failed for {item}",
                    item=item,
                )
            )
        except BaseException as error:
            errors.append(error)

    threads = [
        threading.Thread(target=link, args=(need, f"ITEM-{n}"))
        for need in needs
        for n in range(threads_per_need)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=DEADLINE)
    assert errors == [] and len(returned) == len(threads)
    made = gaps.all()
    assert sorted(gap.need for gap in made) == sorted(needs)
    assert len({gap.id for gap in made}) == len(needs)
    for gap in made:
        assert sorted(gap.items) == sorted(f"ITEM-{n}" for n in range(threads_per_need))
        assert {r.id for r in returned if r.need == gap.need} == {gap.id}
    # The same need in another lane or tenant is another gap item; linking twice links once.
    kwargs = {"need": SECRET, "resolver": "platform", "output": "x", "item": "ITEM-0"}
    other_lane = gaps.open_or_link(tenant=TENANT, lane="rove", **kwargs)
    other_tenant = gaps.open_or_link(tenant="other", lane="walwarden", **kwargs)
    same = gaps.open_or_link(tenant=TENANT, lane="walwarden", **kwargs)
    assert len({other_lane.id, other_tenant.id, same.id}) == 3
    assert same.items.count("ITEM-0") == 1 and len(gaps.all()) == len(needs) + 2
    # Closing is idempotent, and a need whose gap item closed gets a new one when it fails again.
    assert gaps.close(same.id) == gaps.close(same.id) == gaps.get(same.id)
    reopened = gaps.open_or_link(tenant=TENANT, lane="walwarden", **kwargs)
    assert reopened.id != same.id and reopened.items == ("ITEM-0",)
    with pytest.raises(KeyError):
        gaps.get("gap-unknown")


def test_what_cannot_be_exercised_fails_and_names_why() -> None:
    world = World()
    world.tasks["ITEM-1"] = ("secret:NOT_DECLARED", "nonsense", SECRET, "service:cluster-api")

    def raising(need: Need, lane: Lane) -> ProbeResult:
        raise ConnectionError("secret store unreachable")

    def wordless(need: Need, lane: Lane) -> ProbeResult:
        return "fine"  # type: ignore[return-value]

    gaps = InMemoryGapRegistry()
    probes = {**dict.fromkeys(KINDS, world.probe), "secret": raising, "service": wordless}
    reply = Preflight(lookup=world.lookup, probes=probes, gaps=gaps).check(call("ITEM-1"))
    world.verify()
    assert reply["outcome"] == "gap"
    failed = {p["need"]: p["output"] for p in reply["detail"]["probes"] if not p["passed"]}
    assert list(failed) == ["secret:NOT_DECLARED", "nonsense", SECRET, "service:cluster-api"]
    assert failed["secret:NOT_DECLARED"].startswith("undeclared-need: lane 'walwarden'")
    assert failed["nonsense"].startswith("malformed-need:")
    assert failed[SECRET] == "the probe raised ConnectionError: secret store unreachable"
    assert failed["service:cluster-api"] == "the probe returned no result: 'fine'"
    # One gap item per failed need, each with its output; the undeclared ones were not probed.
    assert [(gap.need, gap.output) for gap in gaps.all()] == list(failed.items())
    assert reply["detail"]["gaps"] == [gap.id for gap in gaps.all()]
    assert reply["detail"]["needs"] == list(failed) and reply["detail"]["limit"] == "2h"
    assert [need for _, need in world.probed] == DEFAULTS


def test_a_checker_without_a_probe_for_every_kind_of_need_is_refused() -> None:
    world = World()
    probes = dict.fromkeys(KINDS, world.probe)
    del probes["secret"], probes["runner-pool"]
    with pytest.raises(ValueError, match=r"no probe for \['runner-pool', 'secret'\]"):
        Preflight(lookup=world.lookup, probes=probes, gaps=InMemoryGapRegistry())


def test_the_need_owner_takes_the_wait_and_answers_only_for_a_gap_already_closed() -> None:
    world = World()
    world.tasks["ITEM-1"] = ()
    gaps = InMemoryGapRegistry()
    preflight = world.preflight(gaps)
    gap = gaps.open_or_link(
        tenant=TENANT, lane="walwarden", need=SECRET, resolver="platform", output="x", item="ITEM-1"
    )
    waiting = {"state": "waiting", "owner": "need", "dispatch": 3}
    on_gap = call("ITEM-1", **waiting, detail={"gaps": [gap.id]})
    assert preflight.wait(on_gap) is None
    # So is a wait that names no gap item while the item is linked to an open one.
    assert preflight.wait(call("ITEM-1", **waiting, detail={"need": "a-different-answer"})) is None
    gaps.close(gap.id)
    closed = {"outcome": "closed", "detail": {"closed_gaps": [gap.id]}}
    assert preflight.wait(on_gap) == closed
    # The registry's link answers even when the detail no longer names the gap item.
    assert (
        preflight.wait(call("ITEM-1", **waiting, detail={"need": "a-different-answer"})) == closed
    )
    assert len(gaps.all()) == 1
    # Preflight ran out of its limit: the table hands the need's owner the action, and the
    # gap item names the preflight itself for the lane's resolver.
    late = call("ITEM-1", **waiting, cause="limit", action="open-capability-gap")
    assert preflight.wait(late) is None
    opened = gaps.all()[-1]
    assert (opened.need, opened.lane, opened.resolver, opened.items, opened.open) == (
        PREFLIGHT_NEED,
        "walwarden",
        "platform",
        ("ITEM-1",),
        True,
    )
    assert "limit" in opened.output
    # The item now waits on an open gap item: the wait is taken, whatever closed before it.
    assert preflight.wait(on_gap) is None
    assert [g.id for g in gaps.for_item(TENANT, "ITEM-1")] == [gap.id, opened.id]
    world.verify()


def test_a_gap_item_the_registry_does_not_know_holds_no_item() -> None:
    # What a worker restart does to the in-memory registry: the gap item is gone.
    world = World()
    waiting = {"state": "waiting", "owner": "need", "dispatch": 3}
    lost = call("ITEM-1", **waiting, detail={"gaps": ["gap-7"]})
    restarted = world.preflight(InMemoryGapRegistry())
    assert restarted.wait(lost) == {"outcome": "closed", "detail": {"closed_gaps": ["gap-7"]}}
    # One known and still open among those named keeps the wait.
    gaps = InMemoryGapRegistry()
    gap = gaps.open_or_link(
        tenant=TENANT, lane="walwarden", need=SECRET, resolver="platform", output="x", item="ITEM-1"
    )
    both = call("ITEM-1", **waiting, detail={"gaps": ["gap-7", gap.id]})
    assert world.preflight(gaps).wait(both) is None

    async def scenario() -> None:
        async with kernel(world) as k:
            # Closing a gap item nobody knows tells nobody and is not an error.
            assert await close_gap(k.engine, k.gaps, "gap-7") is None

    asyncio.run(scenario())
    world.verify()


def test_an_item_waiting_on_something_that_is_not_a_capability_gap_keeps_waiting() -> None:
    # The build ends without a change, twice: the decision repeats and the kernel has the item
    # wait on "a different answer". The item had a gap item earlier, closed since. The need's
    # owner must leave that wait alone, or the item goes round again with no timer.
    world = World()
    world.findings[SECRET] = DENIED
    world.replies["building"] = [{"outcome": "no-change"}, {"outcome": "no-change"}]

    async def scenario() -> Recorded:
        async with kernel(world) as k:
            await k.start("ITEM-1", SECRET)
            await k.idle_in("ITEM-1", "waiting")
            world.findings[SECRET] = OK
            await close_gap(k.engine, k.gaps, k.gaps.all()[0].id)
            await until(
                lambda: asyncio.sleep(0, world.states("ITEM-1")),
                lambda states: states.count("waiting") == 2,
                "the wait on a different answer",
            )
            waiting = await k.idle_in("ITEM-1", "waiting")
            assert k.gaps.for_item(TENANT, "ITEM-1") == ()
            return waiting

    waiting = asyncio.run(scenario())
    world.verify(decisions=2)
    assert world.states("ITEM-1") == [
        "admitted",
        "preflight",
        "waiting",
        "preflight",
        "building",
        "decision",
        "building",
        "decision",
        "waiting",
    ]
    assert world.events[-1]["detail"]["need"] == "a-different-answer"
    assert len(world.builds("ITEM-1")) == 2
    # It waits on the table's own limit for a wait, on one timer.
    assert len(waiting.pending_timers) == 1
    assert timedelta(hours=23) < waiting.pending_timers[0] <= timedelta(hours=24)
    # Called directly: no gap item named, none linked, so no answer.
    owner = world.preflight(InMemoryGapRegistry())
    waits = {"state": "waiting", "owner": "need", "detail": {"need": "a-different-answer"}}
    assert owner.wait(call("ITEM-1", **waits)) is None
    assert owner.wait(call("ITEM-1", state="waiting", owner="need", cause="decision")) is None


def test_the_checker_called_twice_for_one_dispatch_links_the_item_once() -> None:
    world = World()
    world.findings[SECRET] = DENIED
    world.findings["service:cluster-api"] = ProbeResult(False, "connection refused")
    world.tasks["ITEM-1"] = (SECRET, "service:cluster-api")
    gaps = InMemoryGapRegistry()
    preflight = world.preflight(gaps)
    first = preflight.check(call("ITEM-1"))
    assert preflight.check(call("ITEM-1")) == first and first["outcome"] == "gap"
    assert [(gap.need, gap.items) for gap in gaps.all()] == [
        (SECRET, ("ITEM-1",)),
        ("service:cluster-api", ("ITEM-1",)),
    ]
    assert [gap.id for gap in gaps.for_item(TENANT, "ITEM-1")] == first["detail"]["gaps"]
    # A later attempt that finds one need met leaves the item waiting on the other alone, and
    # one that finds every need met leaves it waiting on none: no stale link to an open gap.
    world.findings[SECRET] = OK
    second = preflight.check(call("ITEM-1"))
    assert second["detail"]["gaps"] == [gaps.all()[1].id]
    assert [(gap.need, gap.items, gap.open) for gap in gaps.all()] == [
        (SECRET, (), True),
        ("service:cluster-api", ("ITEM-1",), True),
    ]
    world.findings["service:cluster-api"] = OK
    assert preflight.check(call("ITEM-1"))["outcome"] == "ready"
    assert gaps.for_item(TENANT, "ITEM-1") == ()
    assert [gap.items for gap in gaps.all()] == [(), ()]
    world.verify()


def test_a_lookup_that_raises_ends_in_a_gap_item_naming_the_preflight() -> None:
    world = World()

    def lookup(tenant: str, item: str) -> TaskNeeds:
        raise TimeoutError("task store did not answer")

    gaps = InMemoryGapRegistry()
    preflight = Preflight(
        lookup=lookup, probes=dict.fromkeys(KINDS, world.probe), gaps=gaps, sink=world.sunk.append
    )
    reply = preflight.check(call("ITEM-1"))
    output = "the lookup of the item's needs raised TimeoutError: task store did not answer"
    (gap,) = gaps.all()
    assert gap == GapItem(
        gap.id, TENANT, UNKNOWN_LANE, PREFLIGHT_NEED, PLATFORM_RESOLVER, output, ("ITEM-1",)
    )
    assert reply == {
        "outcome": "gap",
        "detail": {
            "lane": UNKNOWN_LANE,
            "probes": [{"need": PREFLIGHT_NEED, "passed": False, "output": output}],
            "need": PREFLIGHT_NEED,
            "needs": [PREFLIGHT_NEED],
            "gaps": [gap.id],
            "resolver": PLATFORM_RESOLVER,
        },
    }
    assert [(r.need, r.passed, r.output) for r in world.sunk] == [(PREFLIGHT_NEED, False, output)]
    # The limit path does not depend on the lookup either: a second item joins the gap item.
    waiting = {"state": "waiting", "owner": "need", "cause": "limit"}
    assert preflight.wait(call("ITEM-2", **waiting, action="open-capability-gap")) is None
    assert gaps.all() == (replace(gap, items=("ITEM-1", "ITEM-2")),)
    # A lookup that answers with something else is no better.
    wordless = Preflight(
        lookup=lambda tenant, item: None,  # type: ignore[arg-type,return-value]
        probes=dict.fromkeys(KINDS, world.probe),
        gaps=InMemoryGapRegistry(),
    )
    assert wordless.check(call("ITEM-1"))["detail"]["need"] == PREFLIGHT_NEED
    assert world.probed == []
    world.verify()


def test_close_gap_that_fails_part_way_still_resumes_the_other_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    world.findings[SECRET] = DENIED
    items = ["ITEM-1", "ITEM-2", "ITEM-3"]
    refused: list[str] = []

    async def flaky(engine: Engine, identifier: str, **outcome: Any) -> None:
        # The engine refuses the first signal for ITEM-1, the first item linked.
        if identifier == workflow_id(TENANT, "ITEM-1") and not refused:
            refused.append(identifier)
            raise EngineUnavailable("UNAVAILABLE: engine restarting")
        await send_outcome(engine, identifier, **outcome)

    monkeypatch.setattr(preflight_module, "send_outcome", flaky)

    async def scenario() -> list[Any]:
        async with kernel(world) as k:
            for item in items:
                await k.start(item, SECRET)
                await k.idle_in(item, "waiting")
            (gap,) = k.gaps.all()
            world.findings[SECRET] = OK
            with pytest.raises(ItemsNotSignalled) as caught:
                await close_gap(k.engine, k.gaps, gap.id)
            assert caught.value.items == ("ITEM-1",) and not caught.value.gap.open
            assert "ITEM-1" in str(caught.value) and "engine restarting" in str(caught.value)
            # The items after the failure were told all the same, and build.
            done = [await k.result(item) for item in items[1:]]
            assert world.states("ITEM-1")[-1] == "waiting" and world.builds("ITEM-1") == []
            # The repeat call tells the one that was missed.
            again = await close_gap(k.engine, k.gaps, gap.id)
            assert again is not None and not again.open
            return [await k.result("ITEM-1"), *done]

    results = asyncio.run(scenario())
    world.verify()
    assert [result["state"] for result in results] == ["merged"] * 3
    assert len(refused) == 1 and all(len(world.builds(item)) == 1 for item in items)


def test_an_item_never_told_its_gap_closed_returns_to_preflight_at_its_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    world.findings[SECRET] = DENIED

    async def lost(engine: Engine, identifier: str, **outcome: Any) -> None:
        raise EngineUnavailable("UNAVAILABLE: engine restarting")

    monkeypatch.setattr(preflight_module, "send_outcome", lost)

    async def scenario() -> Any:
        async with kernel(world) as k:
            await k.start("ITEM-1", SECRET)
            await k.idle_in("ITEM-1", "waiting")
            world.findings[SECRET] = OK
            with pytest.raises(ItemsNotSignalled):
                await close_gap(k.engine, k.gaps, k.gaps.all()[0].id)
            # The wait's limit (the lane's gap-limit) passes: the decision resumes the wait,
            # and the need's owner finds the gap item closed.
            await k.clock.advance(timedelta(hours=2))
            return await k.result("ITEM-1")

    assert asyncio.run(scenario())["state"] == "merged"
    world.verify(decisions=1)
    assert world.states("ITEM-1") == [
        "admitted",
        "preflight",
        "waiting",
        "decision",
        "waiting",
        "preflight",
        *TO_MERGED,
    ]


def test_an_item_on_two_gap_items_waits_again_on_the_one_still_open() -> None:
    world = World()
    service = "service:cluster-api"
    world.findings[SECRET] = DENIED
    world.findings[service] = ProbeResult(False, "connection refused")

    async def scenario() -> tuple[tuple[GapItem, ...], Any]:
        async with kernel(world) as k:
            await k.start("ITEM-1", SECRET, service)
            await k.idle_in("ITEM-1", "waiting")
            secret_gap, service_gap = k.gaps.all()
            assert (secret_gap.need, service_gap.need) == (SECRET, service)
            assert world.events[-1]["detail"]["gaps"] == [secret_gap.id, service_gap.id]
            # One of the two is resolved and closed.
            world.findings[SECRET] = OK
            await close_gap(k.engine, k.gaps, secret_gap.id)
            await until(
                lambda: asyncio.sleep(0, world.states("ITEM-1")),
                lambda states: states.count("waiting") == 2,
                "the second wait",
            )
            await k.idle_in("ITEM-1", "waiting")
            after_one = k.gaps.all()
            assert world.events[-1]["detail"]["gaps"] == [service_gap.id]
            assert world.events[-1]["detail"]["needs"] == [service]
            assert world.builds("ITEM-1") == []
            world.findings[service] = OK
            await close_gap(k.engine, k.gaps, service_gap.id)
            return after_one, await k.result("ITEM-1")

    after_one, result = asyncio.run(scenario())
    world.verify()
    # Still two gap items: the closed one, and the open one the item is still linked to.
    assert [(gap.need, gap.open, gap.items) for gap in after_one] == [
        (SECRET, False, ("ITEM-1",)),
        (service, True, ("ITEM-1",)),
    ]
    assert result["state"] == "merged" and len(world.builds("ITEM-1")) == 1
    assert world.states("ITEM-1") == [
        "admitted",
        "preflight",
        "waiting",
        "preflight",
        "waiting",
        "preflight",
        *TO_MERGED,
    ]
    assert (world.probes_of(SECRET), world.probes_of(service)) == (3, 3)


def test_a_checker_that_does_not_answer_within_its_limit_ends_in_a_preflight_gap_item() -> None:
    world = World(silent_checks=1)

    async def scenario() -> tuple[GapItem, Recorded, Any]:
        async with kernel(world) as k:
            await k.start("ITEM-1")
            preflight = await k.idle_in("ITEM-1", "preflight")
            assert preflight.pending_timers and world.probed == []
            # The preflight limit of the shipped table passes with the checker still out.
            await k.clock.advance(timedelta(minutes=5))
            waiting = await k.idle_in("ITEM-1", "waiting")
            (gap,) = k.gaps.all()
            assert world.builds("ITEM-1") == []
            # The checker comes back; the resolver closes the gap item; the item is probed again.
            await close_gap(k.engine, k.gaps, gap.id)
            return gap, waiting, await k.result("ITEM-1")

    gap, waiting, result = asyncio.run(scenario())
    world.verify()
    assert (gap.need, gap.lane, gap.resolver, gap.items, gap.open) == (
        PREFLIGHT_NEED,
        "walwarden",
        "platform",
        ("ITEM-1",),
        True,
    )
    assert gap.output == "the preflight did not finish within its limit"
    entered = next(e for e in world.events if e["state"] == "waiting")
    assert (entered["cause"], entered["action"]) == ("limit", "open-capability-gap")
    # The owner of a wait cannot set its limit, so this wait has the table's own.
    assert len(waiting.pending_timers) == 1
    assert timedelta(hours=23) < waiting.pending_timers[0] <= timedelta(hours=24)
    assert result["state"] == "merged"
    assert world.states("ITEM-1") == ["admitted", "preflight", "waiting", "preflight", *TO_MERGED]
    assert len(world.builds("ITEM-1")) == 1
