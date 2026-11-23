"""Acceptance (SY-V3-GITHUB-PORT): checking, merging and the repository probe run on the GitHub
port.

Our code is real throughout: the adapters, the HTTP client, and for the last test the item
workflow on the engine's test server. GitHub is the strict fake of `tests/fake_github.py`,
served over real HTTP and held to GitHub's published API description; every test ends by
asking it for violations. No test waits a fixed time.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

import pytest

from sortyard.engine import Registry
from sortyard.engine.testing import time_skipping_engine
from sortyard.kernel.capabilities import Need, load
from sortyard.kernel.item import Owner, register, send_outcome, start_item
from sortyard.kernel.preflight import Probe
from sortyard.kernel.states import shipped
from sortyard.lane.github import (
    CI_OWNER,
    MERGE_OWNER,
    CiAdapter,
    GitHub,
    GitHubError,
    HttpGitHub,
    MergeAdapter,
    RepositoryProbe,
    Target,
    Token,
    branch_of,
)
from tests.fake_github import APP_ID, KEY, PEM, FakeGitHub, FakePull, FakeRepo, serving
from tests.kernel_harness import Owners, until

TENANT = "acme"
REPO = "walwarden/app"
ITEM = "ITEM-1"
BRANCH = "sortyard/ITEM-1"
DIGEST = "sha256:" + "c3" * 32
LANE = load(
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
name = "walwarden/deploy"
workflow-files = true
"""
)


@dataclass
class World:
    fake: FakeGitHub
    port: HttpGitHub
    repo: FakeRepo

    def target_of(self, tenant: str, item: str) -> Target:
        assert tenant == TENANT
        return Target(REPO, "main")

    def open(self, item: str = ITEM) -> FakePull:
        """What the executor leaves behind: the item's branch pushed and its pull request."""
        self.fake.push(self.repo, branch_of(item))
        token = self.port.token(REPO, {"pull_requests": "write"})
        self.port.open_pull(token, REPO, branch=branch_of(item), base="main", title=item)
        return self.repo.pull_of(branch_of(item))

    def calls(self, operation: str) -> int:
        return len(self.fake.seen(operation))


@contextmanager
def world() -> Iterator[World]:
    fake = FakeGitHub(APP_ID, KEY.public_key())
    with serving(fake) as url:
        yield World(fake, HttpGitHub(APP_ID, PEM, base_url=url), fake.repo(REPO))
    fake.verify()


def call(
    state: str, *, item: str = ITEM, action: str | None = None, **detail: Any
) -> dict[str, Any]:
    owner = shipped().state(state).owner
    return {
        "item": item,
        "tenant": TENANT,
        "state": state,
        "owner": owner,
        "dispatch": 4,
        "attempt": 1,
        "cause": "outcome",
        "action": action,
        "detail": detail,
    }


def test_the_ci_adapter_answers_green_red_and_nothing_while_pending() -> None:
    """The ci-adapter answers green, red with the failing checks, and nothing while a required
    check is pending."""
    with world() as w:
        ci = CiAdapter(w.port, w.target_of)
        checking = call("checking")
        # No pull request yet: nothing, and the look says what it waits on.
        assert ci(checking) is None
        assert "sortyard/ITEM-1" in ci.observe(checking).detail["waiting"]

        w.fake.protect(w.repo, "main", ["test", "lint"])
        pull = w.open()
        # Required checks that have not reported, then one that passed and one that has not
        # reported, then one still running: never green.
        assert ci(checking) is None
        w.fake.check(w.repo, pull.head, "test")
        w.fake.check(w.repo, pull.head, "optional")
        assert ci(checking) is None
        w.fake.check(w.repo, pull.head, "lint", None)
        assert ci(checking) is None
        look = ci.observe(checking)
        assert look.outcome is None and look.reply() is None and look.detail["head"] == pull.head

        # Every required check passed: green, whatever a check that is not required says.
        w.fake.check(w.repo, pull.head, "lint")
        w.fake.check(w.repo, pull.head, "optional", "failure")
        green = ci(checking)
        assert green is not None and green["outcome"] == "green"
        assert green["detail"]["head"] == pull.head and green["detail"]["checks"] == [
            "lint",
            "test",
        ]
        # The same call delivered again, and the poller's look, give the same answer.
        assert ci(checking) == green == ci.observe(checking).reply()

        # A required check failed: red at once, naming it, though another is still running.
        w.fake.check(w.repo, pull.head, "lint", "failure")
        w.fake.check(w.repo, pull.head, "test", None)
        red = ci(checking)
        assert red is not None and red["outcome"] == "red"
        assert red["detail"]["failed"] == ["lint"] and "lint" in red["detail"]["finding"]
        # The finding is the same for the same failing checks on a later commit, so the
        # workflow can tell a fix that changed nothing; and differs when the failure differs.
        head = w.fake.push(w.repo, BRANCH)
        for conclusion in ("timed_out", "cancelled", "action_required"):
            w.fake.check(w.repo, head, "lint", conclusion)
            again = ci(checking)
            assert again is not None and again["detail"]["finding"] == red["detail"]["finding"]
            assert again["detail"]["head"] == head
        w.fake.check(w.repo, head, "test", "failure")
        both = ci(checking)
        assert both is not None and both["detail"]["failed"] == ["lint", "test"]
        assert both["detail"]["finding"] != red["detail"]["finding"]
        # Skipped and neutral count as passed.
        w.fake.check(w.repo, head, "test", "skipped")
        w.fake.check(w.repo, head, "lint", "neutral")
        assert (ci(checking) or {})["outcome"] == "green"


