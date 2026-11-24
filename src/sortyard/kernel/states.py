"""The state table: loading and checking it (HARNESS-V3 section 3.1, SY-V3-STATE-TABLE).

The item state machine is data (`item_states.toml`). This module turns that data into typed
values and refuses a table that breaks the zero-stall rule: every state an item can wait in has
an owner, a limit, a default at the limit and a typed reason; no state is called blocked; every
state has an exit and a way to a terminal state. A state that fails those checks cannot be
declared, so the rule needs no sweep to enforce it later.

Loading is a pure function of the text. The item workflow is started with the table's text and
loads it again on every replay, so an item keeps the table it started with while the shipped
file changes under it.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from importlib import resources
from typing import Any

ORIGIN = "@origin"
FORBIDDEN_NAMES = frozenset({"blocked"})
_DURATION = re.compile(r"^(\d{1,9})([smhd])$")
LONGEST = timedelta(days=3650)
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
_STATE_KEYS = frozenset(
    {
        "owner",
        "limit",
        "default",
        "reason",
        "next",
        "initial",
        "queue",
        "decision",
        "terminal",
        "lifecycle",
    }
)
_DEFAULT_KEYS = frozenset(
    {"to", "retry", "then", "redispatch", "answer", "reverse", "on-repeat", "action"}
)


class StateTableError(ValueError):
    """The table breaks a rule. The message names the state and the rule."""


def parse_duration(text: str) -> timedelta:
    """`"90s"`, `"10m"`, `"2h"`, `"7d"`: a positive whole number and one unit."""
    match = _DURATION.match(text)
    if not match or int(match.group(1)) == 0:
        raise ValueError(f"not a duration: {text!r} (use a positive number and s, m, h or d)")
    duration = timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})
    if duration > LONGEST:
        raise ValueError(f"not a duration: {text!r} is longer than ten years")
    return duration


@dataclass(frozen=True)
class Limit:
    """How long an item may stay in a state.

    `kind` is `duration`, `by-risk-tier`, `by-need` (`duration` holds its "otherwise"),
    `repeat-finding` (by progress, with a time bound by risk tier in `by_tier`), `same-pass` or
    `none`. `text` is the limit in words, for records and the tracker view.
    """

    kind: str
    text: str
    duration: timedelta | None = None
    by_tier: Mapping[str, timedelta] = field(default_factory=dict)


@dataclass(frozen=True)
class Default:
    """What happens when the limit passes.

    `kind` is `to` (move to `to`), `retry` (dispatch the owner again `retries` times, then move
    to `to`), `redispatch` (dispatch the owner again), `answer` (decision: `answer` with how to
    `reverse` it; `on_repeat` is the answer given instead when the same question has just
    had the same answer) or `none` (queue).
    """

    kind: str
    text: str
    to: str | None = None
    retries: int = 0
    answer: str | None = None
    reverse: str | None = None
    on_repeat: str | None = None
    action: str | None = None


@dataclass(frozen=True)
class State:
    name: str
    reason: str
    owner: str | None = None
    limit: Limit | None = None
    default: Default | None = None
    next: Mapping[str, str] = field(default_factory=dict)
    initial: bool = False
    queue: bool = False
    decision: bool = False
    terminal: bool = False
    #: The lifecycle kind recorded when an item enters the state, when the table names one.
    lifecycle: str | None = None

    @property
    def kind(self) -> str:
        """What kind of state this is: terminal, decision, queue, need (a wait on a named
        need) or work."""
        if self.terminal:
            return "terminal"
        if self.decision:
            return "decision"
        if self.queue:
            return "queue"
        if self.limit is not None and self.limit.kind == "by-need":
            return "need"
        return "work"


@dataclass(frozen=True)
class StateTable:
    version: int
    reasons: Mapping[str, str]
    states: Mapping[str, State]
    initial: str
    text: str

    def state(self, name: str) -> State:
        return self.states[name]


def _fail(state: str, message: str) -> StateTableError:
    return StateTableError(f"state {state!r}: {message}")


def _limit(name: str, raw: Any) -> Limit:
    if isinstance(raw, Mapping):
        by = raw.get("by")
        rest = {str(key): value for key, value in raw.items() if key != "by"}
        try:
            durations = {key: parse_duration(str(value)) for key, value in rest.items()}
        except ValueError as error:
            raise _fail(name, f"limit: {error}") from None
        text = ", ".join(f"{key} {value}" for key, value in rest.items())
        if by == "risk-tier" and durations:
            return Limit("by-risk-tier", f"by risk tier: {text}", by_tier=durations)
        if by == "repeat-finding" and durations:
            words = f"the same finding twice, or by risk tier: {text}"
            return Limit("repeat-finding", words, by_tier=durations)
        if by == "need" and set(durations) == {"otherwise"}:
            return Limit("by-need", f"set by the need, {text}", duration=durations["otherwise"])
        raise _fail(
            name,
            'a limit table is { by = "risk-tier", <tier> = <duration>, ... }, '
            '{ by = "repeat-finding", <tier> = <duration>, ... } '
            'or { by = "need", otherwise = <duration> }',
        )
    if not isinstance(raw, str) or not raw:
        raise _fail(name, "limit must be a duration, a keyword or a table")
    if raw in ("none", "same-pass"):
        return Limit(raw, raw)
    try:
        return Limit("duration", raw, duration=parse_duration(raw))
    except ValueError as error:
        raise _fail(name, f"limit: {error}") from None


def _default(name: str, raw: Any) -> Default:
    if raw == "none":
        return Default("none", "none")
    if not isinstance(raw, Mapping) or not raw:
        raise _fail(name, 'default must be a table (to, retry/then, redispatch, answer) or "none"')
    unknown = set(raw) - _DEFAULT_KEYS
    if unknown:
        raise _fail(name, f"default has unknown keys {sorted(unknown)}")
    action = raw.get("action")
    if action is not None and (not isinstance(action, str) or not action):
        raise _fail(name, "default action must be a word")
    shape = frozenset(raw) - {"action"}
    suffix = f" ({action})" if action else ""
    if shape == {"to"} and isinstance(raw["to"], str):
        return Default("to", f"to {raw['to']}{suffix}", to=raw["to"], action=action)
    if shape == {"retry", "then"} and isinstance(raw["then"], str):
        retries = raw["retry"]
        if not isinstance(retries, int) or isinstance(retries, bool) or retries < 1:
            raise _fail(name, "default retry must be a whole number of at least 1")
        text = f"retry {retries}, then {raw['then']}{suffix}"
        return Default("retry", text, to=raw["then"], retries=retries, action=action)
    if shape == {"redispatch"} and raw["redispatch"] is True:
        return Default("redispatch", f"redispatch{suffix}", action=action)
    if shape == {"answer", "reverse", "on-repeat"}:
        answer, reverse, on_repeat = raw["answer"], raw["reverse"], raw["on-repeat"]
        if not isinstance(answer, str) or not isinstance(reverse, str) or not reverse.strip():
            raise _fail(name, "a default answer needs the answer and how to reverse it")
        if not isinstance(on_repeat, str):
            raise _fail(name, "on-repeat names the answer given when a decision repeats")
        text = f"answer {answer}; {on_repeat} when it repeats"
        return Default("answer", text, answer=answer, reverse=reverse, on_repeat=on_repeat)
    raise _fail(
        name,
        "default must be exactly one of: to; retry and then; redispatch = true; "
        "answer, reverse and on-repeat",
    )


def _state(name: str, raw: Any, reasons: Mapping[str, str]) -> State:
    if name.strip().lower() in FORBIDDEN_NAMES:
        raise _fail(name, "there is no blocked state; an item waits on a named need or a decision")
    if not isinstance(raw, Mapping):
        raise _fail(name, "must be a table")
    unknown = set(raw) - _STATE_KEYS
    if unknown:
        raise _fail(name, f"unknown keys {sorted(unknown)}")
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason:
        raise _fail(name, "has no reason")
    if reason not in reasons:
        raise _fail(name, f"reason {reason!r} is not declared in [reasons]")
    flags = {key: raw.get(key, False) for key in ("initial", "queue", "decision", "terminal")}
    for key, value in flags.items():
        if not isinstance(value, bool):
            raise _fail(name, f"{key} must be true or false")
    next_raw = raw.get("next", {})
    if not isinstance(next_raw, Mapping) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in next_raw.items()
    ):
        raise _fail(name, "next must map outcomes to state names")
    transitions = dict(next_raw)
    lifecycle = raw.get("lifecycle")
    if lifecycle is not None and (not isinstance(lifecycle, str) or not lifecycle):
        raise _fail(name, "lifecycle names the lifecycle kind of entering the state")

    if flags["terminal"]:
        extra = sorted(set(raw) & {"owner", "limit", "default", "next", "initial", "queue"})
        if extra or flags["decision"]:
            raise _fail(
                name, f"a terminal state ends the item and declares no {extra or 'decision'}"
            )
        return State(name, reason, terminal=True, lifecycle=lifecycle)

    for required in ("owner", "limit", "default"):
        if required not in raw:
            raise _fail(name, f"has no {required}")
    owner = raw["owner"]
    if not isinstance(owner, str) or not owner.strip():
        raise _fail(name, "has no owner")
    limit = _limit(name, raw["limit"])
    default = _default(name, raw["default"])
    if not transitions:
        raise _fail(name, "has no exit: next is empty")

    if (limit.kind == "none") != flags["queue"]:
        raise _fail(name, 'only a queue state (queue = true) has limit "none", and it must')
    if (default.kind == "none") != flags["queue"]:
        raise _fail(name, 'only a queue state has default "none", and it must')
    if (limit.kind == "same-pass") != flags["decision"]:
        raise _fail(name, 'only a decision state has limit "same-pass", and it must')
    if (default.kind == "answer") != flags["decision"]:
        raise _fail(name, "only a decision state has a default answer, and it must")
    if flags["decision"] and default.answer not in transitions:
        raise _fail(name, f"default answer {default.answer!r} is not one of its answers")
    if flags["decision"] and default.on_repeat not in transitions:
        raise _fail(name, f"on-repeat answer {default.on_repeat!r} is not one of its answers")
    if limit.kind == "repeat-finding" and (default.kind != "to" or default.to == name):
        # The limit passes at once when a finding repeats, so a default that stays in the
        # state would spin.
        raise _fail(name, "a repeat-finding limit needs a default that moves the item on (to)")
    if not flags["decision"] and ORIGIN in transitions.values():
        raise _fail(name, f"only a decision state may send an item back to {ORIGIN}")
    if flags["decision"] and (flags["initial"] or flags["queue"]):
        raise _fail(name, "a decision state is neither the initial state nor a queue")
    return State(
        name,
        reason,
        owner=owner,
        limit=limit,
        default=default,
        next=transitions,
        initial=flags["initial"],
        queue=flags["queue"],
        decision=flags["decision"],
        lifecycle=lifecycle,
    )


def _targets(state: State) -> set[str]:
    targets = set(state.next.values())
    if state.default is not None and state.default.to is not None:
        targets.add(state.default.to)
    return targets


def load(text: str) -> StateTable:
    """Parse and check a state table; raise `StateTableError` naming the first broken rule."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise StateTableError(f"not valid TOML: {error}") from None
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise StateTableError("the table has no version number")
    reasons_raw = raw.get("reasons")
    if not isinstance(reasons_raw, Mapping) or not reasons_raw:
        raise StateTableError("the table declares no [reasons]")
    reasons = {str(key): str(value) for key, value in reasons_raw.items()}
    states_raw = raw.get("states")
    if not isinstance(states_raw, Mapping) or not states_raw:
        raise StateTableError("the table declares no states")
    states = {str(name): _state(str(name), body, reasons) for name, body in states_raw.items()}

    initial = [state.name for state in states.values() if state.initial]
    if len(initial) != 1:
        raise StateTableError(f"exactly one state must be initial; found {initial}")
    if not any(state.terminal for state in states.values()):
        raise StateTableError("the table has no terminal state")
    for state in states.values():
        for target in sorted(_targets(state)):
            if target != ORIGIN and target not in states:
                raise _fail(state.name, f"leads to {target!r}, which is not a state")
            if state.decision and target != ORIGIN and states[target].decision:
                raise _fail(
                    state.name, "a decision answers in one pass; it cannot lead to a decision"
                )
        if state.decision:
            # A repeated decision must put a timer between its rounds: its on-repeat answer
            # leads to a wait on a named need, which always has a limit.
            assert state.default is not None and state.default.on_repeat is not None
            repeat_target = state.next[state.default.on_repeat]
            if repeat_target == ORIGIN or states[repeat_target].kind != "need":
                raise _fail(state.name, "on-repeat must lead to a wait on a named need")

    # Every state has a way to a terminal state. A decision's "back to where it came from" is
    # not counted: an exit has to lead somewhere by itself.
    reaches_end = {state.name for state in states.values() if state.terminal}
    grew = True
    while grew:
        grew = False
        for state in states.values():
            if state.name not in reaches_end and _targets(state) & reaches_end:
                reaches_end.add(state.name)
                grew = True
    for state in states.values():
        if state.name not in reaches_end:
            raise _fail(state.name, "has no exit: no path from it reaches a terminal state")

    reachable, frontier = {initial[0]}, [initial[0]]
    while frontier:
        for target in _targets(states[frontier.pop()]):
            if target != ORIGIN and target not in reachable:
                reachable.add(target)
                frontier.append(target)
    for state in states.values():
        if state.name not in reachable:
            raise _fail(state.name, "cannot be reached from the initial state")
    return StateTable(version, reasons, states, initial[0], text)


