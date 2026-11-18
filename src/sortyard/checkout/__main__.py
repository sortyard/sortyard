"""Run and inspect the offline checkout incident replay (§4)."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from sortyard.checkout.policy import POLICIES
from sortyard.checkout.replay import run_replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--policy", required=True, choices=POLICIES)
    args = parser.parse_args()
    print(
        json.dumps(asdict(run_replay(json.loads(args.fixture.read_text()), args.policy)), indent=2)
    )


if __name__ == "__main__":
    main()
