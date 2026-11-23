"""Acceptance (SY-V3-STATE-TABLE): the state table cannot declare a state that stalls.

The loader is the rule: these tests feed it the shipped table with one thing broken and expect
it to refuse, naming the state. The shipped table itself is held to HARNESS-V3 section 3.1.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

from sortyard.kernel.states import (
    StateTableError,
    from_record,
    load,
    parse_duration,
    shipped,
    shipped_text,
    to_record,
)

# The item states of HARNESS-V3 section 3.1 and the owner the design gives each.
SECTION_3_1 = {
    "admitted": "scheduler",
    "preflight": "capability-checker",
    "building": "executor",
    "checking": "ci-adapter",
    "reviewing": "reviewer",
    "fixing": "executor",
    "merging": "merge-adapter",
    "waiting": "need",
    "decision": "decision-service",
    "merged": None,
}


def section(text: str, state: str) -> tuple[int, int]:
    """Where `[states.<state>]` starts and ends in the table text."""
    start = text.index(f"[states.{state}]")
    following = text.find("\n[", start + 1)
    return start, len(text) if following == -1 else following


def without(text: str, state: str, key: str) -> str:
    """The table with one key removed from one state."""
    start, end = section(text, state)
    body, count = re.subn(rf"(?m)^{key} = .*\n", "", text[start:end])
    assert count == 1, f"{state} has no {key} line to remove"
    return text[:start] + body + text[end:]


def replaced(text: str, state: str, key: str, value: str) -> str:
    return without(text, state, key).replace(
        f"[states.{state}]\n", f"[states.{state}]\n{key} = {value}\n"
    )


@pytest.mark.parametrize("key", ["owner", "limit", "default", "reason"])
@pytest.mark.parametrize("state", ["building", "admitted", "decision", "waiting"])
def test_loading_fails_for_a_state_without_owner_limit_default_or_reason(
    state: str, key: str
) -> None:
    """Loading fails for a state without owner, limit, default or reason."""
    with pytest.raises(StateTableError, match=rf"state '{state}': has no {key}"):
        load(without(shipped_text(), state, key))


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("owner", '""', "has no owner"),
        ("owner", '"  "', "has no owner"),
        ("limit", '""', "limit must be"),
        ("limit", '"soon"', "not a duration"),
        ("limit", '"0m"', "not a duration"),
        ("limit", '"99999999999d"', "not a duration"),
        ("limit", '"99999d"', "longer than ten years"),
        (
            "limit",
            '{ by = "repeat-finding", low = "1h" }',
            "needs a default that moves the item on",
        ),
        ("limit", '"none"', "only a queue state"),
        ("limit", '"same-pass"', "only a decision state"),
        ("limit", '{ by = "risk-tier" }', "a limit table is"),
        ("default", '"none"', "only a queue state"),
        ("default", "{}", "default must be"),
        ("default", '{ to = "nowhere" }', "leads to 'nowhere', which is not a state"),
        ("default", '{ retry = 0, then = "decision" }', "at least 1"),
        ("default", '{ to = "decision", redispatch = true }', "exactly one of"),
        ("reason", '"because"', "is not declared in \\[reasons\\]"),
        ("next", "{}", "has no exit"),
        ("next", '{ built = "@origin" }', "only a decision state"),
    ],
)
def test_loading_fails_for_a_field_that_is_present_but_says_nothing(
    key: str, value: str, message: str
) -> None:
    with pytest.raises(StateTableError, match=f"state 'building': .*{message}"):
        load(replaced(shipped_text(), "building", key, value))


def test_loading_fails_for_a_blocked_state_and_for_a_state_with_no_way_out() -> None:
    blocked = """
[states.{name}]
owner = "nobody"
limit = "1h"
default = {{ to = "decision" }}
reason = "queued"
next = {{ unblocked = "building" }}
"""
    for name in ("blocked", "Blocked", "BLOCKED"):
        with pytest.raises(StateTableError, match="there is no blocked state"):
            load(shipped_text() + blocked.format(name=name))

    # Not called blocked, but it is: its only moves lead back to itself.
    parked = """
[states.parked]
owner = "nobody"
limit = "1h"
default = { redispatch = true }
reason = "queued"
next = { again = "parked" }
"""
    with pytest.raises(StateTableError, match="state 'parked': has no exit"):
        load(shipped_text() + parked)

    # A terminal state ends the item; it cannot also be a place to wait.
    with pytest.raises(StateTableError, match="state 'merged': a terminal state"):
        load(replaced(shipped_text(), "merged", "reason", '"done"\nowner = "nobody"'))

    # A decision answers in its own pass: it cannot hand the item to another decision.
    second = """