def test_a_base_branch_with_no_protection_takes_every_check_run_of_the_head() -> None:
    """A repository whose base branch has no protection: every check run of the head counts."""
    with world() as w:
        ci = CiAdapter(w.port, w.target_of)
        checking = call("checking")
        pull = w.open()
        # No check has reported: nothing to call green.
        assert ci(checking) is None
        w.fake.check(w.repo, pull.head, "test")
        w.fake.check(w.repo, pull.head, "docs", None)
        assert ci(checking) is None
        w.fake.check(w.repo, pull.head, "docs")
        green = ci(checking)
        assert green is not None and green["outcome"] == "green"
        assert green["detail"]["checks"] == ["docs", "test"]
        w.fake.check(w.repo, pull.head, "docs", "failure")
        red = ci(checking)
        assert red is not None and (red["outcome"], red["detail"]["failed"]) == ("red", ["docs"])
        # A pull request against another base than the item's is not this item's change.
        other = CiAdapter(w.port, lambda tenant, item: Target(REPO, "release"))
        assert other(checking) is None and "main" in other.observe(checking).detail["waiting"]


def test_the_merge_adapter_merges_once_refuses_a_moved_head_reports_a_conflict_and_updates() -> (
    None
):
    """The merge-adapter merges once, refuses a moved head, reports a conflict and updates a
    branch that is behind."""
    with world() as w:
        merge = MergeAdapter(w.port, w.target_of)
        w.fake.protect(w.repo, "main", ["test"], strict=True)
        pull = w.open()
        reviewed = pull.head
        w.fake.check(w.repo, reviewed, "test")
        merging = call("merging", head=reviewed)

        # A conflict: GitHub reports the branch cannot be merged.
        pull.conflict = True
        conflict = merge(merging)
        assert conflict is not None and conflict["outcome"] == "conflict"
        assert isinstance(conflict["detail"]["finding"], str) and conflict["detail"]["finding"]
        assert merge(merging) == conflict
        pull.conflict = False

        # No reviewed head in the call, or another one: no merge is asked for.
        for stale in (call("merging"), call("merging", head="0" * 40)):
            assert merge(stale) is None
        # The head moved after the review: the pull request is not merged, and the look says why.
        moved = w.fake.push(w.repo, BRANCH)
        w.fake.check(w.repo, moved, "test")
        assert merge(merging) is None
        look = merge.observe(merging)
        assert look.outcome is None
        assert (look.detail["reviewed"], look.detail["head"]) == (reviewed, moved)
        assert w.calls("pulls/merge") == 0 and not pull.merged and pull.merges == 0

        # Reviewed again at the new head, but the base moved on: behind. Without the action
        # nothing is done; with `update-branch` the branch is updated, once per call.
        merging = call("merging", head=moved)
        w.fake.push(w.repo, "main")
        assert merge(merging) is None
        assert (w.calls("pulls/update-branch"), w.calls("pulls/merge")) == (0, 0)
        assert merge(call("merging", head=moved, action="update-branch")) is None
        assert pull.updates == 1 and pull.head != moved
        # The update moved the head, so the reviewed commit is no longer the head: not merged.
        w.fake.check(w.repo, pull.head, "test")
        assert merge(call("merging", head=moved, action="update-branch")) is None
        assert pull.updates == 1 and w.calls("pulls/merge") == 0

        # Approved at the head that is there now. GitHub does not know yet whether it merges:
        # nothing; then it does, and the adapter merges.
        merging = call("merging", head=pull.head)
        pull.computing = 1
        assert merge(merging) is None
        assert w.calls("pulls/merge") == 0
        merged = merge.observe(merging).reply()
        assert merged is not None and merged["outcome"] == "merged"
        assert merged["detail"]["sha"] == w.repo.refs["refs/heads/main"] == pull.merge_sha
        # The same call delivered again answers merged and does not merge again.
        assert merge(merging) == merged == merge.observe(merging).reply()
        assert pull.merges == 1 and w.calls("pulls/merge") == 1


