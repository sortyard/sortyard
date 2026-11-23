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
from collections.abc import Callable, Iterator, Mapping
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
    checks: tuple[str, ...] | None = None  # the checks the lane names for the repository

    def target_of(self, tenant: str, item: str) -> Target:
        assert tenant == TENANT
        return Target(REPO, "main", checks=self.checks)

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
    """A repository whose base branch has no protection: every check run of the head counts,
    and there must be one; checks the lane names are the ones that count instead."""
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

        # The lane names the checks: one that has not reported is waited for although every
        # run there is has passed, and a run that is not named does not count.
        w.checks = ("build", "test")
        w.fake.check(w.repo, pull.head, "docs")
        assert ci(checking) is None
        w.fake.check(w.repo, pull.head, "build")
        w.fake.check(w.repo, pull.head, "docs", "failure")
        named = ci(checking)
        assert named is not None and named["outcome"] == "green"
        assert named["detail"]["checks"] == ["build", "test"]
        # The lane says the repository runs no checks on a pull request: green at once.
        w.checks = ()
        bare = w.open("ITEM-2")
        none = ci(call("checking", item="ITEM-2"))
        assert none is not None and none["outcome"] == "green" and none["detail"]["checks"] == []
        assert none["detail"]["head"] == bare.head and not w.repo.runs.get(bare.head)


def test_the_latest_run_of_a_check_is_the_one_that_counts() -> None:
    """Several runs of one check name on a commit: the latest decides, wherever it is listed."""
    with world() as w:
        ci = CiAdapter(w.port, w.target_of)
        merge = MergeAdapter(w.port, w.target_of)
        checking = call("checking")
        w.fake.protect(w.repo, "main", ["test"])
        pull = w.open()

        def outcome() -> str | None:
            return ci.observe(checking).outcome

        # Failed, then run again and passed: green, also when GitHub lists the newer run first.
        w.fake.check(w.repo, pull.head, "test", "failure")
        w.fake.check(w.repo, pull.head, "test", again=True)
        assert outcome() == "green"
        w.fake.check(w.repo, pull.head, "test", "failure")
        w.fake.check(w.repo, pull.head, "test", again=True, listed_first=True)
        assert outcome() == "green"
        # Passed, then run again and running: pending. Then that run fails: red.
        w.fake.check(w.repo, pull.head, "test", None, again=True, listed_first=True)
        assert outcome() is None
        assert merge(call("merging", head=pull.head)) is None
        w.fake.check(w.repo, pull.head, "test")
        w.fake.check(w.repo, pull.head, "test", "failure", again=True, listed_first=True)
        assert outcome() == "red"
        assert len(w.repo.runs[pull.head]) == 2 and w.calls("pulls/merge") == 0


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

        # The head moved after the review: not merged; `moved`, with both commits. The same
        # for a call that carries no reviewed head at all.
        head = w.fake.push(w.repo, BRANCH)
        w.fake.check(w.repo, head, "test")
        moved = merge(merging)
        assert moved is not None and moved["outcome"] == "moved"
        assert (moved["detail"]["reviewed"], moved["detail"]["head"]) == (reviewed, head)
        assert merge(merging) == moved == merge.observe(merging).reply()
        unreviewed = merge(call("merging"))
        assert unreviewed is not None and unreviewed["outcome"] == "moved"
        assert w.calls("pulls/merge") == 0 and not pull.merged and pull.merges == 0

        # Reviewed again at the new head, and the base moved on: behind. The branch is updated
        # at once. GitHub takes the update and the head moves only later; a look in between
        # starts no second update and merges nothing.
        merging = call("merging", head=head)
        w.fake.push(w.repo, "main")
        w.fake.slow_updates = True
        assert merge(merging) is None
        assert pull.updates == 1 and pull.head == head
        assert merge(merging) is None and merge.observe(merging).outcome is None
        assert pull.updates == 1 and w.calls("pulls/merge") == 0
        landed = w.fake.land(w.repo, pull)
        # The head is now a merge of the base on top of the reviewed commit: no new review is
        # asked for, but its checks have not run: wait for them.
        waiting = merge.observe(merging)
        assert waiting.outcome is None and "checks" in waiting.detail["waiting"]
        assert w.calls("pulls/merge") == 0
        w.fake.check(w.repo, landed, "test", None)
        assert merge(merging) is None
        w.fake.check(w.repo, landed, "test")
        # GitHub does not know yet whether it merges: nothing; then it does.
        pull.computing = 1
        assert merge(merging) is None
        assert w.calls("pulls/merge") == 0
        merged = merge.observe(merging).reply()
        assert merged is not None and merged["outcome"] == "merged"
        assert merged["detail"]["sha"] == w.repo.refs["refs/heads/main"] == pull.merge_sha
        assert (merged["detail"]["reviewed"], merged["detail"]["head"]) == (head, landed)
        assert w.fake.seen("pulls/merge")[0].body == {"sha": landed, "merge_method": "squash"}
        # The same call delivered again answers merged and does not merge again.
        again = merge(merging)
        assert again is not None and again["outcome"] == "merged"
        assert again["detail"]["sha"] == merged["detail"]["sha"]
        assert pull.merges == 1 and pull.updates == 1 and w.calls("pulls/merge") == 1


