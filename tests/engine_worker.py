"""A worker process for the engine failure tests: launch the engine, maybe start a workflow, idle.

    python tests/engine_worker.py SAMPLE DATABASE_URL [--start NAME ID] [--clock-offset SECONDS]

SAMPLE is the path of the sample workflow module (`tests/engine_sample.py` or a changed copy).
`--clock-offset` is the test clock: it moves this process's wall clock forward, so a durable timer
recorded by an earlier worker sees that much time as having passed. The process writes "ready"
to the marks file once launched and runs until it is killed.
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import sys
import time
from types import ModuleType


def load(path: pathlib.Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("engine_sample", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["engine_sample"] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", type=pathlib.Path)
    parser.add_argument("database_url")
    parser.add_argument("--start", nargs=2, metavar=("NAME", "ID"))
    parser.add_argument("--clock-offset", type=float, default=0.0)
    args = parser.parse_args()

    if args.clock_offset:
        real_time = time.time
        offset: float = args.clock_offset
        time.time = lambda: real_time() + offset

    from sortyard.engine import Engine

    sample = load(args.sample)
    engine = Engine(args.database_url)
    engine.launch()
    if args.start:
        name, workflow_id = args.start
        engine.start(sample.WORKFLOWS[name], workflow_id)
    sample.mark("ready")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
