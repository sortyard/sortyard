"""Acceptance (SY-V3-RED-MAIN-OWNED): a red default branch of a lane repository is answered by
exactly one kernel triage item.

The observer (`sortyard.services.red_main`) runs real and in-process. GitHub is the strict fake
held to GitHub's published description (`tests/fake_github.py`), reached by the real App client
over HTTP; the Sortyard API is the strict fake held to `spec/openapi.json`
(`tests/fake_kernel_api.py`), reached by the observer's own API client over HTTP. Both fakes
refuse what their contract does not document; every test ends with `verify()` on both. How a
token is issued for the observer is proved against the real API on Postgres at the end.
"""

from __future__ import annotations

import copy
import pathlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from sortyard.kernel.capabilities import load as load_lane
from sortyard.services import red_main
from sortyard.services.red_main import Act, ActionsGitHub, KernelApi, Observer, Watch
from tests.fake_github import APP_ID, KEY, PEM, FakeGitHub, FakeRepo
from tests.fake_github import serving as serving_github
from tests.fake_kernel_api import FakeKernelApi
from tests.fake_kernel_api import serving as serving_api
from tests.pg import requires_postgres
from tests.test_bootstrap import Deployment, deployment  # noqa: F401  (the fixture)

WS = "ws-estate"
LANE = "canary"
PROJECT = "canary"
REPO = "noncelogic/sortyard-canary"
OTHER = "noncelogic/elsewhere"  # a repository that is in no lane
CI = ".github/workflows/ci.yml"
# The lane took its repositories at this moment; the fake's runs are made after it unless a
# test says otherwise (the fake's clock starts at 2026-01-01).
SINCE = datetime(2025, 12, 31, tzinfo=UTC)


@dataclass
class World:
    github: FakeGitHub
    api: FakeKernelApi
    repo: FakeRepo
    other: FakeRepo
    observer: Observer
    workflow: dict[str, Any]

    def observe(self) -> list[Act]:
        """One pass, as the service makes it."""
        return self.observer.run_once()

    def again(self) -> Observer:
        """A new observer process: nothing remembered from the last one."""
        return Observer(self.observer.github, self.observer.apis, self.observer.watches)

    def verify(self) -> None:
        self.github.verify()
        self.api.verify()


@contextmanager
def world(since: datetime = SINCE) -> Iterator[World]:
    github = FakeGitHub(APP_ID, KEY.public_key())
    api = FakeKernelApi(WS, {LANE: {REPO}})
    with serving_github(github) as github_url, serving_api(api) as api_url:
        repo, other = github.repo(REPO), github.repo(OTHER)
        workflow = github.workflow(repo, CI, "ci")
        # The repository that is in no lane is red; nothing may read it.
        github.workflow_run(other, github.workflow(other, CI, "ci"), "failure")
        token = api.token("operator", PROJECT)
        watch = Watch(LANE, PROJECT, "rb-red-main", since, (REPO,))
        observer = Observer(
            ActionsGitHub(APP_ID, PEM, base_url=github_url),
            {LANE: KernelApi(api_url, WS, lambda: token)},
            [watch],
        )
        yield World(github, api, repo, other, observer, workflow)


def triage(api: FakeKernelApi) -> list[str]:
    """Every triage item ever admitted."""
    return [i for i in api.items if i.startswith(red_main.PREFIX)]


def test_a_red_push_run_on_a_lane_repository_admits_one_triage_item_on_that_lane() -> None:
    """a red push run on a lane repository's default branch admits one triage item on that
    lane"""
    with world() as w:
        assert w.observe() == []  # nothing has run yet
        w.github.workflow_run(w.repo, w.workflow, "success")
        assert w.observe() == []  # green: nothing to answer
        head = w.github.push(w.repo, "main")
        run = w.github.workflow_run(w.repo, w.workflow, "failure")
        acts = w.observe()
        # One observation cycle: the red run is answered by a kernel item.
        assert [(a.what, a.repository, a.workflow, a.run) for a in acts] == [
            ("admitted", REPO, CI, run)
        ]
        (item,) = triage(w.api)
        admitted = w.api.items[item].admitted
        assert (admitted["lane"], admitted["project_id"], admitted["repository"]) == (
            LANE,
            PROJECT,
            REPO,
        )
        assert admitted["base"] == "main"
        incident = admitted["spec"]["incident"]
        assert (incident["repository"], incident["workflow"]) == (REPO, CI)
        assert (incident["run"], incident["head"], incident["branch"]) == (run, head, "main")
        outcome = admitted["spec"]["outcome"]
        assert REPO in outcome and CI in outcome and str(run) in outcome and head in outcome
        assert "passes" in outcome
        assert admitted["spec"]["acceptance"][0]["test"] == CI
        # Later passes, by this process or a new one, admit nothing more: the item is open.
        assert w.observe() == []
        assert w.again().run_once() == []
        assert triage(w.api) == [item]
        # A run that failed to start, or timed out, is red as well; a scheduled run and one
        # started by hand count as runs on the branch.
        w.api.merge(item)
        for conclusion, event in (
            ("startup_failure", "schedule"),
            ("timed_out", "workflow_dispatch"),
        ):
            w.github.workflow_run(w.repo, w.workflow, conclusion, event=event)
            assert [a.what for a in w.observe()] == ["admitted"]
            w.api.merge(triage(w.api)[-1])
        assert len(triage(w.api)) == 3
        # The repository that is in no lane was never read.
        assert all(OTHER not in seen.path for seen in w.github.requests)
        w.verify()