def test_only_merges_of_the_base_on_top_of_the_reviewed_commit_are_not_a_moved_head() -> None:
    """A moved base does not ask for another review; any other commit on top does."""

    def look(arrange: Callable[[World, FakePull, str], None]) -> tuple[World, Mapping[str, Any]]:
        with world() as w:
            pull = w.open()
            reviewed = pull.head
            arrange(w, pull, reviewed)
            w.fake.check(w.repo, pull.head, "test")
            reply = MergeAdapter(w.port, w.target_of)(call("merging", head=reviewed))
        assert reply is not None
        return w, reply

    def base_merges(count: int) -> Callable[[World, FakePull, str], None]:
        def arrange(w: World, pull: FakePull, reviewed: str) -> None:
            for _ in range(count):
                base = w.fake.push(w.repo, "main")
                w.fake.push(w.repo, BRANCH, parents=[pull.head, base])

        return arrange

    def merge_of_another_branch(w: World, pull: FakePull, reviewed: str) -> None:
        other = w.fake.push(w.repo, "feature")
        w.fake.push(w.repo, BRANCH, parents=[reviewed, other])

    def commit_on_a_base_merge(w: World, pull: FakePull, reviewed: str) -> None:
        base_merges(1)(w, pull, reviewed)
        w.fake.push(w.repo, BRANCH)

    def base_merge_on_another_commit(w: World, pull: FakePull, reviewed: str) -> None:
        w.fake.push(w.repo, BRANCH)
        base_merges(1)(w, pull, reviewed)

    def reviewed_as_second_parent(w: World, pull: FakePull, reviewed: str) -> None:
        w.fake.push(w.repo, BRANCH, parents=[w.fake.push(w.repo, "main"), reviewed])

    for count in (1, 2, 10):
        w, reply = look(base_merges(count))
        assert reply["outcome"] == "merged", count
        assert w.repo.pull_of(BRANCH).merges == 1
    for arrange in (
        base_merges(11),  # more than the adapter follows
        merge_of_another_branch,
        commit_on_a_base_merge,
        base_merge_on_another_commit,
        reviewed_as_second_parent,
    ):
        w, reply = look(arrange)
        pull = w.repo.pull_of(BRANCH)
        assert reply["outcome"] == "moved", arrange
        assert reply["detail"]["head"] == pull.head != reply["detail"]["reviewed"]
        assert w.calls("pulls/merge") == 0 and not pull.merged