def test_the_merge_adapter_waits_on_what_blocks_and_takes_a_merge_made_elsewhere() -> None:
    """A pull request GitHub would not merge is left alone; one already merged answers merged."""
    with world() as w:
        merge = MergeAdapter(w.port, w.target_of, method="merge")
        w.fake.protect(w.repo, "main", ["test"])
        pull = w.open()
        merging = call("merging", head=pull.head)
        # The required check has not passed: GitHub calls it blocked; no merge is tried.
        assert merge(merging) is None
        assert "blocked" in merge.observe(merging).detail["waiting"] and w.calls("pulls/merge") == 0
        # The check passes between the look and the merge call for one, and the head moves
        # under the other: GitHub's own refusal is taken as "not yet", never as merged.
        w.fake.check(w.repo, pull.head, "test")
        racing = World(w.fake, _MovesHead(w), w.repo)  # type: ignore[arg-type]
        assert MergeAdapter(racing.port, w.target_of)(merging) is None
        assert w.calls("pulls/merge") == 1 and not pull.merged
        # Someone else merged it at the head that is there now.
        token = w.port.token(REPO, {"contents": "write", "pull_requests": "read"})
        w.fake.check(w.repo, pull.head, "test")
        sha = w.port.merge(token, REPO, pull.number, pull.head, "merge")
        before = w.calls("pulls/merge")
        merged = merge(call("merging", head=pull.head))
        assert merged is not None and (merged["outcome"], merged["detail"]["sha"]) == (
            "merged",
            sha,
        )
        assert w.calls("pulls/merge") == before and pull.merges == 1
        assert w.fake.seen("pulls/merge")[-1].body["merge_method"] == "merge"


class _MovesHead:
    """The real port, except that a commit lands on the branch just before each merge call."""

    def __init__(self, world: World) -> None:
        self._world = world

    def __getattr__(self, name: str) -> Any:
        return getattr(self._world.port, name)

    def merge(self, token: Token, repository: str, number: int, head: str, method: str) -> str:
        moved = self._world.fake.push(self._world.repo, BRANCH)
        self._world.fake.check(self._world.repo, moved, "test")
        return self._world.port.merge(token, repository, number, head, method)