def to_record(table: StateTable) -> dict[str, Any]:
    """The checked table as plain JSON values, for handing to a workflow.

    A workflow keeps the record it started with and rebuilds the table from it on every replay
    with `from_record`, which checks nothing. So an item is never refused, mid-flight, by rules
    the loader gained after the item started.
    """

    def seconds(value: timedelta | None) -> float | None:
        return None if value is None else value.total_seconds()

    states: dict[str, Any] = {}
    for state in table.states.values():
        limit, default = state.limit, state.default
        states[state.name] = {
            "reason": state.reason,
            "owner": state.owner,
            "next": dict(state.next),
            "initial": state.initial,
            "queue": state.queue,
            "decision": state.decision,
            "terminal": state.terminal,
            "lifecycle": state.lifecycle,
            "limit": limit
            and {
                "kind": limit.kind,
                "text": limit.text,
                "duration": seconds(limit.duration),
                "by_tier": {tier: seconds(value) for tier, value in limit.by_tier.items()},
            },
            "default": default
            and {
                "kind": default.kind,
                "text": default.text,
                "to": default.to,
                "retries": default.retries,
                "answer": default.answer,
                "reverse": default.reverse,
                "on_repeat": default.on_repeat,
                "action": default.action,
            },
        }
    return {
        "version": table.version,
        "initial": table.initial,
        "reasons": dict(table.reasons),
        "states": states,
    }


