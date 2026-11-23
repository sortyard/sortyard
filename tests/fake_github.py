"""A strict fake of the part of GitHub's REST API the GitHub port calls, served over real HTTP.

The fake holds repositories, branches, pull requests, check runs and installation tokens, and
answers in GitHub's JSON. It is held to GitHub's published API description, vendored as
`tests/contracts/github/fragment.json` (`Contract`):

- a call to a path or method outside the fragment, an undocumented query parameter or body
  field, a body that does not match the documented request schema, or a missing API header is
  refused and kept in `violations`;
- every reply is checked against the documented response schema of its endpoint and status
  before it is sent; a reply that does not match is kept in `violations` too.

`verify()` fails on any violation; the tests call it when they are done. It also refuses what
GitHub refuses: a JSON web token it cannot verify with the App's public key or that lives longer
than ten minutes, a token used on a repository it was not minted for or for a permission it
does not carry (the permission each endpoint needs is the one GitHub's REST reference names),
a merge whose `sha` is not the head, a merge of a merged pull request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import re
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from jsonschema import Draft4Validator  # type: ignore[import-untyped]

# A throwaway GitHub App for the tests: its id, its key, and the key as the client is given it.
APP_ID = "4242"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
)
FRAGMENT = pathlib.Path(__file__).parent / "contracts" / "github" / "fragment.json"
DOCS = "https://docs.github.com/rest"
WHEN = "2026-01-01T00:00:00Z"
LEVELS = {"read": 1, "write": 2}
# Statuses GitHub gives on any endpoint (bad credentials, no access, not found), which the
# description does not repeat per endpoint; their body is the basic error.
GENERAL = (401, 403, 404)
# What an installation is granted unless a test says otherwise.
GRANTED = {"contents": "write", "pull_requests": "write", "checks": "read", "workflows": "write"}
# The permission each endpoint needs, from the REST reference's fine-grained permission notes.
NEEDS = {
    "pulls/list": ("pull_requests", "read"),
    "pulls/get": ("pull_requests", "read"),
    "pulls/create": ("pull_requests", "write"),
    "pulls/update-branch": ("pull_requests", "write"),
    "pulls/merge": ("contents", "write"),
    "repos/get-branch": ("contents", "read"),
    "checks/list-for-ref": ("checks", "read"),
    "git/list-matching-refs": ("contents", "read"),
    "git/create-ref": ("contents", "write"),
    "git/delete-ref": ("contents", "write"),
    "git/get-commit": ("contents", "read"),
    "repos/compare-commits": ("contents", "read"),
}
APP_OPERATIONS = ("apps/get-repo-installation", "apps/create-installation-access-token")


def _json_schema(node: Any) -> Any:
    """An OpenAPI 3.0 schema as JSON Schema draft 4: `nullable` becomes a null alternative."""
    if isinstance(node, list):
        return [_json_schema(each) for each in node]
    if not isinstance(node, dict):
        return node
    converted = {
        key: {name: _json_schema(each) for name, each in value.items()}
        if key == "properties"
        else _json_schema(value)
        for key, value in node.items()
        if key != "nullable"
    }
    if node.get("nullable") is True:
        return {"anyOf": [converted, {"type": "null"}]}
    return converted


@dataclass(frozen=True)
class Operation:
    id: str
    method: str
    template: str
    pattern: re.Pattern[str]
    query: Mapping[str, Any]
    body: Any
    body_required: bool
    responses: Mapping[str, Any]


class Contract:
    """The vendored fragment of GitHub's published API description, as validators."""

    def __init__(self) -> None:
        raw = json.loads(FRAGMENT.read_text())
        self.source = {key: raw[key] for key in ("source", "file", "commit", "version")}
        self._components = _json_schema(raw["components"])
        self.operations: list[Operation] = []
        for template, methods in raw["paths"].items():
            # A ref or a branch may hold slashes; no other path parameter does.
            pattern = re.sub(
                r"\{(\w+)\}",
                lambda m: (
                    f"(?P<{m[1]}>.+)"
                    if m[1] in ("ref", "branch", "basehead")
                    else f"(?P<{m[1]}>[^/]+)"
                ),
                template,
            )
            for method, operation in methods.items():
                self.operations.append(
                    Operation(
                        id=operation["operationId"],
                        method=method.upper(),
                        template=template,
                        pattern=re.compile(pattern),
                        query={
                            p["name"]: p["schema"]
                            for p in operation["parameters"]
                            if p["in"] == "query"
                        },
                        body=operation["requestBody"],
                        body_required=operation["requestBodyRequired"],
                        responses=operation["responses"],
                    )
                )

    def find(self, method: str, path: str) -> tuple[Operation, dict[str, str]] | None:
        for operation in self.operations:
            matched = operation.pattern.fullmatch(path)
            if matched and operation.method == method:
                return operation, matched.groupdict()
        return None

    def operation(self, operation_id: str) -> Operation:
        return next(each for each in self.operations if each.id == operation_id)

    def errors(self, schema: Any, value: Any) -> list[str]:
        """How `value` fails the published `schema`; empty when it matches."""
        document = {**_json_schema(schema), "components": self._components}
        return sorted(
            f"{'/'.join(str(p) for p in error.absolute_path) or '.'}: {error.message}"
            for error in Draft4Validator(document).iter_errors(value)
        )

    def request_errors(
        self, operation: Operation, query: Mapping[str, str], body: Any
    ) -> list[str]:
        """How a request departs from what the description documents for the operation."""
        found = [
            f"undocumented query parameter {name}" for name in query if name not in operation.query
        ]
        for name, value in query.items():
            schema = operation.query.get(name, {})
            typed: Any = (
                int(value) if schema.get("type") == "integer" and value.isdigit() else value
            )
            found += [f"query {name} {e}" for e in self.errors(schema, typed)]
        if body is None and operation.body_required:
            found.append("no body where one is required")
        if body is not None:
            if operation.body is None:
                return [*found, "a body where none is documented"]
            known = operation.body.get("properties", {})
            if isinstance(body, dict):
                found += [f"undocumented body field {name}" for name in body if name not in known]
            found += [f"body {e}" for e in self.errors(operation.body, body)]
        return found

    def response_errors(self, operation: Operation, status: int, payload: Any) -> list[str]:
        """How a reply departs from the documented response of the operation and status."""
        if str(status) not in operation.responses:
            if status not in GENERAL:
                return [f"status {status} is not documented"]
            schema: Any = {"$ref": "#/components/schemas/basic-error"}
        else:
            schema = operation.responses[str(status)]
        if schema is None:
            if status < 300:
                return [] if payload is None else ["a body where none is documented"]
            schema = {"$ref": "#/components/schemas/basic-error"}
        return self.errors(schema, payload)


