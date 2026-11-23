"""Preflight: every need of a task is exercised before any build is dispatched (HARNESS-V3 3.3).

The state table gives `preflight` to the owner `capability-checker` and `waiting` to the owner
`need`. This module is those two owners and what they stand on; the generic item workflow is
unchanged.

- `Preflight.check` (the capability-checker) looks up the item's lane and declared needs, runs
  one probe per need, records each result, and answers `ready` only when every probe passed.
  When one fails it opens a capability-gap item for the lane's declared resolver, naming the
  need and the probe's output, or links the item to the gap item already open for that need,
  and answers `gap`: the item goes to `waiting` and no build is dispatched.
- `Preflight.wait` (the need) takes the wait: its outcome arrives when the gap item closes.
- `close_gap` closes a gap item and sends `closed` to every item linked to it, so each returns
  to preflight and is probed again, with no hand action.

A probe is an interface (`Probe`); the real GitHub, secret-store and cluster probes are adapters
outside this module. Gap items live behind `GapRegistry`; `InMemoryGapRegistry` is the
implementation here and holds the rule that a need has at most one open gap item.

What cannot be exercised does not pass. A need the lane does not declare, a need that cannot be
read, a probe that raises and a probe that returns something other than a `ProbeResult` are all
failed results, so each ends in a gap item with a resolver and never in a build.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from sortyard.engine import Engine, WorkflowNotFound
from sortyard.kernel.capabilities import KINDS, CapabilityError, Lane, Need
from sortyard.kernel.item import Owner, Payload, send_outcome, workflow_id

CHECKER_OWNER = "capability-checker"
NEED_OWNER = "need"
WAITING_STATE = "waiting"
# The action the state table hands the need's owner when preflight ran out of its limit.
OPEN_GAP_ACTION = "open-capability-gap"
# The need named by the gap item opened then: the preflight itself did not answer.
PREFLIGHT_NEED = "preflight"


@dataclass(frozen=True)
class ProbeResult:
    """What one probe found. `output` is what the probe saw, for whoever resolves a failure.

    The output is written into the gap item and the item's record: a probe never puts a secret's
    value in it.
    """

    passed: bool
    output: str = ""


class Probe(Protocol):
    """Exercises one need of a lane: push a scratch ref, read the named secret, call the API."""

    def __call__(self, need: Need, lane: Lane) -> ProbeResult: ...


@dataclass(frozen=True)
class ProbeRecord:
    """One probe result for one dispatch of one item's preflight."""

    tenant: str
    item: str
    lane: str
    dispatch: int
    need: str
    passed: bool
    output: str

    def to_record(self) -> dict[str, Any]:
        return {"need": self.need, "passed": self.passed, "output": self.output}


# Gets every probe result as it is made. It may be called again for the same result when the
# engine retries the owner step; tenant, item, dispatch and need identify it.
ResultSink = Callable[[ProbeRecord], None]


@dataclass(frozen=True)
class TaskNeeds:
    """An item's lane and the needs its task lists against the lane's capability file."""

    lane: Lane
    needs: tuple[str, ...] = ()


# From (tenant, item) to the item's lane and declared needs.
NeedsLookup = Callable[[str, str], TaskNeeds]


@dataclass(frozen=True)
class GapItem:
    """A capability-gap item: one failed need of one lane, for its declared resolver.

    `output` is the probe output that opened it. `items` are the work items linked to it, in
    the order they were linked; they return to preflight when it closes.
    """

    id: str
    tenant: str
    lane: str
    need: str
    resolver: str
    output: str
    items: tuple[str, ...]
    open: bool = True


class GapRegistry(Protocol):
    """Where capability-gap items live.

    An implementation guarantees, under concurrent calls, that a (tenant, lane, need) has at
    most one open gap item and that linking is atomic with the open-or-find.
    """

    def open_or_link(
        self, *, tenant: str, lane: str, need: str, resolver: str, output: str, item: str
    ) -> GapItem:
        """Link `item` to the open gap item for the need, opening one if there is none."""
        ...

    def get(self, gap_id: str) -> GapItem:
        """The gap item, or `KeyError`."""
        ...

    def close(self, gap_id: str) -> GapItem:
        """Close the gap item and return it as closed. Closing a closed one changes nothing."""
        ...


