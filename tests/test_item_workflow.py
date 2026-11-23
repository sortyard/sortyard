"""Acceptance (SY-V3-STATE-TABLE): one generic workflow runs the state table.

The workflow, the state table and the engine are real (the engine's test server, on its test
clock). The owners, the decision service and the recorder are fakes: plain functions that
answer from a script and keep what they were called with. No test waits a fixed time: limits
pass because the test clock is advanced.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, TypeVar

import pytest

from sortyard.engine import Engine, Recorded, Registry
from sortyard.engine.testing import TestClock, time_skipping_engine
from sortyard.kernel.item import INPUT_SIGNAL, register, send_outcome, start_item
from sortyard.kernel.states import StateTable, load, shipped, shipped_text

DEADLINE = 60.0
T = TypeVar("T")
Reply = Mapping[str, Any] | None

# What every owner answers when nothing goes wrong, by state.
HAPPY: dict[str, Reply] = {
    "admitted": {"outcome": "dispatched"},
    "preflight": {"outcome": "ready"},
    "building": {"outcome": "built"},
    "checking": {"outcome": "green"},
    "reviewing": {"outcome": "approved"},
    "fixing": {"outcome": "fixed"},
    "merging": {"outcome": "merged"},
    # "waiting" has no entry: the need's owner takes the wait and reports when the need closes.
}
SILENT: Reply = None  # the owner took the work; its outcome will arrive as an input


@dataclass
class Fakes:
    """Scripted owners, a scripted decision service and a recorder that keeps every event.

    `script[state]` (or `script["ITEM/state"]` for one item) is the list of replies the
    state's owner gives, one per call; when it runs out (or a state has none) the owner gives
    the happy reply.
    """

    script: dict[str, list[Reply]] = field(default_factory=dict)
    decisions: list[Any] = field(default_factory=list)
    calls: list[Mapping[str, Any]] = field(default_factory=list)
    questions: list[Mapping[str, Any]] = field(default_factory=list)
    events: list[Mapping[str, Any]] = field(default_factory=list)

    def owner(self, call: Mapping[str, Any]) -> Reply:
        self.calls.append(call)
        scripted = self.script.get(f"{call['item']}/{call['state']}") or self.script.get(
            call["state"], []
        )
        return scripted.pop(0) if scripted else HAPPY.get(call["state"])

    def decide(self, question: Mapping[str, Any]) -> Reply:
        self.questions.append(question)
        answer = self.decisions.pop(0) if self.decisions else None
        if isinstance(answer, Exception):
            raise answer
        reply: Reply = answer
        return reply

    def record(self, event: Mapping[str, Any]) -> None:
        self.events.append(event)

    def states(self) -> list[str]:
        return [event["state"] for event in self.events]

    def calls_for(self, state: str) -> list[Mapping[str, Any]]:
        return [call for call in self.calls if call["state"] == state]


@dataclass
class Kernel:
    engine: Engine
    clock: TestClock
    fakes: Fakes

    async def start(self, item: str = "ITEM-1", **options: Any) -> str:
        return await start_item(self.engine, item, tenant="acme", **options)

    async def result(self, identifier: str) -> Any:
        return await asyncio.wait_for(self.engine.result(identifier), DEADLINE)

    async def idle_in(self, identifier: str, state: str) -> Recorded:
        """Wait until the item is waiting in `state`, and return what the engine recorded."""

        async def read() -> tuple[Recorded, list[str]]:
            return await self.engine.recorded(identifier), self.fakes.states()

        recorded, _ = await until(
            read, lambda seen: seen[0].idle and seen[1][-1:] == [state], f"the wait in {state}"
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
async def kernel(fakes: Fakes, table: StateTable | None = None) -> AsyncIterator[Kernel]:
    states = (table or shipped()).states.values()
    owners = {state.owner: fakes.owner for state in states if state.owner is not None}
    registry = Registry()
    register(registry, owners=owners, decide=fakes.decide, record=fakes.record)
    async with time_skipping_engine() as skipping:
        worker = asyncio.create_task(skipping.engine.run_worker(registry))
        try:
            yield Kernel(skipping.engine, skipping.clock, fakes)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


def one_timer(recorded: Recorded, limit: timedelta) -> None:
    """The item waits on exactly one durable timer: what is left of the state's limit."""
    assert len(recorded.pending_timers) == 1, recorded
    assert limit - timedelta(seconds=DEADLINE) < recorded.pending_timers[0] <= limit, recorded