class Refused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class FakePull:
    number: int
    branch: str
    base: str
    title: str
    head: str
    synced: str  # the base commit the branch is up to date with
    open: bool = True
    merged: bool = False
    merge_sha: str | None = None
    conflict: bool = False
    computing: int = 0  # how many more reads answer "mergeability not known yet"
    draft: bool = False
    blocked: bool = False  # GitHub blocks the merge for a reason that is not a check
    pending: bool = False  # an update of the branch was accepted and has not landed yet
    merges: int = 0  # merge calls GitHub carried out
    updates: int = 0  # update-branch calls GitHub carried out


@dataclass
class FakeRepo:
    full_name: str
    refs: dict[str, str]
    commits: dict[str, list[str]] = field(default_factory=dict)  # a commit's parents
    methods: set[str] = field(default_factory=lambda: {"merge", "squash", "rebase"})
    required: dict[str, list[str]] = field(default_factory=dict)
    strict: set[str] = field(default_factory=set)
    pulls: list[FakePull] = field(default_factory=list)
    runs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def pull_of(self, branch: str) -> FakePull:
        return [pull for pull in self.pulls if pull.branch == branch][-1]


@dataclass(frozen=True)
class Seen:
    """One request the fake received."""

    operation: str
    method: str
    path: str
    template: str
    query: Mapping[str, str]
    body: Any
    headers: Mapping[str, str]


