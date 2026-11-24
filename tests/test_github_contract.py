"""Acceptance (SY-V3-GITHUB-PORT): the fake GitHub and the HTTP client are both held to GitHub's
published API description.

The description is vendored as `tests/contracts/github/fragment.json` (its README names the
upstream commit). The client under test is the real one, `HttpGitHub`, talking real HTTP to
the fake served in-process. The fake checks every request and every reply against the fragment
as it serves; these tests drive every port call through it, check again here, and prove the
check bites: a reply that departs from the published shape, an undocumented call and an
undocumented field are each caught.
"""

from __future__ import annotations

import copy
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sortyard.lane.github import GitHubError, HttpGitHub, Token
from sortyard.services.red_main import READ, ActionsGitHub
from tests.fake_github import APP_ID, KEY, PEM, FakeGitHub, FakeRepo, serving

REPO = "walwarden/app"
ALL = {"contents": "write", "pull_requests": "write", "checks": "read"}


@contextmanager
def github(clock: Callable[[], float] = time.time) -> Iterator[tuple[FakeGitHub, ActionsGitHub]]:
    """The fake, served over HTTP, and the real client pointed at it (with the red-main
    observer's reads, which use the same client)."""
    fake = FakeGitHub(APP_ID, KEY.public_key(), clock=clock)
    with serving(fake) as url:
        yield fake, ActionsGitHub(APP_ID, PEM, base_url=url, clock=clock)


def refused(call: Callable[[], Any]) -> int:
    with pytest.raises(GitHubError) as caught:
        call()
    return caught.value.status


def every_call(fake: FakeGitHub, port: HttpGitHub) -> tuple[FakeRepo, Token]:
    """Drive every port call, and every refusal the adapters handle, through the fake."""
    repo = fake.repo(REPO)
    fake.protect(repo, "main", ["test"], strict=True)
    token = port.token(REPO, ALL)
    assert port.find_pull(token, REPO, "sortyard/ITEM-1") is None
    head = fake.push(repo, "sortyard/ITEM-1")
    opened = port.open_pull(token, REPO, branch="sortyard/ITEM-1", base="main", title="ITEM-1")
    found = port.find_pull(token, REPO, "sortyard/ITEM-1")
    assert found is not None and (found.number, found.head) == (opened.number, head)
    assert port.required_checks(token, REPO, "main") == ("test",)
    fake.check(repo, head, "test")
    assert [(c.name, c.status, c.conclusion) for c in port.checks(token, REPO, head)] == [
        ("test", "completed", "success")
    ]
    # Refusals: a second pull request, a merge on the wrong head, a merge while behind, an
    # update that expects another head, a branch and a pull request that do not exist.
    assert (
        refused(
            lambda: port.open_pull(token, REPO, branch="sortyard/ITEM-1", base="main", title="x")
        )
        == 422
    )
    assert refused(lambda: port.merge(token, REPO, opened.number, "0" * 40, "squash")) == 409
    fake.push(repo, "main")
    assert refused(lambda: port.merge(token, REPO, opened.number, head, "squash")) == 405
    assert refused(lambda: port.update_branch(token, REPO, opened.number, "0" * 40)) == 422
    assert refused(lambda: port.required_checks(token, REPO, "no-such-branch")) == 404
    port.update_branch(token, REPO, opened.number, head)
    updated = port.find_pull(token, REPO, "sortyard/ITEM-1")
    assert updated is not None and updated.head != head
    # The update is a merge of the base on top of the old head.
    base = repo.refs["refs/heads/main"]
    assert port.parents(token, REPO, updated.head) == (head, base)
    assert port.parents(token, REPO, head) == (repo.commits[head][0],)
    assert port.on_branch(token, REPO, "main", base)
    assert port.on_branch(token, REPO, "main", repo.commits[base][0])
    assert not port.on_branch(token, REPO, "main", head)
    assert not port.on_branch(token, REPO, "main", updated.head)
    assert port.on_branch(token, REPO, "sortyard/ITEM-1", head)
    assert refused(lambda: port.parents(token, REPO, "0" * 40)) == 404
    assert refused(lambda: port.on_branch(token, REPO, "main", "0" * 40)) == 404
    fake.check(repo, updated.head, "test")
    merge_sha = port.merge(token, REPO, opened.number, updated.head, "squash")
    assert repo.refs["refs/heads/main"] == merge_sha
    main = next(ref for ref in port.refs(token, REPO, "heads") if ref.name == "refs/heads/main")
    port.create_ref(token, REPO, "refs/heads/scratch/one", main.sha)
    assert refused(lambda: port.create_ref(token, REPO, "refs/heads/scratch/one", main.sha)) == 422
    port.delete_ref(token, REPO, "refs/heads/scratch/one")
    assert refused(lambda: port.delete_ref(token, REPO, "refs/heads/scratch/one")) == 422
    return repo, token


