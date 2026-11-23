"""sortyard-worker: what the containers of a worker Job run (HARNESS-V3 section 3.3).

The launcher (`sortyard.lane.worker`) starts one Job per dispatch. Its pod runs this entry
point three times, as three containers, so that the agent never shares a container with the
GitHub token:

- `sortyard-worker clone` (init container; holds the token): clones the item's repository
  twice. A bare clone goes to the state directory, which the agent's container does not mount;
  the agent's workspace is cloned from it. A build starts the work branch at the base branch's
  head; a fix starts it at its own head on the remote; a review checks that head out detached.
  Where the agent started and the branch head seen on the remote are written to the state
  directory.
- `sortyard-worker agent` (no token, no secret volume): runs the configured agent command in
  the workspace with the brief text on standard input, then always writes the command's exit
  status to a sentinel file in the workspace and exits 0.
- `sortyard-worker push` (holds the token): waits for the sentinel and reports the result as
  the container's termination message. It never runs git inside the agent's workspace: it
  fetches the agent's head from the workspace into the bare clone (reading the workspace as
  data, with no token), and pushes from the bare clone, whose configuration the agent never
  touched. A head with no commit beyond where the agent started is `no-change`. Otherwise the
  branch `sortyard/<item id>` is pushed with a lease on the head `clone` saw (so a build may
  replace what an earlier dispatch pushed, and nothing that moved since), the remote is read
  back, and the result is `built` or `fixed` only when the remote branch is at that head.
  For a review nothing is pushed: the agent's answer must end with one line holding a JSON
  object, `{"verdict":"approve"}` or `{"verdict":"findings","findings":[{"key":"...",
  "text":"..."}]}`. The result is `approved`, or `findings` with the first finding's key as
  the one finding key. An answer that cannot be read that way is a failed result, never an
  approval.

Every result carries the head commit. A failed result (`{"outcome":"failed","reason":...}`,
exit status 1) is no outcome: the launcher's observer gives no reply for it.

The token reaches git alone, as a request header set through git's environment for the one
command that needs it and bound to the clone URL: never on a command line, in a repository's
configuration or in a remote URL. It is read from its file when it is used, so a token the
launcher refreshed is the one that pushes. Its value is cut from every message. git runs
without the host's or the user's configuration.

The termination message is capped at 4096 bytes by Kubernetes, so the result is kept compact:
each finding's text is cut to 600 characters, trailing findings are dropped (and counted in
`dropped`), and the leading finding's text is cut further until the result is under 3500
bytes.

Configuration: `SORTYARD_BRIEF` (the brief file), `SORTYARD_WORKDIR` (the workspace volume),
`SORTYARD_STATE` (the state volume of `clone` and `push`), `SORTYARD_GITHUB_TOKEN_FILE` or
`SORTYARD_GITHUB_TOKEN` (the token, for `clone` and `push`) and `SORTYARD_RESULT` (where the
result is written; the termination log unless set).
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

BRIEF_ENV, RESULT_ENV = "SORTYARD_BRIEF", "SORTYARD_RESULT"
WORK_ENV, STATE_ENV = "SORTYARD_WORKDIR", "SORTYARD_STATE"
TOKEN_ENV, TOKEN_FILE_ENV = "SORTYARD_GITHUB_TOKEN", "SORTYARD_GITHUB_TOKEN_FILE"
TERMINATION_LOG = "/dev/termination-log"
TEXT_LIMIT, RESULT_BUDGET = 600, 3500
FAILED = "failed"
# In the workspace: the agent's clone, its exit status once it ended, and a review's answer.
CLONE_DIR, SENTINEL, ANSWER = "clone", "agent-done", "agent-output"
# In the state directory: the bare clone, and what `clone` recorded for `push`.
ORIGIN, RECORD = "origin.git", "state.json"


class WorkerError(Exception):
    """The worker could not do its job; the message becomes the failed result's reason."""


