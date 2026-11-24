"""Acceptance (SY-V3-LANE-RUNTIME): one service takes an item from admitted to merged with no
hand action.

Ours, all real: the API service admits over HTTP, the kernel service runs as its console script
does (`sortyard.services.kernel.serve`, built from environment settings), the engine is its
development server, the ledger a fresh Postgres. Outside: the GitHub fake and the Kubernetes
fake over real HTTP, each held to its published schema; the Jobs the launcher creates are run
by the real `sortyard-worker` entry point against a git remote on disk (tests/runtime_harness.py).

"No hand action" here means: a test admits items, lets the outside world do its part (pods
run, CI reports) and lets the observer loop pass. It sends no outcome and moves no item. The
one exception is named where it happens: a capability-gap item is closed by the test, which
stands in for the resolver's own workflow (a gap item is not yet a work item on a lane).

No test waits a fixed time: each drives passes until the projection shows what it waits for.
"""

from __future__ import annotations

import asyncio
import functools
import pathlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

from sortyard.engine import Engine
from sortyard.kernel.item import workflow_id
from sortyard.kernel.preflight import close_gap
from sortyard.kernel.store import Items, PgGapRegistry
from sortyard.lane.github import GitHubError, HttpGitHub, branch_of
from sortyard.lane.runtime import ensure_pull
from sortyard.services import kernel
from tests.api_harness import WS
from tests.fake_github import APP_ID, PEM
from tests.kernel_harness import until
from tests.pg import requires_postgres
from tests.runtime_harness import OTHER_REPO, REPO, Service, World, drive, world

HAPPY = ["admitted", "preflight", "building", "checking", "reviewing", "merging", "merged"]


def all_merged(w: World, count: int) -> bool:
    states = w.states()
    return len(states) == count and set(states.values()) == {"merged"}


def job_creates(w: World) -> list[str]:
    """The name of every Job the cluster accepted, in order."""
    return [
        exchange.response["metadata"]["name"]
        for exchange in w.cluster.exchanges
        if exchange.method == "POST" and exchange.path.endswith("/jobs") and exchange.status == 201
    ]


def granted_unrecorded(w: World) -> list[str]:
    """Items the scheduler has granted a slot whose move out of the queue is not recorded."""
    with w.connect() as conn:
        rows = conn.execute(
            "SELECT i.id FROM sortyard.item_slot AS g JOIN sortyard.item AS i"
            " ON (i.workspace_id, i.id) = (g.workspace_id, g.item_id) WHERE i.state_kind = 'queue'"
        ).fetchall()
    return [row[0] for row in rows]


def stays(w: World) -> dict[str, dict[str, Any]]:
    """The open stays, read as a new process would read them."""
    return {stay["item"]: stay for stay in Items(w.connect).open_stays()}


@requires_postgres
def test_one_item_goes_admitted_to_merged_with_no_hand_action(tmp_path: pathlib.Path) -> None:
    """One item goes admitted to merged through the real engine, the real ledger and the GitHub
    and jobs fakes with no hand action."""

    async def scenario() -> None:
        async with world(tmp_path) as w:
            needs = ["secret:MODEL_API_KEY", "service:cluster-api"]
            admitted = w.admit("ITEM-1", needs=needs, title="Count to ten")
            assert admitted.status == 201, admitted.body
            service = Service(w)
            try:
                await drive(w, service, lambda: all_merged(w, 1), "ITEM-1 merged")
            finally:
                await service.kill()
            assert w.path("ITEM-1") == HAPPY
            # Preflight exercised every need before the build: the lane's defaults, the
            # item's repository and the two it listed, each with a recorded result.
            probes = Items(w.connect).probe_results(WS, "ITEM-1")
            assert {probe.need for probe in probes} == {
                "worker-image",
                "runner-pool",
                f"repository:{REPO}",
                *needs,
            }
            assert all(probe.passed for probe in probes)
            # One Job per dispatch: the build, then the review. Nothing else was launched.
            assert [brief["mode"] for brief in w.ran] == ["build", "review"]
            assert len(job_creates(w)) == 2
            # The runtime opened the pull request, once, with the item's title and a body
            # naming the item, and it was merged once at the commit the review read.
            (pull,) = w.repo.pulls
            (opened,) = w.fake.seen("pulls/create")
            assert opened.body["title"] == "Count to ten" and "ITEM-1" in opened.body["body"]
            assert (opened.body["head"], opened.body["base"]) == (branch_of("ITEM-1"), "main")
            # (The owner and a pass of the observer may both ask GitHub to merge; GitHub
            # carries out one, and every ask names the reviewed head.)
            assert pull.merged and pull.merges == 1
            assert {asked.body["sha"] for asked in w.fake.seen("pulls/merge")} == {pull.head}
            # Nothing is left open, and the item's lane slot is free again.
            assert stays(w) == {}

    asyncio.run(scenario())


