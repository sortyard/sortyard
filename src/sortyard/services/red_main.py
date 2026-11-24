"""sortyard-red-main: a red default branch of a lane repository is answered by one triage item.

SY-V3-RED-MAIN-OWNED (SORTYARD-204; requirements history CIH-001 sensing and CIH-002 one task
owns one incident). For every repository of a watched lane, each pass reads, as the GitHub App,
the newest finished run of each live workflow on the default branch that ran on push, on a
schedule or by hand (`workflow_dispatch`). A live workflow is one GitHub lists as active whose
file is on the default branch (`.github/workflows/`). Then, by workflow:

- **red** (failure, timed out, failed to start), newer than the lane took the repository
  (`since`), and no open triage item for that repository and workflow: it admits one triage
  item through the API (`admitItem`). The item is built, reviewed and merged by the kernel like
  any other. Its spec names the repository, the workflow, the failing run and its head, and
  asks for the change that turns the workflow green.
- **red again** while that item is open (a later run, not the one it was admitted for): the run
  is recorded on the item as evidence, a request (`requestItemChange`) whose answer is
  `resume` (carry on) and whose reason names the run. It is put on the item's timeline; no
  second item is admitted.
- **green** newer than the failure, or the failing run itself turned green by a re-run, while
  the item is open (not merged): the item is withdrawn as moot (`requestItemChange` with the
  answer `withdraw`, which the shipped decision policy grants an operator: the role binding
  must have the role operator).

Each pass looks at the newest finished run only: two red runs inside one interval record the
later one as evidence.

Other conclusions (cancelled, skipped, neutral) are passed over for the next older run.

Where it sits (SY-DEC-014): outside the counted kernel packages. The kernel owns an item once
admitted; this service owns only "is there an open triage item for this red workflow". It
keeps no state of its own that matters: the deduplication key (repository and workflow) is in
the item's spec (`incident`) and read back through the API (`getProjectQueue`, `getItem`,
`getItemTimeline`), and an item's id is fixed by the run it answers, so admitting it twice
admits it once. What it remembers between passes (requests it sent, until they show on the
timeline) only saves a repeat. A repository that is in no watched lane is never read.

It talks to the API as an operator: each watched lane names a role binding (an operator bound
to the lane's project), and the service issues itself a short-lived token for it from the
database, as `sortyard-api --issue-operator-token` does.

Configuration (environment and mounted files). A required setting that is missing exits with
status 2 and names it.

  SORTYARD_RED_MAIN_CONFIG          required  the watch file (TOML, below)
  SORTYARD_LANES_DIR                required  the lane capability files (*.toml), as the API's
  SORTYARD_API_URL                  required  the API's base URL, e.g. http://sortyard-api:8080
  SORTYARD_WORKSPACE                required  the workspace the items are admitted in
  SORTYARD_DATABASE_*                         as for sortyard-api (HOST, PORT, NAME, USER and
                                              PASSWORD required): where operator tokens are issued
  SORTYARD_GITHUB_APP_ID            required  the GitHub App the read tokens are minted from
  SORTYARD_GITHUB_APP_KEY_FILE      required  path of the App's private key (PEM)
  SORTYARD_GITHUB_API_URL                     (default https://api.github.com)
  SORTYARD_RED_MAIN_INTERVAL_SECONDS          seconds between passes (default 60)

The watch file:

  version = 1
  [[lanes]]
  lane = "canary"                  # a lane capability file; every repository it declares
  project = "canary"               # the project the triage items are admitted to
  role-binding = "rb-red-main"     # an operator binding to that project
  since = 2026-11-24T22:00:00Z     # when the lane took its repositories: older runs file nothing
  risk-tier = "medium"             # optional (default medium)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import pathlib
import signal
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import FrameType
from typing import Any

import psycopg

from sortyard.api import auth
from sortyard.kernel.capabilities import Lane
from sortyard.lane.github import GitHubError, HttpGitHub, Token
from sortyard.services import api as api_service

log = logging.getLogger("sortyard.red_main")

# The events of a run "on the default branch": a push to it, a schedule, a run by hand.
EVENTS = frozenset({"push", "schedule", "workflow_dispatch"})
RED = frozenset({"failure", "timed_out", "startup_failure"})
GREEN = frozenset({"success"})
WORKFLOWS_DIR = ".github/workflows"
# What a read token is minted with: the workflow runs and the workflow files, nothing more.
READ = {"actions": "read", "contents": "read"}
# Every triage item's id starts so; the rest is fixed by the incident's repository, workflow
# and failing run, so a second admission of the same incident is the same item.
PREFIX = "red-main-"
EVIDENCE = "red-main evidence: run {run}"
RUNS_PAGE = 50
# How long a new head of the branch may go without a run of its own before a red run of an
# older commit is answered: a run GitHub starts for a push is listed a few seconds after it.
HEAD_GRACE_SECONDS = 300.0


@dataclass(frozen=True)
class Workflow:
    id: int
    name: str
    path: str


@dataclass(frozen=True)
class Run:
    id: int
    workflow: Workflow
    event: str
    conclusion: str
    head: str
    branch: str
    url: str
    created_at: datetime

    @property
    def red(self) -> bool:
        return self.conclusion in RED


def _when(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.utcoffset() is None:
        raise ValueError(f"a time carries its offset: {text!r}")
    return moment.astimezone(UTC)


class ActionsGitHub(HttpGitHub):
    """The reads this service makes, over the kernel's GitHub client (same App, same rules:
    a token never printed, an error that carries no reply body)."""

    def default_branch(self, token: Token, repository: str) -> str:
        return self._read(lambda r: str(r["default_branch"]), "GET", f"/repos/{repository}", token)

    def head(self, token: Token, repository: str, branch: str) -> str:
        """The commit the branch is at."""
        path = f"/repos/{repository}/branches/{branch}"
        return self._read(lambda r: str(r["commit"]["sha"]), "GET", path, token)

    def workflow_files(self, token: Token, repository: str, branch: str) -> frozenset[str]:
        """The paths of the files under .github/workflows on the branch (none: no directory)."""
        path = f"/repos/{repository}/contents/{WORKFLOWS_DIR}"
        try:
            return self._read(
                lambda r: frozenset(str(each["path"]) for each in r if each["type"] == "file"),
                "GET",
                path,
                token,
                query={"ref": branch},
            )
        except GitHubError as error:
            if error.status == 404:
                return frozenset()
            raise

    def live_workflows(self, token: Token, repository: str, branch: str) -> list[Workflow]:
        """Workflows GitHub lists as active whose file is on the branch."""
        files = self.workflow_files(token, repository, branch)
        found: list[Workflow] = []
        page = 1
        while True:
            total, listed = self._read(
                lambda r: (int(r["total_count"]), list(r["workflows"])),
                "GET",
                f"/repos/{repository}/actions/workflows",
                token,
                query={"per_page": 100, "page": page},
            )
            for each in listed:
                if each["state"] == "active" and each["path"] in files:
                    found.append(Workflow(int(each["id"]), str(each["name"]), str(each["path"])))
            if not listed or page * 100 >= total:
                return found
            page += 1

    def newest_verdict(
        self, token: Token, repository: str, workflow: Workflow, branch: str
    ) -> Run | None:
        """The verdict of the newest run on the branch of the events above: that run when it is
        red or green; none while it has not finished. One that finished neither (cancelled,
        skipped) gives way to the newest red or green run of the same commit. An older commit's
        run never speaks for the branch: right after a fix merges, the run of the merge is the
        newest, and the red runs before it are history (SORTYARD-204, found on the estate)."""

        def shape(reply: Any) -> list[Run]:
            return [
                Run(
                    id=int(each["id"]),
                    workflow=workflow,
                    event=str(each["event"]),
                    # A run that has not finished has no conclusion: it is neither red nor green.
                    conclusion=str(each["conclusion"]) if each["status"] == "completed" else "",
                    head=str(each["head_sha"]),
                    branch=str(each["head_branch"]),
                    url=str(each["html_url"]),
                    created_at=_when(str(each["created_at"])),
                )
                for each in reply["workflow_runs"]
            ]

        runs = self._read(
            shape,
            "GET",
            f"/repos/{repository}/actions/workflows/{workflow.id}/runs",
            token,
            query={"branch": branch, "exclude_pull_requests": "true", "per_page": RUNS_PAGE},
        )
        mine = sorted(
            (run for run in runs if run.event in EVENTS and run.branch == branch),
            key=lambda run: (run.created_at, run.id),
            reverse=True,
        )
        if not mine or not mine[0].conclusion:
            return None
        judged = [run for run in mine if run.head == mine[0].head and run.conclusion in RED | GREEN]
        return judged[0] if judged else None


class ApiError(Exception):
    """The API answered with an error (or not at all). Carries no token."""

    def __init__(self, status: int, method: str, path: str, said: str) -> None:
        super().__init__(f"the API answered {status} to {method} {path}: {said}")
        self.status = status


class KernelApi:
    """The item operations of the public API (spec/openapi.json) this service calls."""

    def __init__(
        self, base_url: str, workspace: str, token: Callable[[], str], timeout: float = 20.0
    ) -> None:
        self._base = f"{base_url.rstrip('/')}/v1/workspaces/{urllib.parse.quote(workspace)}"
        self._token, self._timeout = token, timeout

    def _call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        request = urllib.request.Request(
            self._base + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as reply:
                return reply.status, json.loads(reply.read() or b"null")
        except urllib.error.HTTPError as error:
            with error:
                try:
                    said = json.loads(error.read()).get("detail", error.reason)
                except (ValueError, AttributeError):
                    said = error.reason
            return error.code, {"detail": str(said)[:300]}
        except (OSError, ValueError) as error:
            raise ApiError(0, method, path, f"no answer ({type(error).__name__})") from None

    def _ok(self, method: str, path: str, body: Any = None, *, ok: Iterable[int] = (200,)) -> Any:
        status, reply = self._call(method, path, body)
        if status not in set(ok):
            raise ApiError(status, method, path, str((reply or {}).get("detail", "")))
        return reply

    def queue(self, project: str) -> list[dict[str, Any]]:
        path = f"/projects/{urllib.parse.quote(project)}/queue"
        return list(self._ok("GET", path)["items"])

    def item(self, item: str) -> dict[str, Any]:
        return dict(self._ok("GET", f"/items/{urllib.parse.quote(item, safe='')}"))

    def timeline(self, item: str) -> list[dict[str, Any]]:
        path = f"/items/{urllib.parse.quote(item, safe='')}/timeline"
        return list(self._ok("GET", path)["items"])

    def admit(self, body: Mapping[str, Any]) -> tuple[int, Any]:
        """201 admitted, 200 the same item was admitted before; anything else as answered."""
        return self._call("POST", "/items", dict(body))

    def request(self, item: str, answer: str, reason: str) -> None:
        path = f"/items/{urllib.parse.quote(item, safe='')}/requests"
        self._ok("POST", path, {"answer": answer, "reason": reason}, ok=(202,))


@dataclass(frozen=True)
class Watch:
    """A lane whose repositories are watched, and where its triage items go."""

    lane: str
    project: str
    role_binding: str
    since: datetime
    repositories: tuple[str, ...]
    risk_tier: str = "medium"


def load_watches(text: str, lanes: Mapping[str, Lane]) -> list[Watch]:
    """The watch file, with each lane's repositories from its capability file; `ValueError`
    for a file that cannot be read in full, an unknown lane, or a repository in two lanes."""
    raw = tomllib.loads(text)
    entries = raw.get("lanes")
    if raw.get("version") != 1 or set(raw) - {"version", "lanes"} or not isinstance(entries, list):
        raise ValueError("a watch file is {version = 1, lanes = [...]}")
    watches: list[Watch] = []
    seen: dict[str, str] = {}
    keys = {"lane", "project", "role-binding", "since", "risk-tier"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - keys:
            raise ValueError(f"a watched lane has only the keys {sorted(keys)}: {entry!r}")
        texts = [entry.get(key) for key in ("lane", "project", "role-binding")]
        if not all(isinstance(value, str) and value for value in texts):
            raise ValueError(f"a watched lane names its lane, project and role-binding: {entry!r}")
        since = entry.get("since")
        if not isinstance(since, datetime) or since.utcoffset() is None:
            raise ValueError(f"since is a date and time with its offset: {entry!r}")
        lane = lanes.get(entry["lane"])
        if lane is None:
            raise ValueError(f"no lane capability file for lane {entry['lane']!r}")
        for repository in lane.repositories:
            if repository in seen:
                raise ValueError(f"{repository} is in lanes {seen[repository]!r} and {lane.name!r}")
            seen[repository] = lane.name
        watches.append(
            Watch(
                lane=lane.name,
                project=entry["project"],
                role_binding=entry["role-binding"],
                since=since.astimezone(UTC),
                repositories=tuple(sorted(lane.repositories)),
                risk_tier=str(entry.get("risk-tier", "medium")),
            )
        )
    return watches


def item_id(repository: str, workflow: str, run: int) -> str:
    """The triage item of one failing run: the same run always gives the same id."""
    digest = hashlib.sha256(f"{repository}\n{workflow}".encode()).hexdigest()[:12]
    return f"{PREFIX}{digest}-{run}"


def admission(watch: Watch, repository: str, run: Run) -> dict[str, Any]:
    """The admitItem body of a triage item for a red run. Fixed by the run, so a repeat is
    the same item."""
    workflow = run.workflow
    outcome = (
        f"The workflow {workflow.name!r} ({workflow.path}) of {repository} is red on its default "
        f"branch {run.branch}: its {run.event} run {run.id} failed ({run.conclusion}) at "
        f"{run.head}. Log: {run.url}. Find why it fails and change the repository so that the "
        "workflow passes on the branch again. The workflow itself, its triggers and its tests "
        "stay as strict as they are: the change makes the code pass them, it does not skip, "
        "weaken or delete them."
    )
    return {
        "id": item_id(repository, workflow.path, run.id),
        "project_id": watch.project,
        "title": f"Red main: {workflow.name} on {repository}",
        "lane": watch.lane,
        "repository": repository,
        "base": run.branch,
        "risk_tier": watch.risk_tier,
        "spec": {
            "outcome": outcome,
            "acceptance": [
                {
                    "test": workflow.path,
                    "name": f"the workflow {workflow.name} passes on {run.branch}",
                }
            ],
            # The deduplication key (repository, workflow) and the run the item answers.
            "incident": {
                "kind": "red-main",
                "repository": repository,
                "workflow": workflow.path,
                "workflow_name": workflow.name,
                "branch": run.branch,
                "run": run.id,
                "run_url": run.url,
                "head": run.head,
                "event": run.event,
                "conclusion": run.conclusion,
                "failed_at": run.created_at.isoformat().replace("+00:00", "Z"),
            },
        },
    }


@dataclass(frozen=True)
class Open:
    """An open triage item, as read back through the API."""

    item: str
    run: int
    failed_at: datetime


@dataclass(frozen=True)
class Act:
    """What a pass did about one workflow (for the log and the tests)."""

    what: str  # admitted, known, refused, evidence, withdrawn, unread
    repository: str
    workflow: str | None = None
    item: str | None = None
    run: int | None = None
    detail: str = ""


@dataclass
class Observer:
    github: ActionsGitHub
    apis: Mapping[str, KernelApi]  # by lane
    watches: Sequence[Watch]
    # Requests sent and not yet seen on the timeline: (item, what). Only saves a repeat.
    sent: set[tuple[str, str]] = field(default_factory=set)
    clock: Callable[[], float] = time.monotonic
    # By repository: the branch head last read and when it was first seen (process memory; a
    # restart only waits the grace again).
    heads: dict[str, tuple[str, float]] = field(default_factory=dict)

    def settled(self, repository: str, head: str) -> bool:
        """Whether the branch has been at `head` for the grace period."""
        seen = self.heads.get(repository)
        if seen is None or seen[0] != head:
            self.heads[repository] = seen = (head, self.clock())
        return self.clock() - seen[1] >= HEAD_GRACE_SECONDS

    def run_once(self) -> list[Act]:
        acts: list[Act] = []
        # What one lane, repository or workflow cannot read ends only that part of the pass.
        unread = (GitHubError, ApiError, ValueError, KeyError, TypeError, psycopg.Error)
        for watch in self.watches:
            api = self.apis[watch.lane]
            try:
                opened = self.open_items(api, watch)
            except unread as error:
                acts.append(Act("unread", "", detail=f"lane {watch.lane}: {error}"))
                continue
            for repository in watch.repositories:
                try:
                    acts += self.repository(api, watch, repository, opened)
                except unread as error:
                    acts.append(Act("unread", repository, detail=str(error)))
        for act in acts:
            log.info("%s %s %s %s %s", act.what, act.repository, act.workflow, act.item, act.detail)
        return acts

    def open_items(self, api: KernelApi, watch: Watch) -> dict[tuple[str, str], Open]:
        """The open triage items of the lane, by (repository, workflow), read from their
        specs. Should two answer one key, the one admitted first answers it."""
        found: dict[tuple[str, str], Open] = {}
        for queued in api.queue(watch.project):
            if not str(queued["id"]).startswith(PREFIX):
                continue
            item = api.item(queued["id"])
            spec = item.get("spec") or {}
            incident = spec.get("incident") if isinstance(spec, dict) else None
            if item.get("lane") != watch.lane or not isinstance(incident, dict):
                continue
            if incident.get("kind") != "red-main" or item.get("state_kind") == "terminal":
                continue
            key = (str(incident["repository"]), str(incident["workflow"]))
            found.setdefault(
                key, Open(item["id"], int(incident["run"]), _when(str(incident["failed_at"])))
            )
        return found

    def repository(
        self,
        api: KernelApi,
        watch: Watch,
        repository: str,
        opened: Mapping[tuple[str, str], Open],
    ) -> list[Act]:
        token = self.github.token(repository, READ)
        branch = self.github.default_branch(token, repository)
        # Read after the open items: a fix the queue already shows merged has moved the head.
        head = self.github.head(token, repository, branch)
        settled = self.settled(repository, head)
        acts: list[Act] = []
        for workflow in self.github.live_workflows(token, repository, branch):
            try:
                acts += self.workflow(
                    api, watch, repository, workflow, token, branch, opened, head, settled
                )
            except (GitHubError, ApiError, ValueError, KeyError, TypeError) as error:
                acts.append(Act("unread", repository, workflow.path, detail=str(error)))
        return acts

    def workflow(
        self,
        api: KernelApi,
        watch: Watch,
        repository: str,
        workflow: Workflow,
        token: Token,
        branch: str,
        opened: Mapping[tuple[str, str], Open],
        head: str,
        settled: bool,
    ) -> list[Act]:
        run = self.github.newest_verdict(token, repository, workflow, branch)
        if run is None:
            return []
        here = opened.get((repository, workflow.path))
        # A red run of a commit the branch has moved past is answered only once the new head
        # has had time to get a run of its own (a merged fix's run is listed seconds after the
        # merge; found on the estate) or never will (a workflow that skips some pushes).
        current = run.head == head or settled
        if run.red and here is None and run.created_at > watch.since and current:
            return [self.admit(api, watch, repository, run)]
        if run.red and here is not None and run.id != here.run:
            return self.evidence(api, here, repository, run)
        # Green after the failure: a newer run, or the failing run itself re-run green (a re-run
        # keeps the run's id and its created_at).
        newer = here is not None and (run.created_at > here.failed_at or run.id == here.run)
        if not run.red and here is not None and newer:
            return self.withdraw(api, here, repository, run)
        return []

    def admit(self, api: KernelApi, watch: Watch, repository: str, run: Run) -> Act:
        body = admission(watch, repository, run)
        status, reply = api.admit(body)
        what = {201: "admitted", 200: "known"}.get(status, "refused")
        detail = "" if status in (200, 201) else f"{status} {(reply or {}).get('detail', '')}"
        return Act(what, repository, run.workflow.path, body["id"], run.id, detail)

    def _requested(self, api: KernelApi, item: str, mark: str) -> bool:
        """Whether a request whose reason holds `mark` is on the item's timeline."""
        for event in api.timeline(item):
            request = (event.get("facts") or {}).get("request")
            if isinstance(request, dict) and mark in str(request.get("reason", "")):
                self.sent.discard((item, mark))
                return True
        return (item, mark) in self.sent

    def evidence(self, api: KernelApi, here: Open, repository: str, run: Run) -> list[Act]:
        mark = EVIDENCE.format(run=run.id)
        if self._requested(api, here.item, mark):
            return []
        reason = (
            f"{mark}: the workflow {run.workflow.name} ({run.workflow.path}) failed again "
            f"({run.conclusion}) on {run.branch} at {run.head}, {run.event} run {run.id}: "
            f"{run.url}. Recorded as evidence on this item; no other item is admitted for it."
        )
        api.request(here.item, "resume", reason)
        self.sent.add((here.item, mark))
        return [Act("evidence", repository, run.workflow.path, here.item, run.id)]

    def withdraw(self, api: KernelApi, here: Open, repository: str, run: Run) -> list[Act]:
        mark = f"red-main moot: run {run.id}"
        if self._requested(api, here.item, mark):
            # Asked before and still open: the request was not granted (the binding's role is
            # not operator, or it arrived as the item moved). Said every pass, asked once.
            return [Act("not-withdrawn", repository, run.workflow.path, here.item, run.id)]
        reason = (
            f"{mark}: the workflow {run.workflow.name} ({run.workflow.path}) passed on "
            f"{run.branch} at {run.head} ({run.event} run {run.id}, {run.url}), after the "
            f"failure this item answers (run {here.run}). The incident is over; the item is moot."
        )
        api.request(here.item, "withdraw", reason)
        self.sent.add((here.item, mark))
        return [Act("withdrawn", repository, run.workflow.path, here.item, run.id)]