def test_what_cannot_clear_by_itself_in_merging_answers_conflict_with_a_stable_finding() -> None:
    """A pull request GitHub will not merge until someone changes it answers `conflict` with
    the same finding on every look; what clears by itself is waited for; a merge made
    elsewhere answers merged."""
    findings: dict[str, str] = {}

    def stuck(name: str, w: World, adapter: MergeAdapter, asked: Mapping[str, Any]) -> None:
        merges = w.calls("pulls/merge")
        first, second = adapter(asked), adapter.observe(asked).reply()
        assert first is not None and first["outcome"] == "conflict", name
        assert first == second
        finding = first["detail"]["finding"]
        for sha in w.repo.commits:
            assert sha not in finding
        findings[name] = finding
        assert w.calls("pulls/merge") == merges + (2 if name == "method" else 0)

    with world() as w:
        merge = MergeAdapter(w.port, w.target_of)
        stuck("no pull request", w, merge, call("merging", head="0" * 40))
        pull = w.open()
        merging = call("merging", head=pull.head)
        w.fake.check(w.repo, pull.head, "test")
        elsewhere = MergeAdapter(w.port, lambda tenant, item: Target(REPO, "release"))
        stuck("base", w, elsewhere, merging)
        pull.draft = True
        stuck("draft", w, merge, merging)
        pull.draft, pull.blocked = False, True
        stuck("blocked", w, merge, merging)
        pull.blocked = False
        w.fake.check(w.repo, pull.head, "test", "failure")
        stuck("checks", w, merge, merging)
        assert (
            findings["checks"]
            == (CiAdapter(w.port, w.target_of)(call("checking")) or {})["detail"]["finding"]
        )
        w.fake.check(w.repo, pull.head, "test")
        w.repo.methods = {"merge", "rebase"}
        stuck("method", w, merge, merging)
        assert w.calls("pulls/merge") == 2 and not pull.merged
        w.repo.methods.add("squash")
        pull.open = False
        stuck("closed", w, merge, merging)
        pull.open = True
        assert len(set(findings.values())) == 7

        # A check the base requires has not reported: that clears by itself; no finding.
        w.fake.protect(w.repo, "main", ["test", "lint"])
        assert merge(merging) is None
        w.fake.check(w.repo, pull.head, "lint")
        # A commit lands between the look and the merge call: GitHub refuses, nothing merged,
        # and it is not called a conflict; the next look calls it moved.
        calls = w.calls("pulls/merge")
        racing = MergeAdapter(_MovesHead(w), w.target_of)
        assert racing(merging) is None
        assert w.calls("pulls/merge") == calls + 1 and not pull.merged
        late = merge(merging)
        assert late is not None and late["outcome"] == "moved"
        # The action `update-branch` asks for an update even when GitHub does not call the
        # branch behind; GitHub having nothing to update is not an error, and the merge goes on.
        merging = call("merging", head=pull.head, action="update-branch")
        w.fake.check(w.repo, pull.head, "lint")
        updates = w.calls("pulls/update-branch")
        # The same call delivered twice at once: the second merge call is refused because the
        # first one merged. Both answer merged; GitHub merged once.
        twice = MergeAdapter(_MergesTwice(w.port), w.target_of, method="merge")
        merged = twice(merging)
        assert merged is not None and merged["outcome"] == "merged"
        assert merged["detail"]["sha"] == pull.merge_sha and pull.merges == 1
        assert w.calls("pulls/update-branch") == updates + 1 and pull.updates == 0
        assert w.fake.seen("pulls/merge")[-1].body["merge_method"] == "merge"

        # Merged by someone else, at a head that was never reviewed: merged, with both commits
        # in the detail, and no merge call.
        w.repo.required.clear()
        w.checks = ()
        other = w.open("ITEM-2")
        token = w.port.token(REPO, {"contents": "write"})
        sha = w.port.merge(token, REPO, other.number, other.head, "merge")
        calls = w.calls("pulls/merge")
        found = merge(call("merging", item="ITEM-2", head="0" * 40))
        assert found is not None and found["outcome"] == "merged"
        assert found["detail"] == {
            "pull": other.number,
            "head": other.head,
            "reviewed": "0" * 40,
            "sha": sha,
        }
        assert w.calls("pulls/merge") == calls
        # A repository the lane says runs no checks: an approved head merges with none.
        third = w.open("ITEM-3")
        bare = merge(call("merging", item="ITEM-3", head=third.head))
        assert bare is not None and bare["outcome"] == "merged" and third.merges == 1