@requires_postgres
def test_ten_items_in_a_row_go_admitted_to_merged(tmp_path: pathlib.Path) -> None:
    """Ten items in a row go admitted to merged, including one fix round and one capability gap
    that closes."""
    items = [f"ITEM-{number}" for number in range(1, 11)]

    async def scenario() -> None:
        async with world(tmp_path) as w:
            w.red_once = {"ITEM-3"}  # its first head fails the check: one fix round
            # ITEM-5 needs a repository the lane declares and GitHub does not have yet.
            needs = {"ITEM-5": [f"repository:{OTHER_REPO}"]}
            # Ten at once, on a lane with two slots.
            with ThreadPoolExecutor(10) as pool:
                replies = list(
                    pool.map(lambda item: w.admit(item, needs=needs.get(item, [])), items)
                )
            assert [reply.status for reply in replies] == [201] * 10
            gaps = PgGapRegistry(w.connect)
            service = Service(w)
            try:
                await drive(w, service, lambda: w.states()["ITEM-5"] == "waiting", "ITEM-5 waiting")
                # Let every grant already made be recorded before the gap closes.
                await drive(w, service, lambda: not granted_unrecorded(w), "grants recorded")
                (gap,) = gaps.for_item(WS, "ITEM-5")
                assert (gap.need, gap.resolver, gap.open) == (
                    f"repository:{OTHER_REPO}",
                    "platform",
                    True,
                )
                # The resolver's part, done here by hand: the repository appears, and the gap
                # item is closed. `close_gap` is what the resolver's workflow will call.
                w.fake.repo(OTHER_REPO)
                await close_gap(w.engine, gaps, gap.id)
                await drive(w, service, lambda: all_merged(w, 10), "ten items merged")
            finally:
                await service.kill()

            paths = {item: w.path(item) for item in items}
            fix = [*HAPPY[:4], "fixing", "checking", *HAPPY[4:]]
            gap_path = ["admitted", "preflight", "waiting", *HAPPY[1:]]
            assert paths == {**dict.fromkeys(items, HAPPY), "ITEM-3": fix, "ITEM-5": gap_path}
            # The fix Job was told the finding, and started from the branch the build pushed.
            (fixed,) = [brief for brief in w.ran if brief["mode"] == "fix"]
            assert fixed["item"] == "ITEM-3" and "test" in fixed["finding"]["failed"]
            assert sorted(brief["mode"] for brief in w.ran) == sorted(
                ["build"] * 10 + ["review"] * 10 + ["fix"]
            )
            # Every item has one pull request, merged once.
            assert sorted(pull.branch for pull in w.repo.pulls) == sorted(map(branch_of, items))
            assert all(pull.merged and pull.merges == 1 for pull in w.repo.pulls)
            # No item was dispatched while two others held the lane's slots. Read from the
            # ledger: walk every transition in order, counting the items in work.
            with w.connect() as conn:
                moves = conn.execute(
                    "SELECT object_id, doc -> 'transition' ->> 'from', doc -> 'transition' ->> 'to'"
                    " FROM sortyard.event WHERE object_kind = 'item' AND object_id <> 'item-1'"
                    " ORDER BY seq"
                ).fetchall()
            # An item back from a wait is in work without a new dispatch (the scheduler's
            # rule: a wait frees the slot), so it is counted apart: at most one such item
            # here, and never a dispatch beside two items that were themselves dispatched.
            holding: set[str] = set()
            returned: set[str] = set()
            dispatched: list[str] = []
            for item, left, entered in moves:
                if left == "admitted":
                    beside = sorted(holding - returned)
                    assert len(beside) < 2, f"{item} dispatched beside {beside}"
                    dispatched.append(item)
                if entered in ("merged", "waiting"):
                    holding.discard(item)
                    returned.discard(item)
                elif entered != "admitted":
                    holding.add(item)
                    if left == "waiting":
                        returned.add(item)
                assert len(holding) <= 3
            assert sorted(dispatched) == sorted(items)

    asyncio.run(scenario())