class OperatorTokens:
    """A short-lived operator token for one role binding, issued from the database as
    `sortyard-api --issue-operator-token` does, and issued again before it expires."""

    TTL = timedelta(minutes=30)

    def __init__(self, connect: Callable[[], psycopg.Connection[Any]], role_binding: str) -> None:
        self._connect, self._binding = connect, role_binding
        self._issued: auth.Issued | None = None
        self._lock = threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            now = datetime.now(UTC)
            if self._issued is None or self._issued.expires_at - now < self.TTL / 2:
                with self._connect() as conn:
                    self._issued = auth.issue_operator_token(
                        conn, self._binding, int(self.TTL.total_seconds())
                    )
            return self._issued.token


REQUIRED = (
    "SORTYARD_RED_MAIN_CONFIG",
    "SORTYARD_LANES_DIR",
    "SORTYARD_API_URL",
    "SORTYARD_WORKSPACE",
    "SORTYARD_DATABASE_HOST",
    "SORTYARD_DATABASE_NAME",
    "SORTYARD_DATABASE_USER",
    "SORTYARD_DATABASE_PASSWORD",
    "SORTYARD_GITHUB_APP_ID",
    "SORTYARD_GITHUB_APP_KEY_FILE",
)


def build(env: Mapping[str, str]) -> tuple[Observer, float]:
    """The observer and its interval from the environment; `ValueError` names what is wrong."""
    missing = [name for name in REQUIRED if not env.get(name)]
    if missing:
        raise ValueError(f"required settings missing: {', '.join(missing)}")
    lanes = api_service.load_lanes(env["SORTYARD_LANES_DIR"])
    watches = load_watches(pathlib.Path(env["SORTYARD_RED_MAIN_CONFIG"]).read_text(), lanes)
    # The database settings only: Kubernetes puts SORTYARD_API_PORT=tcp://... into a pod of a
    # release named sortyard (the API Service's link variable), which is no port number.
    database = {name: value for name, value in env.items() if name.startswith("SORTYARD_DATABASE_")}
    conninfo = api_service.Config.from_env(database).conninfo()
    github = ActionsGitHub(
        env["SORTYARD_GITHUB_APP_ID"],
        pathlib.Path(env["SORTYARD_GITHUB_APP_KEY_FILE"]).read_bytes(),
        base_url=env.get("SORTYARD_GITHUB_API_URL") or "https://api.github.com",
    )
    apis = {
        watch.lane: KernelApi(
            env["SORTYARD_API_URL"],
            env["SORTYARD_WORKSPACE"],
            OperatorTokens(lambda: psycopg.connect(conninfo), watch.role_binding),
        )
        for watch in watches
    }
    interval = float(env.get("SORTYARD_RED_MAIN_INTERVAL_SECONDS") or 60)
    return Observer(github, apis, watches), interval


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sortyard-red-main", description=__doc__.split("\n")[0])
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        observer, interval = build(os.environ)
    except (ValueError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"sortyard-red-main: {error}", file=sys.stderr)
        return 2
    stop = threading.Event()

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d, stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    log.info("watching lanes %s", [watch.lane for watch in observer.watches])
    while not stop.is_set():
        try:
            observer.run_once()
        except (psycopg.Error, ValueError) as error:  # the token store, or a reply it cannot read
            log.warning("pass failed: %s", error)
        if args.once:
            break
        stop.wait(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