def _token() -> str:
    if os.environ.get(TOKEN_FILE_ENV):
        return pathlib.Path(os.environ[TOKEN_FILE_ENV]).read_text().strip()
    return os.environ.get(TOKEN_ENV, "")


def _basic(token: str) -> str:
    return base64.b64encode(f"x-access-token:{token}".encode()).decode()


def scrub(text: str, token: str) -> str:
    """`text` without the token, plain or as git sends it."""
    for hidden in (token, _basic(token)) if token else ():
        text = text.replace(hidden, "***")
    return text


def _without_token() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in (TOKEN_ENV, TOKEN_FILE_ENV)}


def git(*args: str, cwd: pathlib.Path, url: str = "") -> str:
    """Run git in `cwd` with no host or user configuration; `url` names the remote the
    command talks to, and it alone is sent the token."""
    env = _without_token()
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    token = _token() if url else ""
    if token:
        env.update(
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0=f"http.{url}.extraheader",
            GIT_CONFIG_VALUE_0=f"Authorization: Basic {_basic(token)}",
        )
    done = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        tail = scrub(done.stderr.strip(), token)[-300:]
        raise WorkerError(f"git {args[0]} exited {done.returncode}: {tail}")
    return done.stdout.strip()


def _verdict(answer: str, head: str) -> dict[str, Any]:
    """The review result in the agent's answer, or `WorkerError` when it holds none."""
    lines = [line for line in answer.splitlines() if line.strip()]
    try:
        verdict = json.loads(lines[-1]) if lines else None
    except ValueError:
        verdict = None
    if not isinstance(verdict, Mapping):
        raise WorkerError("the review answer does not end with a JSON object")
    findings = verdict.get("findings")
    if verdict.get("verdict") == "approve" and not findings:
        return {"outcome": "approved", "head": head}
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

    def fits() -> bool:
        return len(json.dumps(result).encode()) <= RESULT_BUDGET

    while not fits() and len(kept) > 1:
        kept.pop()
        result["dropped"] = len(findings) - len(kept)
    while not fits() and len(kept[0]["text"]) > 1:
        kept[0]["text"] = kept[0]["text"][: len(kept[0]["text"]) * 9 // 10]
    return result


def clone(brief: Mapping[str, Any], work: pathlib.Path, state: pathlib.Path) -> dict[str, Any]:
    """Make the bare clone and the agent's workspace, and record where the agent starts."""
    mode, branch, url = str(brief["mode"]), str(brief["branch"]), str(brief["clone_url"])
    origin, workspace = state / ORIGIN, work / CLONE_DIR
    git("clone", "--quiet", "--bare", url, str(origin), cwd=state, url=url)
    try:
        seen = git("rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=origin)
    except WorkerError:
        seen = ""  # the work branch is not on the remote yet
    # No hard links: the agent must not hold the bare clone's own object files.
    git("clone", "--quiet", "--no-hardlinks", str(origin), str(workspace), cwd=work)
    git("remote", "set-url", "origin", url, cwd=workspace)
    if mode == "build":
        git(
            "checkout",
            "--quiet",
            "-B",
            branch,
            f"refs/remotes/origin/{brief['base']}",
            cwd=workspace,
        )
    elif not seen:
        raise WorkerError(f"the branch {branch} is not on the remote")
    elif mode == "fix":
        git("checkout", "--quiet", "-B", branch, seen, cwd=workspace)
    else:
        git("checkout", "--quiet", "--detach", seen, cwd=workspace)
    git("config", "user.name", str(brief.get("author_name") or "sortyard-worker"), cwd=workspace)
    email = str(brief.get("author_email") or "worker@sortyard.invalid")
    git("config", "user.email", email, cwd=workspace)
    before = git("rev-parse", "--verify", "HEAD^{commit}", cwd=workspace)
    (state / RECORD).write_text(json.dumps({"before": before, "seen": seen}))
    return {"outcome": "cloned", "head": before}


def agent(brief: Mapping[str, Any], work: pathlib.Path) -> dict[str, Any]:
    """Run the agent command in the workspace and leave its exit status in the sentinel."""
    status = 127
    try:
        with (work / ANSWER).open("w") as answer:
            status = subprocess.run(
                [str(part) for part in brief["agent"]],
                input=str(brief.get("text") or ""),
                cwd=work / CLONE_DIR,
                env=_without_token(),
                stdout=answer if brief["mode"] == "review" else None,
                text=True,
                check=False,
            ).returncode
        sys.stdout.write((work / ANSWER).read_text())
    finally:
        partial = work / f"{SENTINEL}.tmp"
        partial.write_text(str(status))
        partial.replace(work / SENTINEL)
    return {"outcome": "agent-ended", "status": status}


def push(brief: Mapping[str, Any], work: pathlib.Path, state: pathlib.Path) -> dict[str, Any]:
    """Wait for the agent to end, then report: push its commits, or read its review."""
    mode, branch, url = str(brief["mode"]), str(brief["branch"]), str(brief["clone_url"])
    while not (work / SENTINEL).exists():
        time.sleep(1)  # the Job's deadline bounds this wait
    status = (work / SENTINEL).read_text().strip()
    if status != "0":
        raise WorkerError(f"the agent command exited {status[:20]}")
    record = json.loads((state / RECORD).read_text())
    before, seen, origin = str(record["before"]), str(record["seen"]), state / ORIGIN
    if mode == "review":
        return _verdict((work / ANSWER).read_text(), before)
    # The workspace is read as data: fetched by path from the bare clone, with no token.
    git("fetch", "--quiet", "--no-tags", (work / CLONE_DIR).as_uri(), "HEAD", cwd=origin)
    head = git("rev-parse", "--verify", "FETCH_HEAD^{commit}", cwd=origin)
    if int(git("rev-list", "--count", f"{before}..{head}", cwd=origin)) == 0:
        return {"outcome": "no-change", "head": before}
    ref = f"refs/heads/{branch}"
    lease = f"--force-with-lease={ref}:{seen}"
    git("push", "--quiet", lease, url, f"{head}:{ref}", cwd=origin, url=url)
    if git("ls-remote", url, ref, cwd=origin, url=url).split()[:1] != [head]:
        raise WorkerError(f"the remote branch {branch} is not at the pushed head")
    return {"outcome": "built" if mode == "build" else "fixed", "head": head}


def main(argv: Sequence[str] | None = None) -> int:
    step = (sys.argv[1:] if argv is None else list(argv))[:1]
    result: dict[str, Any]
    try:
        if step not in (["clone"], ["agent"], ["push"]):
            raise WorkerError("usage: sortyard-worker clone|agent|push")
        brief = json.loads(pathlib.Path(os.environ[BRIEF_ENV]).read_text())
        if brief.get("mode") not in ("build", "fix", "review") or not brief.get("agent"):
            raise WorkerError("the brief names no work this worker does")
        work = pathlib.Path(os.environ[WORK_ENV])
        if step == ["agent"]:
            result = agent(brief, work)
        else:
            run = clone if step == ["clone"] else push
            result = run(brief, work, pathlib.Path(os.environ[STATE_ENV]))
    except Exception as error:
        try:
            token = _token()
        except OSError:
            token = ""
        reason = scrub(f"{type(error).__name__}: {error}", token)[:500]
        if step == ["agent"] and WORK_ENV in os.environ:
            # The agent never ran: say so, so that `push` does not wait for it.
            (pathlib.Path(os.environ[WORK_ENV]) / SENTINEL).write_text("no agent")
        result = {"outcome": FAILED, "reason": reason}
    text = json.dumps(result, separators=(",", ":"))
    print(text, flush=True)
    pathlib.Path(os.environ.get(RESULT_ENV) or TERMINATION_LOG).write_text(text)
    return 1 if result["outcome"] == FAILED and step != ["agent"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