@requires_postgres
def test_the_service_is_stopped_mid_build_and_mid_check_and_every_item_still_merges(
    tmp_path: pathlib.Path,
) -> None:
    """The service is stopped mid-build and mid-check and every item still merges after it
    restarts."""

    async def scenario() -> None:
        async with world(tmp_path) as w:
            for item in ("A", "B", "C"):
                assert w.admit(item).status == 201
            # A's build pod does not finish and CI does not report: A stays mid-build, B
            # mid-check, C queued behind the lane's two slots.
            w.held, w.ci_held = {"A"}, True
            first = Service(w)
            await drive(
                w,
                first,
                lambda: w.states() == {"A": "building", "B": "checking", "C": "admitted"},
                "A building, B checking, C queued",
            )
            before = stays(w)
            await first.kill()
            # While the service is down the outside world carries on: A's pod finishes and
            # pushes, CI reports on B's head. No one is there to see either.
            w.held, w.ci_held = set(), False
            await w.turn()
            assert w.states() == {"A": "building", "B": "checking", "C": "admitted"}
            assert stays(w) == before  # the open stays are in Postgres, not in the service

            # A new service: new objects, the same database and the same engine server. It
            # is stopped once more, mid-merge: GitHub has not yet said whether C merges.
            second = Service(w)
            w.held = {"C:review"}
            await drive(w, second, lambda: w.states()["C"] == "reviewing", "C in review")
            w.repo.pull_of(branch_of("C")).computing = 10_000  # reads that answer "not yet"
            w.held = set()
            await drive(w, second, lambda: w.states()["C"] == "merging", "C merging")
            assert not w.repo.pull_of(branch_of("C")).merged
            await second.kill()
            w.repo.pull_of(branch_of("C")).computing = 0

            third = Service(w)
            try:
                await drive(w, third, lambda: all_merged(w, 3), "every item merged")
            finally:
                await third.kill()
            assert {item: w.path(item) for item in "ABC"} == dict.fromkeys("ABC", HAPPY)
            # Nothing was done twice for being interrupted: one Job per dispatch (a build
            # and a review each), one pull request each, each merged once.
            assert sorted(brief["item"] + ":" + brief["mode"] for brief in w.ran) == sorted(
                f"{item}:{mode}" for item in "ABC" for mode in ("build", "review")
            )
            assert len(job_creates(w)) == len(set(job_creates(w))) == 6
            assert len(w.fake.seen("pulls/create")) == 3
            assert all(pull.merged and pull.merges == 1 for pull in w.repo.pulls)

    asyncio.run(scenario())


@requires_postgres
def test_gap_items_and_probe_results_survive_a_restart(tmp_path: pathlib.Path) -> None:
    """Gap items and probe results survive a restart."""

    async def scenario() -> None:
        async with world(tmp_path) as w:
            assert w.admit("G", needs=[f"repository:{OTHER_REPO}"]).status == 201
            first = Service(w)
            await drive(w, first, lambda: w.states()["G"] == "waiting", "G waiting on its gap")
            await first.kill()

            # Read by objects made after the service stopped: nothing of it is left but rows.
            gaps, items = PgGapRegistry(w.connect), Items(w.connect)
            (gap,) = gaps.for_item(WS, "G")
            assert (gap.lane, gap.need, gap.items, gap.open) == (
                "walwarden",
                f"repository:{OTHER_REPO}",
                ("G",),
                True,
            )
            assert gaps.get(gap.id) == gap
            failed = [probe for probe in items.probe_results(WS, "G") if not probe.passed]
            assert [(probe.need, probe.output) for probe in failed] == [(gap.need, gap.output)]
            assert gap.output  # the probe's output, for whoever resolves it

            # The resolver fixes the need and closes the gap item while the service is down,
            # and no one tells the item (the `closed` signal is the part that was lost).
            w.fake.repo(OTHER_REPO)
            assert not gaps.close(gap.id).open
            assert w.states()["G"] == "waiting"

            # The restarted service finds the wait, sees its gap item closed, and the item
            # goes back through preflight (which now passes) to merged.
            second = Service(w)
            try:
                await drive(w, second, lambda: all_merged(w, 1), "G merged")
            finally:
                await second.kill()
            assert w.path("G") == ["admitted", "preflight", "waiting", *HAPPY[1:]]
            results = Items(w.connect).probe_results(WS, "G")
            dispatches = sorted({probe.dispatch for probe in results})
            assert len(dispatches) == 2  # both preflights are on record
            again = [probe for probe in results if probe.dispatch == dispatches[1]]
            assert all(probe.passed for probe in again) and len(again) == 4
            assert [g.open for g in PgGapRegistry(w.connect).all()] == [False]

    asyncio.run(scenario())


