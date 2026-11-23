"""A worker process for the engine failure tests: launch the engine, maybe start a workflow, idle.

    python tests/engine_worker.py SAMPLE DATABASE_URL [--start NAME ID] [--clock-offset SECONDS]

SAMPLE is the path of the sample workflow module (`tests/engine_sample.py` or a changed copy).
`--clock-offset` is the test clock: it moves this process's wall clock forward, so a durable timer
recorded by an earlier worker sees that much time as having passed. The test clock also reports
every wait of an hour or more the process is asked for, as "wait SECONDS" in the marks file: when
a resumed timer is still pending, that is the time left that the worker computed from the
recorded deadline under its clock. The process writes "ready" to the marks file once launched and
runs until it is killed.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import pathlib
import sys
import threading
import time
from types import ModuleType
from typing import SupportsIndex


def load(path: pathlib.Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("engine_sample", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["engine_sample"] = module
    spec.loader.exec_module(module)
    return module


LONG_WAIT = 60 * 60


def install_test_clock(offset: float, marks: pathlib.Path) -> None:
    """Move the wall clock forward by `offset` and report each wait of `LONG_WAIT` or more.

    Installed before the engine is imported, so the engine only ever sees the test clock.
    """
    real_time, real_sleep = time.time, time.sleep

    def sleep(seconds: float | SupportsIndex) -> None:
        seconds = float(seconds)
        if seconds >= LONG_WAIT:
            with marks.open("a") as f:
                f.write(f"wait {seconds!r}\n")
        real_sleep(seconds)

    time.time = lambda: real_time() + offset
    time.sleep = sleep


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", type=pathlib.Path)
    parser.add_argument("database_url")
    parser.add_argument("--start", nargs=2, metavar=("NAME", "ID"))
    parser.add_argument("--clock-offset", type=float, default=0.0)
    args = parser.parse_args()

    install_test_clock(args.clock_offset, pathlib.Path(os.environ["SORTYARD_ENGINE_MARKS"]))

    from sortyard.engine import Engine

    sample = load(args.sample)
    engine = Engine(args.database_url)
    engine.launch()
    if args.start:
        name, workflow_id = args.start
        engine.start(sample.WORKFLOWS[name], workflow_id)
    sample.mark("ready")
    threading.Event().wait()


if __name__ == "__main__":
    main()