def test_every_fake_response_matches_the_published_github_schema_for_its_endpoint() -> None:
    """Every fake response matches the published GitHub schema for its endpoint."""
    with github() as (fake, port):
        every_call(fake, port)
        # Credentials GitHub refuses: no access to the repository, no such permission.
        fake.repo("walwarden/other")
        narrow = port.token("walwarden/other", {"contents": "read"})
        assert refused(lambda: port.refs(narrow, REPO, "heads")) == 404
        assert (
            refused(lambda: port.create_ref(narrow, "walwarden/other", "refs/heads/x", "0" * 40))
            == 403
        )
        assert refused(lambda: port.token("walwarden/other", {"administration": "write"})) == 422
        assert refused(lambda: port.token("nobody/nothing", {"contents": "read"})) == 404
        # The red-main observer's reads (src/sortyard/services/red_main.py).
        repo = fake.repos[REPO]
        workflow = fake.workflow(repo, ".github/workflows/ci.yml", "ci")
        fake.workflow_run(repo, workflow, "failure")
        reads = port.token(REPO, READ)
        assert port.default_branch(reads, REPO) == "main"
        (live,) = port.live_workflows(reads, REPO, "main")
        run = port.newest_verdict(reads, REPO, live, "main")
        assert run is not None and run.red and run.workflow == live
        assert port.workflow_files(reads, REPO, "no-such-branch") == frozenset()  # a 404
        assert refused(lambda: port.live_workflows(narrow, REPO, "main")) == 404
    fake.verify()
    # Every operation of the vendored fragment was served, and each reply matches its schema
    # (checked here again, apart from the fake's own check).
    contract = fake.contract
    assert {operation for operation, _, _ in fake.replies} == {o.id for o in contract.operations}
    statuses = {status for _, status, _ in fake.replies}
    assert statuses >= {200, 201, 202, 204, 403, 404, 405, 409, 422}
    for operation, status, payload in fake.replies:
        assert contract.response_errors(contract.operation(operation), status, payload) == []

    # The check bites: each successful reply, with one required field dropped or one field of
    # the wrong type, no longer passes; the fake reports it when it serves such a reply.
    damaged = 0
    for operation, status, payload in fake.replies:
        if status >= 300 or not payload:
            continue
        first = payload[0] if isinstance(payload, list) else payload
        if not isinstance(first, dict):
            continue
        for key in ("token", "id", "ref", "sha", "number", "name", "total_count", "message"):
            if key not in first:
                continue
            broken = copy.deepcopy(payload)
            target = broken[0] if isinstance(broken, list) else broken
            target[key] = ["not", "the", "type"]
            assert contract.response_errors(contract.operation(operation), status, broken), (
                operation,
                key,
            )
            damaged += 1
    assert damaged >= 10

    with github() as (wrong, port):
        wrong.repo(REPO)
        token = port.token(REPO, ALL)

        def drop_object(operation: str, payload: Any) -> Any:
            return [{k: v for k, v in each.items() if k != "object"} for each in payload]

        wrong.mutate = drop_object
        with pytest.raises(GitHubError):
            port.refs(token, REPO, "heads")
    assert any("git/list-matching-refs 200 reply" in violation for violation in wrong.violations)
    with pytest.raises(AssertionError):
        wrong.verify()


def test_the_fake_refuses_what_the_published_description_does_not_document() -> None:
    """A call, a query parameter or a body field outside the description is a violation."""

    def send(url: str, method: str, path: str, token: Token, body: Any = None) -> int:
        request = urllib.request.Request(
            url + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token.value}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return int(response.status)
        except urllib.error.HTTPError as error:
            return error.code

    cases: list[tuple[str, str, Any, str]] = [
        ("GET", f"/repos/{REPO}/issues", None, "undocumented call"),
        ("PATCH", f"/repos/{REPO}/pulls/1", {"state": "closed"}, "undocumented call"),
        ("GET", f"/repos/{REPO}/pulls?branch=x", None, "undocumented query parameter branch"),
        ("GET", f"/repos/{REPO}/pulls?state=merged", None, "query state"),
        ("POST", f"/repos/{REPO}/git/refs", {"ref": "refs/heads/x"}, "body"),
        ("POST", f"/repos/{REPO}/git/refs", None, "no body where one is required"),
        ("POST", f"/repos/{REPO}/pulls", None, "no body where one is required"),
        ("PUT", f"/repos/{REPO}/pulls/1/merge", {"head_sha": "abc"}, "undocumented body field"),
        ("PUT", f"/repos/{REPO}/pulls/1/merge", {"merge_method": "fast"}, "pulls/merge: body"),
    ]
    for method, path, body, expected in cases:
        with github() as (fake, port):
            fake.repo(REPO)
            token = port.token(REPO, ALL)
            assert send(fake.url, method, path, token, body) in (404, 422)
        assert any(expected in violation for violation in fake.violations), (path, fake.violations)


