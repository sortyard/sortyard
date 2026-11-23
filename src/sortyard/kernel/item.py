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

Nothing an owner, the decision service or a signal sends can stop the workflow: a reply that is
not understood counts as no reply, and the limit and its default still apply. Two rules keep an
item from spinning between rounds with no timer:

- An outcome the state does not know is not acted on at once. The item stays until the limit
  passes, then takes the default. So an owner that keeps answering nonsense is dispatched once
  per limit, not in a loop.
- A decision that repeats (the same question, straight after it got the same answer) does not
  give that answer again. It gives the table's `on-repeat` answer, which leads to a wait on a
  named need: "a different answer". That is a stop on evidence of repetition, not on a count.

Nothing outside the workflow changes an item's state. A person or an agent who wants a change
sends a request (`send_request`); the workflow takes the item to its decision state with the
request as the question, and the decision service answers it like any other decision.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from sortyard.engine import Context, Engine, LimitPassed, Registry, StepFailed
from sortyard.kernel.states import (
    ORIGIN,
    Default,
    State,
    StateTable,
    from_record,
    parse_duration,
    shipped,
    to_record,
)

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
    registry: Registry,
    *,
    owners: Mapping[str, Owner],
    decide: Decide,
    record: Record,
    table: StateTable | None = None,
) -> None:
    """Put the item workflow and its three steps on a worker's registry.

    `owners` maps an owner name from the state table to the function that does that owner's
    work. It gets the call (item, tenant, state, owner, dispatch, attempt, cause, action,
    detail) and returns `{"outcome": ..., "detail": {...}}`, or nothing when the outcome will
    arrive as an input. `decide` gets the question and returns `{"answer": ..., "reverse":
    ...}` or nothing. `record` gets every transition event and must persist it; the item does
    not move on until it has. It may be called more than once for a transition; the item and
    the event's sequence identify it.

    Every owner `table` names (the shipped table unless given) must be in `owners`: a worker
    that cannot do a state's work is refused here, not found out by an item waiting in it.
    """
    table = table or shipped()
    missing = sorted(
        {state.owner for state in table.states.values() if state.owner and not state.decision}
        - set(owners)
    )
    if missing:
        raise ValueError(f"no owner registered for {missing}")

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


def _is_answer(candidate: Any, state: State) -> bool:
    """A decision answer counts only if it names one of the state's answers and says how to
    reverse it."""
    if not isinstance(candidate, Mapping):
        return False
    answer, reverse = candidate.get("answer"), candidate.get("reverse")
    return (
        isinstance(answer, str)
        and answer in state.next
        and isinstance(reverse, str)
        and bool(reverse.strip())
    )


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

    The item runs on `table` (the shipped one unless given) for its whole life, as checked
    now. `decision_default` is the item's own answer for decisions policy does not cover:
    `{"answer": ..., "reverse": ...}`; one that no decision state of the table could give is
    refused here.
    """
    table = table or shipped()
    for state in table.states.values():
        if state.limit and state.limit.by_tier and risk_tier not in state.limit.by_tier:
            raise ValueError(f"state {state.name!r} has no limit for risk tier {risk_tier!r}")
    decisions = [state for state in table.states.values() if state.decision]
    if decision_default is not None and not any(
        _is_answer(decision_default, state) for state in decisions
    ):
        raise ValueError("decision_default must name an answer of the table and how to reverse it")
    identifier = workflow_id(tenant, item)
    await engine.start(
        ITEM_WORKFLOW,
        identifier,
        {
            "item": item,
            "tenant": tenant,
            "risk_tier": risk_tier,
            "table": to_record(table),
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
    dispatch: int | None = None,
) -> None:
    """Report an owner's outcome for the state the item is in.

    An outcome for another state is ignored, and so is one that arrived before the item
    entered the state. Pass the `dispatch` number the owner was called with to have a late
    report from an earlier stay in the same state ignored too.
    """
    await engine.signal(
        identifier,
        INPUT_SIGNAL,
        {
            "kind": "outcome",
            "state": state,
            "dispatch": dispatch,
            "outcome": outcome,
            "detail": dict(detail or {}),
        },
    )


async def send_request(
    engine: Engine,
    identifier: str,
    *,
    request_id: str,
    answer: str,
    reason: str,
    by: Payload,
) -> None:
    """Ask the item's workflow for a change: that its next decision be `answer`.

    The request is a question, not a write. The workflow takes the item to its decision state
    and the decision service answers; the request, the answer and its source are recorded.
    """
    await engine.signal(
        identifier,
        INPUT_SIGNAL,
        {
            "kind": "request",
            "request": {"id": request_id, "answer": answer, "reason": reason, "by": dict(by)},
        },
    )


def _request(received: Any) -> dict[str, Any] | None:
    """The request an input carries, if it is one the workflow can read."""
    if not isinstance(received, Mapping) or received.get("kind") != "request":
        return None
    request = received.get("request")
    if not isinstance(request, Mapping) or not isinstance(request.get("answer"), str):
        return None
    return dict(request)


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
    """The time the item may stay in `state`: none only for a queue."""
    limit = state.limit
    assert limit is not None
    if limit.by_tier:  # by risk tier, and the time bound of repeat-finding
        return limit.by_tier.get(tier) or min(limit.by_tier.values())
    if limit.kind == "by-need":
        try:
            return parse_duration(str(detail.get("limit")))
        except ValueError:
            return limit.duration
    return limit.duration


def _outcome(reply: Any) -> tuple[str, dict[str, Any]] | None:
    """The outcome and detail of an owner's reply or an outcome input, if it carries one."""
    if not isinstance(reply, Mapping) or not isinstance(reply.get("outcome"), str):
        return None
    detail = reply.get("detail")
    return reply["outcome"], dict(detail) if isinstance(detail, Mapping) else {}


