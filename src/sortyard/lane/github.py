"""The GitHub port, and the three things a lane runs on it (HARNESS-V3 sections 3.1, 3.3).

`GitHub` is the port: mint an installation token scoped to one repository with named
permissions, find and open the pull request of a branch, read the required checks of a base
branch and the check runs of a head commit, update a pull request branch, merge with the head
commit matched, and list, create and delete refs. `HttpGitHub` is the real client (standard
library HTTP, the App's JSON web token signed with `cryptography`: SY-DEC-008).

Built on the port:

- `CiAdapter`, the `ci-adapter` owner of `checking`: `green` when every required check of the
  head passed, `red` with the failing check names as the finding when one failed, nothing while
  a check is pending or missing. A base branch with no required checks takes every check run
  of the head.
- `MergeAdapter`, the `merge-adapter` owner of `merging`: merges a pull request whose head is
  the commit the review approved (`detail["head"]`) and answers `merged`; answers `conflict`
  when GitHub reports the branch cannot be merged; updates the branch when it is behind and the
  action is `update-branch`; answers `merged` without merging again when it is already merged.
  A head that differs from the reviewed one is never merged: the stay is left open with the
  reason, and the state's limit applies.
- `RepositoryProbe`, the preflight probe of a `repository` need: pushes and deletes a scratch
  ref with a token minted for that one repository, and for a repository declared with
  workflow-files asks for, and checks it was given, the workflows permission.

There is no webhook receiver, so everything is poll-shaped. An owner is called with the item
workflow's call and answers at once when GitHub already knows the result; otherwise it answers
nothing and the stay stays open. `observe` is the same look for a poller: it returns an
`Observation` whose `outcome` is none while the stay is open (`detail["waiting"]` says why) and
whose `reply()` is what to send with `send_outcome`. Both are safe to call twice for one
dispatch: nothing is remembered between calls, and the pull request of an item is found each
time by its branch name, `sortyard/<item id>`.

A token is never printed or returned in an error: `Token` hides its value from `repr`, and a
`GitHubError` carries only the status, the method, the path and GitHub's own message.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sortyard.kernel.capabilities import REPOSITORY, Lane, Need
from sortyard.kernel.item import Payload
from sortyard.kernel.preflight import ProbeResult

API = "https://api.github.com"
API_VERSION = "2022-11-28"
CI_OWNER = "ci-adapter"
MERGE_OWNER = "merge-adapter"
UPDATE_BRANCH_ACTION = "update-branch"
# Check conclusions that count as passed; any other conclusion of a completed check failed.
PASSED = frozenset({"success", "neutral", "skipped"})
# The `mergeable_state` values GitHub gives a pull request it would merge now.
MERGEABLE_STATES = frozenset({"clean", "unstable", "has_hooks"})
SCRATCH_PREFIX = "refs/heads/sortyard-probe/"


class GitHubError(Exception):
    """GitHub refused a call or could not be reached. `status` is 0 when there was no answer.

    The message holds the status, the method, the path and GitHub's `message`; never a header,
    a request body or a response body, so never a token.
    """

    def __init__(self, status: int, method: str, path: str, message: str) -> None:
        super().__init__(f"GitHub answered {status} to {method} {path}: {message}")
        self.status = status


@dataclass(frozen=True)
class Token:
    """An installation token for one repository. The value is kept out of `repr`."""

    value: str = field(repr=False)
    expires_at: str
    permissions: Mapping[str, str]


@dataclass(frozen=True)
class Pull:
    """A pull request, as far as the adapters read it. `head` is the head commit."""

    number: int
    head: str
    base: str
    open: bool
    merged: bool
    mergeable: bool | None
    mergeable_state: str
    merge_sha: str | None


@dataclass(frozen=True)
class Check:
    """One check run of a commit."""

    name: str
    status: str
    conclusion: str | None

    @property
    def done(self) -> bool:
        return self.status == "completed"

    @property
    def failed(self) -> bool:
        return self.done and self.conclusion not in PASSED


@dataclass(frozen=True)
class Ref:
    name: str  # fully qualified: refs/heads/main
    sha: str


class GitHub(Protocol):
    """What a lane asks of GitHub. `repository` is always `owner/name`."""

    def token(self, repository: str, permissions: Mapping[str, str]) -> Token:
        """A new installation token for that one repository with those permissions only."""
        ...

    def find_pull(self, token: Token, repository: str, branch: str) -> Pull | None:
        """The pull request of a branch of the repository: the open one, else the newest."""
        ...

    def open_pull(
        self, token: Token, repository: str, *, branch: str, base: str, title: str, body: str = ""
    ) -> Pull: ...

    def required_checks(self, token: Token, repository: str, branch: str) -> tuple[str, ...]:
        """The checks the branch's protection requires; none for an unprotected branch."""
        ...

    def checks(self, token: Token, repository: str, sha: str) -> tuple[Check, ...]: ...

    def update_branch(self, token: Token, repository: str, number: int, head: str) -> None:
        """Bring the pull request's branch up to date with its base, if its head is `head`."""
        ...

    def merge(self, token: Token, repository: str, number: int, head: str, method: str) -> str:
        """Merge the pull request if its head is `head`; the merge commit."""
        ...

    def refs(self, token: Token, repository: str, prefix: str) -> tuple[Ref, ...]:
        """The refs whose name starts with `refs/<prefix>`."""
        ...

    def create_ref(self, token: Token, repository: str, ref: str, sha: str) -> None: ...

    def delete_ref(self, token: Token, repository: str, ref: str) -> None: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an error, not a place to send the Authorization header."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _pull(raw: Mapping[str, Any]) -> Pull:
    return Pull(
        number=raw["number"],
        head=raw["head"]["sha"],
        base=raw["base"]["ref"],
        open=raw["state"] == "open",
        merged=bool(raw.get("merged")),
        mergeable=raw.get("mergeable"),
        mergeable_state=str(raw.get("mergeable_state") or "unknown"),
        merge_sha=raw.get("merge_commit_sha"),
    )


