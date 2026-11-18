"""Compute comparable delivery measures from observed lifecycle facts (native execution §5)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from statistics import median

from sortyard.lifecycle.contracts import EventKind, EventMode, LifecycleEvent, normalize


class Measure(StrEnum):
    MERGED_PRS_PER_DAY = "merged_prs_per_day"
    REAL_HANDBACKS_PER_DAY = "real_handbacks_per_day"
    MEDIAN_RELEASE_TO_MERGE_HOURS = "median_release_to_merge_hours"
    RED_MAIN_HOURS_PER_WEEK = "red_main_hours_per_week"
    OVERDUE_READINESS_HOLDS = "overdue_readiness_holds"
    SILENT_REFUSALS = "silent_refusals"


@dataclass(frozen=True)
class ScorecardWindow:
    start: datetime
    end: datetime
    board: str | None = None
    repo: str | None = None

    def __post_init__(self) -> None:
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError("scorecard window endpoints require explicit timezones")
        object.__setattr__(self, "start", self.start.astimezone(UTC))
        object.__setattr__(self, "end", self.end.astimezone(UTC))
        if self.start >= self.end:
            raise ValueError("scorecard window end must follow start")


@dataclass(frozen=True)
class ScorecardRow:
    value: float | int | None
    samples: int
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scorecard:
    window: ScorecardWindow
    rows: dict[Measure, ScorecardRow]
    diagnostics: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "window": {
                "start": self.window.start.isoformat(),
                "end": self.window.end.isoformat(),
                "board": self.window.board,
                "repo": self.window.repo,
            },
            "rows": {
                measure.value: {
                    "value": row.value,
                    "samples": row.samples,
                    "issues": list(row.issues),
                }
                for measure, row in self.rows.items()
            },
            "diagnostics": list(self.diagnostics),
        }


def _timestamp(event: LifecycleEvent) -> datetime:
    assert event.observed_at is not None
    return event.observed_at


def _merge_rate(merges: list[LifecycleEvent], days: float) -> ScorecardRow:
    prs = {(event.repo, event.pr_id) for event in merges if event.repo and event.pr_id}
    unidentified = sum(event.repo is None or event.pr_id is None for event in merges)
    issues = (
        (f"{unidentified} merge events lack a repository or PR identity",) if unidentified else ()
    )
    return ScorecardRow(len(prs) / days, len(prs), issues)


def _handback_rate(handbacks: list[LifecycleEvent], days: float) -> ScorecardRow:
    valid = sum(
        bool(event.board and event.repo and event.task_id and event.owner and event.reason)
        for event in handbacks
    )
    incomplete = len(handbacks) - valid
    issues = (f"{incomplete} handbacks lack task scope, owner or reason",) if incomplete else ()
    return ScorecardRow(valid / days, valid, issues)


def _task_revision(event: LifecycleEvent) -> tuple[str, str, str, str] | None:
    if event.board and event.repo and event.task_id and event.task_revision:
        return (event.board, event.repo, event.task_id, event.task_revision)
    return None


def _lead_time(releases: list[LifecycleEvent], merges: list[LifecycleEvent]) -> ScorecardRow:
    first_release: dict[tuple[str, str, str, str], datetime] = {}
    incomplete_releases = 0
    for event in releases:
        key = _task_revision(event)
        if key is None or not (event.artifact_revision and event.binding):
            incomplete_releases += 1
            continue
        timestamp = _timestamp(event)
        first_release[key] = min(timestamp, first_release.get(key, timestamp))

    first_merge: dict[tuple[str, str, str, str], datetime] = {}
    unidentified = 0
    for event in merges:
        key = _task_revision(event)
        if key is None or event.pr_id is None:
            unidentified += 1
            continue
        timestamp = _timestamp(event)
        first_merge[key] = min(timestamp, first_merge.get(key, timestamp))

    durations = []
    for key, merged_at in first_merge.items():
        released_at = first_release.get(key)
        if released_at is not None and released_at <= merged_at:
            durations.append((merged_at - released_at).total_seconds() / 3600)

    issues = []
    unmatched = unidentified + len(first_merge) - len(durations)
    if incomplete_releases:
        issues.append(f"{incomplete_releases} release events lack revision or binding evidence")
    if unmatched:
        issues.append(f"{unmatched} merged task revisions lack a qualifying release or identity")
    if not durations:
        issues.append("no joined release-to-merge observations")
    return ScorecardRow(median(durations) if durations else None, len(durations), tuple(issues))


def _red_intervals(
    changes: list[LifecycleEvent], window: ScorecardWindow
) -> tuple[list[tuple[datetime, datetime]], list[str]]:
    first = _timestamp(changes[0])
    active_since = None
    intervals = []
    issues = []
    check = changes[0].check_id
    if first > window.start:
        issues.append(f"required check set {check} lacks state at window start")

    previous = None
    for event in changes:
        timestamp = _timestamp(event)
        if previous and _timestamp(previous) == timestamp and previous.kind is not event.kind:
            issues.append(f"required check set {check} has conflicting states at {timestamp}")
        previous = event
        if event.kind is EventKind.MAIN_RED and timestamp < window.end:
            active_since = active_since or timestamp
        elif event.kind is EventKind.MAIN_GREEN and active_since is not None:
            if timestamp > window.start:
                intervals.append((max(active_since, window.start), timestamp))
            active_since = None
    if active_since is not None:
        issues.append(f"required check set {check} has an open red interval")
    return intervals, issues


def _red_main(events: list[LifecycleEvent], window: ScorecardWindow) -> ScorecardRow:
    issues = []
    if window.repo is None:
        issues.append("red-main hours require one product repository")
    if window.end - window.start != timedelta(days=7):
        issues.append("red-main hours require a seven-day window")
    groups: dict[str, list[LifecycleEvent]] = defaultdict(list)
    for event in events:
        if event.check_id is None:
            issues.append(f"main state event {event.event_id} lacks a required check set")
        else:
            groups[event.check_id].append(event)
    if not groups:
        issues.append("no required default-branch check set was observed")

    intervals = []
    for changes in groups.values():
        check_intervals, check_issues = _red_intervals(changes, window)
        intervals.extend(check_intervals)
        issues.extend(check_issues)

    # Union the intervals so one unhealthy hour contributes once per product.
    seconds = 0.0
    counted_to = window.start
    for start, end in sorted(intervals):
        if end > counted_to:
            seconds += (end - max(start, counted_to)).total_seconds()
            counted_to = end
    return ScorecardRow(seconds / 3600, len(intervals), tuple(issues))


def _readiness(
    transitions: list[LifecycleEvent],
    end: datetime,
    reconciliation_interval: timedelta | None,
) -> ScorecardRow:
    holds: dict[tuple[str, str, str], datetime] = {}
    latest: dict[tuple[str, str, str], LifecycleEvent] = {}
    issues = []
    if reconciliation_interval is None:
        issues.append("reconciliation cadence is unknown")
    for event in transitions:
        if not (event.board and event.repo and event.task_id):
            issues.append(f"readiness event {event.event_id} lacks task scope")
            continue
        if event.kind is EventKind.READINESS_HOLD and not (event.reason and event.owner):
            issues.append(f"readiness hold {event.event_id} lacks a reason or owner")
            continue
        key = (event.board, event.repo, event.task_id)
        timestamp = _timestamp(event)
        previous = latest.get(key)
        if previous and timestamp == _timestamp(previous) and event.kind is not previous.kind:
            issues.append(f"readiness transitions disagree at one timestamp for {event.task_id}")
        latest[key] = event
        if event.kind is EventKind.READINESS_HOLD:
            holds.setdefault(key, timestamp)
        else:
            holds.pop(key, None)
    interval = reconciliation_interval
    value = sum(end - start > interval for start in holds.values()) if interval else None
    return ScorecardRow(value, len(holds), tuple(issues))


def _silent_refusals(refusals: list[LifecycleEvent]) -> ScorecardRow:
    inspected = [
        event
        for event in refusals
        if event.board
        and event.repo
        and event.task_id
        and event.projection_reason_present is not None
    ]
    unknown = len(refusals) - len(inspected)
    issues = (f"{unknown} refusals lack attributable task-projection evidence",) if unknown else ()
    silent = sum(event.projection_reason_present is False for event in inspected)
    return ScorecardRow(silent, len(inspected), issues)


def build_scorecard(
    events: Iterable[LifecycleEvent],
    window: ScorecardWindow,
    *,
    complete: Collection[Measure] = (),
    reconciliation_interval: timedelta | None = None,
) -> Scorecard:
    """Score a half-open reporting window from observed facts and explicit source coverage.

    A complete row asserts coverage for the population and window. Lead time and hold age
    also require relevant history before the window. Red-main hours require all required
    check sets, including their state at the window's start. Sample counts describe the
    evidence seen even when coverage is insufficient to publish a value.
    """
    if reconciliation_interval is not None and reconciliation_interval <= timedelta(0):
        raise ValueError("reconciliation interval must be positive")

    observed_input = []
    had_input = False
    for event in events:
        had_input = True
        if event.mode is EventMode.OBSERVED:
            observed_input.append(event)
    observed, diagnostics = normalize(observed_input)
    observed_ids = {event.event_id for event in observed}
    rejected = [event for event in observed_input if event.event_id not in observed_ids]
    exclusively_simulated = had_input and not observed_input
    if exclusively_simulated:
        diagnostics = ("input contains only replay or shadow events",)

    history: dict[EventKind, list[LifecycleEvent]] = defaultdict(list)
    current: dict[EventKind, list[LifecycleEvent]] = defaultdict(list)
    missing_scope: dict[EventKind, list[LifecycleEvent]] = defaultdict(list)
    conflicting: dict[EventKind, list[LifecycleEvent]] = defaultdict(list)
    for event in sorted((*observed, *rejected), key=_timestamp):
        timestamp = _timestamp(event)
        if timestamp > window.end:
            break
        if timestamp == window.end and event.kind is not EventKind.MAIN_GREEN:
            continue
        if window.board is not None and event.board not in (window.board, None):
            continue
        if window.repo is not None and event.repo not in (window.repo, None):
            continue
        if event.event_id not in observed_ids:
            conflicting[event.kind].append(event)
            continue
        if (window.board and event.board is None) or (window.repo and event.repo is None):
            missing_scope[event.kind].append(event)
            continue
        history[event.kind].append(event)
        if window.start <= timestamp < window.end:
            current[event.kind].append(event)

    days = (window.end - window.start).total_seconds() / 86400
    merges = current[EventKind.MERGED]
    handbacks = current[EventKind.HANDBACK]
    releases = [event for event in history[EventKind.RELEASED] if _timestamp(event) < window.end]
    main_state = sorted(history[EventKind.MAIN_GREEN] + history[EventKind.MAIN_RED], key=_timestamp)
    readiness = sorted(
        (
            event
            for kind in (EventKind.READINESS_HOLD, EventKind.READINESS_CLEARED)
            for event in history[kind]
            if _timestamp(event) < window.end
        ),
        key=_timestamp,
    )
    rows = {
        Measure.MERGED_PRS_PER_DAY: _merge_rate(merges, days),
        Measure.REAL_HANDBACKS_PER_DAY: _handback_rate(handbacks, days),
        Measure.MEDIAN_RELEASE_TO_MERGE_HOURS: _lead_time(releases, merges),
        Measure.RED_MAIN_HOURS_PER_WEEK: _red_main(main_state, window),
        Measure.OVERDUE_READINESS_HOLDS: _readiness(readiness, window.end, reconciliation_interval),
        Measure.SILENT_REFUSALS: _silent_refusals(current[EventKind.REFUSED]),
    }
    related = {
        Measure.MERGED_PRS_PER_DAY: (EventKind.MERGED,),
        Measure.REAL_HANDBACKS_PER_DAY: (EventKind.HANDBACK,),
        Measure.MEDIAN_RELEASE_TO_MERGE_HOURS: (EventKind.RELEASED, EventKind.MERGED),
        Measure.RED_MAIN_HOURS_PER_WEEK: (EventKind.MAIN_RED, EventKind.MAIN_GREEN),
        Measure.OVERDUE_READINESS_HOLDS: (EventKind.READINESS_HOLD, EventKind.READINESS_CLEARED),
        Measure.SILENT_REFUSALS: (EventKind.REFUSED,),
    }
    lookback = {
        EventKind.RELEASED,
        EventKind.MAIN_RED,
        EventKind.MAIN_GREEN,
        EventKind.READINESS_HOLD,
        EventKind.READINESS_CLEARED,
    }
    for measure, row in rows.items():
        issues = list(row.issues)
        if measure not in complete:
            issues.append("source coverage for this measure and window was not established")
        if exclusively_simulated:
            issues.append("input contains only replay or shadow events")
        if any(
            kind in lookback or window.start <= _timestamp(event) < window.end
            for kind in related[measure]
            for event in conflicting[kind]
        ):
            issues.append("relevant observed events have conflicting event IDs")
        missing = sum(
            kind in lookback or window.start <= _timestamp(event) < window.end
            for kind in related[measure]
            for event in missing_scope[kind]
        )
        if missing:
            issues.append(f"{missing} relevant events lack board or repository attribution")
        if issues:
            rows[measure] = replace(row, value=None, issues=tuple(issues))
    return Scorecard(window, rows, diagnostics)
