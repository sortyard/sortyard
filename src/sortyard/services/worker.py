"""sortyard-worker: what the containers of a worker Job run (HARNESS-V3 section 3.3).

The launcher (`sortyard.lane.worker`) starts one Job per dispatch. Its pod runs this entry
point three times, as three containers, so that the agent never shares a container with the
GitHub token:

- `sortyard-worker clone` (init container; holds the token): clones the item's repository
  twice. A bare clone goes to the state directory, which the agent's container does not mount;
  the agent's workspace is cloned from it. A build starts the work branch at the base branch's
  head; a fix starts it at its own head on the remote; a review checks that head out detached.
  Where the agent started and the branch head seen on the remote are written to the state
  directory, with a random key for this Job; a copy of the key is left in the workspace.
- `sortyard-worker agent` (no token, no secret volume): takes the key out of the workspace
  (reads it, deletes the file), then runs the configured agent command in the clone with the
  brief text on standard input and the seconds the Job has (the brief's `limit_seconds`, the
  Job's deadline) in `SORTYARD_LIMIT_SECONDS`; an agent that stops at that limit has its work
  pushed like any other. A review's answer is what the command's own process wrote to
  its standard output, read from a socket and held in memory. When the command has exited,
  every process it left is killed, and only then is the sentinel written: the exit status and
  the answer, with a keyed digest of both. The container exits 0.
- `sortyard-worker push` (holds the token): waits for the sentinel, checks its digest with the
  key in the state directory, and reports the result as the container's termination message.
  A sentinel that does not carry that digest is a failed result. It never runs git inside the
  agent's workspace: it fetches the agent's head from the workspace into the bare clone
  (reading the workspace as data, with no token), and pushes from the bare clone, whose
  configuration the agent never touched. A head with no commit beyond where the agent started
  is `no-change`. Otherwise the branch `sortyard/<item id>` is pushed with a lease on the head
  `clone` saw (so a build may replace what an earlier dispatch pushed, and nothing that moved
  since), the remote is read back, and the result is `built` or `fixed` only when the remote
  branch is at that head. For a review nothing is pushed: the agent's answer must end with
  one line holding a JSON object, `{"verdict":"approve"}` or
  `{"verdict":"findings","findings":[{"key":"...","text":"..."}]}`. The result is
  `approved`, or `findings` with the first finding's key as the one finding key. An answer
  that cannot be read that way is a failed result, never an approval.

What anything the agent command starts cannot do (SY-DEC-012 in DECISIONS.md): write the
sentinel or the answer. It runs as the entry point's user and can write every file of the
workspace, so the sentinel is not trusted for being a file there: it is trusted for the
digest, whose key it cannot read. The key is in no file it can open once the command starts,
and the entry point's memory is closed to it (the entry point is not dumpable, so the kernel
refuses same-user ptrace and its `/proc` files, and it does not run the command while holding
CAP_SYS_PTRACE, CAP_SYS_ADMIN or CAP_DAC_READ_SEARCH, or any capability as a user who is not
root; the command runs with no-new-privileges). The answer is not in a file at all: the kernel
names the writer of each piece read from the command's standard output, and only the command's
own process is heard (`AttestedOutput`, which a wrapper that relays a program's answer uses in
turn). What is left to such code is to make the result fail, or to act on the command process
itself (see SY-DEC-012 for the residual risk).

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
import contextlib
import ctypes
import fcntl
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

BRIEF_ENV, RESULT_ENV = "SORTYARD_BRIEF", "SORTYARD_RESULT"
WORK_ENV, STATE_ENV = "SORTYARD_WORKDIR", "SORTYARD_STATE"
TOKEN_ENV, TOKEN_FILE_ENV = "SORTYARD_GITHUB_TOKEN", "SORTYARD_GITHUB_TOKEN_FILE"
LIMIT_ENV = "SORTYARD_LIMIT_SECONDS"
TERMINATION_LOG = "/dev/termination-log"
TEXT_LIMIT, RESULT_BUDGET = 600, 3500
FAILED = "failed"
# In the workspace: the agent's clone, the sentinel the entry point seals once the agent ended
# (exit status, a review's answer, their keyed digest), and the key until `agent` takes it.
CLONE_DIR, SENTINEL, KEY = "clone", "agent-done", "agent-key"
# In the state directory: the bare clone, and what `clone` recorded for `push` (the key too).
ORIGIN, RECORD = "origin.git", "state.json"
# The end of a review's answer that is kept (its last line is the verdict), the most `push`
# reads of a sentinel, how long the agent's leftover processes are given to die, and how often
# `push` looks for the sentinel: bytes, bytes, seconds, seconds.
ANSWER_LIMIT, SENTINEL_LIMIT, REAP_SECONDS, POLL_SECONDS = 1 << 20, 8 << 20, 20.0, 0.2
PR_SET_DUMPABLE, PR_SET_CHILD_SUBREAPER, PR_SET_NO_NEW_PRIVS = 4, 36, 38  # <linux/prctl.h>
# Capabilities with which the agent command could read the entry point's memory (the key),
# write as another process, or open a file of the state volume by its handle (open_by_handle_at
# reaches files of the same filesystem that the container does not mount): the entry point
# does not run it while it holds one. As any user but root it holds none at all.
UNSAFE_CAPABILITIES = {
    "CAP_DAC_READ_SEARCH": 2,
    "CAP_SYS_PTRACE": 19,
    "CAP_SYS_ADMIN": 21,
}  # <linux/capability.h>
PROC_STATUS = "/proc/self/status"
# Room for the writer's credentials (pid, uid, gid) that come with each read of the answer.
CREDENTIALS = socket.CMSG_SPACE(struct.calcsize("3i"))


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


def _agent_env(brief: Mapping[str, Any]) -> dict[str, str]:
    """The agent's environment: this container's less the token, and the brief's limit."""
    limit = brief.get("limit_seconds")
    return {**_without_token(), **({LIMIT_ENV: str(limit)} if isinstance(limit, int) else {})}


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
    key = secrets.token_hex(32)
    (state / RECORD).write_text(json.dumps({"before": before, "seen": seen, "key": key}))
    _put(work / KEY, key)
    return {"outcome": "cloned", "head": before}