REQUESTED = "@request"


async def _outcome_input(
    ctx: Context, state: State, dispatch: int, deadline: datetime | None, take_requests: bool
) -> tuple[str, dict[str, Any]] | None:
    """The next outcome input the state knows, for this stay; nothing once the deadline passes.

    Inputs for another state or another stay, inputs that are not understood and outcomes the
    state does not know are passed over: the item keeps waiting, inside its limit. A request
    ends the wait too, when the table has a decision state to put it to: it comes back as
    (`REQUESTED`, the request).
    """
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
            and received.get("state") == state.name
            and received.get("dispatch") in (None, dispatch)
        ):
            outcome = _outcome(received)
            if outcome is not None and outcome[0] in state.next:
                return outcome
        request = _request(received) if take_requests else None
        if request is not None:
            return REQUESTED, request


async def item_workflow(ctx: Context, arg: Any) -> dict[str, Any]:
    table = from_record(arg["table"])
    item, tenant, tier = arg["item"], arg["tenant"], arg["risk_tier"]
    item_default: Any = arg.get("decision_default")

    state = table.state(table.initial)
    origin: State | None = None
    detail: dict[str, Any] = {}
    retries_used: dict[str, int] = {}
    findings: list[str] = []
    attempt: dict[str, int] = {}
    # The last decision: what was asked and what was answered. Cleared when an owner's
    # outcome moves the item on, so only a decision that comes straight back repeats.
    last_decision: list[Any] | None = None
    # How the item came to enter `state`; written into the transition event.
    move: dict[str, Any] = {"from_state": None, "from_kind": None, "cause": "start"}
    sequence = 0
    # Requests that arrived while the item was not waiting for input, oldest first.
    requests: list[dict[str, Any]] = []
    deciders = [candidate for candidate in table.states.values() if candidate.decision]

    while True:
        entered = ctx.now()
        sequence += 1
        attempt[state.name] = attempt.get(state.name, 0) + 1
        limit = None if state.terminal or state.decision else _limit_for(state, tier, detail)
        deadline = None if limit is None else entered + limit
        # Whatever outcome arrived before now answers an earlier stay, not this one. A request
        # is not tied to a stay: it is kept.
        for received in ctx.drain_signals(INPUT_SIGNAL):
            request = _request(received)
            if request is not None:
                requests.append(request)
        await ctx.step(
            RECORD_STEP,
            {
                "item": item,
                "tenant": tenant,
                "sequence": sequence,
                "state": state.name,
                "state_kind": state.kind,
                "owner": state.owner,
                "limit": state.limit.text if state.limit else None,
                "limit_seconds": None if limit is None else limit.total_seconds(),
                "deadline": None if deadline is None else deadline.isoformat(),
                "reason": state.reason,
                "attempt": attempt[state.name],
                "detail": detail,
                "entered_at": entered.isoformat(),
                "outcome": None,
                "default": None,
                "action": None,
                "decision": None,
                "request": None,
                **move,
            },
        )
        if state.terminal:
            return {"item": item, "tenant": tenant, "state": state.name, "transitions": sequence}
        declared_limit, default = state.limit, state.default
        assert declared_limit is not None and default is not None
        here = {"from_state": state.name, "from_kind": state.kind}

        if state.decision:
            question = {
                "item": item,
                "tenant": tenant,
                "state": origin.name if origin else None,
                "cause": move["cause"],
                "outcome": move.get("outcome"),
                "default": move.get("default"),
                "action": move.get("action"),
                "request": move.get("request"),
                "detail": detail,
            }
            try:
                reply = await ctx.step(DECIDE_STEP, question)
            except (StepFailed, LimitPassed):
                reply = None
            candidates: list[tuple[str, Any]] = [
                ("policy", reply),
                ("item", item_default),
                # The loader checked that the table's own default qualifies.
                ("table", {"answer": default.answer, "reverse": default.reverse}),
            ]
            source, chosen = next(c for c in candidates if _is_answer(c[1], state))
            answer: str = chosen["answer"]
            reverse: str = chosen["reverse"]
            asked = [question["state"], question["cause"], question["outcome"], detail]
            # A request is a deliberate act, paced by whoever sends it: never a repetition.
            if question["cause"] != "request" and last_decision == [*asked, answer]:
                # The same question, straight after the same answer: giving it again would
                # go round again. Wait on a named need instead: a different answer.
                assert default.on_repeat is not None
                source, answer = "repeat", default.on_repeat
                reverse = "Close the need, or send the item a decision with a different answer."
                detail = {"need": "a-different-answer", "question": question}
            elif isinstance(chosen.get("detail"), Mapping):
                detail = dict(chosen["detail"])
            last_decision = [*asked, answer]
            # A decision starts progress over: the findings seen before it no longer count.
            findings.clear()
            target = state.next[answer]
            move = {
                **here,
                "cause": "decision",
                "decision": {
                    "question": question,
                    "answer": answer,
                    "reverse": reverse,
                    "source": source,
                },
            }
            resumed = origin if origin is not None else table.state(table.initial)
            state = resumed if target == ORIGIN else table.state(target)
            continue

        if requests and deciders:
            # A request waiting from before: put it to the decision before any work is
            # dispatched for this stay.
            origin = state
            move = {**here, "cause": "request", "request": requests.pop(0)}
            state = deciders[0]
            continue

        # Evidence of repetition: the item enters with a finding it entered with before.
        repeated = False
        if declared_limit.kind == "repeat-finding" and isinstance(detail.get("finding"), str):
            repeated = detail["finding"] in findings
            findings.append(detail["finding"])

        outcome: tuple[str, dict[str, Any]] | None = None
        cause, unknown = "limit", None
        if not repeated:
            call = {
                "item": item,
                "tenant": tenant,
                "state": state.name,
                "owner": state.owner,
                "dispatch": sequence,
                "attempt": attempt[state.name],
                "cause": move["cause"],
                "action": move.get("action"),
                "detail": detail,
            }
            answered = True
            reply = None
            try:
                reply = await ctx.step(
                    OWNER_STEP, call, limit=None if deadline is None else deadline - ctx.now()
                )
            except LimitPassed:
                answered = False
            except StepFailed:
                answered, cause = False, "owner-failed"
            if answered:
                outcome = _outcome(reply)
                if outcome is not None and outcome[0] not in state.next:
                    # Not an outcome this state has. Keep it for the record and wait out the
                    # limit for one that is.
                    cause, unknown, outcome = "unknown-outcome", outcome[0], None
                if outcome is None:
                    outcome = await _outcome_input(ctx, state, sequence, deadline, bool(deciders))

        origin = state
        if outcome is not None and outcome[0] == REQUESTED:
            move = {**here, "cause": "request", "request": outcome[1]}
            state = deciders[0]
            continue
        if outcome is None:
            move = {
                **here,
                "cause": cause,
                "outcome": unknown,
                "default": default.text,
                "action": default.action,
            }
            state = table.state(_apply_default(state, default, retries_used))
        else:
            retries_used.pop(state.name, None)
            move = {**here, "cause": "outcome", "outcome": outcome[0]}
            detail = outcome[1]
            state = table.state(state.next[outcome[0]])
            if not state.decision:
                last_decision = None