def test_the_repository_probe_pushes_and_deletes_a_scratch_ref() -> None:
    """The repository probe pushes and deletes a scratch ref and fails when the workflows
    permission is missing."""
    with world() as w:
        probe: Probe = RepositoryProbe(w.port)
        before = dict(w.repo.refs)
        result = probe(Need.parse(f"repository:{REPO}"), LANE)
        assert result.passed, result
        created = [seen.body for seen in w.fake.seen("git/create-ref")]
        deleted = [seen.path for seen in w.fake.seen("git/delete-ref")]
        assert len(created) == 1 and created[0]["sha"] == before["refs/heads/main"]
        assert created[0]["ref"] not in before and created[0]["ref"].startswith("refs/heads/")
        assert deleted == [f"/repos/{REPO}/git/{created[0]['ref']}"]
        assert w.repo.refs == before
        # The token was asked for that repository and to write contents; not for workflows.
        minted = w.fake.seen("apps/create-installation-access-token")[-1].body
        assert minted == {"repositories": ["app"], "permissions": {"contents": "write"}}
        # Probed again (the same dispatch delivered twice): another scratch ref, also removed.
        assert probe(Need.parse(f"repository:{REPO}"), LANE).passed
        assert w.fake.seen("git/create-ref")[1].body["ref"] != created[0]["ref"]
        assert w.repo.refs == before

        # A repository declared with workflow-files: the token must carry workflows too.
        deploy = w.fake.repo("walwarden/deploy")
        assert probe(Need.parse("repository:walwarden/deploy"), LANE).passed
        minted = w.fake.seen("apps/create-installation-access-token")[-1].body
        assert minted["permissions"] == {"contents": "write", "workflows": "write"}
        assert minted["repositories"] == ["deploy"]

        # The installation is not granted workflows: the probe fails, names the permission's
        # refusal, and pushes nothing.
        w.fake.granted["walwarden"] = {"contents": "write"}
        pushes = w.calls("git/create-ref")
        failed = probe(Need.parse("repository:walwarden/deploy"), LANE)
        assert not failed.passed and "permissions" in failed.output
        assert w.calls("git/create-ref") == pushes and len(deploy.refs) == 1
        # The repository without workflow files still passes on that grant.
        assert probe(Need.parse(f"repository:{REPO}"), LANE).passed
        # A grant to read only: the scratch ref cannot be pushed.
        w.fake.granted["walwarden"] = {"contents": "read"}
        assert not probe(Need.parse(f"repository:{REPO}"), LANE).passed

        # A token that came back without the permission it was asked for does not pass either.
        w.fake.granted["walwarden"] = {"contents": "write", "workflows": "write"}
        short = RepositoryProbe(_DropsWorkflows(w.port))
        lacking = short(Need.parse("repository:walwarden/deploy"), LANE)
        assert not lacking.passed and "workflows" in lacking.output
        # A scratch ref that could not be deleted is a failure that names the ref.
        stuck = RepositoryProbe(_CannotDelete(w.port))(Need.parse(f"repository:{REPO}"), LANE)
        assert not stuck.passed and "refs/heads/" in stuck.output
        # A repository the lane does not declare, a need of another kind, a repository GitHub
        # does not have: each a failed result, none an exception.
        undeclared = replace(LANE, repositories={})
        assert not probe(Need.parse(f"repository:{REPO}"), undeclared).passed
        assert not probe(Need.parse("runner-pool"), LANE).passed
        gone = replace(LANE, repositories={"walwarden/gone": LANE.repositories[REPO]})
        assert not probe(Need.parse("repository:walwarden/gone"), gone).passed
        for token in w.fake.minted():
            for output in (result.output, failed.output, lacking.output, stuck.output):
                assert token not in output


class _DropsWorkflows:
    def __init__(self, port: GitHub) -> None:
        self._port = port

    def __getattr__(self, name: str) -> Any:
        return getattr(self._port, name)

    def token(self, repository: str, permissions: Mapping[str, str]) -> Token:
        token = self._port.token(repository, permissions)
        return replace(token, permissions={"contents": "write"})


class _CannotDelete(_DropsWorkflows):
    def token(self, repository: str, permissions: Mapping[str, str]) -> Token:
        return self._port.token(repository, permissions)

    def delete_ref(self, token: Token, repository: str, ref: str) -> None:
        raise GitHubError(422, "DELETE", ref, "Reference does not exist")


def everything_said(error: BaseException) -> str:
    """All the text an exception can put in a log: itself, its chain and its traceback."""
    said = "".join(traceback.format_exception(error))
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        said += f" {error} {error!r} {error.args!r} {vars(error)!r}"
        error = error.__cause__ or error.__context__  # type: ignore[assignment]
    return said