def _put(path: pathlib.Path, text: str) -> None:
    """Write `text` to a new file of our own and move it to `path`, whatever is there: a link
    there is replaced, not followed; a directory there is moved aside, which needs no access to
    it; a directory of ours made unwritable is made writable again."""
    try:
        handle, partial = tempfile.mkstemp(dir=path.parent, prefix=".sortyard-")
    except PermissionError:
        os.chmod(path.parent, stat.S_IMODE(os.stat(path.parent).st_mode) | stat.S_IRWXU)
        handle, partial = tempfile.mkstemp(dir=path.parent, prefix=".sortyard-")
    with os.fdopen(handle, "w") as file:
        file.write(text)
    try:
        os.replace(partial, path)
    except OSError:
        os.rename(path, f"{partial}.aside")
        os.replace(partial, path)


def _digest(key: str, status: str, answer: str) -> str:
    sealed = json.dumps([status, answer]).encode()
    return hmac.new(key.encode(), sealed, hashlib.sha256).hexdigest()


def _privileged(status: str) -> str:
    """The capability in `status` (a `/proc/<pid>/status` text) that would let the agent
    command read this process's memory, pass itself off as another process or open a file it
    was not given, if any; and for a process whose effective user is not root, any capability
    it holds (none is needed to run an agent)."""
    fields = dict(line.partition(":")[::2] for line in status.splitlines())
    held = 0
    for name in ("CapPrm", "CapEff", "CapAmb"):
        held |= int(fields.get(name, "0").strip() or "0", 16)
    for cap, bit in UNSAFE_CAPABILITIES.items():
        if held >> bit & 1:
            return cap
    uids = fields.get("Uid", "").split()
    if held and (len(uids) < 2 or uids[1] != "0"):
        return f"capabilities {held:#x} as a user who is not root"
    return ""


def _descendants() -> list[int]:
    """Every process started, however far down, by this one, as `/proc` shows them now."""
    parents: dict[int, int] = {}
    for entry in os.listdir("/proc"):
        if entry.isdigit():
            try:
                fields = pathlib.Path("/proc", entry, "stat").read_text().rsplit(")", 1)[1]
            except (OSError, IndexError):
                continue  # it ended while we looked
            parents[int(entry)] = int(fields.split()[1])
    mine, found = {os.getpid()}, True
    while found:
        found = False
        for pid, parent in parents.items():
            if parent in mine and pid not in mine:
                mine.add(pid)
                found = True
    return sorted(mine - {os.getpid()})


def _kill_descendants() -> bool:
    """Kill every process the agent command left and collect them; whether none is left.

    A process whose parent ends is re-parented to this one (the container's first process, and
    a child subreaper wherever it is not), so leaving the process group or the session does not
    take it out of reach, and "this process has no child" means no process it started lives:
    that, from `waitpid`, is the test, not a scan of `/proc`, which a process can slip past."""
    until = time.monotonic() + REAP_SECONDS
    while True:
        for pid in _descendants():
            with contextlib.suppress(OSError):  # gone already
                os.kill(pid, signal.SIGKILL)
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            return True
        if time.monotonic() > until:
            return False
        time.sleep(0.01)


