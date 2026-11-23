"""The generic item workflow: one function that runs any state table (HARNESS-V3 section 3.1).

For each state the item enters, the workflow records the transition, calls the state's owner
step, starts the state's limit as a durable timer, and takes whichever comes first: the owner's
outcome (looked up in the state's `next`) or the limit, in which case the state's declared
default is applied and recorded. A decision state asks the decision step once and always leaves
with an answer in the same pass: the policy's, else the item's own default, else the table's,
recorded with the question and how to reverse it.

Behaviour lives in three steps the worker supplies (`register`): the owners that do the work,
the decision service, and the recorder that persists each transition. The workflow itself is
replayed from history, so it holds no I/O and reads no clock but the engine's.

An owner replies in one of two ways. It returns an outcome at once, or it returns none and the
outcome arrives later as an input signal (`send_outcome`), which is how a webhook reports that
a build, a check or a review finished. Either way the limit covers the whole stay.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from sortyard.engine import Context, Engine, LimitPassed, Registry, StepFailed
from sortyard.kernel.states import ORIGIN, Default, State, StateTable, load, parse_duration, shipped

ITEM_WORKFLOW = "sortyard.item"
OWNER_STEP = "sortyard.item.owner"
DECIDE_STEP = "sortyard.item.decide"
RECORD_STEP = "sortyard.item.record"
INPUT_SIGNAL = "sortyard.item.input"

# What a step may take for one attempt. An owner step dispatches work and returns; work that
# takes long reports back through `send_outcome`, inside the state's limit.
STEP_TIMEOUT = timedelta(seconds=60)

Payload = Mapping[str, Any]
Owner = Callable[[Payload], Payload | None]
Decide = Callable[[Payload], Payload | None]
Record = Callable[[Payload], None]


def workflow_id(tenant: str, item: str) -> str:
    return f"item:{tenant}:{item}"


def register(
    registry: Registry, *, owners: Mapping[str, Owner], decide: Decide, record: Record
) -> None:
    """Put the item workflow and its three steps on a worker's registry.

    `owners` maps an owner name from the state table to the function that does that owner's
    work. It gets the call (item, tenant, state, owner, attempt, cause, action, detail) and
    returns `{"outcome": ..., "detail": {...}}`, or nothing when the outcome will arrive as an
    input. `decide` gets the question and returns `{"answer": ..., "reverse": ...}` or nothing.
    `record` gets every transition event and must persist it; the item does not move on until
    it has.
    """

    def owner_step(call: Payload) -> Payload | None:
        owner = owners.get(call["owner"])
        if owner is None:
            raise LookupError(f"no owner {call['owner']!r} is registered on this worker")
        return owner(call)

    # Owners and the recorder are retried until they succeed; the state's limit bounds an
    # owner. The decision step gets one attempt: a decision answers in the pass that asks.
    registry.step(OWNER_STEP, timeout=STEP_TIMEOUT)(owner_step)
    registry.step(RECORD_STEP, timeout=STEP_TIMEOUT)(record)
    registry.step(DECIDE_STEP, timeout=STEP_TIMEOUT, max_attempts=1)(decide)
    registry.workflow(ITEM_WORKFLOW)(item_workflow)


async def start_item(
    engine: Engine,
    item: str,
    *,
    tenant: str,
    risk_tier: str = "medium",
    table: StateTable | None = None,
    decision_default: Payload | None = None,
) -> str:
    """Start the workflow of one item and return its workflow id.

    The item runs on `table` (the shipped one unless given) for its whole life.
    `decision_default` is the item's own answer for decisions policy does not cover:
    `{"answer": ..., "reverse": ...}`.
    """
    table = table or shipped()
    for state in table.states.values():
        if (
            state.limit
            and state.limit.kind == "by-risk-tier"
            and risk_tier not in state.limit.by_tier
        ):
            raise ValueError(f"state {state.name!r} has no limit for risk tier {risk_tier!r}")
    identifier = workflow_id(tenant, item)
    await engine.start(
        ITEM_WORKFLOW,
        identifier,
        {
            "item": item,
            "tenant": tenant,
            "risk_tier": risk_tier,
            "table": table.text,
            "decision_default": dict(decision_default) if decision_default else None,
        },
    )
    return identifier


async def send_outcome(
    engine: Engine,
    identifier: str,
    *,
    state: str,
    outcome: str,
    detail: Payload | None = None,
    attempt: int | None = None,
) -> None:
    """Report an owner's outcome for the state the item is in.

    An outcome for another state is ignored. Pass the `attempt` the owner was called with to
    have a late report from an earlier dispatch of the same state ignored too.
    """
    await engine.signal(
        identifier,
        INPUT_SIGNAL,
        {
            "kind": "outcome",
            "state": state,
            "attempt": attempt,
            "outcome": outcome,
            "detail": dict(detail or {}),
        },
    )


def _apply_default(state: State, default: Default, retries_used: dict[str, int]) -> str:
    """The state the declared default sends the item to; counts the retries it spends."""
    if default.kind == "retry":
        used = retries_used.get(state.name, 0)
        if used < default.retries:
            retries_used[state.name] = used + 1
            return state.name
        retries_used.pop(state.name, None)
    if default.kind in ("to", "retry"):
        assert default.to is not None
        return default.to
    return state.name  # redispatch


def _limit_for(state: State, tier: str, detail: Payload) -> timedelta | None:
    limit = state.limit
    assert limit is not None
    if limit.kind == "by-risk-tier":
        return limit.by_tier.get(tier) or min(limit.by_tier.values())
    if limit.kind == "by-need":
        try:
            return parse_duration(str(detail.get("limit")))
        except ValueError:
            return limit.duration
    return limit.duration  # a duration, or none for a queue and for repeat-finding


def _answer(state: State, policy: Any, item_default: Payload | None) -> tuple[str, Payload]:
    """The decision's answer and where it came from: policy, else the item, else the table.

    A candidate counts only if it names one of the state's answers and says how to reverse it.
    """
    assert state.default is not None
    table_default = {"answer": state.default.answer, "reverse": state.default.reverse}
    for source, candidate in (("policy", policy), ("item", item_default)):
        if (
            isinstance(candidate, Mapping)
            and candidate.get("answer") in state.next
            and isinstance(candidate.get("reverse"), str)
            and candidate["reverse"].strip()
        ):
            return source, candidate
    return "table", table_default  # the loader checked that this one qualifies


async def _outcome_input(
    ctx: Context, state: str, attempt: int, deadline: datetime | None
) -> Payload | None:
    """The next outcome input for this dispatch of `state`, or nothing once the deadline passes."""
    while True:
        remaining = None if deadline is None else deadline - ctx.now()
        if remaining is not None and remaining <= timedelta(0):
            return None
        try:
            received = await ctx.wait_signal(INPUT_SIGNAL, timeout=remaining)
        except TimeoutError:
            return None
        if (
            isinstance(received, Mapping)
            and received.get("kind") == "outcome"
            and received.get("state") == state
            and received.get("attempt") in (None, attempt)
        ):
            return received


async def item_workflow(ctx: Context, arg: Any) -> dict[str, Any]:
    table = load(arg["table"])
    item, tenant, tier = arg["item"], arg["tenant"], arg["risk_tier"]
    item_default: Payload | None = arg.get("decision_default")

    state = table.state(table.initial)
    origin: State | None = None
    detail: dict[str, Any] = {}
    retries_used: dict[str, int] = {}
    findings: list[str] = []
    attempt: dict[str, int] = {}
    # How the item came to enter `state`; written into the transition event.
    move: dict[str, Any] = {"from_state": None, "cause": "start"}
    sequence = 0

    while True:
        entered = ctx.now()
        sequence += 1
        await ctx.step(
            RECORD_STEP,
            {
                "item": item,
                "tenant": tenant,
                "sequence": sequence,
                "state": state.name,
                "owner": state.owner,
                "limit": state.limit.text if state.limit else None,
                "reason": state.reason,
                "entered_at": entered.isoformat(),
                "outcome": None,
                "default": None,
                "action": None,
                "decision": None,
                **move,
            },
        )
        if state.terminal:
            return {"item": item, "tenant": tenant, "state": state.name, "transitions": sequence}
        declared_limit, default = state.limit, state.default
        assert declared_limit is not None and default is not None
        attempt[state.name] = attempt.get(state.name, 0) + 1

        if state.decision:
            question = {
                "item": item,
                "tenant": tenant,
                "state": origin.name if origin else None,
                "cause": move["cause"],
                "outcome": move.get("outcome"),
                "default": move.get("default"),
                "action": move.get("action"),
                "detail": detail,
            }
            try:
                reply = await ctx.step(DECIDE_STEP, question)
            except (StepFailed, LimitPassed):
                reply = None
            source, candidate = _answer(state, reply, item_default)
            answer = candidate["answer"]
            target = state.next[answer]
            if isinstance(candidate.get("detail"), Mapping):
                detail = dict(candidate["detail"])
            # A decision starts progress over: the findings seen before it no longer count.
            findings.clear()
            move = {
                "from_state": state.name,
                "cause": "decision",
                "decision": {
                    "question": question,
                    "answer": answer,
                    "reverse": candidate["reverse"],
                    "source": source,
                },
            }
            resumed = origin if origin is not None else table.state(table.initial)
            state = resumed if target == ORIGIN else table.state(target)
            continue

        passed = False
        limit = _limit_for(state, tier, detail)
        if declared_limit.kind == "repeat-finding":
            finding = str(detail.get("finding", ""))
            passed = finding in findings
            findings.append(finding)
        outcome: str | None = None
        cause = "limit"
        if not passed:
            call = {
                "item": item,
                "tenant": tenant,
                "state": state.name,
                "owner": state.owner,
                "attempt": attempt[state.name],
                "cause": move["cause"],
                "action": move.get("action"),
                "detail": detail,
            }
            reply = None
            try:
                reply = await ctx.step(OWNER_STEP, call, limit=limit)
            except LimitPassed:
                passed = True
            except StepFailed:
                passed, cause = True, "owner-failed"
            if not passed:
                if not (isinstance(reply, Mapping) and reply.get("outcome") is not None):
                    reply = await _outcome_input(
                        ctx,
                        state.name,
                        attempt[state.name],
                        None if limit is None else entered + limit,
                    )
                if reply is None:
                    passed = True
                else:
                    outcome = str(reply["outcome"])
                    if isinstance(reply.get("detail"), Mapping):
                        detail = dict(reply["detail"])
                    if outcome not in state.next:
                        passed, cause = True, "unknown-outcome"

        origin = state
        if passed:
            move = {
                "from_state": state.name,
                "cause": cause,
                "outcome": outcome,
                "default": default.text,
                "action": default.action,
            }
            state = table.state(_apply_default(state, default, retries_used))
        else:
            assert outcome is not None
            retries_used.pop(state.name, None)
            move = {"from_state": state.name, "cause": "outcome", "outcome": outcome}
            state = table.state(state.next[outcome])