def test_a_second_red_run_of_the_same_workflow_is_evidence_on_the_open_triage_item() -> None:
    """a second red run of the same workflow is evidence on the open triage item, not a new
    item"""
    with world() as w:
        first = w.github.workflow_run(w.repo, w.workflow, "failure")
        w.observe()
        (item,) = triage(w.api)
        w.api.move(item, "building")
        second = w.github.workflow_run(w.repo, w.workflow, "failure", event="workflow_dispatch")
        acts = w.observe()
        assert [(a.what, a.item, a.run) for a in acts] == [("evidence", item, second)]
        assert triage(w.api) == [item]
        (sent,) = w.api.seen("requestItemChange")
        assert sent.body["answer"] == "resume"
        assert f"run {second}" in sent.body["reason"] and str(first) not in sent.body["reason"]
        # It is on the item's timeline, and the item carries on where it was.
        recorded = [
            e["facts"]["request"] for e in w.api.items[item].events if "request" in e["facts"]
        ]
        assert [r["reason"] for r in recorded] == [sent.body["reason"]]
        assert w.api.items[item].state == "building"
        # Recorded once: later passes, and a new observer that remembers nothing, read it back.
        assert w.observe() == []
        assert w.again().run_once() == []
        assert len(w.api.seen("requestItemChange")) == 1
        # A third red run is evidence too; still one item.
        third = w.github.workflow_run(w.repo, w.workflow, "failure", event="schedule")
        assert [(a.what, a.run) for a in w.observe()] == [("evidence", third)]
        assert triage(w.api) == [item]
        # Two observers at once (two replicas, or a restart mid-pass) still admit one item
        # for one red run: the item's id is fixed by the run.
        w.api.merge(item)
        fourth = w.github.workflow_run(w.repo, w.workflow, "failure")
        api, watch = w.observer.apis[LANE], w.observer.watches[0]
        stale = w.observer.open_items(api, watch)  # both read the queue before either admits
        both = w.observer.repository(api, watch, REPO, stale)
        both += w.again().repository(api, watch, REPO, stale)
        assert sorted(a.what for a in both) == ["admitted", "known"]
        assert len(w.api.open_ids()) == 1 and w.api.open_ids()[0].endswith(f"-{fourth}")
        w.verify()


def test_a_green_run_newer_than_the_failure_withdraws_an_unmerged_triage_item_as_moot() -> None:
    """a green run newer than the failure withdraws an unmerged triage item as moot"""
    with world() as w:
        w.github.workflow_run(w.repo, w.workflow, "failure")
        w.observe()
        (item,) = triage(w.api)
        w.api.move(item, "checking")
        # A cancelled run says nothing either way; an in-progress run has no verdict yet.
        w.github.workflow_run(w.repo, w.workflow, "cancelled")
        w.github.workflow_run(w.repo, w.workflow, None)
        assert w.observe() == []
        green = w.github.workflow_run(w.repo, w.workflow, "success")
        acts = w.observe()
        assert [(a.what, a.item, a.run) for a in acts] == [("withdrawn", item, green)]
        (sent,) = w.api.seen("requestItemChange")
        assert sent.body["answer"] == "withdraw" and "moot" in sent.body["reason"]
        assert w.api.items[item].state == "withdrawn"
        assert w.observe() == []
        # A merged item is not withdrawn: the incident ends with it. The run it answered is
        # still the newest red one until main runs again: it is the same item, not a new one.
        w.github.workflow_run(w.repo, w.workflow, "failure")
        w.observe()
        merged = triage(w.api)[-1]
        w.api.merge(merged)
        assert [a.what for a in w.observe()] == ["known"]
        w.github.workflow_run(w.repo, w.workflow, "success")
        assert w.observe() == []
        assert w.api.items[merged].state == "merged"
        assert len(w.api.seen("requestItemChange")) == 1
        w.verify()