def test_an_installation_token_is_for_one_repository_and_never_appears_in_an_error() -> None:
    """An installation token is requested for one repository with named permissions and never
    appears in an error."""
    errors: list[BaseException] = []

    def failing(what: Any) -> GitHubError:
        with pytest.raises(GitHubError) as caught:
            what()
        errors.append(caught.value)
        return caught.value

    fake = FakeGitHub(APP_ID, KEY.public_key())
    with serving(fake) as url:
        port = HttpGitHub(APP_ID, PEM, base_url=url)
        repo = fake.repo(REPO)
        fake.repo("walwarden/deploy")
        token = port.token(REPO, {"contents": "read", "pull_requests": "read"})
        asked = fake.seen("apps/create-installation-access-token")[0].body
        assert asked == {
            "repositories": ["app"],
            "permissions": {"contents": "read", "pull_requests": "read"},
        }
        assert token.permissions == asked["permissions"] and token.value in fake.minted()
        # GitHub holds the token to that: not another repository, not another permission.
        assert port.refs(token, REPO, "heads")
        assert failing(lambda: port.refs(token, "walwarden/deploy", "heads")).status == 404
        assert failing(lambda: port.checks(token, REPO, repo.refs["refs/heads/main"])).status == 403
        assert failing(lambda: port.create_ref(token, REPO, "refs/heads/x", "0" * 40)).status == 403
        assert failing(lambda: port.token(REPO, {"administration": "write"})).status == 422
        assert token.value not in repr(token) and token.value not in str(token)

        # The adapters' own tokens, and what they return for the record.
        w = World(fake, port, repo)
        pull = w.open()
        fake.check(repo, pull.head, "test", "failure")
        ci, merge = CiAdapter(port, w.target_of), MergeAdapter(port, w.target_of)
        recorded: list[Any] = [ci(call("checking")), ci.observe(call("checking")).detail]
        recorded.append(merge.observe(call("merging", head="0" * 40)).detail)
        fake.check(repo, pull.head, "test")
        recorded += [ci(call("checking")), merge(call("merging", head=pull.head))]
        assert recorded[-1]["outcome"] == "merged"
        # An adapter whose call GitHub refuses raises: the engine retries the step.
        fake.granted["walwarden"] = {"contents": "read"}
        failing(lambda: merge(call("merging", head=pull.head)))
        fake.granted["walwarden"] = {
            "contents": "write",
            "pull_requests": "write",
            "checks": "read",
        }
        fake.verify()

        # GitHub answers with a token but not in the documented shape: an error without it.
        def no_expiry(operation: str, payload: Any) -> Any:
            return {"token": payload["token"]} if "token" in (payload or {}) else payload

        fake.mutate = no_expiry
        failing(lambda: port.token(REPO, {"contents": "read"}))

        # GitHub repeats the credential in its message: the error does not.
        def echoes(operation: str, payload: Any) -> Any:
            return {**payload, "message": f"no access for {token.value}"}

        fake.mutate = echoes
        assert failing(lambda: port.create_ref(token, REPO, "refs/heads/x", "0" * 40)).status == 403
        fake.mutate = None
        last = port.token(REPO, {"contents": "read"})
    # GitHub is gone: no answer, and still no token.
    assert failing(lambda: port.refs(last, REPO, "heads")).status == 0

    secrets = [*fake.minted(), PEM.decode(), *(s.headers["authorization"] for s in fake.requests)]
    assert len(fake.minted()) >= 8 and len(errors) == 8
    for secret in secrets:
        credential = secret.rpartition(" ")[2]
        for error in errors:
            assert credential not in everything_said(error)
        assert credential not in json.dumps(recorded)