def _start(
    argv: Sequence[str], text: str, cwd: pathlib.Path, stdout: int | None, env: dict[str, str]
) -> Any:
    """Start the agent command with `text` on its standard input, fed from a thread."""
    child = subprocess.Popen(list(argv), stdin=subprocess.PIPE, stdout=stdout, cwd=cwd, env=env)

    def feed() -> None:
        assert child.stdin is not None
        try:
            with child.stdin as stdin:
                stdin.write(text.encode())
        except OSError:
            pass  # the command did not read its input to the end

    threading.Thread(target=feed, daemon=True).start()
    return child


class AttestedOutput:
    """The standard output of one child process, as only that process wrote it.

    The channel a wrapper uses when it prints an answer it got from a program it runs (an agent
    command that runs Claude Code and post-processes its output): the worker attests only its
    own child, so the wrapper must attest its own in the same way, and a file or a pipe is no
    such channel. Code the program runs can rename a file over the one the wrapper reads, and
    can open a pipe again through `/proc/<pid>/fd` (that needs only PTRACE_MODE_READ, which Yama
    `ptrace_scope` 1 does not refuse). This is one end of a Unix socket pair, which `/proc`
    does not open again; with `SO_PASSCRED` the kernel names the process that wrote each piece
    read and never joins two writers' pieces in one read, and a writer can claim another's pid
    only with CAP_SYS_ADMIN over our pid namespace. Only the child's own pieces are kept; what
    other processes write there (ones the child gave the socket to, or that took it) goes to
    `echo` if one is given, and is never part of what `collect` returns.

        with AttestedOutput() as output:
            child = subprocess.Popen(argv, stdout=output.child_fd, ...)
            output.started()
            answer = output.collect(child, timeout=limit)  # bytes; the child is not reaped

    The caller must not let the child, or code the child runs, act on the caller's own
    process: run it with `ptrace_scope` 1 or more, make the caller non-dumpable, and do not
    reap the child (or let anything else reap it) before `collect` returns, so that its pid is
    not given to another process while its output is read.
    """

    def __init__(self, echo: Any = None, limit: int = ANSWER_LIMIT) -> None:
        self._ours, self._theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self._ours.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        self._echo, self._limit = echo, limit

    @property
    def child_fd(self) -> int:
        """The descriptor to give the child as its standard output."""
        return self._theirs.fileno()

    def started(self) -> None:
        """Close our copy of the child's end, once the child holds it."""
        self._theirs.close()

    def close(self) -> None:
        self._theirs.close()
        self._ours.close()

    def __enter__(self) -> AttestedOutput:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def collect(self, child: subprocess.Popen[Any], timeout: float | None = None) -> bytes:
        """The last `limit` bytes the child's own process wrote, read until it exits (its exit
        is seen without reaping it) and then up to what was queued at that moment: a process
        left holding the socket cannot make this wait. `subprocess.TimeoutExpired` when the
        child runs past `timeout` seconds; it is then still running."""
        self.started()
        until = None if timeout is None else time.monotonic() + timeout
        answer, left = b"", -1  # left: the bytes still to read once the child has ended
        while left:
            if left < 0 and os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT):
                queued = fcntl.ioctl(self._ours.fileno(), termios.FIONREAD, b"\0" * 4)
                left = struct.unpack("i", queued)[0]
                continue
            if left < 0 and until is not None and time.monotonic() > until:
                raise subprocess.TimeoutExpired(child.args, timeout or 0.0, answer)
            if left < 0 and not select.select([self._ours], [], [], 0.05)[0]:
                continue
            size = 65536 if left < 0 else min(left, 65536)
            try:
                data, extra, _, _ = self._ours.recvmsg(size, CREDENTIALS, socket.MSG_DONTWAIT)
            except BlockingIOError:
                if left > 0:
                    break  # what was queued is gone: not ours to wait for
                continue
            if not data:
                break  # every holder closed it: nothing more can come
            writer = [
                struct.unpack("i", body[:4])[0]
                for level, kind, body in extra
                if (level, kind) == (socket.SOL_SOCKET, socket.SCM_CREDENTIALS)
            ]
            if self._echo is not None:
                self._echo.write(data)
            if writer == [child.pid]:
                answer = (answer + data)[-self._limit :]
            left -= len(data) if left > 0 else 0
        if self._echo is not None:
            self._echo.flush()
        return answer


