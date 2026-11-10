"""Shared runner for services that are structure-only in this phase.

A stub service starts, logs that it has no work loop yet, and idles until SIGTERM/SIGINT so it
behaves like a real long-running Deployment. ``--once`` runs a single cycle and exits (tests).
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from collections.abc import Sequence
from types import FrameType


def run(name: str, summary: str, argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"sortyard-{name}", description=summary)
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--interval", type=float, default=30.0, help="seconds between idle cycles")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log = logging.getLogger(f"sortyard.{name}")

    stop = threading.Event()

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d, stopping", signum)
        stop.set()

    if not args.once:
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)

    log.info("%s: stub service started (no work loop yet)", name)
    while not args.once and not stop.wait(args.interval):
        log.info("%s: idle", name)
    log.info("%s: stopped", name)
    return 0