def test_the_http_client_sends_the_documented_method_path_and_body_for_each_port_call() -> None:
    """The HTTP client sends the documented method, path and body for each port call."""
    with github() as (fake, port):
        repo, token = every_call(fake, port)
    fake.verify()  # no request departed from the documented parameters and body schemas
    contract = fake.contract
    for seen in fake.requests:
        operation = contract.operation(seen.operation)
        assert (seen.method, seen.template) == (operation.method, operation.template)
        assert contract.request_errors(operation, seen.query, seen.body) == []
        assert seen.headers["x-github-api-version"] == "2022-11-28"

    def sent(operation: str) -> list[tuple[str, str, Any, Any]]:
        return [(s.method, s.path, dict(s.query) or None, s.body) for s in fake.seen(operation)]

    pull = repo.pull_of("sortyard/ITEM-1")
    assert sent("apps/get-repo-installation") == [
        ("GET", f"/repos/{REPO}/installation", None, None)
    ]
    installation = fake.replies[0][2]["id"]
    assert sent("apps/create-installation-access-token") == [
        (
            "POST",
            f"/app/installations/{installation}/access_tokens",
            None,
            {"repositories": ["app"], "permissions": ALL},
        )
    ]
    listing = {"head": "walwarden:sortyard/ITEM-1", "state": "all", "per_page": "100"}
    assert sent("pulls/list")[0] == ("GET", f"/repos/{REPO}/pulls", listing, None)
    assert sent("pulls/get")[0] == ("GET", f"/repos/{REPO}/pulls/{pull.number}", None, None)
    assert sent("pulls/create")[0] == (
        "POST",
        f"/repos/{REPO}/pulls",
        None,
        {"head": "sortyard/ITEM-1", "base": "main", "title": "ITEM-1", "body": ""},
    )
    assert sent("repos/get-branch")[0] == ("GET", f"/repos/{REPO}/branches/main", None, None)
    checks = sent("checks/list-for-ref")[0]
    assert checks[0] == "GET" and checks[1].endswith("/check-runs")
    assert checks[2] == {"per_page": "100", "page": "1"}
    update = sent("pulls/update-branch")[-1]
    assert update[:2] == ("PUT", f"/repos/{REPO}/pulls/{pull.number}/update-branch")
    assert set(update[3]) == {"expected_head_sha"}
    merge = sent("pulls/merge")[-1]
    assert merge[:2] == ("PUT", f"/repos/{REPO}/pulls/{pull.number}/merge")
    assert merge[3] == {"sha": pull.head, "merge_method": "squash"}
    commit = sent("git/get-commit")[0]
    assert commit == ("GET", f"/repos/{REPO}/git/commits/{pull.head}", None, None)
    compared = sent("repos/compare-commits")[0]
    assert compared[:3] == ("GET", f"/repos/{REPO}/compare/main...{pull.synced}", {"per_page": "1"})
    assert sent("git/list-matching-refs") == [
        ("GET", f"/repos/{REPO}/git/matching-refs/heads", None, None)
    ]
    created = sent("git/create-ref")[0]
    assert created[:2] == ("POST", f"/repos/{REPO}/git/refs")
    assert created[3]["ref"] == "refs/heads/scratch/one" and len(created[3]["sha"]) == 40
    assert sent("git/delete-ref")[0][:2] == ("DELETE", f"/repos/{REPO}/git/refs/heads/scratch/one")

    # The App's own token goes only to the two App endpoints; everything else carries the
    # installation token that was minted.
    for seen in fake.requests:
        scheme, _, credential = seen.headers["authorization"].partition(" ")
        assert scheme == "Bearer"
        if seen.operation.startswith("apps/"):
            assert credential.count(".") == 2 and credential != token.value
        else:
            assert credential == token.value


