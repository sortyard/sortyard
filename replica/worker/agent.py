"""The replica's scripted agent: what stands where a lane's agent CLI would (replica only).

The worker entry point (`sortyard-worker agent`) runs it in the item's clone with the brief
text on standard input, as it runs any agent command:

    agent.py build|fix [SECONDS]   wait SECONDS (so the replica can stop the kernel while an
                                   item is being built), then commit one file on the work branch
    agent.py review                answer with an approval, the way a reviewer is asked to

It holds no credential and pushes nothing: the worker's `push` container does that.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    brief = sys.stdin.read()
    if mode == "review":
        print("Read the change against the spec.")
        checked, ran = ["the change against the spec"], ["git diff: read"]
        print(json.dumps({"verdict": "approve", "checked": checked, "evidence": ran}))
        return 0
    if mode not in ("build", "fix"):
        print("usage: agent.py build|fix [SECONDS] | review", file=sys.stderr)
        return 2
    time.sleep(float(argv[2]) if len(argv) > 2 else 0)
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    # The branch is in the name and the content, so two items never make the same commit.
    path = pathlib.Path("changes") / (branch.replace("/", "-") + f"-{mode}.txt")
    path.parent.mkdir(exist_ok=True)
    path.write_text(f"{mode} on {branch} by the replica's scripted agent\n\n{brief}")
    git("add", str(path))
    git("commit", "--quiet", "-m", f"{mode}: {branch}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
