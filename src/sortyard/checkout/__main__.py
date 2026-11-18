"""Run and inspect the offline checkout incident replay (§4)."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from sortyard.checkout.lifecycle import replay_events
from sortyard.checkout.policy import POLICIES
from sortyard.checkout.replay import run_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--policy", required=True, choices=POLICIES)
    parser.add_argument("--lifecycle", action="store_true", help="include shared lifecycle facts")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    result = run_replay(fixture, args.policy)
    output = asdict(result)
    if args.lifecycle:
        output["lifecycle_events"] = [event.to_dict() for event in replay_events(fixture, result)]
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
