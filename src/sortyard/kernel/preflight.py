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
failed results, so each ends in a gap item with a resolver and never in a build. So does a
lookup of the item's needs that raises: the gap item then names the preflight itself.

What is not known does not hold an item. A gap item the registry does not know counts as
closed: an item waiting on it returns to preflight and is probed again.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection, Mapping
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
# The need named by a gap item when the preflight itself could not be done: it ran out of its
# limit, or the item's lane and needs could not be read.
PREFLIGHT_NEED = "preflight"
# The lane a gap item names when the item's lane could not be read. Not a valid lane name, so
# it cannot be taken for a declared lane.
UNKNOWN_LANE = "(unknown)"
# Who resolves a gap when the lane, and so its declared resolver, could not be read: the
# platform lane, as HARNESS-V3 section 3.3 gives it.
PLATFORM_RESOLVER = "platform"


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
    """Where capability-gap items live, and which of them each work item waits on.

    An implementation guarantees, under concurrent calls, that a (tenant, lane, need) has at
    most one open gap item and that linking is atomic with the open-or-find.
    """

    def open_or_link(
        self, *, tenant: str, lane: str, need: str, resolver: str, output: str, item: str
    ) -> GapItem:
        """Link `item` to the open gap item for the need, opening one if there is none.

        The item then waits on that gap item. Linking an item twice links it once.
        """
        ...

    def get(self, gap_id: str) -> GapItem:
        """The gap item, or `KeyError`."""
        ...

    def close(self, gap_id: str) -> GapItem:
        """Close the gap item and return it as closed, or `KeyError`. Closing a closed one
        changes nothing."""
        ...

    def for_item(self, tenant: str, item: str) -> tuple[GapItem, ...]:
        """The gap items the item waits on, open and closed, in the order it was linked."""
        ...

    def settle(self, tenant: str, item: str, keep: Collection[str] = ()) -> None:
        """The item's preflight answered: it now waits on the gap items `keep` and no others.

        The item is unlinked from every other open gap item, which it no longer needs closed. A
        closed gap item keeps the items it had, as the record of what it held up.
        """
        ...