class HttpGitHub:
    """The port over GitHub's REST API, as a GitHub App.

    `app_id` and `private_key` (the App's RSA key, PEM) sign a short-lived JSON web token; it is
    used only to find a repository's installation and mint that installation's tokens.
    """

    def __init__(
        self,
        app_id: str,
        private_key: bytes,
        *,
        base_url: str = API,
        timeout: float = 20.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        key = serialization.load_pem_private_key(private_key, password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("a GitHub App key is an RSA private key")
        if not base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be an http(s) URL")
        self._app_id, self._key, self._clock = app_id, key, clock
        self._base, self._timeout = base_url.rstrip("/"), timeout
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._installations: dict[str, int] = {}

    def _app_token(self) -> str:
        """The App's JSON web token (RS256), valid nine minutes; GitHub allows ten."""
        now = int(self._clock())
        claims = {"iat": now - 60, "exp": now + 480, "iss": self._app_id}
        signed = ".".join(
            _b64(json.dumps(part, separators=(",", ":")).encode())
            for part in ({"alg": "RS256", "typ": "JWT"}, claims)
        )
        signature = self._key.sign(signed.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signed}.{_b64(signature)}"

    def _call(
        self,
        method: str,
        path: str,
        bearer: str,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> Any:
        path = urllib.parse.quote(path, safe="/")
        url = self._base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        request = urllib.request.Request(
            url,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
                "User-Agent": "sortyard",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        # Every error is raised `from None`: the cause may hold the request or a reply body.
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            try:
                said = json.loads(error.read())["message"]
            except (ValueError, KeyError, TypeError):
                said = error.reason
            said = str(said).replace(bearer, "[credential]")[:300]
            raise GitHubError(error.code, method, path, said) from None
        except OSError as error:  # no connection, a timeout, a reset
            raise GitHubError(0, method, path, f"no answer ({type(error).__name__})") from None
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            raise GitHubError(0, method, path, "the reply is not JSON") from None

    def _read(
        self, shape: Callable[[Any], Any], method: str, path: str, token: Token, **more: Any
    ) -> Any:
        """A call whose reply `shape` reads; a reply it cannot read is an error with no body."""
        reply = self._call(method, path, token.value, **more)
        try:
            return shape(reply)
        except (KeyError, TypeError, IndexError):
            raise GitHubError(0, method, path, "the reply does not have the shape") from None

    def token(self, repository: str, permissions: Mapping[str, str]) -> Token:
        app = Token(self._app_token(), "", {})
        installation = self._installations.get(repository)
        if installation is None:
            found = self._read(
                lambda r: int(r["id"]), "GET", f"/repos/{repository}/installation", app
            )
            installation = self._installations[repository] = found
        path = f"/app/installations/{installation}/access_tokens"
        body = {"repositories": [repository.split("/", 1)[1]], "permissions": dict(permissions)}

        def shape(reply: Any) -> Token:
            value, expires = reply["token"], reply["expires_at"]
            if not (isinstance(value, str) and value and isinstance(expires, str)):
                raise TypeError
            return Token(value, expires, dict(reply.get("permissions") or {}))

        try:
            minted: Token = self._read(shape, "POST", path, app, body=body)
        except GitHubError:
            self._installations.pop(repository, None)  # the installation may have changed
            raise
        return minted

    def find_pull(self, token: Token, repository: str, branch: str) -> Pull | None:
        owner = repository.split("/", 1)[0]
        query = {"head": f"{owner}:{branch}", "state": "all", "per_page": 100}

        def newest(reply: Any) -> int | None:
            numbers = sorted((each["state"] == "open", int(each["number"])) for each in reply)
            return numbers[-1][1] if numbers else None

        number = self._read(newest, "GET", f"/repos/{repository}/pulls", token, query=query)
        if number is None:
            return None
        found: Pull = self._read(_pull, "GET", f"/repos/{repository}/pulls/{number}", token)
        return found

    def open_pull(
        self, token: Token, repository: str, *, branch: str, base: str, title: str, body: str = ""
    ) -> Pull:
        sent = {"head": branch, "base": base, "title": title, "body": body}
        opened: Pull = self._read(_pull, "POST", f"/repos/{repository}/pulls", token, body=sent)
        return opened

    def required_checks(self, token: Token, repository: str, branch: str) -> tuple[str, ...]:
        def shape(reply: Any) -> tuple[str, ...]:
            required = (reply.get("protection") or {}).get("required_status_checks") or {}
            return tuple(str(context) for context in required.get("contexts") or ())

        path = f"/repos/{repository}/branches/{branch}"
        contexts: tuple[str, ...] = self._read(shape, "GET", path, token)
        return contexts

    def checks(self, token: Token, repository: str, sha: str) -> tuple[Check, ...]:
        def shape(reply: Any) -> tuple[int, list[Check]]:
            runs = [
                Check(str(run["name"]), str(run["status"]), run["conclusion"])
                for run in reply["check_runs"]
            ]
            return int(reply["total_count"]), runs

        found: list[Check] = []
        page = 1
        while True:
            query = {"per_page": 100, "page": page}
            path = f"/repos/{repository}/commits/{sha}/check-runs"
            total, runs = self._read(shape, "GET", path, token, query=query)
            found += runs
            if not runs or len(found) >= total:
                return tuple(found)
            page += 1

    def update_branch(self, token: Token, repository: str, number: int, head: str) -> None:
        path = f"/repos/{repository}/pulls/{number}/update-branch"
        self._call("PUT", path, token.value, body={"expected_head_sha": head})

    def merge(self, token: Token, repository: str, number: int, head: str, method: str) -> str:
        def shape(reply: Any) -> str:
            if reply["merged"] is not True:
                raise TypeError
            return str(reply["sha"])

        path = f"/repos/{repository}/pulls/{number}/merge"
        sha: str = self._read(shape, "PUT", path, token, body={"sha": head, "merge_method": method})
        return sha

    def refs(self, token: Token, repository: str, prefix: str) -> tuple[Ref, ...]:
        def shape(reply: Any) -> tuple[Ref, ...]:
            return tuple(Ref(str(each["ref"]), str(each["object"]["sha"])) for each in reply)

        path = f"/repos/{repository}/git/matching-refs/{prefix}"
        found: tuple[Ref, ...] = self._read(shape, "GET", path, token)
        return found

    def create_ref(self, token: Token, repository: str, ref: str, sha: str) -> None:
        self._call("POST", f"/repos/{repository}/git/refs", token.value, {"ref": ref, "sha": sha})

    def delete_ref(self, token: Token, repository: str, ref: str) -> None:
        path = f"/repos/{repository}/git/{ref}"  # ref is fully qualified: git/refs/heads/...
        self._call("DELETE", path, token.value)


@dataclass(frozen=True)
class Target:
    """Where an item's change goes: the repository, its base branch, and whether the lane
    declares workflow files there (the merge token then asks for the workflows permission)."""

    repository: str
    base: str
    workflow_files: bool = False


# From (tenant, item) to the item's repository and base branch.
TargetLookup = Callable[[str, str], Target]


def branch_of(item: str) -> str:
    """The branch an item's change is pushed to. Its pull request is found by this name."""
    return f"sortyard/{item}"


@dataclass(frozen=True)
class Observation:
    """What one look at GitHub found for a stay. `outcome` is none while the stay is open;
    `detail["waiting"]` then says what it waits on."""

    outcome: str | None
    detail: Mapping[str, Any]

    def reply(self) -> Payload | None:
        """The owner's reply, and what a poller sends with `send_outcome`: none while open."""
        if self.outcome is None:
            return None
        return {"outcome": self.outcome, "detail": dict(self.detail)}


def _waiting(why: str, **more: Any) -> Observation:
    return Observation(None, {"waiting": why, **more})


class _Adapter:
    PERMISSIONS: ClassVar[Mapping[str, str]] = {}

    def __init__(self, port: GitHub, target_of: TargetLookup) -> None:
        self._port, self._target_of = port, target_of

    def __call__(self, call: Payload) -> Payload | None:
        return self.observe(call).reply()

    def observe(self, call: Payload) -> Observation:
        """Look at GitHub for the stay `call` describes (tenant, item, action, detail)."""
        target = self._target_of(call["tenant"], call["item"])
        permissions = dict(self.PERMISSIONS)
        if target.workflow_files and permissions.get("contents") == "write":
            permissions["workflows"] = "write"
        token = self._port.token(target.repository, permissions)
        branch = branch_of(call["item"])
        pull = self._port.find_pull(token, target.repository, branch)
        if pull is None:
            return _waiting(f"no pull request for branch {branch}")
        if pull.base != target.base:
            return _waiting(f"pull request {pull.number} targets {pull.base}, not {target.base}")
        return self._look(call, target, token, pull)

    def _look(self, call: Payload, target: Target, token: Token, pull: Pull) -> Observation:
        raise NotImplementedError


class CiAdapter(_Adapter):
    """The `ci-adapter` owner of `checking`."""

    PERMISSIONS: ClassVar[Mapping[str, str]] = {
        "contents": "read",
        "pull_requests": "read",
        "checks": "read",
    }

    def _look(self, call: Payload, target: Target, token: Token, pull: Pull) -> Observation:
        if not pull.open:
            return _waiting(f"pull request {pull.number} is closed")
        seen = {"pull": pull.number, "head": pull.head}
        runs = self._port.checks(token, target.repository, pull.head)
        required = self._port.required_checks(token, target.repository, pull.base)
        by_name: dict[str, list[Check]] = {name: [] for name in required}
        for run in runs:
            if not required or run.name in by_name:
                by_name.setdefault(run.name, []).append(run)
        failed = sorted(name for name, its in by_name.items() if any(r.failed for r in its))
        if failed:
            finding = "checks failed: " + ", ".join(failed)
            return Observation("red", {**seen, "finding": finding, "failed": failed})
        # A required check with no run has not reported: it is pending, not passed.
        pending = sorted(n for n, its in by_name.items() if not its or not all(r.done for r in its))
        if pending or not by_name:
            return _waiting("checks pending" if pending else "no check has reported", **seen)
        return Observation("green", {**seen, "checks": sorted(by_name)})


class MergeAdapter(_Adapter):
    """The `merge-adapter` owner of `merging`."""

    PERMISSIONS: ClassVar[Mapping[str, str]] = {"contents": "write", "pull_requests": "write"}

    def __init__(self, port: GitHub, target_of: TargetLookup, *, method: str = "squash") -> None:
        super().__init__(port, target_of)
        self._method = method

    def _look(self, call: Payload, target: Target, token: Token, pull: Pull) -> Observation:
        seen = {"pull": pull.number, "head": pull.head}
        if pull.merged:
            return Observation("merged", {**seen, "sha": pull.merge_sha})
        if not pull.open:
            return _waiting(f"pull request {pull.number} is closed", **seen)
        reviewed = (call.get("detail") or {}).get("head")
        if reviewed != pull.head:
            return _waiting("head moved since review", reviewed=reviewed, **seen)
        if pull.mergeable is False:
            return Observation("conflict", {**seen, "finding": f"merge conflict with {pull.base}"})
        try:
            if pull.mergeable_state == "behind" and call.get("action") == UPDATE_BRANCH_ACTION:
                self._port.update_branch(token, target.repository, pull.number, pull.head)
                return _waiting("branch updated from its base", **seen)
            if pull.mergeable is None or pull.mergeable_state not in MERGEABLE_STATES:
                return _waiting(f"not mergeable yet: {pull.mergeable_state}", **seen)
            merged = self._port.merge(
                token, target.repository, pull.number, pull.head, self._method
            )
        except GitHubError as error:
            if error.status not in (405, 409, 422):
                raise
            # GitHub would not: not mergeable after all, or the head moved under the call.
            return _waiting(f"GitHub refused: {error}", **seen)
        return Observation("merged", {**seen, "sha": merged})


class RepositoryProbe:
    """The preflight probe of a `repository` need (`sortyard.kernel.preflight.Probe`)."""

    def __init__(
        self,
        port: GitHub,
        *,
        scratch_prefix: str = SCRATCH_PREFIX,
        unique: Callable[[], str] = lambda: secrets.token_hex(8),
    ) -> None:
        self._port, self._prefix, self._unique = port, scratch_prefix, unique

    def __call__(self, need: Need, lane: Lane) -> ProbeResult:
        declared = lane.repositories.get(need.name) if need.kind == REPOSITORY else None
        if declared is None:
            return ProbeResult(False, f"lane {lane.name} declares no repository for {need.text}")
        wanted = {"contents": "write"}
        if declared.workflow_files:
            wanted["workflows"] = "write"
        ref = self._prefix + self._unique()
        try:
            token = self._port.token(need.name, wanted)
            short = sorted(k for k, level in wanted.items() if token.permissions.get(k) != level)
            if short:
                return ProbeResult(False, f"the token for {need.name} lacks {', '.join(short)}")
            heads = self._port.refs(token, need.name, "heads")
            if not heads:
                return ProbeResult(False, f"{need.name} has no branch to point a scratch ref at")
            self._port.create_ref(token, need.name, ref, heads[0].sha)
        except GitHubError as error:
            return ProbeResult(False, str(error))
        try:
            self._port.delete_ref(token, need.name, ref)
        except GitHubError as error:
            return ProbeResult(False, f"pushed {ref} but could not delete it: {error}")
        return ProbeResult(True, f"pushed and deleted {ref} in {need.name}")
