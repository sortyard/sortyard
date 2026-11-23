"""sortyard-worker: the entry point inside a worker Job (HARNESS-V3 section 3.3).

The launcher (`sortyard.lane.worker`) starts one Job per dispatch and this is what the Job
runs. It reads its brief, clones the item's repository, runs the configured agent command, and
reports one result as the container's termination message:

- **build**: the work branch starts at the base branch's head. After the agent, a head that
  has not moved is `no-change`; otherwise the branch is pushed and the result is `built`.
- **fix**: the work branch starts at its own head on the remote. A head that has not moved is
  `no-change`; otherwise the branch is pushed and the result is `fixed`.
- **review**: the work branch's head is checked out and nothing is pushed. The agent's answer
  must end with one line holding a JSON object, `{"verdict":"approve"}` or
  `{"verdict":"findings","findings":[{"key":"...","text":"..."}]}`. The result is `approved`,
  or `findings` with the first finding's key as the one finding key. An answer that cannot be
  read that way is a failed result, never an approval.

Every result carries the head commit. A failed result (`{"outcome":"failed","reason":...}`,
exit status 1) is no outcome: the launcher's observer gives no reply for it.

The agent never holds the GitHub token. The token reaches git alone, as a request header set
through git's environment for the one command that needs it and bound to the clone URL: it is
not in the agent's environment, not on a command line, and not in the clone's configuration or
remote URL. The push names the clone URL and runs no hook, so nothing the agent left in the
clone runs with the token or redirects it. The token's value is cut from every message.

The termination message is capped at 4096 bytes by Kubernetes, so the result is kept compact:
each finding's text is cut to 600 characters and trailing findings are dropped (and counted in
`dropped`) until the result is under 3500 bytes.

Configuration: `SORTYARD_BRIEF` (the brief file), `SORTYARD_GITHUB_TOKEN_FILE` or
`SORTYARD_GITHUB_TOKEN` (the token), `SORTYARD_WORKDIR` (where the clone goes) and
`SORTYARD_RESULT` (where the result is written; the termination log unless set).
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from typing import Any

BRIEF_ENV, RESULT_ENV, WORK_ENV = "SORTYARD_BRIEF", "SORTYARD_RESULT", "SORTYARD_WORKDIR"
TOKEN_ENV, TOKEN_FILE_ENV = "SORTYARD_GITHUB_TOKEN", "SORTYARD_GITHUB_TOKEN_FILE"
TERMINATION_LOG = "/dev/termination-log"
TEXT_LIMIT, RESULT_BUDGET = 600, 3500
FAILED = "failed"


class WorkerError(Exception):
    """The worker could not do its job; the message becomes the failed result's reason."""


class Git:
    """git in one clone, with the token given to the commands that talk to the remote."""

    def __init__(self, url: str, token: str, directory: pathlib.Path) -> None:
        self.url, self.directory = url, directory
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        self._hidden = [value for value in (token, basic) if token]
        self._auth = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.{url}.extraheader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        }

    def scrub(self, text: str) -> str:
        for value in self._hidden:
            text = text.replace(value, "***")
        return text

    def agent_environment(self) -> dict[str, str]:
        """This process's environment without the token, in any variable."""
        return {
            name: value
            for name, value in os.environ.items()
            if name not in (TOKEN_ENV, TOKEN_FILE_ENV)
            and not any(hidden in value for hidden in self._hidden)
        }

    def __call__(self, *args: str, remote: bool = False, cwd: pathlib.Path | None = None) -> str:
        env = {**self.agent_environment(), "GIT_TERMINAL_PROMPT": "0"}
        if remote and self._hidden:
            env.update(self._auth)
        done = subprocess.run(
            ["git", *args],
            cwd=cwd or self.directory,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            tail = self.scrub(done.stderr.strip())[-300:]
            raise WorkerError(f"git {args[0]} exited {done.returncode}: {tail}")
        return done.stdout.strip()

    def head(self, ref: str = "HEAD") -> str:
        return self("rev-parse", "--verify", f"{ref}^{{commit}}")


def _verdict(answer: str, head: str) -> dict[str, Any]:
    """The review result in the agent's answer, or `WorkerError` when it holds none."""
    lines = [line for line in answer.splitlines() if line.strip()]
    try:
        verdict = json.loads(lines[-1]) if lines else None
    except ValueError:
        verdict = None
    if not isinstance(verdict, Mapping):
        raise WorkerError("the review answer does not end with a JSON object")
    if verdict.get("verdict") == "approve":
        return {"outcome": "approved", "head": head}
    findings = verdict.get("findings")
    if verdict.get("verdict") != "findings" or not isinstance(findings, list) or not findings:
        raise WorkerError("the review verdict is neither approve nor findings with a finding")
    kept: list[dict[str, str]] = []
    for finding in findings:
        key = finding.get("key") if isinstance(finding, Mapping) else None
        text = finding.get("text") if isinstance(finding, Mapping) else None
        slug = (
            re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:80] if isinstance(key, str) else ""
        )
        if not slug or not isinstance(text, str) or not text.strip():
            raise WorkerError("a review finding has no key or no text")
        kept.append({"key": slug, "text": text.strip()[:TEXT_LIMIT]})
    result: dict[str, Any] = {
        "outcome": "findings",
        "head": head,
        "finding": kept[0]["key"],
        "findings": kept,
    }
    while len(json.dumps(result).encode()) > RESULT_BUDGET and len(kept) > 1:
        kept.pop()
        result["dropped"] = len(findings) - len(kept)
    if len(json.dumps(result).encode()) > RESULT_BUDGET:
        raise WorkerError("the leading review finding does not fit the result")
    return result