[states.appeal]
decision = true
owner = "decision-service"
limit = "same-pass"
default = { answer = "rebuild", reverse = "Decide again.", on-repeat = "escalate" }
reason = "decision-required"
next = { rebuild = "building", escalate = "decision" }
"""
    with pytest.raises(StateTableError, match="cannot lead to a decision"):
        load(shipped_text() + second)

    with pytest.raises(StateTableError, match="exactly one state must be initial"):
        load(without(shipped_text(), "admitted", "initial"))
    answer = '{ answer = "resume", reverse = "%s", on-repeat = "%s" }'
    with pytest.raises(StateTableError, match="a default answer needs"):
        load(replaced(shipped_text(), "decision", "default", answer % ("", "wait")))
    # A decision that repeats must lead to a wait on a named need, which always has a limit.
    with pytest.raises(StateTableError, match="on-repeat must lead to a wait on a named need"):
        load(replaced(shipped_text(), "decision", "default", answer % ("Undo it.", "rebuild")))
    with pytest.raises(StateTableError, match="on-repeat must lead to a wait on a named need"):
        load(replaced(shipped_text(), "decision", "default", answer % ("Undo it.", "resume")))
    with pytest.raises(StateTableError, match="on-repeat answer 'ask' is not one of its answers"):
        load(replaced(shipped_text(), "decision", "default", answer % ("Undo it.", "ask")))

    # A state nothing leads to is not part of the machine.
    island = """
[states.island]
owner = "nobody"
limit = "1h"
default = { to = "decision" }
reason = "queued"
next = { rescued = "building" }
"""
    with pytest.raises(StateTableError, match="state 'island': cannot be reached"):
        load(shipped_text() + island)


def test_the_shipped_table_declares_every_section_3_1_state_and_no_blocked_state() -> None:
    """The shipped table declares every section 3.1 state and no blocked state."""
    table = shipped()
    assert {name: state.owner for name, state in table.states.items()} == SECTION_3_1
    assert "blocked" not in {name.lower() for name in table.states}
    assert table.initial == "admitted"
    assert [name for name, state in table.states.items() if state.terminal] == ["merged"]

    for state in table.states.values():
        assert state.reason in table.reasons
        if state.terminal:
            continue
        assert state.owner and state.limit and state.default and state.next, state.name

    # The limits and defaults section 3.1 states.
    def limit(name: str) -> timedelta | None:
        declared = table.state(name).limit
        assert declared is not None
        return declared.duration

    def default(name: str) -> tuple[str, str | None, int]:
        declared = table.state(name).default
        assert declared is not None
        return declared.kind, declared.to, declared.retries

    assert limit("checking") == timedelta(minutes=10)
    assert limit("reviewing") == timedelta(minutes=30)
    assert limit("merging") == timedelta(minutes=30)
    assert default("preflight") == ("to", "waiting", 0)
    assert default("building") == ("retry", "decision", 1)
    assert default("checking") == ("retry", "decision", 1)
    assert default("reviewing") == ("redispatch", None, 0)
    assert default("fixing") == ("to", "decision", 0)
    assert default("merging") == ("redispatch", None, 0)
    assert default("waiting") == ("to", "decision", 0)
    building, fixing, waiting = (table.state(n).limit for n in ("building", "fixing", "waiting"))
    assert building is not None and set(building.by_tier) == {"low", "medium", "high"}
    assert fixing is not None and fixing.kind == "repeat-finding"
    assert set(fixing.by_tier) == {"low", "medium", "high"}  # bounded by time as well
    assert waiting is not None and waiting.kind == "by-need"

    # The decision state answers in the same pass, and its own default says how to reverse it.
    decision = table.state("decision")
    assert decision.limit is not None and decision.limit.kind == "same-pass"
    assert decision.default is not None and decision.default.answer in decision.next
    assert decision.default.reverse
    assert decision.default.on_repeat == "wait" and decision.next["wait"] == "waiting"
    assert [state.kind for state in table.states.values()] == [
        *["queue", "work", "work", "work", "work", "work", "work", "need", "decision"],
        "terminal",
    ]


def test_a_table_survives_the_trip_into_a_workflow_and_back() -> None:
    """An item keeps the table it was checked with: the record rebuilds it without the loader."""
    table = shipped()
    rebuilt = from_record(to_record(table))
    assert rebuilt.states == table.states
    assert (rebuilt.version, rebuilt.initial, rebuilt.reasons) == (
        table.version,
        table.initial,
        table.reasons,
    )


def test_a_queue_state_has_no_limit_and_reports_its_age_instead() -> None:
    admitted = shipped().state("admitted")
    assert admitted.queue and admitted.limit is not None and admitted.limit.kind == "none"
    assert admitted.default is not None and admitted.default.kind == "none"
    # A queue still has an owner, a reason and an exit.
    assert admitted.owner == "scheduler" and admitted.reason == "queued" and admitted.next
    # Declaring a queue with a limit, or a limit of none without a queue, is refused both ways.
    with pytest.raises(StateTableError, match="only a queue state"):
        load(replaced(shipped_text(), "admitted", "limit", '"1h"'))


def test_durations() -> None:
    assert parse_duration("90s") == timedelta(seconds=90)
    assert parse_duration("7d") == timedelta(days=7)
    for bad in ("", "10", "m", "1.5h", "-5m", "0s", "5 m", "99999999999d", "3651d"):
        with pytest.raises(ValueError, match="not a duration"):
            parse_duration(bad)