def test_a_deleted_workflow_or_a_run_older_than_the_lane_files_nothing() -> None:
    """a deleted workflow or a run older than the lane files nothing"""
    with world(since=datetime(2026, 1, 1, 0, 1, tzinfo=UTC)) as w:
        # A red run from before the lane took the repository.
        w.github.workflow_run(w.repo, w.workflow, "failure", at="2026-01-01T00:00:30Z")
        assert w.observe() == []
        # A workflow whose file left the default branch, though GitHub still lists it.
        gone = w.github.workflow(w.repo, ".github/workflows/gone.yml", "gone")
        w.github.delete_file(w.repo, gone["path"])
        w.github.workflow_run(w.repo, gone, "failure", at="2026-01-01T00:05:00Z")
        # A workflow GitHub lists as deleted or disabled.
        for state in ("deleted", "disabled_manually"):
            off = w.github.workflow(w.repo, f".github/workflows/{state}.yml", state, state=state)
            w.github.workflow_run(w.repo, off, "failure", at="2026-01-01T00:05:00Z")
        # Red runs that are not of the default branch: a pull request's, another branch's.
        later = "2026-01-01T00:06:00Z"
        w.github.workflow_run(w.repo, w.workflow, "failure", event="pull_request", at=later)
        w.github.workflow_run(w.repo, w.workflow, "failure", branch="feature", at=later)
        assert w.observe() == []
        assert triage(w.api) == []
        # The same red run once the lane holds the repository is answered.
        w.github.workflow_run(w.repo, w.workflow, "failure", at="2026-01-01T00:07:00Z")
        assert [a.what for a in w.observe()] == ["admitted"]
        w.verify()


def test_a_red_run_of_a_repository_that_is_in_no_lane_files_nothing() -> None:
    """A red run of a repository that is in no lane files nothing: its repository is never
    read, and a watch file cannot put one repository in two lanes."""
    with world() as w:
        assert w.observe() == []
        assert triage(w.api) == []
        assert all(OTHER not in seen.path for seen in w.github.requests)
        assert w.github.seen("actions/list-workflow-runs")  # the lane's repository was read
        w.verify()
    text = (
        "[images]\n"
        'worker = "r/w@sha256:' + "0" * 64 + '"\nci = "r/w@sha256:' + "0" * 64 + '"\n'
        f'[[repositories]]\nname = "{REPO}"\n'
    )
    head = 'version = 1\nresolver = "p"\nrunner-pool = "aks"\n'
    lanes = {name: load_lane(f'{head}lane = "{name}"\n{text}') for name in ("canary", "walwarden")}
    two = (
        'version = 1\n[[lanes]]\nlane = "canary"\nproject = "c"\nrole-binding = "rb"\n'
        "since = 2026-11-24T22:00:00Z\n"
        '[[lanes]]\nlane = "walwarden"\nproject = "w"\nrole-binding = "rb"\n'
        "since = 2026-11-24T22:00:00Z\n"
    )
    with pytest.raises(ValueError, match="is in lanes"):
        red_main.load_watches(two, lanes)


def test_an_unreadable_github_or_api_is_reported_and_files_nothing() -> None:
    """A repository GitHub will not read, or an API that refuses, ends the pass for that lane
    with an `unread` act: nothing is admitted on what was not read."""
    with world() as w:
        w.github.workflow_run(w.repo, w.workflow, "failure")
        w.observer.apis = {LANE: KernelApi(w.api.url, WS, lambda: "sy_not_a_token")}
        (act,) = w.observe()
        assert act.what == "unread" and "401" in act.detail
        assert triage(w.api) == []
        w.github.granted["noncelogic"].pop("actions")  # the App lost actions:read
        w.observer.apis = {LANE: KernelApi(w.api.url, WS, lambda: w.api.token("operator"))}
        (act,) = w.observe()
        assert act.what == "unread" and act.repository == REPO
        assert triage(w.api) == []
        w.verify()