def test_an_item_passes_admitted_to_merged_through_fake_owner_steps() -> None:
    """An item passes admitted to merged through fake owner steps."""
    # The executor takes the build and reports back later, as a webhook would; every other
    # owner answers at once.
    fakes = Fakes(script={"building": [SILENT]})

    async def scenario() -> Any:
        async with kernel(fakes) as k:
            identifier = await k.start()
            building = await k.idle_in(identifier, "building")
            one_timer(building, timedelta(hours=1))  # the medium risk tier's limit
            # An outcome for a state the item is not in changes nothing, and neither does a
            # late one from an earlier dispatch of this state.
            await send_outcome(k.engine, identifier, state="checking", outcome="green")
            await send_outcome(
                k.engine, identifier, state="building", outcome="no-change", dispatch=1
            )
            # Nor do inputs that say nothing the workflow understands, or an outcome the
            # state does not have.
            await k.engine.signal(
                identifier, INPUT_SIGNAL, {"kind": "outcome", "state": "building"}
            )
            await k.engine.signal(identifier, INPUT_SIGNAL, ["not", "a", "mapping"])
            await send_outcome(k.engine, identifier, state="building", outcome="exploded")
            late = await until(
                lambda: k.engine.recorded(identifier),
                lambda r: r.idle and len(r.signals) == 5,
                "the stray inputs read",
            )
            assert late.defect is None
            one_timer(late, timedelta(hours=1))
            assert fakes.states()[-1] == "building"
            await send_outcome(k.engine, identifier, state="building", outcome="built")
            return await k.result(identifier)

    result = asyncio.run(scenario())
    order = ["admitted", "preflight", "building", "checking", "reviewing", "merging", "merged"]
    assert result == {"item": "ITEM-1", "tenant": "acme", "state": "merged", "transitions": 7}
    assert fakes.states() == order
    assert [event["sequence"] for event in fakes.events] == [1, 2, 3, 4, 5, 6, 7]
    assert [event["from_state"] for event in fakes.events] == [None, *order[:-1]]
    assert [event["cause"] for event in fakes.events] == ["start"] + ["outcome"] * 6
    assert [event["outcome"] for event in fakes.events[1:]] == [
        "dispatched",
        "ready",
        "built",
        "green",
        "approved",
        "merged",
    ]
    # Every event names the state's owner, limit and reason, as the table declares them.
    table = shipped()
    for event in fakes.events:
        state = table.state(event["state"])
        assert event["item"] == "ITEM-1" and event["tenant"] == "acme"
        assert event["owner"] == state.owner
        assert event["limit"] == (state.limit.text if state.limit else None)
        assert event["reason"] == state.reason
        assert event["entered_at"]
    # Each owner was called once, by the name the table gives the state.
    assert [(call["state"], call["owner"], call["attempt"]) for call in fakes.calls] == [
        (name, table.state(name).owner, 1) for name in order[:-1]
    ]
    # The owner is told which stay it is dispatched for: the transition's sequence.
    assert [call["dispatch"] for call in fakes.calls] == [1, 2, 3, 4, 5, 6]
    building = fakes.events[2]
    assert (building["state_kind"], building["from_kind"]) == ("work", "work")
    assert building["limit_seconds"] == 3600 and building["attempt"] == 1
    assert building["deadline"] > building["entered_at"]
    assert fakes.events[0]["limit_seconds"] is None and fakes.events[0]["deadline"] is None
    assert fakes.questions == []


