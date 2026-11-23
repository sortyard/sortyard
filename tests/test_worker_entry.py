"""Acceptance (SY-V3-WORKER-LAUNCHER): the entry point inside a worker Job.

`sortyard-worker` runs for real, as a child process, against local git repositories: a bare
repository on disk is the remote, cloned over `file://`, and the agent is a scripted command
that writes down the environment, input and clone it was given. One test serves the clone URL
over real HTTP in this process to read the header git sends. Nothing reaches a network.
"""

from __future__ import annotations

import base64
import json
import pathlib
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from sortyard.services import worker as entry
from tests.worker_harness import (
    TOKEN,
    agent_command,
    git,
    make_remote,
    remote_head,
    run_worker,
    seen,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRANCH = "sortyard/ITEM-7"
BASIC = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()


def brief(bare: pathlib.Path, mode: str, agent: list[str], **over: Any) -> dict[str, Any]:
    made = {
        "version": 1,
        "mode": mode,
        "tenant": "acme",
        "item": "ITEM-7",
        "dispatch": 3,
        "repository": "walwarden/app",
        "clone_url": bare.as_uri(),
        "base": "main",
        "branch": BRANCH,
        "spec": {"outcome": "the thing works"},
        "agent": agent,
        "text": "Build ITEM-7: the thing works.\n",
    }
    return {**made, **over}


def push_branch(tmp_path: pathlib.Path, bare: pathlib.Path, *files: str) -> str:
    """Put the work branch on the remote with one commit per file; returns its head."""
    clone = tmp_path / f"author-{len(list(tmp_path.iterdir()))}"
    git("clone", "--quiet", bare.as_uri(), str(clone), cwd=tmp_path)
    git("checkout", "--quiet", "-B", BRANCH, cwd=clone)
    if remote_head(bare, BRANCH):
        git("reset", "--quiet", "--hard", f"origin/{BRANCH}", cwd=clone)
    for name in files:
        (clone / name).write_text("by the author\n")
        git("add", name, cwd=clone)
        git("commit", "--quiet", "-m", f"add {name}", cwd=clone)
    git("push", "--quiet", "origin", BRANCH, cwd=clone)
    return git("rev-parse", "HEAD", cwd=clone)


def test_the_entry_point_runs_the_agent_command_without_the_github_token_and_pushes_the_branch_to_a_local_remote(  # noqa: E501
    tmp_path: pathlib.Path,
) -> None:
    """The entry point runs the agent command without the GitHub token and pushes the branch to
    a local remote."""
    bare = make_remote(tmp_path)
    base = remote_head(bare, "main")
    job = tmp_path / "job"
    status, text = run_worker(job, brief(bare, "build", agent_command(tmp_path, "commit:new.txt")))
    result = json.loads(text)
    assert status == 0
    # The branch is on the remote, at the commit the agent made on top of the base.
    head = remote_head(bare, BRANCH)
    assert head is not None and head != base
    assert result == {"outcome": "built", "head": head}
    assert git("rev-parse", f"{head}^", cwd=bare) == base
    assert git("show", f"{head}:new.txt", cwd=bare) == "made by the agent"
    assert remote_head(bare, "main") == base
    # What the agent was given: the brief text, the clone on the work branch, at the base.
    agent = seen(tmp_path)
    assert agent["stdin"] == "Build ITEM-7: the thing works.\n"
    assert pathlib.Path(agent["cwd"]).parent == job / "work"
    assert (agent["branch"], agent["head"], agent["files"]) == (BRANCH, base, ["README.md"])
    # What it was not given: the token, in any form, anywhere it could read it from its
    # environment or the clone.
    for hidden in (TOKEN, BASIC):
        assert hidden not in json.dumps(agent["env"])
        assert hidden not in agent["config"] and hidden not in agent["remotes"]
    assert "SORTYARD_GITHUB_TOKEN" not in agent["env"]
    assert "SORTYARD_GITHUB_TOKEN_FILE" not in agent["env"]
    assert not any(name.startswith("GIT_CONFIG_KEY") for name in agent["env"])
    # The rest of the environment is the worker's own: a lane secret reaches the agent.
    assert agent["env"]["MODEL_API_KEY"] == "model-key-for-the-agent"
    # The token is nowhere in what the worker left on disk either.
    for path in (job / "work").rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes(), path
            assert BASIC.encode() not in path.read_bytes(), path


def test_the_token_is_withheld_when_it_arrives_in_the_environment(tmp_path: pathlib.Path) -> None:
    """The token delivered as an environment variable is removed from the agent's environment."""
    bare = make_remote(tmp_path)
    status, text = run_worker(
        tmp_path / "job",
        brief(bare, "build", agent_command(tmp_path, "commit:new.txt")),
        token_in="env",
    )
    assert (status, json.loads(text)["outcome"]) == (0, "built")
    env = seen(tmp_path)["env"]
    assert TOKEN not in json.dumps(env) and "SORTYARD_GITHUB_TOKEN" not in env


def test_the_entry_point_reports_no_change_when_the_agent_committed_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """The entry point reports no-change when the agent committed nothing."""
    bare = make_remote(tmp_path)
    base = remote_head(bare, "main")
    status, text = run_worker(
        tmp_path / "job", brief(bare, "build", agent_command(tmp_path, "say:x"))
    )
    assert status == 0
    assert json.loads(text) == {"outcome": "no-change", "head": base}
    assert remote_head(bare, BRANCH) is None  # nothing was pushed
    # A build never reports the work of an earlier dispatch as its own: with the branch on
    # the remote already, the agent still starts at the base, and committing nothing is
    # no-change.
    earlier = push_branch(tmp_path, bare, "earlier.txt")
    status, text = run_worker(
        tmp_path / "job2", brief(bare, "build", agent_command(tmp_path, "say:x"))
    )
    assert json.loads(text) == {"outcome": "no-change", "head": base}
    assert seen(tmp_path)["files"] == ["README.md"]
    assert remote_head(bare, BRANCH) == earlier


def test_a_rebuild_replaces_the_branch_an_earlier_dispatch_pushed(tmp_path: pathlib.Path) -> None:
    """A build after an earlier one starts from the base and replaces the branch it saw."""
    bare = make_remote(tmp_path)
    base = remote_head(bare, "main")
    push_branch(tmp_path, bare, "earlier.txt")
    status, text = run_worker(
        tmp_path / "job", brief(bare, "build", agent_command(tmp_path, "commit:again.txt"))
    )
    head = remote_head(bare, BRANCH)
    assert head is not None
    assert (status, json.loads(text)) == (0, {"outcome": "built", "head": head})
    assert git("rev-parse", f"{head}^", cwd=bare) == base


def test_a_fix_starts_from_the_branch_head_and_reports_fixed_or_no_change(
    tmp_path: pathlib.Path,
) -> None:
    """A fix starts from the branch's own head: a new commit is fixed, none is no-change."""
    bare = make_remote(tmp_path)
    before = push_branch(tmp_path, bare, "feature.txt")
    fix = brief(bare, "fix", agent_command(tmp_path, "say:nothing to do"), finding={"finding": "k"})
    status, text = run_worker(tmp_path / "job", fix)
    assert (status, json.loads(text)) == (0, {"outcome": "no-change", "head": before})
    assert remote_head(bare, BRANCH) == before

    fix["agent"] = agent_command(tmp_path, "commit:fix.txt")
    status, text = run_worker(tmp_path / "job2", fix)
    head = remote_head(bare, BRANCH)
    assert head is not None
    assert (status, json.loads(text)) == (0, {"outcome": "fixed", "head": head})
    assert git("rev-parse", f"{head}^", cwd=bare) == before
    assert seen(tmp_path)["files"] == ["README.md", "feature.txt"]
    # A fix of a branch that is not on the remote is a failed result, not a build.
    gone = brief(bare, "fix", agent_command(tmp_path, "commit:x.txt"), branch="sortyard/ITEM-8")
    status, text = run_worker(tmp_path / "job3", gone)
    assert (status, json.loads(text)["outcome"]) == (1, "failed")
    assert remote_head(bare, "sortyard/ITEM-8") is None


def test_a_review_checks_out_the_branch_head_and_reports_approved_or_findings_with_one_key(
    tmp_path: pathlib.Path,
) -> None:
    """A review reads the branch head and reports approved, or findings with one finding key."""
    bare = make_remote(tmp_path)
    head = push_branch(tmp_path, bare, "feature.txt")
    review = brief(bare, "review", agent_command(tmp_path, "review"))
    status, text = run_worker(tmp_path / "job", review)
    assert status == 0
    assert json.loads(text) == {
        "outcome": "findings",
        "head": head,
        "finding": "missing-fix-txt",
        "findings": [
            {"key": "missing-fix-txt", "text": "The change does not add fix.txt."},
            {"key": "style", "text": "Second finding."},
        ],
    }
    assert (seen(tmp_path)["head"], seen(tmp_path)["branch"]) == (head, "HEAD")
    assert TOKEN not in json.dumps(seen(tmp_path)["env"])

    fixed = push_branch(tmp_path, bare, "fix.txt")
    status, text = run_worker(tmp_path / "job2", review)
    assert (status, json.loads(text)) == (0, {"outcome": "approved", "head": fixed})
    assert remote_head(bare, BRANCH) == fixed  # a review pushes nothing


@pytest.mark.parametrize(
    "answer",
    [
        "looks good to me",
        "",
        '{"verdict":"approve"}\nand one more thought',
        '{"verdict":"approved"}',
        '["approve"]',
        '{"verdict":"findings","findings":[]}',
        '{"verdict":"findings"}',
        '{"verdict":"findings","findings":[{"text":"no key"}]}',
        '{"verdict":"findings","findings":[{"key":"  ","text":"blank key"}]}',
        '{"verdict":"findings","findings":[{"key":"k","text":""}]}',
        '{"verdict":"findings","findings":["k"]}',
    ],
)
def test_a_review_answer_that_cannot_be_read_is_a_failed_result_never_approved(
    tmp_path: pathlib.Path, answer: str
) -> None:
    """An unreadable review answer, or findings without a key, is failed: never approved."""
    bare = make_remote(tmp_path)
    push_branch(tmp_path, bare, "feature.txt")
    status, text = run_worker(
        tmp_path / "job", brief(bare, "review", agent_command(tmp_path, f"say:{answer}"))
    )
    result = json.loads(text)
    assert status == 1
    assert set(result) == {"outcome", "reason"} and result["outcome"] == "failed"


def test_a_long_review_is_cut_to_fit_the_termination_message() -> None:
    """A long review keeps its leading finding and stays under the termination message cap."""
    findings = [{"key": f"Finding {n}", "text": "x" * 5000} for n in range(40)]
    answer = "prose\n" + json.dumps({"verdict": "findings", "findings": findings})
    result = entry._verdict(answer, "a" * 40)
    encoded = json.dumps(result, separators=(",", ":")).encode()
    assert len(encoded) < 4096
    assert result["finding"] == "finding-0" == result["findings"][0]["key"]
    assert 1 <= len(result["findings"]) < 40
    assert result["dropped"] == 40 - len(result["findings"])
    assert all(len(finding["text"]) <= entry.TEXT_LIMIT for finding in result["findings"])


def test_a_failing_agent_is_a_failed_result_and_nothing_is_pushed(tmp_path: pathlib.Path) -> None:
    """An agent command that exits non-zero gives a failed result and pushes nothing."""
    bare = make_remote(tmp_path)
    status, text = run_worker(
        tmp_path / "job", brief(bare, "build", agent_command(tmp_path, "fail"))
    )
    assert (status, json.loads(text)["outcome"]) == (1, "failed")
    assert remote_head(bare, BRANCH) is None


def test_any_agent_command_given_as_configuration_runs(tmp_path: pathlib.Path) -> None:
    """The agent is whatever argv the brief carries: here a shell command, not the script."""
    bare = make_remote(tmp_path)
    shell = [
        "/bin/sh",
        "-c",
        'cat > from-stdin.txt && git add from-stdin.txt && git commit -q -m "by sh"',
    ]
    status, text = run_worker(tmp_path / "job", brief(bare, "build", shell))
    head = remote_head(bare, BRANCH)
    assert head is not None
    assert (status, json.loads(text)) == (0, {"outcome": "built", "head": head})
    assert git("show", f"{head}:from-stdin.txt", cwd=bare) == "Build ITEM-7: the thing works."


def test_a_hook_the_agent_left_does_not_run_when_the_worker_pushes(tmp_path: pathlib.Path) -> None:
    """The push that carries the token runs no hook from the clone."""
    bare = make_remote(tmp_path)
    status, text = run_worker(
        tmp_path / "job", brief(bare, "build", agent_command(tmp_path, "hook"))
    )
    assert (status, json.loads(text)["outcome"]) == (0, "built")
    assert remote_head(bare, BRANCH) is not None
    assert not (tmp_path / "seen.json.hook").exists()


def test_git_sends_the_token_as_a_header_to_the_clone_url_and_no_message_carries_it(
    tmp_path: pathlib.Path,
) -> None:
    """Over HTTP the token travels as a request header to the clone URL; when the remote
    refuses, neither the result nor the output names it."""
    got: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            got.append((self.path, self.headers.get("Authorization")))
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/walwarden/app.git"
        made = brief(tmp_path, "build", agent_command(tmp_path, "commit:new.txt"), clone_url=url)
        status, text = run_worker(tmp_path / "job", made)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    assert got and all(path.startswith("/walwarden/app.git/") for path, _ in got)
    assert {header for _, header in got} == {f"Basic {BASIC}"}
    result = json.loads(text)
    assert (status, result["outcome"]) == (1, "failed")
    assert TOKEN not in text and BASIC not in text
    assert "403" in result["reason"]
    assert not (tmp_path / "seen.json").exists()  # the agent never ran


def test_the_scrubber_cuts_the_token_from_a_message() -> None:
    """A message that would carry the token, plain or encoded, has it cut."""
    scrub = entry.Git("https://git.test/o/r.git", TOKEN, pathlib.Path()).scrub
    assert scrub(f"fatal: {TOKEN} and Basic {BASIC}") == "fatal: *** and Basic ***"


def test_a_missing_brief_is_a_failed_result(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no brief to read the worker still writes a result: failed."""
    monkeypatch.setenv("SORTYARD_BRIEF", str(tmp_path / "absent.json"))
    monkeypatch.setenv("SORTYARD_RESULT", str(tmp_path / "result.json"))
    monkeypatch.setenv("SORTYARD_GITHUB_TOKEN", TOKEN)
    monkeypatch.delenv("SORTYARD_GITHUB_TOKEN_FILE", raising=False)
    assert entry.main([]) == 1
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["outcome"] == "failed" and TOKEN not in result["reason"]


def test_sortyard_worker_is_a_console_script_of_the_package() -> None:
    """`sortyard-worker` is a console script that resolves to the entry point."""
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["sortyard-worker"] == "sortyard.services.worker:main"
    assert callable(entry.main)