def test_the_item_workflow_runs_checking_and_merging_on_the_adapters() -> None:
    """The item workflow takes the adapters' answers: a look that found nothing leaves the stay
    open for a later report, an approval is merged once, and a red that repeats ends in a
    decision."""
    events: list[Mapping[str, Any]] = []
    calls: list[Mapping[str, Any]] = []

    with world() as w:
        w.fake.protect(w.repo, "main", ["test"])
        ci, merge = CiAdapter(w.port, w.target_of), MergeAdapter(w.port, w.target_of)

        def executor(asked: Mapping[str, Any]) -> Mapping[str, Any]:
            calls.append(asked)
            if asked["state"] == "building":
                w.open(asked["item"])
                return {"outcome": "built"}
            # A fix that changes nothing about the failing check.
            head = w.fake.push(w.repo, branch_of(asked["item"]))
            w.fake.check(w.repo, head, "test", "failure")
            return {"outcome": "fixed"}

        def reviewer(asked: Mapping[str, Any]) -> Mapping[str, Any]:
            head = w.repo.pull_of(branch_of(asked["item"])).head
            return {"outcome": "approved", "detail": {"head": head}}

        def checking(asked: Mapping[str, Any]) -> Mapping[str, Any] | None:
            calls.append(asked)
            return ci(asked)

        def merging(asked: Mapping[str, Any]) -> Mapping[str, Any] | None:
            calls.append(asked)
            return merge(asked)

        scripted = Owners(decisions=[{"answer": "wait", "reverse": "send another answer"}])
        owners: dict[str, Owner] = {
            state.owner: scripted.owner for state in shipped().states.values() if state.owner
        }
        owners |= {
            "executor": executor,
            "reviewer": reviewer,
            CI_OWNER: checking,
            MERGE_OWNER: merging,
        }
        registry = Registry()
        register(registry, owners=owners, decide=scripted.decide, record=events.append)

        def states(item: str) -> list[str]:
            return [event["state"] for event in events if event["item"] == item]

        async def scenario() -> Any:
            async with time_skipping_engine() as skipping:
                engine = skipping.engine
                worker = asyncio.create_task(engine.run_worker(registry))
                try:
                    # ITEM-1: the check has not reported when the adapter is first asked.
                    first = await start_item(engine, "ITEM-1", tenant=TENANT)
                    await until(
                        lambda: engine.recorded(first),
                        lambda r: r.idle and states("ITEM-1")[-1:] == ["checking"],
                        "ITEM-1 waiting in checking",
                    )
                    asked = next(c for c in calls if c["state"] == "checking")
                    assert ci.observe(asked).outcome is None
                    pull = w.repo.pull_of("sortyard/ITEM-1")
                    w.fake.check(w.repo, pull.head, "test")
                    # The poller: look again, and report what was found for that dispatch.
                    found = ci.observe(asked)
                    assert found.outcome == "green"
                    await send_outcome(
                        engine,
                        first,
                        state="checking",
                        outcome=found.outcome,
                        detail=found.detail,
                        dispatch=asked["dispatch"],
                    )
                    result = await asyncio.wait_for(engine.result(first), 60)
                    # The merging call delivered once more changes nothing.
                    again = merge(next(c for c in calls if c["state"] == "merging"))
                    # ITEM-2: its check fails, and fails the same way after the fix.
                    second = await start_item(engine, "ITEM-2", tenant=TENANT)
                    await until(
                        lambda: engine.recorded(second),
                        lambda r: r.idle and states("ITEM-2")[-1:] == ["checking"],
                        "ITEM-2 waiting in checking",
                    )
                    two = w.repo.pull_of("sortyard/ITEM-2")
                    w.fake.check(w.repo, two.head, "test", "failure")
                    asked = next(
                        c for c in calls if c["item"] == "ITEM-2" and c["state"] == "checking"
                    )
                    red = ci.observe(asked)
                    await send_outcome(
                        engine,
                        second,
                        state="checking",
                        outcome=str(red.outcome),
                        detail=red.detail,
                        dispatch=asked["dispatch"],
                    )
                    await until(
                        lambda: engine.recorded(second),
                        lambda r: r.idle and states("ITEM-2")[-1:] == ["waiting"],
                        "ITEM-2 waiting on a decision's need",
                    )
                    return result, again
                finally:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)

        result, again = asyncio.run(scenario())
        one = w.repo.pull_of("sortyard/ITEM-1")
        assert result["state"] == "merged"
        assert states("ITEM-1")[-4:] == ["checking", "reviewing", "merging", "merged"]
        assert one.merged and one.merges == 1 and again is not None and again["outcome"] == "merged"
        assert w.repo.refs["refs/heads/main"] == one.merge_sha
        # ITEM-2: red, a fix, the same red: the second stay in fixing dispatched no one and
        # went to the decision, on the finding the adapter gave.
        assert states("ITEM-2")[3:] == [
            "checking",
            "fixing",
            "checking",
            "fixing",
            "decision",
            "waiting",
        ]
        fixes = [c for c in calls if c["item"] == "ITEM-2" and c["state"] == "fixing"]
        assert len(fixes) == 1 and fixes[0]["detail"]["finding"] == "checks failed: test"
        assert not w.repo.pull_of("sortyard/ITEM-2").merged
        for token in w.fake.minted():
            assert token not in json.dumps(events)