def test_a_limit_that_passes_applies_the_declared_default_and_records_it() -> None:
    """A limit that passes applies the declared default and records it."""
    # The reviewer takes the review twice and never reports. The checks, later, never report.
    fakes = Fakes(script={"reviewing": [SILENT, SILENT], "checking": [None, SILENT, SILENT]})
    fakes.script["checking"][0] = HAPPY["checking"]
    half_hour, ten_minutes = timedelta(minutes=30), timedelta(minutes=10)

    async def scenario() -> Any:
        async with kernel(fakes) as k:
            identifier = await k.start()
            # reviewing: 30 minutes, then "dispatch the reviewer again".
            one_timer(await k.idle_in(identifier, "reviewing"), half_hour)
            assert len(fakes.calls_for("reviewing")) == 1
            await k.clock.advance(half_hour - timedelta(minutes=2))
            still = await k.idle_in(identifier, "reviewing")
            assert len(still.pending_timers) == 1 and len(fakes.calls_for("reviewing")) == 1
            await k.clock.advance(timedelta(minutes=2))
            await until(
                lambda: asyncio.sleep(0, fakes.calls_for("reviewing")),
                lambda calls: len(calls) == 2,
                "the reviewer dispatched again",
            )
            one_timer(await k.idle_in(identifier, "reviewing"), half_hour)  # a fresh limit
            # The second review finds something; the fix sends the item back to checking,
            # where the checks now stay silent: 10 minutes, one rerun, then a decision.
            await send_outcome(k.engine, identifier, state="reviewing", outcome="findings")
            one_timer(await k.idle_in(identifier, "checking"), ten_minutes)
            await k.clock.advance(ten_minutes)
            await until(
                lambda: asyncio.sleep(0, fakes.calls_for("checking")),
                lambda calls: len(calls) == 3,
                "the checks rerun",
            )
            one_timer(await k.idle_in(identifier, "checking"), ten_minutes)
            await k.clock.advance(ten_minutes)
            # The decision (table default: resume) sends it back to checking, which is green.
            return await k.result(identifier)

    result = asyncio.run(scenario())
    assert result["state"] == "merged"
    defaults = [
        (e["from_state"], e["state"], e["cause"], e["default"], e["action"])
        for e in fakes.events
        if e["cause"] == "limit"
    ]
    assert defaults == [
        ("reviewing", "reviewing", "limit", "redispatch", None),
        ("checking", "checking", "limit", "retry 1, then decision (rerun-checks)", "rerun-checks"),
        ("checking", "decision", "limit", "retry 1, then decision (rerun-checks)", "rerun-checks"),
    ]
    # The owner dispatched after a default is told the attempt and the default's action.
    assert [call["attempt"] for call in fakes.calls_for("reviewing")] == [1, 2, 3]
    assert [(c["attempt"], c["cause"], c["action"]) for c in fakes.calls_for("checking")] == [
        (1, "outcome", None),
        (2, "outcome", None),
        (3, "limit", "rerun-checks"),
        (4, "decision", None),
    ]
    assert fakes.states() == [
        *["admitted", "preflight", "building", "checking"],
        *["reviewing", "reviewing", "fixing", "checking", "checking", "decision", "checking"],
        *["reviewing", "merging", "merged"],
    ]


def test_a_decision_state_returns_an_answer_in_the_same_pass_with_the_reversal_recorded() -> None:
    """A decision state returns an answer in the same pass with the reversal recorded."""
    no_change: Reply = {"outcome": "no-change", "detail": {"note": "nothing to build"}}
    items = ["POLICY", "NO-POLICY", "NO-REVERSAL", "POLICY-DOWN", "NO-DEFAULT"]
    fakes = Fakes(script={f"{item}/building": [no_change] for item in items})
    policy = {"answer": "rebuild", "reverse": "Reopen the item with the earlier spec."}
    # One decision per item, in order: policy answers; policy has no answer; policy answers
    # without saying how to reverse it; the policy service is down; and no answer anywhere.
    fakes.decisions = [policy, None, {"answer": "rebuild"}, RuntimeError("policy down"), None]
    item_default = {"answer": "wait", "reverse": "Close the need by hand."}

    async def scenario() -> list[Recorded]:
        recorded = []
        async with kernel(fakes) as k:
            for item in items:
                own = None if item in ("POLICY", "NO-DEFAULT") else item_default
                identifier = await k.start(item, decision_default=own)
                if own is not None:
                    # The item's own answer was "wait": close the need and let it carry on.
                    await k.idle_in(identifier, "waiting")
                    await send_outcome(k.engine, identifier, state="waiting", outcome="closed")
                await k.result(identifier)
                recorded.append(await k.engine.recorded(identifier))
        return recorded

    recorded = asyncio.run(scenario())
    decided = [event for event in fakes.events if event["cause"] == "decision"]
    table_reverse = "Send the item a decision request with a different answer."
    assert [
        (
            e["item"],
            e["state"],
            e["decision"]["answer"],
            e["decision"]["reverse"],
            e["decision"]["source"],
        )
        for e in decided
    ] == [
        ("POLICY", "building", "rebuild", policy["reverse"], "policy"),
        ("NO-POLICY", "waiting", "wait", item_default["reverse"], "item"),
        ("NO-REVERSAL", "waiting", "wait", item_default["reverse"], "item"),
        ("POLICY-DOWN", "waiting", "wait", item_default["reverse"], "item"),
        # "resume" sends the item back to the state that asked.
        ("NO-DEFAULT", "building", "resume", table_reverse, "table"),
    ]
    for event in decided:
        # The question is recorded with the answer: which state asked, and why.
        question = event["decision"]["question"]
        assert question["state"] == "building" and question["cause"] == "outcome"
        assert question["outcome"] == "no-change"
        assert question["detail"] == {"note": "nothing to build"}
    assert len(fakes.questions) == 5  # asked once per decision, never retried
    # Same pass: the decision's answer is the very next event, and the items with no "wait"
    # answer finished without a timer firing or an input arriving.
    for item in items:
        events = [event for event in fakes.events if event["item"] == item]
        asked = next(index for index, event in enumerate(events) if event["state"] == "decision")
        assert events[asked + 1]["cause"] == "decision"
        assert events[asked + 1]["sequence"] == events[asked]["sequence"] + 1
    assert recorded[0].signals == () and recorded[4].signals == ()