def run(brief: Mapping[str, Any], token: str, workdir: pathlib.Path) -> dict[str, Any]:
    """Do the brief's work in a fresh clone under `workdir` and return the result."""
    mode, branch, base = str(brief["mode"]), str(brief["branch"]), str(brief["base"])
    argv = [str(part) for part in brief["agent"]]
    if mode not in ("build", "fix", "review") or not argv:
        raise WorkerError(f"the brief names no work this worker does: mode {mode!r}")
    clone = pathlib.Path(tempfile.mkdtemp(prefix="clone-", dir=workdir))
    git = Git(str(brief["clone_url"]), token, clone)
    git("clone", "--quiet", git.url, str(clone), remote=True, cwd=workdir)
    try:
        seen = git.head(f"refs/remotes/origin/{branch}")
    except WorkerError:
        seen = ""  # the work branch is not on the remote yet
    if mode == "build":
        git("checkout", "--quiet", "-B", branch, f"refs/remotes/origin/{base}")
    elif not seen:
        raise WorkerError(f"the branch {branch} is not on the remote")
    elif mode == "fix":
        git("checkout", "--quiet", "-B", branch, seen)
    else:
        git("checkout", "--quiet", "--detach", seen)
    before = git.head()
    git("config", "user.name", str(brief.get("author_name") or "sortyard-worker"))
    git("config", "user.email", str(brief.get("author_email") or "worker@sortyard.invalid"))

    agent = subprocess.run(
        argv,
        input=str(brief.get("text") or ""),
        cwd=clone,
        env=git.agent_environment(),
        stdout=subprocess.PIPE if mode == "review" else None,
        text=True,
        check=False,
    )
    if agent.returncode != 0:
        raise WorkerError(f"the agent command exited {agent.returncode}")
    if mode == "review":
        sys.stdout.write(git.scrub(agent.stdout))
        return _verdict(agent.stdout, before)
    head = git.head()
    if head == before:
        return {"outcome": "no-change", "head": head}
    git(
        "-c",
        "core.hooksPath=/dev/null",
        "push",
        "--quiet",
        f"--force-with-lease=refs/heads/{branch}:{seen}",
        git.url,
        f"{head}:refs/heads/{branch}",
        remote=True,
    )
    return {"outcome": "built" if mode == "build" else "fixed", "head": head}


def main(argv: Sequence[str] | None = None) -> int:
    del argv  # configured by the Job's environment alone
    token = os.environ.get(TOKEN_ENV, "")
    result: dict[str, Any]
    try:
        if os.environ.get(TOKEN_FILE_ENV):
            token = pathlib.Path(os.environ[TOKEN_FILE_ENV]).read_text().strip()
        brief = json.loads(pathlib.Path(os.environ[BRIEF_ENV]).read_text())
        workdir = pathlib.Path(os.environ.get(WORK_ENV) or tempfile.mkdtemp(prefix="sortyard-"))
        result = run(brief, token, workdir)
    except Exception as error:
        reason = f"{type(error).__name__}: {error}"
        if token:
            reason = Git("", token, pathlib.Path()).scrub(reason)
        result = {"outcome": FAILED, "reason": reason[:500]}
    text = json.dumps(result, separators=(",", ":"))
    print(text, flush=True)
    pathlib.Path(os.environ.get(RESULT_ENV) or TERMINATION_LOG).write_text(text)
    return 1 if result["outcome"] == FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