def from_record(record: Mapping[str, Any]) -> StateTable:
    """Rebuild a table from `to_record`'s output. Nothing is checked: it was, when it was made."""

    def duration(value: float | None) -> timedelta | None:
        return None if value is None else timedelta(seconds=value)

    states: dict[str, State] = {}
    for name, raw in record["states"].items():
        limit, default = raw["limit"], raw["default"]
        states[name] = State(
            name,
            raw["reason"],
            owner=raw["owner"],
            limit=limit
            and Limit(
                limit["kind"],
                limit["text"],
                duration=duration(limit["duration"]),
                by_tier={
                    tier: timedelta(seconds=value) for tier, value in limit["by_tier"].items()
                },
            ),
            default=default and Default(**default),
            next=raw["next"],
            initial=raw["initial"],
            queue=raw["queue"],
            decision=raw["decision"],
            terminal=raw["terminal"],
            lifecycle=raw.get("lifecycle"),
        )
    return StateTable(record["version"], record["reasons"], states, record["initial"], "")


def shipped_text() -> str:
    """The text of the item state table this package ships."""
    return resources.files("sortyard.kernel").joinpath("item_states.toml").read_text()


def shipped() -> StateTable:
    return load(shipped_text())


def merged_states(table: StateTable | None = None) -> list[str]:
    """The states that mean a merged change. Only they clear a blocked_by link; any other
    terminal state (withdrawn) ends the item without that."""
    states = (table or shipped()).states.values()
    return [state.name for state in states if state.lifecycle == "merged"]
