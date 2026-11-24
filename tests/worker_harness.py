"""Shared pieces of the worker tests: local git remotes, a scripted agent, and the lane.

Nothing here reaches a network. A remote is a bare repository on disk, cloned over `file://`.
The agent is a small Python script that writes down what it was given (its environment, its
standard input, its working directory, the clone's git configuration) and then does what its
first argument says, so a test can assert on what the real entry point handed it.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from typing import Any

from sortyard.kernel.capabilities import Lane, load

TOKEN = "ghs_per0job1token2for3the4worker5tests"
DIGEST = "sha256:" + "c3" * 32
LANE: Lane = load(
    f"""
version = 1
lane = "walwarden"
resolver = "platform"
runner-pool = "walwarden-runners"

[images]
worker = "registry.test/walwarden/worker@{DIGEST}"
ci = "registry.test/walwarden/ci@{DIGEST}"

[[repositories]]
name = "walwarden/app"

[[repositories]]
name = "walwarden/infra"
workflow-files = true

[[secrets]]
name = "DEPLOY_TOKEN"

[[secrets]]
name = "MODEL_API_KEY"

[[services]]
name = "cluster-api"
"""
)

AGENT = r"""
import json, os, pathlib, subprocess, sys

seen, action = pathlib.Path(sys.argv[1]), sys.argv[2]


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


seen.write_text(json.dumps({
    "env": dict(os.environ),
    "stdin": sys.stdin.read(),
    "cwd": os.getcwd(),
    "config": pathlib.Path(".git/config").read_text(),
    "remotes": git("remote", "-v"),
    "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
    "head": git("rev-parse", "HEAD").strip(),
    "files": sorted(p.name for p in pathlib.Path(".").iterdir() if p.name != ".git"),
}))


def commit(name):
    # The branch is in the content, so two items' commits are never the same commit.
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    pathlib.Path(name).write_text("made by the agent on " + branch + "\n")
    git("add", name)
    git("commit", "-q", "-m", "add " + name)


if action.startswith("commit:"):
    commit(action.split(":", 1)[1])
elif action == "hook":
    hook = pathlib.Path(".git/hooks/pre-push")
    hook.write_text("#!/bin/sh\nenv > " + str(seen) + ".hook\n")
    hook.chmod(0o755)
    commit("hooked.txt")
elif action == "review":
    # Approves once the fix is in, as a reviewer reading the branch would.
    print("I read the change.")
    if pathlib.Path("fix.txt").exists():
        print(json.dumps({"verdict": "approve"}))
    else:
        print(json.dumps({"verdict": "findings", "findings": [
            {"key": "Missing fix.txt", "text": "The change does not add fix.txt."},
            {"key": "style", "text": "Second finding."}]}))
elif action.startswith("say:"):
    print(action.split(":", 1)[1])
elif action == "fail":
    sys.exit(3)
"""


def git(*args: str, cwd: pathlib.Path) -> str:
    """git as the tests run it: no host configuration, a fixed identity."""
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "seed",
        "GIT_AUTHOR_EMAIL": "seed@example.invalid",
        "GIT_COMMITTER_NAME": "seed",
        "GIT_COMMITTER_EMAIL": "seed@example.invalid",
    }
    done = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def make_remote(root: pathlib.Path, repository: str = "walwarden/app") -> pathlib.Path:
    """A bare repository at root/<repository>.git with one commit on main."""
    bare = root / f"{repository}.git"
    bare.mkdir(parents=True)
    git("init", "--quiet", "--bare", "--initial-branch=main", ".", cwd=bare)
    seed = root / "seed"
    seed.mkdir(exist_ok=True)
    git("init", "--quiet", "--initial-branch=main", ".", cwd=seed)
    (seed / "README.md").write_text("seed\n")
    git("add", "README.md", cwd=seed)
    git("commit", "--quiet", "-m", "seed", cwd=seed)
    git("push", "--quiet", bare.as_uri(), "main", cwd=seed)
    return bare


def remote_head(bare: pathlib.Path, branch: str) -> str | None:
    """The head of a branch on the remote, or nothing when the remote has no such branch."""
    done = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=bare,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() or None


def agent_command(root: pathlib.Path, action: str, name: str = "seen") -> list[str]:
    """The argv of the scripted agent; what it saw lands in root/<name>.json."""
    script = root / "agent.py"
    script.write_text(AGENT)
    return [sys.executable, str(script), str(root / f"{name}.json"), action]


def seen(root: pathlib.Path, name: str = "seen") -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((root / f"{name}.json").read_text())
    return loaded


def run_worker(
    root: pathlib.Path, brief: dict[str, Any], token: str = TOKEN, *, token_in: str = "file"
) -> tuple[int, str]:
    """Run the real entry point as a Job's pod would: `clone`, then `agent`, then `push`, each
    its own process with its own environment, sharing the workspace directory. Only `clone`
    and `push` are given the state directory and the token file. Returns the exit status and
    the result text (the termination message) of `push`, or of `clone` when it failed, as a
    failed init container ends the pod.

    With `token_in="env"` the token is instead put in the environment of all three, the agent
    step included: the worst a deployment could do.
    """
    trusted, untrusted = worker_env(root, brief, token, token_in=token_in)
    status, text = 0, ""
    for step in ("clone", "agent", "push"):
        done = subprocess.run(
            [sys.executable, "-m", "sortyard.services.worker", step],
            env=untrusted if step == "agent" else trusted,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert token not in done.stdout + done.stderr, f"{step} printed the token"
        status, text = done.returncode, (root / "result.json").read_text()
        if step == "agent":
            assert status == 0, "the agent container always exits 0"
        elif status != 0:
            break
    return status, text


def worker_env(
    root: pathlib.Path, brief: dict[str, Any], token: str = TOKEN, *, token_in: str = "file"
) -> tuple[dict[str, str], dict[str, str]]:
    """Lay out a Job's directories under `root` and give the environment of the containers
    that hold the token (`clone`, `push`) and of the one that does not (`agent`)."""
    root.mkdir(parents=True, exist_ok=True)
    for directory in ("work", "state"):
        (root / directory).mkdir(exist_ok=True)
    (root / "brief.json").write_text(json.dumps(brief))
    shared = {
        **{k: v for k, v in os.environ.items() if not k.startswith("SORTYARD_")},
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "SORTYARD_BRIEF": str(root / "brief.json"),
        "SORTYARD_WORKDIR": str(root / "work"),
        "SORTYARD_RESULT": str(root / "result.json"),
    }
    trusted = {**shared, "SORTYARD_STATE": str(root / "state")}
    # A lane secret the agent is meant to have: only the GitHub token is withheld.
    untrusted = {**shared, "MODEL_API_KEY": "model-key-for-the-agent"}
    if token_in == "file":
        (root / "token").write_text(token + "\n")
        trusted["SORTYARD_GITHUB_TOKEN_FILE"] = str(root / "token")
    else:
        trusted["SORTYARD_GITHUB_TOKEN"] = untrusted["SORTYARD_GITHUB_TOKEN"] = token
    return trusted, untrusted


def start_step(step: str, env: dict[str, str], result: pathlib.Path) -> subprocess.Popen[str]:
    """Start one step of the real entry point as its own process, as a container of the pod
    runs beside the others; its result (the termination message) lands in `result`."""
    return subprocess.Popen(
        [sys.executable, "-m", "sortyard.services.worker", step],
        env={**env, "SORTYARD_RESULT": str(result)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