class _Wrapped:
    """The real port, with one call changed by a subclass."""

    def __init__(self, port: GitHub) -> None:
        self._port = port

    def __getattr__(self, name: str) -> Any:
        return getattr(self._port, name)


class _MovesHead(_Wrapped):
    """A commit, with its check passed, lands on the branch just before each merge call."""

    def __init__(self, world: World) -> None:
        super().__init__(world.port)
        self._world = world

    def merge(self, token: Token, repository: str, number: int, head: str, method: str) -> str:
        moved = self._world.fake.push(self._world.repo, BRANCH)
        for name in ("test", "lint"):
            self._world.fake.check(self._world.repo, moved, name)
        return self._port.merge(token, repository, number, head, method)


class _MergesTwice(_Wrapped):
    """Each merge call is made twice: what a call delivered twice at once does."""

    def merge(self, token: Token, repository: str, number: int, head: str, method: str) -> str:
        self._port.merge(token, repository, number, head, method)
        return self._port.merge(token, repository, number, head, method)


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


class _DropsWorkflows(_Wrapped):
    def token(self, repository: str, permissions: Mapping[str, str]) -> Token:
        token = self._port.token(repository, permissions)
        return replace(token, permissions={"contents": "write"})


class _CannotDelete(_Wrapped):
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
        # GitHub's reply with the token in it breaks off: the bytes that did arrive are not
        # in the error.
        fake.truncate = True
        assert failing(lambda: port.token(REPO, {"contents": "read"})).status == 0
        assert not fake.truncate
        last = port.token(REPO, {"contents": "read"})
    # GitHub is gone: no answer, and still no token.
    assert failing(lambda: port.refs(last, REPO, "heads")).status == 0

    secrets = [*fake.minted(), PEM.decode(), *(s.headers["authorization"] for s in fake.requests)]
    assert len(fake.minted()) >= 8 and len(errors) == 9
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
            if asked["item"] == "ITEM-3" and asked["attempt"] == 1:
                # A commit lands on the branch after this review read it.
                w.fake.check(w.repo, w.fake.push(w.repo, "sortyard/ITEM-3"), "test")
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
                    # ITEM-3: its head moves after the review: back through checking and
                    # review, then merged at the head that was reviewed the second time.
                    w.checks = ("test",)
                    third = await start_item(engine, "ITEM-3", tenant=TENANT)
                    await until(
                        lambda: engine.recorded(third),
                        lambda r: r.idle and states("ITEM-3")[-1:] == ["checking"],
                        "ITEM-3 waiting in checking",
                    )
                    asked = next(
                        c for c in calls if c["item"] == "ITEM-3" and c["state"] == "checking"
                    )
                    w.fake.check(w.repo, w.repo.pull_of("sortyard/ITEM-3").head, "test")
                    await send_outcome(
                        engine,
                        third,
                        state="checking",
                        outcome="green",
                        detail=ci.observe(asked).detail,
                        dispatch=asked["dispatch"],
                    )
                    await asyncio.wait_for(engine.result(third), 60)
                    return result, again
                finally:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)

        result, again = asyncio.run(scenario())
        one = w.repo.pull_of("sortyard/ITEM-1")
        assert result["state"] == "merged"
        assert states("ITEM-1")[-4:] == ["checking", "reviewing", "merging", "merged"]
        assert one.merged and one.merges == 1 and again is not None and again["outcome"] == "merged"
        assert one.merge_sha in w.repo.commits
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
        # ITEM-3: `moved` took it from merging back to checking, as the state table says.
        assert states("ITEM-3")[3:] == [
            "checking",
            "reviewing",
            "merging",
            "checking",
            "reviewing",
            "merging",
            "merged",
        ]
        moved = next(e for e in events if e["item"] == "ITEM-3" and e.get("outcome") == "moved")
        three = w.repo.pull_of("sortyard/ITEM-3")
        assert moved["detail"]["head"] == three.head != moved["detail"]["reviewed"]
        assert three.merges == 1
        for token in w.fake.minted():
            assert token not in json.dumps(events)
