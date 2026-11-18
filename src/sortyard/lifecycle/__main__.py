"""Build a cutover scorecard from a versioned lifecycle JSON export (native execution §5)."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from math import ceil, floor
from pathlib import Path

from sortyard.lifecycle.conductor_logs import Coverage, conductor_log
from sortyard.lifecycle.contracts import EventMode, LifecycleEvent
from sortyard.lifecycle.dv32 import stage_event
from sortyard.lifecycle.scorecard import Measure, ScorecardWindow, build_scorecard


def _load(
    path: Path, *, dv32: bool, conductor: bool
) -> tuple[list[LifecycleEvent], list[Coverage], int, list[str]]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and not (dv32 or conductor):
        data = data.get("lifecycle_events")
    if not isinstance(data, list):
        raise ValueError("expected an array of records or a replay's lifecycle_events")
    events: list[LifecycleEvent] = []
    coverage: list[Coverage] = []
    unmapped = 0
    invalid: list[str] = []
    event: LifecycleEvent | Coverage | None
    for index, row in enumerate(data, 1):
        try:
            if not isinstance(row, dict):
                raise ValueError("record must be an object")
            if conductor:
                event = conductor_log(row)
            elif dv32:
                event = stage_event(row)
            else:
                event = LifecycleEvent.from_dict(row)
            if isinstance(event, Coverage):
                coverage.append(event)
            elif event is None:
                unmapped += 1
            else:
                events.append(event)
        except ValueError as exc:
            invalid.append(f"record {index}: {exc}")
    return events, coverage, unmapped, invalid


def _coverage_counts(
    coverage: list[Coverage], window: ScorecardWindow
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for record in set(coverage):
        if not window.start <= record.observed_at < window.end:
            continue
        if window.board and record.board != window.board:
            continue
        if window.repo and record.repo != window.repo:
            continue
        status = "complete" if record.complete else "incomplete"
        bucket = counts.setdefault(record.kind, {"complete": 0, "incomplete": 0})
        bucket[status] += 1
    return dict(sorted(counts.items()))


def _covered_cadence(records: list[Coverage], kind: str, window: ScorecardWindow) -> int | None:
    if not (window.board and window.repo):
        return None
    candidates = [
        record
        for record in records
        if (record.kind, record.board, record.repo) == (kind, window.board, window.repo)
        and record.observed_at < window.end
    ]
    if not candidates:
        return None
    cadence = max(candidates, key=lambda record: record.observed_at).cadence_seconds
    if cadence is None:
        return None
    first_slot = floor(window.start.timestamp() / cadence)
    end_slot = ceil(window.end.timestamp() / cadence)
    observed_slots = set()
    for record in candidates:
        slot = floor(record.observed_at.timestamp() / cadence)
        if first_slot <= slot < end_slot:
            if not record.complete or record.cadence_seconds != cadence:
                return None
            observed_slots.add(slot)
    return cadence if len(observed_slots) == end_slot - first_slot else None


_COVERAGE_MEASURES = {
    "red_main": Measure.RED_MAIN_HOURS_PER_WEEK,
    "readiness": Measure.OVERDUE_READINESS_HOLDS,
    "refusals": Measure.SILENT_REFUSALS,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    format_args = parser.add_mutually_exclusive_group()
    format_args.add_argument(
        "--dv32", action="store_true", help="read minimized DV-32 span records"
    )
    format_args.add_argument(
        "--conductor-logs", action="store_true", help="read minimized incumbent SigNoz log records"
    )
    parser.add_argument("--start", type=datetime.fromisoformat, required=True)
    parser.add_argument("--end", type=datetime.fromisoformat, required=True)
    parser.add_argument("--board")
    parser.add_argument("--repo")
    parser.add_argument(
        "--complete",
        action="append",
        choices=tuple(Measure),
        default=[],
        help="assert one measure has complete source coverage for this cohort and window",
    )
    parser.add_argument("--reconciliation-seconds", type=int)
    args = parser.parse_args()
    try:
        events, coverage, unmapped, invalid = _load(
            args.events, dv32=args.dv32, conductor=args.conductor_logs
        )
        window = ScorecardWindow(args.start, args.end, board=args.board, repo=args.repo)
        interval = (
            timedelta(seconds=args.reconciliation_seconds)
            if args.reconciliation_seconds is not None
            else None
        )
        # The narrow OTel mapping cannot attest to any delivery measure.
        complete = () if invalid or args.dv32 else tuple(Measure(value) for value in args.complete)
        counts = _coverage_counts(coverage, window)
        if args.conductor_logs:
            cadence = {
                kind: _covered_cadence(coverage, kind, window) for kind in _COVERAGE_MEASURES
            }
            unsupported = {
                measure for kind, measure in _COVERAGE_MEASURES.items() if not cadence[kind]
            }
            readiness = cadence["readiness"]
            if readiness is not None and interval is None:
                interval = timedelta(seconds=readiness)
            elif readiness is not None and interval != timedelta(seconds=readiness):
                unsupported.add(Measure.OVERDUE_READINESS_HOLDS)
            complete = tuple(measure for measure in complete if measure not in unsupported)
        scorecard = build_scorecard(
            events, window, complete=complete, reconciliation_interval=interval
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    output = scorecard.to_dict()
    modes = Counter(event.mode for event in events)
    output["intake"] = {
        "mapped_records": len(events),
        "by_mode": {mode.value: modes[mode] for mode in EventMode},
        "unmapped_records": unmapped,
        "invalid_records": invalid,
        "asserted_complete": list(complete),
    }
    if args.conductor_logs:
        output["coverage"] = counts
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
