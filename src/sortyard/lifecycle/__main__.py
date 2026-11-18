"""Build a cutover scorecard from a versioned lifecycle JSON export (native execution §5)."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from sortyard.lifecycle.contracts import EventMode, LifecycleEvent
from sortyard.lifecycle.dv32 import stage_event
from sortyard.lifecycle.scorecard import Measure, ScorecardWindow, build_scorecard


def _load(path: Path, *, dv32: bool) -> tuple[list[LifecycleEvent], int, list[str]]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and not dv32:
        data = data.get("lifecycle_events")
    if not isinstance(data, list):
        raise ValueError("expected an array of records or a replay's lifecycle_events")
    events: list[LifecycleEvent] = []
    unmapped = 0
    invalid: list[str] = []
    for index, row in enumerate(data, 1):
        try:
            if not isinstance(row, dict):
                raise ValueError("record must be an object")
            event = stage_event(row) if dv32 else LifecycleEvent.from_dict(row)
            if event is None:
                unmapped += 1
            else:
                events.append(event)
        except ValueError as exc:
            invalid.append(f"record {index}: {exc}")
    return events, unmapped, invalid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("--dv32", action="store_true", help="read minimized DV-32 span records")
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
        events, unmapped, invalid = _load(args.events, dv32=args.dv32)
        window = ScorecardWindow(args.start, args.end, board=args.board, repo=args.repo)
        interval = (
            timedelta(seconds=args.reconciliation_seconds)
            if args.reconciliation_seconds is not None
            else None
        )
        # The narrow OTel mapping cannot attest to any delivery measure.
        complete = () if invalid or args.dv32 else tuple(Measure(value) for value in args.complete)
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
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