class InMemoryGapRegistry:
    """`GapRegistry` in one process's memory, safe to call from many threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gaps: dict[str, GapItem] = {}
        self._open: dict[tuple[str, str, str], str] = {}

    def open_or_link(
        self, *, tenant: str, lane: str, need: str, resolver: str, output: str, item: str
    ) -> GapItem:
        key = (tenant, lane, need)
        with self._lock:
            gap_id = self._open.get(key)
            if gap_id is None:
                gap_id = f"gap-{len(self._gaps) + 1}"
                gap = GapItem(gap_id, tenant, lane, need, resolver, output, (item,))
                self._open[key] = gap_id
            else:
                gap = self._gaps[gap_id]
                if item not in gap.items:
                    gap = replace(gap, items=(*gap.items, item))
            self._gaps[gap_id] = gap
            return gap

    def get(self, gap_id: str) -> GapItem:
        with self._lock:
            return self._gaps[gap_id]

    def close(self, gap_id: str) -> GapItem:
        with self._lock:
            gap = self._gaps[gap_id]
            if gap.open:
                gap = replace(gap, open=False)
                self._gaps[gap_id] = gap
                del self._open[(gap.tenant, gap.lane, gap.need)]
            return gap

    def all(self) -> tuple[GapItem, ...]:
        """Every gap item, open and closed, in the order they were opened."""
        with self._lock:
            return tuple(self._gaps.values())


class Preflight:
    """The `capability-checker` and `need` owners.

    `lookup` gives an item's lane and declared needs. `probes` has one probe per kind of need
    (`sortyard.kernel.capabilities.KINDS`); a checker that cannot exercise a kind is refused
    here, not found out by an item. `gaps` is where gap items are opened. `sink`, when given,
    gets every probe result; every result is also returned in the outcome's detail, which the
    item workflow records with the transition.
    """

    def __init__(
        self,
        *,
        lookup: NeedsLookup,
        probes: Mapping[str, Probe],
        gaps: GapRegistry,
        sink: ResultSink | None = None,
    ) -> None:
        missing = sorted(set(KINDS) - set(probes))
        if missing:
            raise ValueError(f"no probe for {missing}")
        self._lookup = lookup
        self._probes = dict(probes)
        self._gaps = gaps
        self._sink = sink

    def owners(self) -> dict[str, Owner]:
        """The two owners by the names the state table gives them, for `item.register`."""
        return {CHECKER_OWNER: self.check, NEED_OWNER: self.wait}

    def _probe(self, text: str, lane: Lane) -> ProbeResult:
        """Exercise the need `text` names; anything short of a passing result is a failure."""
        try:
            need = lane.check(text)
        except CapabilityError as error:
            return ProbeResult(False, str(error))
        try:
            result = self._probes[need.kind](need, lane)
        except Exception as error:
            return ProbeResult(False, f"the probe raised {type(error).__name__}: {error}")
        if not isinstance(result, ProbeResult) or not isinstance(result.passed, bool):
            return ProbeResult(False, f"the probe returned no result: {result!r}")
        return ProbeResult(result.passed, str(result.output))

    def check(self, call: Payload) -> Payload:
        """The capability-checker: one probe per need; `ready`, or `gap` and no build."""
        tenant, item = str(call["tenant"]), str(call["item"])
        task = self._lookup(tenant, item)
        lane = task.lane
        # The lane's defaults, then the task's own needs, each once. A task need is kept as
        # the text the task gave, so one the lane does not declare is still named in its gap.
        texts = dict.fromkeys([need.text for need in lane.defaults])
        for listed in task.needs:
            texts.setdefault(listed if isinstance(listed, str) else repr(listed))
        records: list[ProbeRecord] = []
        for text in texts:
            result = self._probe(text, lane)
            record = ProbeRecord(
                tenant, item, lane.name, int(call["dispatch"]), text, result.passed, result.output
            )
            if self._sink is not None:
                self._sink(record)
            records.append(record)
        detail: dict[str, Any] = {
            "lane": lane.name,
            "probes": [record.to_record() for record in records],
        }
        failed = [record for record in records if not record.passed]
        if not failed:
            return {"outcome": "ready", "detail": detail}
        opened = [
            self._gaps.open_or_link(
                tenant=tenant,
                lane=lane.name,
                need=record.need,
                resolver=lane.resolver,
                output=record.output,
                item=item,
            )
            for record in failed
        ]
        detail.update(
            need=failed[0].need,
            needs=[record.need for record in failed],
            gaps=[gap.id for gap in opened],
            resolver=lane.resolver,
        )
        if lane.gap_limit_text is not None:
            detail["limit"] = lane.gap_limit_text  # the need sets the limit of the wait
        return {"outcome": "gap", "detail": detail}

    def wait(self, call: Payload) -> Payload | None:
        """The need: the item waits; `closed` arrives from `close_gap`.

        Two cases answer here. A gap item the item waits on closed before the item reached the
        wait: its `closed` was sent too early to be read, so the answer is given now. And
        preflight ran out of its limit, so no probe result names a need: a gap item naming the
        preflight itself is opened for the lane's resolver and the item waits on that.
        """
        detail = call.get("detail")
        waits_on = detail.get("gaps") if isinstance(detail, Mapping) else None
        if isinstance(waits_on, list) and waits_on:
            closed = [gap_id for gap_id in waits_on if self._closed(gap_id)]
            return {"outcome": "closed", "detail": {"closed_gaps": closed}} if closed else None
        if call.get("action") == OPEN_GAP_ACTION:
            tenant, item = str(call["tenant"]), str(call["item"])
            lane = self._lookup(tenant, item).lane
            self._gaps.open_or_link(
                tenant=tenant,
                lane=lane.name,
                need=PREFLIGHT_NEED,
                resolver=lane.resolver,
                output="the preflight did not finish within its limit",
                item=item,
            )
        return None

    def _closed(self, gap_id: object) -> bool:
        try:
            return isinstance(gap_id, str) and not self._gaps.get(gap_id).open
        except KeyError:
            return False


async def close_gap(engine: Engine, gaps: GapRegistry, gap_id: str) -> GapItem:
    """Close a gap item and send every item linked to it back to preflight.

    Each linked item gets the outcome `closed` for its wait; an item that is not waiting
    ignores it, and one whose workflow has ended is passed over. Safe to call again: closing a
    closed gap item sends the outcome again, which is how a call that failed part-way (the
    engine was unavailable) is finished.
    """
    gap = gaps.close(gap_id)
    for item in gap.items:
        try:
            await send_outcome(
                engine,
                workflow_id(gap.tenant, item),
                state=WAITING_STATE,
                outcome="closed",
                detail={"closed_gaps": [gap.id]},
            )
        except WorkflowNotFound:
            continue
    return gap