def test_fixing_passes_its_limit_when_the_same_finding_comes_back() -> None:
    finding: Reply = {"outcome": "findings", "detail": {"finding": "F-1: missing null check"}}
    other: Reply = {"outcome": "findings", "detail": {"finding": "F-2: unbounded retry"}}
    conflict: Reply = {"outcome": "conflict"}
    red: Reply = {"outcome": "red"}
    # After the three reviews: a merge conflict and two red checks, none naming a finding.
    fakes = Fakes(
        script={
            "reviewing": [finding, other, finding],
            "merging": [conflict],
            "checking": [None, None, None, None, red, red],
        }
    )
    fakes.script["checking"][:4] = [HAPPY["checking"]] * 4

    async def scenario() -> Any:
        async with kernel(fakes) as k:
            return await k.result(await k.start())

    assert asyncio.run(scenario())["state"] == "merged"
    # F-1, then F-2 (a different finding: progress), then F-1 again: the limit passes, the
    # executor is not dispatched for it, and the decision gets the default's action.
    into_fixing = [e for e in fakes.events if e["from_state"] in ("reviewing", "fixing")]
    assert [(e["from_state"], e["state"], e["cause"], e["action"]) for e in into_fixing[:8]] == [
        ("reviewing", "fixing", "outcome", None),
        ("fixing", "checking", "outcome", None),
        ("reviewing", "fixing", "outcome", None),
        ("fixing", "checking", "outcome", None),
        ("reviewing", "fixing", "outcome", None),
        ("fixing", "decision", "limit", "narrow-or-split"),
        ("fixing", "checking", "outcome", None),
        ("reviewing", "merging", "outcome", None),
    ]
    # The decision (resume) starts progress over, so the executor is dispatched a third time.
    assert [call["attempt"] for call in fakes.calls_for("fixing")][:3] == [1, 2, 4]
    assert len(fakes.questions) == 1
    assert fakes.questions[0]["state"] == "fixing"
    assert fakes.questions[0]["action"] == "narrow-or-split"
    # Entering fixing without a named finding is no evidence of repetition: the conflict and
    # the two red checks each dispatch the executor, and F-1 from long before is not held
    # against them.
    assert [call["detail"] for call in fakes.calls_for("fixing")[3:]] == [{}, {}, {}]
    assert [call["attempt"] for call in fakes.calls_for("fixing")] == [1, 2, 4, 5, 6, 7]


def test_an_outcome_delivered_twice_is_not_applied_to_the_next_stay() -> None:
    fakes = Fakes(script={"reviewing": [SILENT, SILENT]})
    finding = {"finding": "F-1: missing null check"}

    async def scenario() -> Any:
        async with kernel(fakes) as k:
            identifier = await k.start()
            await k.idle_in(identifier, "reviewing")
            # The reviewer's webhook fires twice.
            for _ in range(2):
                await send_outcome(
                    k.engine, identifier, state="reviewing", outcome="findings", detail=finding
                )

            # The fix goes through and the item is back in review, waiting: the second copy
            # was dropped, not taken as this review's verdict.
            def second_review(recorded: Recorded) -> bool:
                return recorded.idle and len(fakes.calls_for("reviewing")) == 2

            await until(lambda: k.engine.recorded(identifier), second_review, "the second review")
            assert fakes.states().count("fixing") == 1 and fakes.questions == []
            await send_outcome(k.engine, identifier, state="reviewing", outcome="approved")
            return await k.result(identifier)

    assert asyncio.run(scenario())["state"] == "merged"
    assert fakes.states().count("fixing") == 1 and fakes.questions == []