def test_the_watch_file_is_read_in_full_or_refused() -> None:
    """The watch file names, for each lane, its project, role binding and since; anything
    else, or a lane with no capability file, is refused."""
    text = (
        'version = 1\nlane = "canary"\nresolver = "p"\nrunner-pool = "aks"\n[images]\n'
        'worker = "r/w@sha256:' + "0" * 64 + '"\nci = "r/w@sha256:' + "0" * 64 + '"\n'
        f'[[repositories]]\nname = "{REPO}"\n[[repositories]]\nname = "{OTHER}"\n'
    )
    lanes = {"canary": load_lane(text)}
    good = (
        'version = 1\n[[lanes]]\nlane = "canary"\nproject = "canary"\n'
        'role-binding = "rb-red-main"\nsince = 2026-11-24T22:00:00Z\nrisk-tier = "low"\n'
    )
    (watch,) = red_main.load_watches(good, lanes)
    assert watch == Watch(
        "canary",
        "canary",
        "rb-red-main",
        datetime(2026, 11, 24, 22, tzinfo=UTC),
        (OTHER, REPO),
        "low",
    )
    for bad in (
        good.replace("version = 1", "version = 2"),
        good.replace('lane = "canary"', 'lane = "nowhere"'),
        good.replace("since = 2026-11-24T22:00:00Z", "since = 2026-11-24T22:00:00"),
        good.replace('risk-tier = "low"', 'colour = "red"'),
        good.replace('role-binding = "rb-red-main"\n', ""),
    ):
        with pytest.raises(ValueError):
            red_main.load_watches(bad, lanes)