@requires_postgres
def test_an_outcome_observed_for_an_earlier_stay_of_the_same_state_is_not_applied(
    tmp_path: pathlib.Path,
) -> None:
    """A look made with a stay read earlier sends that stay's dispatch number, so when the item
    is in a later stay of the same state the outcome is not applied."""

    async def scenario() -> None:
        async with world(tmp_path) as w:
            assert w.admit("S").status == 201
            w.red_once, w.ci_held = {"S"}, True
            identifier = workflow_id(WS, "S")
            service = Service(w)
            try:
                await drive(w, service, lambda: w.states()["S"] == "checking", "S checking")
                stale = stays(w)["S"]  # what a slow pass, or another process, read
                # The check fails; the fix is pushed; S is in checking again, a later stay,
                # and CI has not reported on the new head.
                w.ci_held, w.held = False, {"S:fix"}
                await drive(w, service, lambda: w.states()["S"] == "fixing", "S fixing")
                w.ci_held, w.held = True, set()
                await drive(
                    w,
                    service,
                    lambda: w.path("S")[-3:] == ["checking", "fixing", "checking"],
                    "S checking again",
                )
                # The ci-adapter has had its own first look at the new stay, and found nothing.
                await until(
                    lambda: w.engine.recorded(identifier), lambda r: r.idle, "S waiting in checking"
                )
                current = stays(w)["S"]
                assert current["state"] == stale["state"] == "checking"
                assert current["dispatch"] > stale["dispatch"]
                # CI turns green on the new head. A second observer (another process's, built
                # from the same settings) now looks with the stay it read long ago: it finds
                # green and sends it, with the old dispatch number.
                w.ci_held = False
                await w.turn()
                engine = await Engine.connect(w.target)
                other = kernel.assemble(w.settings()).observer(engine)
                sent = len((await engine.recorded(identifier)).signals)
                assert await other.look(stale) == "green"
                await until(
                    lambda: engine.recorded(identifier),
                    lambda recorded: recorded.idle and len(recorded.signals) == sent + 1,
                    "the workflow has read the late outcome",
                )
                # Not applied: S is still in the same stay.
                assert stays(w)["S"] == current
                assert w.path("S")[-1] == "checking"
                # The same look with the stay as it is now is applied, as any pass would.
                assert await other.look(current) == "green"
                await drive(w, service, lambda: all_merged(w, 1), "S merged")
            finally:
                await service.kill()
            assert w.path("S") == [*HAPPY[:4], "fixing", "checking", *HAPPY[4:]]

    asyncio.run(scenario())


@requires_postgres
def test_the_pull_request_of_an_item_is_opened_once_however_often_it_is_ensured(
    tmp_path: pathlib.Path,
) -> None:
    """Opening the pull request is safe to repeat and safe to race: one pull request per
    branch, and a closed one is replaced."""

    async def scenario() -> None:
        async with world(tmp_path) as w:
            assert w.admit("P", title="A pull request").status == 201
            w.fake.push(w.repo, branch_of("P"))
            port = HttpGitHub(APP_ID, PEM, base_url=w.fake.url)
            spec = Items(w.connect).spec(WS, "P")
            ensure = functools.partial(ensure_pull, port, spec)
            with ThreadPoolExecutor(6) as pool:
                for done in [pool.submit(ensure) for _ in range(6)]:
                    done.result()
            ensure()
            (pull,) = w.repo.pulls
            assert (pull.title, pull.base, pull.branch) == ("A pull request", "main", "sortyard/P")
            created = [status for name, status, _ in w.fake.replies if name == "pulls/create"]
            assert created.count(201) == 1  # the others were refused, and found it there
            # Closed without merging (someone closed it): the next ensure opens another.
            pull.open = False
            ensure()
            assert [each.open for each in w.repo.pulls] == [False, True]
            # A branch that was never pushed cannot have one: the refusal is raised, not hidden.
            with pytest.raises(GitHubError) as refused:
                ensure_pull(port, replace(spec, item="NEVER-PUSHED"))
            assert refused.value.status == 422
            assert len(w.repo.pulls) == 2

    asyncio.run(scenario())