def test_a_new_state_is_added_by_editing_only_the_data_file() -> None:
    text = shipped_text().replace(
        'next = { built = "checking", no-change = "decision" }',
        'next = { built = "linting", no-change = "decision" }',
    )
    text += """
[states.linting]
owner = "ci-adapter"
limit = "5m"
default = { to = "decision" }
reason = "checks-running"
next = { linted = "checking" }
"""
    table = load(text)
    fakes = Fakes(script={"linting": [{"outcome": "linted"}]})

    async def scenario() -> Any:
        async with kernel(fakes, table) as k:
            return await k.result(await k.start(table=table))

    assert asyncio.run(scenario())["state"] == "merged"
    assert fakes.states() == [
        *["admitted", "preflight", "building", "linting", "checking"],
        *["reviewing", "merging", "merged"],
    ]
    linting = next(event for event in fakes.events if event["state"] == "linting")
    assert (linting["owner"], linting["limit"], linting["reason"]) == (
        "ci-adapter",
        "5m",
        "checks-running",
    )


def test_a_wait_on_a_need_takes_the_needs_limit() -> None:
    gap: Reply = {"outcome": "gap", "detail": {"need": "secret:deploy-key", "limit": "2h"}}
    silent_gap: Reply = {"outcome": "gap", "detail": {"need": "runner:pool-a"}}
    absurd: Reply = {"outcome": "gap", "detail": {"need": "x", "limit": "99999999999d"}}
    fakes = Fakes(script={"preflight": [gap, silent_gap, absurd]})

    async def scenario() -> Any:
        async with kernel(fakes) as k:
            identifier = await k.start()
            # The need set two hours.
            one_timer(await k.idle_in(identifier, "waiting"), timedelta(hours=2))
            await send_outcome(k.engine, identifier, state="waiting", outcome="closed")
            # The second need set nothing: the table's "otherwise" applies. When it passes the
            # default is a decision, whose default answer resumes the wait.
            one_timer(await k.idle_in(identifier, "waiting"), timedelta(hours=24))
            await k.clock.advance(timedelta(hours=24))
            await until(
                lambda: asyncio.sleep(0, fakes.questions), lambda q: len(q) == 1, "the decision"
            )
            one_timer(await k.idle_in(identifier, "waiting"), timedelta(hours=24))
            await send_outcome(k.engine, identifier, state="waiting", outcome="closed")
            # The third need set a limit no clock can hold: "otherwise" applies again.
            one_timer(await k.idle_in(identifier, "waiting"), timedelta(hours=24))
            await send_outcome(k.engine, identifier, state="waiting", outcome="closed")
            return await k.result(identifier)

    assert asyncio.run(scenario())["state"] == "merged"
    assert [call["detail"].get("need") for call in fakes.calls_for("waiting")] == [
        "secret:deploy-key",
        "runner:pool-a",
        "runner:pool-a",
        "x",
    ]
    assert fakes.questions[0]["state"] == "waiting" and fakes.questions[0]["cause"] == "limit"
    waits = [event for event in fakes.events if event["state"] == "waiting"]
    assert [event["limit_seconds"] for event in waits] == [7200, 86400, 86400, 86400]
    assert all(event["state_kind"] == "need" for event in waits)


def test_an_outcome_the_state_does_not_know_waits_out_the_limit_then_gets_the_default() -> None:
    # The merge adapter answers with an outcome the table does not have, every time.
    exploded: Reply = {"outcome": "exploded"}
    fakes = Fakes(script={"merging": [exploded, exploded]})
    half_hour = timedelta(minutes=30)

    async def scenario() -> Any:
        async with kernel(fakes) as k:
            identifier = await k.start()
            # Not acted on at once: the item stays, inside its limit, dispatched once.
            one_timer(await k.idle_in(identifier, "merging"), half_hour)
            assert len(fakes.calls_for("merging")) == 1
            await k.clock.advance(half_hour)
            await until(
                lambda: asyncio.sleep(0, fakes.calls_for("merging")),
                lambda calls: len(calls) == 2,
                "the merge adapter dispatched again",
            )
            one_timer(await k.idle_in(identifier, "merging"), half_hour)
            # A real outcome inside the limit is still taken.
            await send_outcome(k.engine, identifier, state="merging", outcome="merged")
            return await k.result(identifier)

    assert asyncio.run(scenario())["state"] == "merged"
    unknown = [event for event in fakes.events if event["cause"] == "unknown-outcome"]
    assert [(e["from_state"], e["state"], e["outcome"], e["action"]) for e in unknown] == [
        ("merging", "merging", "exploded", "update-branch")
    ]
    assert len(fakes.calls_for("merging")) == 2  # once per limit, not in a loop