def test_the_checks_of_a_commit_are_read_across_pages() -> None:
    """More check runs than one page holds are all read."""
    with github() as (fake, port):
        repo = fake.repo(REPO)
        token = port.token(REPO, ALL)
        head = fake.push(repo, "sortyard/ITEM-1")
        for index in range(230):
            fake.check(repo, head, f"check-{index:03}", "failure" if index == 229 else "success")
        runs = port.checks(token, REPO, head)
    fake.verify()
    assert len(runs) == 230 and [run.name for run in runs if run.failed] == ["check-229"]
    assert [seen.query["page"] for seen in fake.seen("checks/list-for-ref")] == ["1", "2", "3"]


def test_the_fake_refuses_an_app_token_github_would_refuse() -> None:
    """A JSON web token signed by another key, or one that lives too long, mints nothing."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    now = [1_800_000_000.0]
    fake = FakeGitHub(APP_ID, KEY.public_key(), clock=lambda: now[0])
    with serving(fake) as url:
        fake.repo(REPO)
        assert refused(lambda: HttpGitHub(APP_ID, other, base_url=url).token(REPO, ALL)) == 401
        late = HttpGitHub(APP_ID, PEM, base_url=url, clock=lambda: now[0] + 3600)
        assert refused(lambda: late.token(REPO, ALL)) == 401
        assert (
            refused(
                lambda: HttpGitHub("1", PEM, base_url=url, clock=lambda: now[0]).token(REPO, ALL)
            )
            == 401
        )
        port = HttpGitHub(APP_ID, PEM, base_url=url, clock=lambda: now[0])
        token = port.token(REPO, ALL)
        assert port.refs(token, REPO, "heads")
        now[0] += 3601  # the installation token has expired
        assert refused(lambda: port.refs(token, REPO, "heads")) == 401
    assert fake.minted() == [token.value]
    fake.verify()


def test_a_redirect_is_refused_and_the_credential_goes_to_no_other_host() -> None:
    """A redirect is an error: the host it points at sees no request, so no credential."""
    arrived: list[str | None] = []

    class Elsewhere(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            arrived.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, format: str, *args: Any) -> None:
            return

    class Redirects(Elsewhere):
        target = ""

        def do_GET(self) -> None:
            self.send_response(301)
            self.send_header("Location", self.target + self.path)
            self.send_header("Content-Length", "0")
            self.end_headers()

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), each) for each in (Elsewhere, Redirects)]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        elsewhere, redirecting = (f"http://localhost:{s.server_address[1]}" for s in servers)
        Redirects.target = elsewhere
        port = HttpGitHub(APP_ID, PEM, base_url=redirecting)
        token = Token("ghs_" + "s" * 36, "", {})
        with pytest.raises(GitHubError) as caught:
            port.refs(token, REPO, "heads")
        assert caught.value.status == 301 and arrived == []
        assert refused(lambda: port.token(REPO, ALL)) == 301 and arrived == []
        # The redirect is real: a client that follows redirects ends up at the other host.
        request = urllib.request.Request(f"{redirecting}/x", headers={"Authorization": "none"})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.read() == b"[]"
        assert len(arrived) == 1
    finally:
        for server, thread in zip(servers, threads, strict=True):
            server.shutdown()
            server.server_close()
            thread.join()


def test_a_pull_request_is_opened_only_by_a_token_that_reads_contents() -> None:
    """GitHub refuses to open a pull request for a token with pull_requests:write alone, with a
    422 whose errors say "not all refs are readable" (SORTYARD-178, seen on the estate canary),
    and opens it once the token reads contents too. The fake answers the same, in the
    documented validation-error shape."""
    with github() as (fake, port):
        repo = fake.repo(REPO)
        fake.push(repo, "sortyard/ITEM-1")
        short = port.token(REPO, {"pull_requests": "write"})
        with pytest.raises(GitHubError) as caught:
            port.open_pull(short, REPO, branch="sortyard/ITEM-1", base="main", title="ITEM-1")
        assert (caught.value.status, caught.value.said) == (422, "Validation Failed")
        (said,) = [payload for name, status, payload in fake.replies if status == 422]
        assert said["errors"] == [
            {"resource": "PullRequest", "code": "custom", "message": "not all refs are readable"}
        ]
        assert repo.pulls == []
        enough = port.token(REPO, {"pull_requests": "write", "contents": "read"})
        opened = port.open_pull(enough, REPO, branch="sortyard/ITEM-1", base="main", title="ITEM-1")
        assert [pull.number for pull in repo.pulls] == [opened.number]
        fake.verify()