def test_the_service_refuses_to_start_without_a_required_setting(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every required setting is named when it is missing, and the service exits 2."""
    for name in red_main.REQUIRED:
        monkeypatch.delenv(name, raising=False)
    assert red_main.main(["--once"]) == 2
    err = capsys.readouterr().err
    assert all(name in err for name in red_main.REQUIRED)


def test_the_fake_kernel_api_refuses_what_the_contract_does_not_allow() -> None:
    """The fake API is held to spec/openapi.json: a reply that departs from the documented
    schema, an undocumented call, an operation it does not serve, a body the schema refuses and
    a role the operation does not list are each caught."""
    import json
    import urllib.request

    def send(url: str, method: str, path: str, token: str, body: Any = None) -> int:
        request = urllib.request.Request(
            url + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as reply:
                return int(reply.status)
        except urllib.error.HTTPError as error:
            return error.code

    base = f"/v1/workspaces/{WS}"
    cases: list[tuple[str, str, Any, str, str]] = [
        ("GET", "/v1/nowhere", None, "operator", "undocumented call"),
        ("GET", f"{base}/tasks", None, "operator", "unserved operation: listTasks"),
        ("POST", f"{base}/items", {"id": "x"}, "operator", "admitItem: body"),
        ("POST", f"{base}/items/x/requests", {"answer": "go"}, "operator", "requestItemChange"),
        ("POST", f"{base}/items", {"id": "x"}, "viewer", "role viewer is not allowed"),
    ]
    for method, path, body, role, expected in cases:
        fake = FakeKernelApi(WS, {LANE: {REPO}})
        with serving_api(fake) as url:
            assert send(url, method, path, fake.token(role), body) >= 400
        assert any(expected in each for each in fake.violations), (path, fake.violations)
        with pytest.raises(AssertionError):
            fake.verify()

    # A reply the fake would send wrong is caught as it is served.
    with world() as w:
        w.github.workflow_run(w.repo, w.workflow, "failure")
        w.observe()
        replies = copy.deepcopy(w.api.replies)
        w.verify()
        for operation, status, payload in replies:
            if status >= 300 or not isinstance(payload, dict):
                continue
            broken = copy.deepcopy(payload)
            key = "items" if "items" in broken else "id"
            broken[key] = 7
            contract = w.api.contract
            assert contract.response_errors(
                contract.operation(operation), status, "application/json", broken
            ), operation
        w.api.mutate = lambda operation, payload: {"items": [{"id": 1}]}
        w.observe()
        assert any("getProjectQueue 200 reply" in each for each in w.api.violations)
        with pytest.raises(AssertionError):
            w.api.verify()


@requires_postgres
def test_the_observer_gets_its_operator_token_from_the_database_and_the_api_takes_it(
    deployment: Deployment,  # noqa: F811  (the fixture of tests/test_bootstrap.py)
) -> None:
    """The service issues itself a short-lived operator token for its role binding, as
    `sortyard-api --issue-operator-token` does, keeps it while it is young, and the real API
    takes it for the item operations."""
    from tests.test_bootstrap import DECLARED

    code, _, err = deployment.bootstrap(DECLARED)
    assert code == 0, err
    tokens = red_main.OperatorTokens(lambda: psycopg.connect(deployment.conninfo), "rb-first")
    token = tokens()
    assert tokens() == token  # one token while it is young
    with deployment.serving() as api:
        reply = api.call("GET", "/v1/workspaces/ws-acme/projects/proj-app/queue", token=token)
        assert reply.status == 200 and reply.body == {"items": []}
    with pytest.raises(ValueError, match="no role binding"):
        red_main.OperatorTokens(lambda: psycopg.connect(deployment.conninfo), "rb-none")()


def test_a_failing_run_re_run_green_withdraws_its_item_and_two_workflows_have_an_item_each() -> (
    None
):
    """A re-run keeps the run's id and its created_at: the failing run itself turned green
    ends the incident. Two red workflows of one repository are two incidents, and a green run
    of one withdraws only its own item."""
    with world() as w:
        other = w.github.workflow(w.repo, ".github/workflows/health.yml", "health")
        flaky = w.github.workflow_run(w.repo, w.workflow, "failure")
        w.github.workflow_run(w.repo, other, "failure")
        assert sorted(str(a.workflow) for a in w.observe() if a.what == "admitted") == [
            CI,
            other["path"],
        ]
        assert len(w.api.open_ids()) == 2
        (run,) = [r for r in w.repo.actions if r["id"] == flaky]
        run["conclusion"] = "success"  # re-run, green
        acts = w.observe()
        assert [(a.what, a.workflow, a.run) for a in acts] == [("withdrawn", CI, flaky)]
        (still,) = w.api.open_ids()
        assert w.api.items[still].admitted["spec"]["incident"]["workflow"] == other["path"]
        w.verify()


def test_a_withdraw_the_policy_does_not_grant_is_reported_and_a_withdrawn_run_is_not_refiled() -> (
    None
):
    """A binding whose role is not operator asks for the withdrawal once, and each pass says
    the item is still open; an item withdrawn by hand while its run is the newest red one is
    not admitted again (the API refuses its id) and nothing else is filed."""
    with world() as w:
        w.github.workflow_run(w.repo, w.workflow, "failure")
        w.observe()
        (item,) = triage(w.api)
        admin = w.api.token("admin", PROJECT)
        w.observer.apis = {LANE: KernelApi(w.api.url, WS, lambda: admin)}
        w.github.workflow_run(w.repo, w.workflow, "success")
        assert [a.what for a in w.observe()] == ["withdrawn"]
        assert w.api.items[item].state == "admitted"  # decided as resume: not granted
        assert [a.what for a in w.observe()] == ["not-withdrawn"]
        assert [a.what for a in w.again().run_once()] == ["not-withdrawn"]
        assert len(w.api.seen("requestItemChange")) == 1
        w.verify()
    with world() as w:
        w.github.workflow_run(w.repo, w.workflow, "failure")
        w.observe()
        (item,) = triage(w.api)
        operator = w.api.token("operator", PROJECT)
        KernelApi(w.api.url, WS, lambda: operator).request(item, "withdraw", "by hand")
        (act,) = w.observe()
        assert act.what == "refused" and "ended-item" in act.detail
        assert triage(w.api) == [item] and w.api.open_ids() == []
        w.verify()


def test_a_red_run_before_the_fix_merged_is_not_answered_while_the_merge_runs() -> None:
    """The newest run speaks for the branch, not the newest finished one. Found on the estate
    (SORTYARD-204 drill, 2026-11-24): a fix merged while the run of the merge commit was still
    in progress, the newest finished run was the earlier red one recorded as evidence, and a
    second item was admitted for it. A run of an older commit never speaks for the branch."""
    with world() as w:
        w.github.workflow_run(w.repo, w.workflow, "failure")
        w.observe()
        (item,) = triage(w.api)
        w.github.workflow_run(w.repo, w.workflow, "failure", event="workflow_dispatch")
        assert [a.what for a in w.observe()] == ["evidence"]
        w.api.merge(item)
        w.github.push(w.repo, "main")  # the fix lands; its run starts
        merge_run = w.github.workflow_run(w.repo, w.workflow, None)
        assert w.observe() == []
        assert w.again().run_once() == []
        (run,) = [r for r in w.repo.actions if r["id"] == merge_run]
        run["conclusion"] = "success"
        assert w.observe() == []
        assert triage(w.api) == [item]
        # A newest run that finished neither red nor green leaves the branch without a verdict;
        # the red run of an older commit is not taken in its place.
        w.github.workflow_run(w.repo, w.workflow, "failure")  # the same commit, red again
        assert [a.what for a in w.observe()] == ["admitted"]
        w.api.merge(triage(w.api)[-1])
        w.github.push(w.repo, "main")
        w.github.workflow_run(w.repo, w.workflow, "cancelled")
        assert w.observe() == []
        assert len(triage(w.api)) == 2
        w.verify()