def test_a_decision_that_repeats_waits_on_a_named_need_instead_of_going_round_again() -> None:
    # The executor reports "no change" every time and no policy answers, so the table's default
    # (resume) sends the item straight back to the same build.
    no_change: Reply = {"outcome": "no-change"}
    fakes = Fakes(script={"building": [no_change] * 4})

    async def scenario() -> Any:
        async with kernel(fakes) as k:
            identifier = await k.start()
            # Two builds, two decisions, and the item is waiting with a timer running.
            waiting = await k.idle_in(identifier, "waiting")
            one_timer(waiting, timedelta(hours=24))
            assert len(fakes.calls_for("building")) == 2
            assert len(fakes.questions) == 2
            # Closing the need lets it try again: the same two rounds, then the wait again.
            await send_outcome(k.engine, identifier, state="waiting", outcome="closed")
            await until(
                lambda: asyncio.sleep(0, fakes.calls_for("building")),
                lambda calls: len(calls) == 4,
                "the next two builds",
            )
            one_timer(await k.idle_in(identifier, "waiting"), timedelta(hours=24))
            # The build now succeeds (the script is spent).
            await send_outcome(k.engine, identifier, state="waiting", outcome="closed")
            return await k.result(identifier)

    assert asyncio.run(scenario())["state"] == "merged"
    decided = [event["decision"] for event in fakes.events if event["cause"] == "decision"]
    assert [(d["answer"], d["source"]) for d in decided] == [
        ("resume", "table"),
        ("wait", "repeat"),
        ("resume", "table"),
        ("wait", "repeat"),
    ]
    assert all(d["reverse"].strip() for d in decided)
    need = fakes.calls_for("waiting")[0]["detail"]
    assert need["need"] == "a-different-answer"
    assert need["question"]["state"] == "building" and need["question"]["outcome"] == "no-change"
    assert len(fakes.calls_for("building")) == 5


def test_replies_that_are_not_understood_never_stop_an_item() -> None:
    no_change: Reply = {"outcome": "no-change"}
    # Owner replies that carry no outcome the workflow can read count as "will report later".
    fakes = Fakes(
        script={
            "preflight": [{"outcome": 7}],
            "building": [no_change, {"detail": "not a mapping"}],
            "checking": [["green"]],  # type: ignore[list-item]
        }
    )
    # A decision answer that is not an answer falls through to the table's default.
    fakes.decisions = [{"answer": ["rebuild"], "reverse": "x"}]

    async def scenario() -> tuple[Any, Recorded]:
        async with kernel(fakes) as k:
            identifier = await k.start()
            for state, outcome in (("preflight", "ready"), ("building", "built")):
                await k.idle_in(identifier, state)
                await send_outcome(k.engine, identifier, state=state, outcome=outcome)
            await k.idle_in(identifier, "checking")
            await send_outcome(k.engine, identifier, state="checking", outcome="green")
            return await k.result(identifier), await k.engine.recorded(identifier)

    result, recorded = asyncio.run(scenario())
    assert result["state"] == "merged" and recorded.defect is None
    decided = [event["decision"] for event in fakes.events if event["cause"] == "decision"]
    assert [(d["answer"], d["source"]) for d in decided] == [("resume", "table")]


def test_a_worker_or_an_item_that_cannot_run_the_table_is_refused_at_the_start() -> None:
    fakes = Fakes()
    owners = {state.owner: fakes.owner for state in shipped().states.values() if state.owner}
    del owners["reviewer"]
    with pytest.raises(ValueError, match=r"no owner registered for \['reviewer'\]"):
        register(Registry(), owners=owners, decide=fakes.decide, record=fakes.record)

    async def scenario() -> None:
        async with kernel(fakes) as k:
            for bad in ({"answer": ["rebuild"], "reverse": "x"}, {"answer": "rebuild"}, {}):
                with pytest.raises(ValueError, match="decision_default must name an answer"):
                    await k.start(decision_default=bad)

    asyncio.run(scenario())


def test_an_item_cannot_start_on_a_risk_tier_the_table_has_no_limit_for() -> None:
    async def scenario() -> None:
        async with kernel(Fakes()) as k:
            with pytest.raises(ValueError, match="no limit for risk tier 'extreme'"):
                await k.start(risk_tier="extreme")
            low = await k.start("LOW", risk_tier="low")
            assert (await k.result(low))["state"] == "merged"

    asyncio.run(scenario())