class FakeGitHub:
    def __init__(
        self, app_id: str, public_key: rsa.RSAPublicKey, clock: Callable[[], float] = time.time
    ) -> None:
        self.contract = Contract()
        self.app_id, self._public_key, self._clock = app_id, public_key, clock
        self.url = "http://fake.invalid"
        self.repos: dict[str, FakeRepo] = {}
        self.granted: dict[str, dict[str, str]] = {}  # by owner: the installation's grant
        self.tokens: dict[str, tuple[set[str], dict[str, str], float]] = {}
        self.requests: list[Seen] = []
        self.replies: list[tuple[str, int, Any]] = []
        self.violations: list[str] = []
        # Changes a reply before it is checked and sent: how a test makes the fake wrong.
        self.mutate: Callable[[str, Any], Any] | None = None
        # update-branch answers 202 and the head moves only when the test calls `land`.
        self.slow_updates = False
        # The next reply says it is longer than it is, and the connection closes.
        self.truncate = False
        self._lock = threading.Lock()
        self._count = 0

    # What a test arranges.

    def commit(self, repo: FakeRepo, parents: list[str]) -> str:
        self._count += 1
        sha = hashlib.sha1(str(self._count).encode()).hexdigest()
        repo.commits[sha] = parents
        return sha

    def repo(self, full_name: str, granted: Mapping[str, str] | None = None) -> FakeRepo:
        owner = full_name.split("/")[0]
        if granted is not None or owner not in self.granted:
            self.granted[owner] = dict(GRANTED if granted is None else granted)
        repo = self.repos[full_name] = FakeRepo(full_name, {})
        repo.refs["refs/heads/main"] = self.commit(repo, [])
        return repo

    def push(self, repo: FakeRepo, branch: str, parents: list[str] | None = None) -> str:
        """A new commit on a branch (on its head, or on main's for a new branch, unless
        `parents` says otherwise); an open pull request of the branch gets it as its head."""
        ref = f"refs/heads/{branch}"
        on = repo.refs.get(ref, repo.refs["refs/heads/main"])
        sha = repo.refs[ref] = self.commit(repo, [on] if parents is None else parents)
        for pull in repo.pulls:
            if pull.open and pull.branch == branch:
                pull.head = sha
        return sha

    def land(self, repo: FakeRepo, pull: FakePull) -> str:
        """The branch update lands: a merge of the base into the branch becomes the head."""
        base = repo.refs[f"refs/heads/{pull.base}"]
        pull.head = repo.refs[f"refs/heads/{pull.branch}"] = self.commit(repo, [pull.head, base])
        pull.synced, pull.pending = base, False
        return pull.head

    def protect(
        self, repo: FakeRepo, branch: str, contexts: list[str], strict: bool = False
    ) -> None:
        repo.required[branch] = contexts
        if strict:
            repo.strict.add(branch)

    def check(
        self,
        repo: FakeRepo,
        sha: str,
        name: str,
        conclusion: str | None = "success",
        *,
        again: bool = False,
        listed_first: bool = False,
    ) -> None:
        """A check run reports on a commit; with no conclusion it is still in progress.

        It replaces the runs of that name unless `again`: then it is a later run beside them,
        listed after them, or before them when `listed_first`.
        """
        self._count += 1
        run = {
            "name": name,
            "status": "in_progress" if conclusion is None else "completed",
            "conclusion": conclusion,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1_767_225_600 + self._count)),
        }
        runs = [each for each in repo.runs.get(sha, []) if again or each["name"] != name]
        repo.runs[sha] = [run, *runs] if listed_first else [*runs, run]

    def verify(self) -> None:
        assert not self.violations, self.violations

    def minted(self) -> list[str]:
        return list(self.tokens)

    def seen(self, operation: str) -> list[Seen]:
        return [request for request in self.requests if request.operation == operation]

    # The API.

    def handle(
        self, method: str, target: str, headers: Mapping[str, str], raw: bytes
    ) -> tuple[int, Any]:
        with self._lock:
            split = urlsplit(target)
            path, query = unquote(split.path), dict(parse_qsl(split.query))
            found = self.contract.find(method, path)
            if found is None:
                self.violations.append(f"undocumented call: {method} {path}")
                return 404, self._error("Not Found")
            operation, params = found
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw.decode(errors="replace")
            lowered = {name.lower(): value for name, value in headers.items()}
            self.requests.append(
                Seen(operation.id, method, path, operation.template, query, body, lowered)
            )
            problems = self.contract.request_errors(operation, query, body)
            if lowered.get("accept") != "application/vnd.github+json":
                problems.append("no Accept: application/vnd.github+json")
            if not lowered.get("x-github-api-version"):
                problems.append("no X-GitHub-Api-Version")
            if problems:
                self.violations += [f"{operation.id}: {problem}" for problem in problems]
                status, payload = 422, self._error("; ".join(problems))
            else:
                try:
                    status, payload = self._serve(operation, params, lowered, query, body or {})
                except Refused as refused:
                    status, payload = refused.status, self._error(refused.message)
            if self.mutate is not None:
                payload = self.mutate(operation.id, payload)
            self.violations += [
                f"{operation.id} {status} reply: {problem}"
                for problem in self.contract.response_errors(operation, status, payload)
            ]
            self.replies.append((operation.id, status, payload))
            return status, payload

    def _error(self, message: str) -> dict[str, str]:
        return {"message": message, "documentation_url": DOCS}

    def _serve(
        self,
        operation: Operation,
        params: dict[str, str],
        headers: Mapping[str, str],
        query: Mapping[str, str],
        body: dict[str, Any],
    ) -> tuple[int, Any]:
        scheme, _, credential = headers.get("authorization", "").partition(" ")
        if scheme not in ("Bearer", "token") or not credential:
            raise Refused(401, "Requires authentication")
        if operation.id in APP_OPERATIONS:
            self._app(credential)
            if operation.id == "apps/get-repo-installation":
                self._repo(params)
                return 200, self._installation(params["owner"])
            return self._mint(int(params["installation_id"]), body)
        repo = self._repo(params)
        repos, permissions, expires = self.tokens.get(credential, (set(), {}, 0.0))
        if expires <= self._clock():
            raise Refused(401, "Bad credentials")
        if repo.full_name not in repos:
            raise Refused(404, "Not Found")
        permission, level = NEEDS[operation.id]
        if LEVELS.get(permissions.get(permission, ""), 0) < LEVELS[level]:
            raise Refused(403, "Resource not accessible by integration")
        handler: Callable[..., tuple[int, Any]] = getattr(
            self, "_" + re.sub(r"\W", "_", operation.id)
        )
        return handler(repo, params, query, body)

    def _app(self, token: str) -> None:
        """Refuse a JSON web token GitHub would refuse."""
        try:
            signed, _, signature = token.rpartition(".")
            header, claims = (
                json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
                for part in signed.split(".")
            )
            self._public_key.verify(
                base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
                signed.encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            now = self._clock()
            good = (
                header["alg"] == "RS256"
                and str(claims["iss"]) == self.app_id
                and claims["iat"] <= now < claims["exp"] <= now + 600
            )
        except (ValueError, KeyError, TypeError, InvalidSignature):
            good = False
        if not good:
            raise Refused(401, "A JSON web token could not be decoded")

    def _repo(self, params: Mapping[str, str]) -> FakeRepo:
        repo = self.repos.get(f"{params['owner']}/{params['repo']}")
        if repo is None:
            raise Refused(404, "Not Found")
        return repo

    def _installation_id(self, owner: str) -> int:
        return 7000 + sorted(self.granted).index(owner)

    def _mint(self, installation: int, body: dict[str, Any]) -> tuple[int, Any]:
        owner = next((o for o in self.granted if self._installation_id(o) == installation), None)
        if owner is None:
            raise Refused(404, "Not Found")
        granted = self.granted[owner]
        mine = {name for name in self.repos if name.split("/")[0] == owner}
        names = (
            {f"{owner}/{name}" for name in body["repositories"]} if "repositories" in body else mine
        )
        if not names <= mine:
            raise Refused(422, "There is at least one repository that does not exist")
        asked: dict[str, str] = body.get("permissions", granted)
        if any(
            LEVELS[level] > LEVELS.get(granted.get(name, ""), 0) for name, level in asked.items()
        ):
            raise Refused(422, "The permissions requested are not granted to this installation.")
        value = "ghs_" + hashlib.sha256(f"token {len(self.tokens)}".encode()).hexdigest()[:36]
        expires = self._clock() + 3600
        self.tokens[value] = (names, dict(asked), expires)
        return 201, {
            "token": value,
            "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires)),
            "permissions": dict(asked),
            "repository_selection": "selected" if "repositories" in body else "all",
            "repositories": [self._repository(name) for name in sorted(names)],
        }

    def _pulls_list(self, repo: FakeRepo, params: Any, query: Mapping[str, str], body: Any) -> Any:
        state = query.get("state", "open")
        owner, _, branch = query.get("head", "").partition(":")
        return 200, [
            self._pull(repo, pull, full=False)
            for pull in repo.pulls
            if state in ("all", "open" if pull.open else "closed")
            and (
                not query.get("head")
                or (owner, branch) == (repo.full_name.split("/")[0], pull.branch)
            )
        ]

    def _pulls_get(self, repo: FakeRepo, params: Mapping[str, str], query: Any, body: Any) -> Any:
        return 200, self._pull(repo, self._find(repo, params), full=True)

    def _pulls_create(self, repo: FakeRepo, params: Any, query: Any, body: dict[str, Any]) -> Any:
        head = repo.refs.get(f"refs/heads/{body['head']}")
        base = repo.refs.get(f"refs/heads/{body['base']}")
        if head is None or base is None:
            raise Refused(422, "Validation Failed")
        if any(pull.open and pull.branch == body["head"] for pull in repo.pulls):
            raise Refused(422, "A pull request already exists for this branch")
        pull = FakePull(
            len(repo.pulls) + 1, body["head"], body["base"], body.get("title", ""), head, base
        )
        repo.pulls.append(pull)
        return 201, self._pull(repo, pull, full=True)

    def _pulls_update_branch(
        self, repo: FakeRepo, params: Mapping[str, str], query: Any, body: dict[str, Any]
    ) -> Any:
        pull = self._find(repo, params)
        if body.get("expected_head_sha", pull.head) != pull.head:
            raise Refused(422, "expected head sha didn't match current head ref.")
        if pull.pending or pull.synced == repo.refs[f"refs/heads/{pull.base}"]:
            raise Refused(422, "There are no new commits on the base branch.")
        pull.pending = True
        pull.updates += 1
        if not self.slow_updates:
            self.land(repo, pull)
        url = f"{self.url}/repos/{repo.full_name}/pulls/{pull.number}"
        return 202, {"message": "Updating pull request branch.", "url": url}

    def _pulls_merge(
        self, repo: FakeRepo, params: Mapping[str, str], query: Any, body: dict[str, Any]
    ) -> Any:
        pull = self._find(repo, params)
        if pull.merged or not pull.open:
            raise Refused(405, "Pull Request is not mergeable")
        if body.get("sha", pull.head) != pull.head:
            raise Refused(409, "Head branch was modified. Review and try the merge again.")
        method = body.get("merge_method", "merge")
        if method not in repo.methods:
            raise Refused(405, f"{method.title()} merges are not allowed on this repository.")
        mergeable, state = self._mergeable(repo, pull, reading=False)
        if not mergeable or state != "clean":
            raise Refused(405, f"Pull Request is not mergeable ({state})")
        base = repo.refs[f"refs/heads/{pull.base}"]
        pull.merge_sha = repo.refs[f"refs/heads/{pull.base}"] = self.commit(repo, [base])
        pull.merged, pull.open = True, False
        pull.merges += 1
        return 200, {
            "sha": pull.merge_sha,
            "merged": True,
            "message": "Pull Request successfully merged",
        }

    def _repos_get_branch(
        self, repo: FakeRepo, params: Mapping[str, str], query: Any, body: Any
    ) -> Any:
        name = params["branch"]
        sha = repo.refs.get(f"refs/heads/{name}")
        if sha is None:
            raise Refused(404, "Branch not found")
        url = f"{self.url}/repos/{repo.full_name}"
        contexts = repo.required.get(name, [])
        return 200, {
            "name": name,
            "commit": self._commit(repo, sha),
            "_links": {"html": f"{url}/tree/{name}", "self": f"{url}/branches/{name}"},
            "protected": name in repo.required,
            "protection": {
                "enabled": name in repo.required,
                "required_status_checks": {
                    "enforcement_level": "non_admins" if contexts else "off",
                    "contexts": contexts,
                    "checks": [{"context": context, "app_id": None} for context in contexts],
                },
            },
            "protection_url": f"{url}/branches/{name}/protection",
        }

    def _checks_list_for_ref(
        self, repo: FakeRepo, params: Mapping[str, str], query: Mapping[str, str], body: Any
    ) -> Any:
        sha, url = params["ref"], f"{self.url}/repos/{repo.full_name}"
        runs = [
            {
                "id": index,
                "node_id": f"CR_{index}",
                "head_sha": sha,
                "name": run["name"],
                "url": f"{url}/check-runs/{index}",
                "html_url": None,
                "details_url": None,
                "status": run["status"],
                "conclusion": run["conclusion"],
                "started_at": run["at"],
                "completed_at": run["at"] if run["conclusion"] else None,
                "external_id": None,
                "check_suite": {"id": 1},
                "output": {
                    "title": None,
                    "summary": None,
                    "text": None,
                    "annotations_count": 0,
                    "annotations_url": f"{url}/check-runs/{index}/annotations",
                },
                "app": None,
                "pull_requests": [],
            }
            for index, run in enumerate(repo.runs.get(sha, []), start=1)
        ]
        size, page = int(query.get("per_page", 30)), int(query.get("page", 1))
        return 200, {"total_count": len(runs), "check_runs": runs[(page - 1) * size : page * size]}

    def _git_get_commit(
        self, repo: FakeRepo, params: Mapping[str, str], query: Any, body: Any
    ) -> Any:
        sha, url = params["commit_sha"], f"{self.url}/repos/{repo.full_name}"
        if sha not in repo.commits:
            raise Refused(404, "Not Found")
        who = {"date": WHEN, "email": "bot@example.test", "name": "bot"}
        return 200, {
            "sha": sha,
            "node_id": f"C_{sha[:8]}",
            "url": f"{url}/git/commits/{sha}",
            "html_url": f"{url}/commit/{sha}",
            "author": who,
            "committer": who,
            "tree": {"sha": sha, "url": f"{url}/git/trees/{sha}"},
            "message": "a change",
            "parents": self._commit(repo, sha)["parents"],
            "verification": {
                "verified": False,
                "reason": "unsigned",
                "signature": None,
                "payload": None,
                "verified_at": None,
            },
        }

    def _repos_compare_commits(
        self, repo: FakeRepo, params: Mapping[str, str], query: Mapping[str, str], body: Any
    ) -> Any:
        names = params["basehead"].split("...")
        shas = [repo.refs.get(f"refs/heads/{name}", name) for name in names]
        if len(shas) != 2 or any(sha not in repo.commits for sha in shas):
            raise Refused(404, "Not Found")
        base, head = (self._ancestry(repo, sha) for sha in shas)
        ahead, behind = [sha for sha in head if sha not in base], base.keys() - head.keys()
        status = ("ahead" if ahead else "identical") if not behind else "behind"
        url = f"{self.url}/repos/{repo.full_name}/compare/{params['basehead']}"
        # The newest commit both have: `head` is listed nearest first.
        common = next((sha for sha in head if sha in base), shas[0])
        return 200, {
            "url": url,
            "html_url": url,
            "permalink_url": url,
            "diff_url": f"{url}.diff",
            "patch_url": f"{url}.patch",
            "base_commit": self._commit(repo, shas[0]),
            "merge_base_commit": self._commit(repo, common),
            "status": "diverged" if ahead and behind else status,
            "ahead_by": len(ahead),
            "behind_by": len(behind),
            "total_commits": len(ahead),
            "commits": [self._commit(repo, sha) for sha in ahead[: int(query.get("per_page", 30))]],
        }

    def _ancestry(self, repo: FakeRepo, sha: str) -> dict[str, None]:
        """The commit and everything it descends from, nearest first."""
        found: dict[str, None] = {}
        queue = [sha]
        while queue:
            each = queue.pop(0)
            if each not in found:
                found[each] = None
                queue += repo.commits[each]
        return found

    def _commit(self, repo: FakeRepo, sha: str) -> dict[str, Any]:
        url = f"{self.url}/repos/{repo.full_name}"
        return {
            "url": f"{url}/commits/{sha}",
            "sha": sha,
            "node_id": f"C_{sha[:8]}",
            "html_url": f"{url}/commit/{sha}",
            "comments_url": f"{url}/commits/{sha}/comments",
            "commit": {
                "author": None,
                "committer": None,
                "comment_count": 0,
                "message": "a change",
                "tree": {"sha": sha, "url": f"{url}/git/trees/{sha}"},
                "url": f"{url}/git/commits/{sha}",
            },
            "author": None,
            "committer": None,
            "parents": [
                {
                    "sha": parent,
                    "url": f"{url}/commits/{parent}",
                    "html_url": f"{url}/commit/{parent}",
                }
                for parent in repo.commits[sha]
            ],
        }

    def _git_list_matching_refs(
        self, repo: FakeRepo, params: Mapping[str, str], query: Any, body: Any
    ) -> Any:
        prefix = f"refs/{params['ref']}"
        return 200, [self._ref(repo, name) for name in sorted(repo.refs) if name.startswith(prefix)]

    def _git_create_ref(self, repo: FakeRepo, params: Any, query: Any, body: dict[str, Any]) -> Any:
        name, sha = body["ref"], body["sha"]
        if not name.startswith("refs/") or name.count("/") < 2 or sha not in repo.commits:
            raise Refused(422, "Reference update failed")
        if name in repo.refs:
            raise Refused(422, "Reference already exists")
        repo.refs[name] = sha
        return 201, self._ref(repo, name)

    def _git_delete_ref(
        self, repo: FakeRepo, params: Mapping[str, str], query: Any, body: Any
    ) -> Any:
        if repo.refs.pop(f"refs/{params['ref']}", None) is None:
            raise Refused(422, "Reference does not exist")
        return 204, None

    # The objects GitHub answers with.

    def _find(self, repo: FakeRepo, params: Mapping[str, str]) -> FakePull:
        for pull in repo.pulls:
            if str(pull.number) == params["pull_number"]:
                return pull
        raise Refused(404, "Not Found")

    def _mergeable(
        self, repo: FakeRepo, pull: FakePull, reading: bool = True
    ) -> tuple[bool | None, str]:
        if pull.merged or not pull.open:
            return None, "unknown"
        if reading and pull.computing:
            pull.computing -= 1
            return None, "unknown"
        if pull.conflict:
            return False, "dirty"
        if pull.base in repo.strict and pull.synced != repo.refs[f"refs/heads/{pull.base}"]:
            return True, "behind"
        if pull.draft:
            return True, "draft"
        latest = sorted(repo.runs.get(pull.head, []), key=lambda run: str(run["at"]))
        runs = {run["name"]: run["conclusion"] for run in latest}
        required = repo.required.get(pull.base, [])
        if pull.blocked or any(runs.get(name) != "success" for name in required):
            return True, "blocked"
        return True, "clean"

    def _ref(self, repo: FakeRepo, name: str) -> dict[str, Any]:
        url, sha = f"{self.url}/repos/{repo.full_name}/git", repo.refs[name]
        return {
            "ref": name,
            "node_id": f"REF_{sha[:8]}",
            "url": f"{url}/{name}",
            "object": {"type": "commit", "sha": sha, "url": f"{url}/commits/{sha}"},
        }

    def _user(self, login: str) -> dict[str, Any]:
        url = f"{self.url}/users/{login}"
        urls = [
            "events",
            "followers",
            "following",
            "gists",
            "organizations",
            "received_events",
            "repos",
            "starred",
            "subscriptions",
        ]
        return {
            "login": login,
            "id": 1,
            "node_id": f"U_{login}",
            "avatar_url": f"{url}/avatar",
            "gravatar_id": None,
            "html_url": url,
            "site_admin": False,
            "type": "Organization",
            "url": url,
            **{f"{name}_url": f"{url}/{name}" for name in urls},
        }

    def _repository(self, full_name: str) -> dict[str, Any]:
        url = f"{self.url}/repos/{full_name}"
        urls = [
            "archive",
            "assignees",
            "blobs",
            "branches",
            "collaborators",
            "comments",
            "commits",
            "compare",
            "contents",
            "contributors",
            "deployments",
            "downloads",
            "events",
            "forks",
            "git_commits",
            "git_refs",
            "git_tags",
            "hooks",
            "issue_comment",
            "issue_events",
            "issues",
            "keys",
            "labels",
            "languages",
            "merges",
            "milestones",
            "notifications",
            "pulls",
            "releases",
            "stargazers",
            "statuses",
            "subscribers",
            "subscription",
            "tags",
            "teams",
            "trees",
            "clone",
            "git",
            "ssh",
            "svn",
        ]
        counts = "forks forks_count open_issues open_issues_count size stargazers_count watchers"
        flags = "fork private has_downloads has_issues has_projects has_wiki has_pages archived"
        return {
            "id": 1,
            "node_id": f"R_{full_name}",
            "name": full_name.split("/")[1],
            "full_name": full_name,
            "owner": self._user(full_name.split("/")[0]),
            "html_url": url,
            "url": url,
            "description": None,
            "homepage": None,
            "language": None,
            "mirror_url": None,
            "license": None,
            "default_branch": "main",
            "pushed_at": WHEN,
            "created_at": WHEN,
            "updated_at": WHEN,
            **{f"{name}_url": f"{url}/{name}" for name in urls},
            **dict.fromkeys([*counts.split(), "watchers_count"], 0),
            **dict.fromkeys([*flags.split(), "disabled"], False),
        }

    def _installation(self, owner: str) -> dict[str, Any]:
        identifier = self._installation_id(owner)
        url = f"{self.url}/app/installations/{identifier}"
        return {
            "id": identifier,
            "app_id": 1,
            "app_slug": "sortyard",
            "target_id": 1,
            "target_type": "Organization",
            "single_file_name": None,
            "repository_selection": "all",
            "access_tokens_url": f"{url}/access_tokens",
            "html_url": url,
            "repositories_url": f"{self.url}/installation/repositories",
            "events": [],
            "account": self._user(owner),
            "permissions": self.granted[owner],
            "created_at": WHEN,
            "updated_at": WHEN,
            "suspended_by": None,
            "suspended_at": None,
        }

    def _pull(self, repo: FakeRepo, pull: FakePull, full: bool) -> dict[str, Any]:
        owner = repo.full_name.split("/")[0]
        url = f"{self.url}/repos/{repo.full_name}/pulls/{pull.number}"
        links = "comments commits statuses html issue review_comments review_comment self"
        side = {"repo": self._repository(repo.full_name), "user": self._user(owner)}
        found: dict[str, Any] = {
            "id": pull.number,
            "node_id": f"PR_{pull.number}",
            "number": pull.number,
            "title": pull.title,
            "body": None,
            "state": "open" if pull.open else "closed",
            "locked": False,
            "user": self._user(owner),
            "labels": [],
            "milestone": None,
            "assignee": None,
            "head": {
                "label": f"{owner}:{pull.branch}",
                "ref": pull.branch,
                "sha": pull.head,
                **side,
            },
            "base": {
                "label": f"{owner}:{pull.base}",
                "ref": pull.base,
                "sha": repo.refs[f"refs/heads/{pull.base}"],
                **side,
            },
            "merge_commit_sha": pull.merge_sha,
            "created_at": WHEN,
            "updated_at": WHEN,
            "closed_at": None if pull.open else WHEN,
            "merged_at": WHEN if pull.merged else None,
            "draft": pull.draft,
            "author_association": "MEMBER",
            "auto_merge": None,
            "url": url,
            "html_url": url,
            "_links": {name: {"href": f"{url}/{name}"} for name in links.split()},
            **{
                f"{name}_url": f"{url}/{name}"
                for name in [
                    "comments",
                    "commits",
                    "diff",
                    "issue",
                    "patch",
                    "review_comment",
                    "review_comments",
                    "statuses",
                ]
            },
        }
        if full:
            mergeable, state = self._mergeable(repo, pull)
            found |= {
                "merged": pull.merged,
                "mergeable": mergeable,
                "mergeable_state": state,
                "merged_by": None,
                "maintainer_can_modify": False,
                **dict.fromkeys(
                    [
                        "additions",
                        "changed_files",
                        "comments",
                        "commits",
                        "deletions",
                        "review_comments",
                    ],
                    0,
                ),
            }
        return found


class _Handler(BaseHTTPRequestHandler):
    fake: FakeGitHub

    def _serve(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        status, payload = self.fake.handle(self.command, self.path, dict(self.headers), raw)
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        cut, self.fake.truncate = self.fake.truncate, False
        self.send_header("Content-Length", str(len(data) + (64 if cut else 0)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

    def log_message(self, format: str, *args: Any) -> None:
        return


@contextmanager
def serving(fake: FakeGitHub) -> Iterator[str]:
    """Serve the fake over HTTP on a free local port; yields (and sets `fake.url` to) its URL."""
    handler = type("Handler", (_Handler,), {"fake": fake})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield fake.url
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