def _run(
    argv: Sequence[str], text: str, cwd: pathlib.Path, capture: bool, env: dict[str, str]
) -> tuple[int, str]:
    """Run the agent command to its exit: its exit status and, with `capture`, the end of what
    the command's own process wrote to its standard output (`AttestedOutput`). Everything
    written there is copied to our output; only the command's own pieces are its answer."""
    if not capture:
        return _start(argv, text, cwd, None, env).wait(), ""
    with AttestedOutput(echo=sys.stdout.buffer) as output:
        child = _start(argv, text, cwd, output.child_fd, env)
        answer = output.collect(child)
    return child.wait(), answer.decode(errors="replace")


def agent(brief: Mapping[str, Any], work: pathlib.Path) -> dict[str, Any]:
    """Run the agent command in the clone; once it and everything it started are gone, seal
    its exit status and its answer in the sentinel."""
    unsafe = _privileged(pathlib.Path(PROC_STATUS).read_text())
    if unsafe:
        raise WorkerError(f"the agent container holds {unsafe}: the answer could not be sealed")
    key = (work / KEY).read_text()
    (work / KEY).unlink()
    # Nothing the command starts may read the key from this process or gain a privilege
    # through a program it runs, and every process it leaves must stay findable. Without all
    # three, the command does not run.
    libc = ctypes.CDLL(None, use_errno=True)
    for option in (PR_SET_DUMPABLE, PR_SET_NO_NEW_PRIVS, PR_SET_CHILD_SUBREAPER):
        if libc.prctl(option, 0 if option == PR_SET_DUMPABLE else 1, 0, 0, 0):
            raise WorkerError(f"prctl failed: {os.strerror(ctypes.get_errno())}")
    status, answer = "127", ""
    try:
        argv = [str(part) for part in brief["agent"]]
        text, capture = str(brief.get("text") or ""), brief["mode"] == "review"
        code, answer = _run(argv, text, work / CLONE_DIR, capture, _agent_env(brief))
        status = str(code)
    except OSError as error:
        print(f"the agent command could not be run: {error}", file=sys.stderr)
    finally:
        if not _kill_descendants():
            status = "with processes that could not be killed"
        sealed = {"status": status, "answer": answer, "digest": _digest(key, status, answer)}
        _put(work / SENTINEL, json.dumps(sealed))
    return {"outcome": "agent-ended", "status": status}


def _sealed(work: pathlib.Path, key: str) -> tuple[str, str]:
    """Wait for the sentinel; the exit status and the answer in it, when the entry point of
    the agent container sealed them. Anything else at that path is `WorkerError`."""
    path = work / SENTINEL
    while not os.path.lexists(path):
        time.sleep(POLL_SECONDS)  # the Job's deadline bounds this wait
    try:
        # Not through a link, and never blocking on what was put there.
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise ValueError("not a file")
            sealed = json.loads(file.read(SENTINEL_LIMIT))
        status, answer, digest = sealed["status"], sealed["answer"], sealed["digest"]
        if not all(isinstance(part, str) for part in (status, answer, digest)):
            raise ValueError("not text")
        if not hmac.compare_digest(digest.encode(), _digest(key, status, answer).encode()):
            raise ValueError("another digest")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise WorkerError(
            "the agent-ended sentinel was not written by the worker's entry point"
        ) from error
    return status, answer


def push(brief: Mapping[str, Any], work: pathlib.Path, state: pathlib.Path) -> dict[str, Any]:
    """Wait for the agent to end, then report: push its commits, or read its review."""
    mode, branch, url = str(brief["mode"]), str(brief["branch"]), str(brief["clone_url"])
    record = json.loads((state / RECORD).read_text())
    status, answer = _sealed(work, str(record["key"]))
    if status != "0":
        raise WorkerError(f"the agent command exited {status[:40]}")
    before, seen, origin = str(record["before"]), str(record["seen"]), state / ORIGIN
    if mode == "review":
        return _verdict(answer, before)
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
            # The agent never ran: leave an unsealed sentinel, so that `push` does not wait
            # for it and reports a failed result.
            with contextlib.suppress(OSError):  # then the Job's deadline ends the wait
                _put(pathlib.Path(os.environ[WORK_ENV]) / SENTINEL, "no agent")
        result = {"outcome": FAILED, "reason": reason}
    text = json.dumps(result, separators=(",", ":"))
    print(text, flush=True)
    pathlib.Path(os.environ.get(RESULT_ENV) or TERMINATION_LOG).write_text(text)
    return 1 if result["outcome"] == FAILED and step != ["agent"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
