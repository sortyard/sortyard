"""A worker process for the engine failure tests: serve a sample module until killed.

    python tests/engine_worker.py SAMPLE TARGET

SAMPLE is the path of the sample workflow module (`tests/engine_sample.py` or a changed copy of
it); TARGET is the engine service address. The process holds no state: everything it knows
about a workflow it reads from the engine.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import sys
import threading
import time
from types import ModuleType

from sortyard.engine import Engine


def load(path: pathlib.Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("engine_sample", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["engine_sample"] = module
    spec.loader.exec_module(module)
    return module


def exit_with_parent() -> None:
    """Do not outlive the test process, however it ends (a worker is never the last one left)."""
    parent = os.getppid()

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(0.5)
        os._exit(1)

    threading.Thread(target=watch, daemon=True).start()


async def main(sample: pathlib.Path, target: str) -> None:
    engine = await Engine.connect(target)
    await engine.run_worker(load(sample).REGISTRY)


if __name__ == "__main__":
    exit_with_parent()
    asyncio.run(main(pathlib.Path(sys.argv[1]), sys.argv[2]))