class InMemoryGapRegistry:
    """`GapRegistry` in one process's memory, safe to call from many threads.

    It does not outlive the process. After a restart no gap item is known, and an unknown gap
    item counts as closed: items waiting on one return to preflight when their wait is next
    dispatched, which is at the latest when its limit passes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gaps: dict[str, GapItem] = {}
        self._open: dict[tuple[str, str, str], str] = {}
        self._waits: dict[tuple[str, str], list[str]] = {}

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
            waits = self._waits.setdefault((tenant, item), [])
            if gap_id not in waits:
                waits.append(gap_id)
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

    def for_item(self, tenant: str, item: str) -> tuple[GapItem, ...]:
        with self._lock:
            return tuple(self._gaps[gap_id] for gap_id in self._waits.get((tenant, item), ()))

    def settle(self, tenant: str, item: str, keep: Collection[str] = ()) -> None:
        with self._lock:
            waits = self._waits.pop((tenant, item), [])
            for gap_id in waits:
                gap = self._gaps[gap_id]
                if gap_id not in keep and gap.open:
                    left = tuple(linked for linked in gap.items if linked != item)
                    self._gaps[gap_id] = replace(gap, items=left)
            kept = [gap_id for gap_id in waits if gap_id in keep]
            if kept:
                self._waits[(tenant, item)] = kept

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
    item workflow records with the transition. `resolver` is who gets a gap item when the
    item's lane, and so the resolver it declares, could not be read.
    """

    def __init__(
        self,
        *,
        lookup: NeedsLookup,
        probes: Mapping[str, Probe],
        gaps: GapRegistry,
        sink: ResultSink | None = None,
        resolver: str = PLATFORM_RESOLVER,
    ) -> None:
        missing = sorted(set(KINDS) - set(probes))
        if missing:
            raise ValueError(f"no probe for {missing}")
        self._lookup = lookup
        self._probes = dict(probes)
        self._gaps = gaps
        self._sink = sink
        self._resolver = resolver

    def owners(self) -> dict[str, Owner]:
        """The two owners by the names the state table gives them, for `item.register`."""
        return {CHECKER_OWNER: self.check, NEED_OWNER: self.wait}

    def _task(self, tenant: str, item: str) -> TaskNeeds | str:
        """The item's lane and needs, or why they could not be read."""
        try:
            task = self._lookup(tenant, item)
        except Exception as error:
            return f"the lookup of the item's needs raised {type(error).__name__}: {error}"
        if not isinstance(task, TaskNeeds) or not isinstance(task.lane, Lane):
            return f"the lookup of the item's needs returned no task: {task!r}"
        return task

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
        """The capability-checker: one probe per need; `ready`, or `gap` and no build.

        Safe to run again for the same dispatch (the engine retries a step whose worker died):
        the item is linked to a gap item once, and when this run answers the item waits on
        exactly the gap items this run found.
        """
        tenant, item = str(call["tenant"]), str(call["item"])
        dispatch = int(call["dispatch"])
        task = self._task(tenant, item)
        records: list[ProbeRecord] = []
        if isinstance(task, str):
            # No lane, so no need can be exercised: the preflight itself is the failed need.
            lane_name, resolver, limit = UNKNOWN_LANE, self._resolver, None
            records.append(
                ProbeRecord(tenant, item, lane_name, dispatch, PREFLIGHT_NEED, False, task)
            )
        else:
            lane = task.lane
            lane_name, resolver, limit = lane.name, lane.resolver, lane.gap_limit_text
            # The lane's defaults, then the task's own needs, each once. A task need is kept
            # as the text the task gave, so one the lane does not declare is still named in
            # its gap item.
            texts = dict.fromkeys([need.text for need in lane.defaults])
            for listed in task.needs:
                texts.setdefault(listed if isinstance(listed, str) else repr(listed))
            for text in texts:
                result = self._probe(text, lane)
                records.append(
                    ProbeRecord(
                        tenant, item, lane_name, dispatch, text, result.passed, result.output
                    )
                )
        if self._sink is not None:
            for record in records:
                self._sink(record)
        detail: dict[str, Any] = {
            "lane": lane_name,
            "probes": [record.to_record() for record in records],
        }
        failed = [record for record in records if not record.passed]
        opened = [
            self._gaps.open_or_link(
                tenant=tenant,
                lane=lane_name,
                need=record.need,
                resolver=resolver,
                output=record.output,
                item=item,
            )
            for record in failed
        ]
        self._gaps.settle(tenant, item, keep=[gap.id for gap in opened])
        if not failed:
            return {"outcome": "ready", "detail": detail}
        detail.update(
            need=failed[0].need,
            needs=[record.need for record in failed],
            gaps=[gap.id for gap in opened],
            resolver=resolver,
        )
        if limit is not None:
            detail["limit"] = limit  # the need sets the limit of the wait
        return {"outcome": "gap", "detail": detail}

    def wait(self, call: Payload) -> Payload | None:
        """The need: the item waits; `closed` arrives from `close_gap`.

        Two cases do something here.

        Preflight ran out of its limit, so no probe result names a need: a gap item naming the
        preflight itself is opened and the item waits on that. It is for the lane's resolver,
        or, when the lane cannot be read either, for this checker's own.

        The gap items the item waits on are all closed already. A `closed` sent before the item
        reached the wait cannot be read, so the answer is given now. The gap items are the ones
        the registry links the item to; when it links the item to none, they are the ones the
        detail names, and one the registry does not know counts as closed.

        An item that waits on something that is not a capability gap (none linked, none named)
        is left to wait: that wait is what a repeated decision ends in, and answering it here
        would send the item round again.
        """
        tenant, item = str(call["tenant"]), str(call["item"])
        if call.get("action") == OPEN_GAP_ACTION:
            task = self._task(tenant, item)
            output = "the preflight did not finish within its limit"
            if isinstance(task, str):
                lane_name, resolver, output = UNKNOWN_LANE, self._resolver, f"{output}; {task}"
            else:
                lane_name, resolver = task.lane.name, task.lane.resolver
            self._gaps.open_or_link(
                tenant=tenant,
                lane=lane_name,
                need=PREFLIGHT_NEED,
                resolver=resolver,
                output=output,
                item=item,
            )
            return None
        detail = call.get("detail")
        named = detail.get("gaps") if isinstance(detail, Mapping) else None
        named = [gap_id for gap_id in named if isinstance(gap_id, str)] if named else []
        linked = self._gaps.for_item(tenant, item)
        # What the registry links the item to decides; the detail's names decide only when
        # the registry links it to nothing (it lost the gap items, or never had them).
        if linked:
            if any(gap.open for gap in linked):
                return None
            closed = [gap.id for gap in linked]
        elif named and all(self._closed(gap_id) for gap_id in named):
            closed = named
        else:
            return None
        return {"outcome": "closed", "detail": {"closed_gaps": closed}}

    def _closed(self, gap_id: str) -> bool:
        try:
            return not self._gaps.get(gap_id).open
        except KeyError:
            return True  # not known: nothing to wait for


class ItemsNotSignalled(Exception):
    """A gap item was closed, but some linked items could not be told. `items` names them.

    Calling `close_gap` again tells them. An item that is never told still leaves its wait
    when the wait's limit passes.
    """

    def __init__(self, gap: GapItem, failures: Mapping[str, Exception]) -> None:
        told = ", ".join(f"{item} ({error})" for item, error in failures.items())
        super().__init__(f"gap item {gap.id} is closed, but these items were not told: {told}")
        self.gap = gap
        self.items = tuple(failures)


async def close_gap(engine: Engine, gaps: GapRegistry, gap_id: str) -> GapItem | None:
    """Close a gap item and send every item linked to it back to preflight.

    Each linked item gets the outcome `closed` for its wait; an item that is not waiting
    ignores it, and one whose workflow has ended is passed over. Every linked item is tried:
    when some could not be told, `ItemsNotSignalled` names them after the rest were told. Safe
    to call again: closing a closed gap item sends the outcome again.

    A gap item the registry does not know gives None and nothing is sent, since nothing says
    which items it held. Those items are not held by it either: an unknown gap item counts as
    closed when their wait is next dispatched.
    """
    try:
        gap = gaps.close(gap_id)
    except KeyError:
        return None
    failures: dict[str, Exception] = {}
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
        except Exception as error:
            failures[item] = error
    if failures:
        raise ItemsNotSignalled(gap, failures)
    return gap
