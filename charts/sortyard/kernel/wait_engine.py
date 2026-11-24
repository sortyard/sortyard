"""Wait for the workflow engine: the kernel pod's init container (templates/kernel.yaml).

Returns once the engine at SORTYARD_ENGINE_TARGET answers for SORTYARD_ENGINE_NAMESPACE: an
unknown workflow is refused by name only by a server that has its store and that namespace.
The kernel service ends when the engine does not answer; started before the engine is ready it
would be restarted with a growing delay, so the pod waits here first. After
SORTYARD_ENGINE_WAIT_SECONDS without the answer it fails and says what it waited for; the pod
restarts it, so it keeps trying and nothing is left waiting unseen.

Runs in the Sortyard image, through `sortyard.engine` alone.
"""

from __future__ import annotations

import asyncio
import gc
import os
import sys
import time

from sortyard.engine import Engine, WorkflowNotFound


async def unanswered(target: str, namespace: str) -> str | None:
    """Why the engine did not answer, or nothing when it did."""
    try:
        engine = await Engine.connect(target, namespace=namespace)
        await engine.recorded("sortyard-wait-engine-no-such-workflow")
    except WorkflowNotFound:
        return None
    except Exception as error:
        return f"{type(error).__name__}: {error}"
    return None


async def asked(target: str, namespace: str) -> str | None:
    """One try, bounded; the engine client is gone again before this returns.

    The client must not outlive the event loop it was made on: left to the interpreter's
    exit, the SDK's native runtime is torn down under it and the process can end with a
    segmentation fault after it has already said the engine answers (seen in about one run in
    fifteen on a loaded host). The answer above is an exception, whose traceback keeps the
    client alive until the garbage is collected, so it is collected here, inside the loop.
    """
    try:
        return await asyncio.wait_for(unanswered(target, namespace), timeout=15)
    except TimeoutError:
        return "no answer within 15s"
    finally:
        gc.collect()


def main() -> int:
    target = os.environ["SORTYARD_ENGINE_TARGET"]
    namespace = os.environ.get("SORTYARD_ENGINE_NAMESPACE", "default")
    limit = float(os.environ.get("SORTYARD_ENGINE_WAIT_SECONDS", "300"))
    started = time.monotonic()
    while True:
        why = asyncio.run(asked(target, namespace))
        if why is None:
            print(f"kernel: the engine at {target} answers for namespace {namespace}", flush=True)
            return 0
        if time.monotonic() - started >= limit:
            print(
                f"kernel: gave up waiting for the engine at {target} (namespace {namespace}) "
                f"after {limit:.0f}s: {why}. This container is restarted and waits again.",
                file=sys.stderr,
            )
            return 1
        print(f"kernel: waiting for the engine at {target}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
