"""The worker launcher: the executor and reviewer owners, on the jobs port (HARNESS-V3 3.3).

The state table gives `building` and `fixing` to the owner `executor` and `reviewing` to the
owner `reviewer`. `Launcher` is both. Each dispatch launches one worker Job and answers nothing;
`Launcher.observe` later turns the finished Job into the state's outcome, for whoever polls the
open stays and sends it on (`sortyard.kernel.item.send_outcome`).

Nothing is remembered between calls. The Job's name is derived from the tenant, the item and
the dispatch (`job_name`), so a repeated call finds the Job it already made and a Job that
outlives this process is observed by the next one.

What a Job gets:

- the lane's worker image, by digest, in three containers that run `sortyard-worker`
  (`sortyard.services.worker`), so that the agent never shares a container with the token:
  the init container `clone` and the container `push` mount the per-job secret; the container
  `agent` mounts neither it nor any path to it, and alone gets the lane's declared secrets,
  by reference (`secretKeyRef`): the launcher never reads one;
- its **brief** (`brief`), mounted as a file: the item spec, the repository, the base branch,
  the branch `sortyard/<item id>`, for a fix the finding, and the agent command to run;
- a GitHub **token** minted for this Job and scoped to the item's one repository
  (`TokenSource`), in a per-job secret that the Job owns. `observe` replaces the token while
  the Job runs once it is older than `WorkerConfig.token_age`, and deletes the secret when the
  Job ends.

A launch first deletes the Jobs of the item's earlier dispatches with what they created, so a
Job whose stay closed before it ended (its limit passed) leaves nothing behind once the item
is dispatched again. The Job's deadline is the stay's limit (`limit_seconds` of the call), and
its brief and the agent's `SORTYARD_LIMIT_SECONDS` give that figure, so the agent can stop in time.

`push` reports the result as its termination message. `observe` trusts that message only as
far as the state can use it: an outcome the state has, a head commit, and for findings one
finding key. Anything else, a failed Job and a vanished Job are no reply, so the state's limit
and default apply.

`probes` gives the preflight its `secret`, `service` and `worker-image` probes.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sortyard.kernel.capabilities import REPOSITORY, SECRET, SERVICE, WORKER_IMAGE, Lane, Need
from sortyard.kernel.item import Owner, Payload
from sortyard.kernel.preflight import Probe, ProbeResult
from sortyard.lane.github import branch_of, permissions_for
from sortyard.lane.jobs import (
    BRIEF_KEY,
    DISPATCH_LABEL,
    ITEM_LABEL,
    JOB_LABEL,
    RESULT_CONTAINER,
    RUNNING,
    SUCCEEDED,
    TOKEN_KEY,
    Jobs,
)

EXECUTOR_OWNER, REVIEWER_OWNER = "executor", "reviewer"
BUILD, FIX, REVIEW = "build", "fix", "review"
# What the worker does in each state, and the outcomes it may report there.
MODES: Mapping[str, str] = {"building": BUILD, "fixing": FIX, "reviewing": REVIEW}
OUTCOMES: Mapping[str, frozenset[str]] = {
    "building": frozenset({"built", "no-change"}),
    "fixing": frozenset({"fixed"}),
    "reviewing": frozenset({"approved", "findings"}),
}
# Where the Job's files are mounted, and the variables that tell the entry point so.
BRIEF_DIR, TOKEN_DIR = "/var/run/sortyard/brief", "/var/run/sortyard/github"
# The agent's workspace, and what `clone` hands `push` where the agent cannot reach.
WORK_DIR, STATE_DIR = "/work", "/var/run/sortyard/state"
BRIEF_ENV, TOKEN_FILE_ENV, WORK_ENV, STATE_ENV, LIMIT_ENV = (
    "SORTYARD_BRIEF",
    "SORTYARD_GITHUB_TOKEN_FILE",
    "SORTYARD_WORKDIR",
    "SORTYARD_STATE",
    "SORTYARD_LIMIT_SECONDS",
)
CLONE, AGENT = "clone", "agent"
# A container's termination message is cut at 4096 bytes; the worker keeps its result under it.
TERMINATION_LOG, RESULT_LIMIT = "/dev/termination-log", 4096

# The branch a worker pushes is the one the adapters find the pull request by.
branch = branch_of

_HEAD = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
_DIGEST = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")

# Mints a token for one repository ("owner/name") with the named permissions.
TokenSource = Callable[[str, Mapping[str, str]], str]


@dataclass(frozen=True)
class Work:
    """What an item's worker needs to know: its lane, its one repository and its spec."""

    lane: Lane
    repository: str
    spec: Mapping[str, Any]
    base: str = "main"


# From (tenant, item) to the item's work.
WorkLookup = Callable[[str, str], Work]


@dataclass(frozen=True)
class WorkerConfig:
    """How workers run here. Everything a deployment decides, none of it in the kernel.

    `agents` gives the agent command (an argv; the brief text is its standard input) for each
    of `BUILD`, `FIX` and `REVIEW`. `secrets` maps a secret name the lane declares to the
    Kubernetes Secret and key holding it; a name not listed is read from the Secret named
    after it in lower case with dashes, under the key of the same name. `services` maps a
    declared service name to the URL its probe calls. In seconds: `deadline` bounds a Job whose
    call names no limit, `ttl` is how long a finished Job is kept, and `token_age` is how old
    a running Job's token may get before `observe` replaces it.
    """

    agents: Mapping[str, Sequence[str]]
    git_url: str = "https://github.com/{repository}.git"
    secrets: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    services: Mapping[str, str] = field(default_factory=dict)
    command: Sequence[str] = ("sortyard-worker",)
    deadline: int = 7200
    ttl: int = 86400
    token_age: int = 1800

    def __post_init__(self) -> None:
        missing = sorted(
            {BUILD, FIX, REVIEW} - {mode for mode, argv in self.agents.items() if argv}
        )
        if missing:
            raise ValueError(f"no agent command for {missing}")

    def secret_ref(self, name: str) -> tuple[str, str]:
        return self.secrets.get(name) or (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), name)


def job_name(tenant: str, item: str, dispatch: int) -> str:
    """The Job of one dispatch of one item: a DNS label, the same in every process."""
    return f"sy-{item_label(tenant, item)}-{int(dispatch)}"


def item_label(tenant: str, item: str) -> str:
    """What every Job of one item of one tenant is labelled with."""
    return hashlib.sha256(f"{len(tenant)}:{tenant}:{item}".encode()).hexdigest()[:24]


def brief(mode: str, work: Work, call: Payload, config: WorkerConfig) -> dict[str, Any]:
    """The brief of one Job: what the entry point needs, and `text`, what the agent is told."""
    item, detail = str(call["item"]), dict(call.get("detail") or {})
    limit = call.get("limit_seconds")  # the stay's limit; the configured deadline when it has none
    seconds = int(limit) if isinstance(limit, int | float) and limit >= 1 else config.deadline
    made: dict[str, Any] = {
        "version": 1,
        "mode": mode,
        "tenant": str(call["tenant"]),
        "item": item,
        "dispatch": int(call["dispatch"]),
        "repository": work.repository,
        "clone_url": config.git_url.format(repository=work.repository),
        "base": work.base,
        "branch": branch(item),
        "spec": dict(work.spec),
        "agent": list(config.agents[mode]),
        "limit_seconds": seconds,  # the Job's deadline: what the agent has, clone and push included
    }
    lines = [
        f"Item {item} in repository {work.repository}.",
        f"Base branch: {work.base}. Work branch: {made['branch']} (checked out here).",
        f"This Job is stopped {seconds} seconds after it starts ({LIMIT_ENV}): end before then.",
        "The item's spec:",
        json.dumps(made["spec"], indent=2, sort_keys=True),
    ]
    if mode == FIX:
        made["finding"] = detail
        lines += [
            "Fix this finding, and nothing else:",
            json.dumps(detail, indent=2, sort_keys=True),
        ]
    if mode == REVIEW:
        lines += [
            f"Review the change on {made['branch']} against {work.base} and the spec. "
            "Change nothing. End your answer with one line holding a single JSON object: "
            '{"verdict":"approve"} or {"verdict":"findings","findings":[{"key":"<a short stable '
            'name for the finding>","text":"<what is wrong and where>"}]}, most important first.'
        ]
    else:
        lines += ["Commit your work on the checked-out branch. Do not push; the worker pushes."]
    made["text"] = "\n".join(lines) + "\n"
    return made


def manifest(
    name: str,
    lane: Lane,
    config: WorkerConfig,
    deadline: int,
    labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The batch/v1 Job the launcher creates under `name` for a task of `lane`.

    Three containers of the lane's worker image share the workspace. `clone` (an init
    container) and `push` hold the per-job secret and a state volume of their own; `agent`
    holds neither, and alone gets the lane's declared secrets and the deadline (`LIMIT_ENV`).
    """
    labels = {"app.kubernetes.io/managed-by": "sortyard", JOB_LABEL: name, **(labels or {})}
    brief = {"name": "brief", "mountPath": BRIEF_DIR, "readOnly": True}
    work = {"name": "work", "mountPath": WORK_DIR}
    trusted: list[dict[str, Any]] = [
        {"name": "github", "mountPath": TOKEN_DIR, "readOnly": True},
        {"name": "state", "mountPath": STATE_DIR},
    ]
    shared = [
        {"name": BRIEF_ENV, "value": f"{BRIEF_DIR}/{BRIEF_KEY}"},
        {"name": WORK_ENV, "value": WORK_DIR},
    ]
    holds_token = [
        {"name": TOKEN_FILE_ENV, "value": f"{TOKEN_DIR}/{TOKEN_KEY}"},
        {"name": STATE_ENV, "value": STATE_DIR},
    ]
    lane_secrets = [
        {"name": declared, "valueFrom": {"secretKeyRef": {"name": secret, "key": key}}}
        for declared in lane.secrets
        for secret, key in [config.secret_ref(declared)]
    ]

    def container(step: str, env: list[dict[str, Any]], mounts: list[dict[str, Any]]) -> Any:
        return {
            "name": step,
            "image": lane.worker_image.reference,
            "command": [*config.command, step],
            "env": [*shared, *env],
            "terminationMessagePath": TERMINATION_LOG,
            "terminationMessagePolicy": "File",
            "volumeMounts": [brief, work, *mounts],
        }

    pod = {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "initContainers": [container(CLONE, holds_token, trusted)],
        "containers": [
            container(AGENT, [*lane_secrets, {"name": LIMIT_ENV, "value": str(deadline)}], []),
            container(RESULT_CONTAINER, holds_token, trusted),
        ],
        "volumes": [
            {"name": "brief", "configMap": {"name": name}},
            {"name": "github", "secret": {"secretName": name}},
            {"name": "work", "emptyDir": {}},
            {"name": "state", "emptyDir": {}},
        ],
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": deadline,
            "ttlSecondsAfterFinished": config.ttl,
            "template": {"metadata": {"labels": labels}, "spec": pod},
        },
    }


def outcome_of(state: str, message: str) -> Payload | None:
    """The outcome a worker's termination message carries for `state`, if it is one the state
    can use: a known outcome, the head commit, and for findings one finding key."""
    try:
        result = json.loads(message)
    except ValueError:
        return None
    outcome = result.get("outcome") if isinstance(result, Mapping) else None
    if not isinstance(outcome, str) or outcome not in OUTCOMES.get(state, ()):
        return None
    head = result.get("head")
    if not isinstance(head, str) or not _HEAD.fullmatch(head):
        return None
    detail: dict[str, Any] = {"head": head}
    if result["outcome"] == "findings":
        key, findings = result.get("finding"), result.get("findings")
        if not isinstance(key, str) or not key.strip() or not isinstance(findings, list):
            return None
        detail.update(finding=key, findings=findings)
    return {"outcome": result["outcome"], "detail": detail}


class Launcher:
    """The `executor` and `reviewer` owners and their observer. `clock` gives the time in
    seconds, for the age of a token."""

    def __init__(
        self,
        *,
        jobs: Jobs,
        lookup: WorkLookup,
        tokens: TokenSource,
        config: WorkerConfig,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._jobs, self._lookup, self._tokens = jobs, lookup, tokens
        self._config, self._clock = config, clock

    def owners(self) -> dict[str, Owner]:
        """The two owners by the names the state table gives them, for `item.register`."""
        return {EXECUTOR_OWNER: self.launch, REVIEWER_OWNER: self.launch}

    def _mint(self, tenant: str, item: str, state: str) -> tuple[Work, Callable[[], str]]:
        """The item's work, and how to mint the token a Job of `state` needs."""
        work, mode = self._lookup(tenant, item), MODES[state]
        repository = work.lane.repositories[work.lane.check(Need(REPOSITORY, work.repository)).name]
        review = {"contents": "read", "pull_requests": "read"}
        wanted = review if mode == REVIEW else {"contents": "write"}
        permissions = permissions_for(wanted, repository.workflow_files)
        return work, lambda: self._tokens(work.repository, permissions)

    def launch(self, call: Payload) -> None:
        """Launch the Job of this dispatch, unless it is there already, after deleting the
        Jobs of the item's earlier dispatches. The outcome comes later, from `observe`. Safe
        to call again for the same dispatch."""
        tenant, item, state = str(call["tenant"]), str(call["item"]), str(call["state"])
        dispatch = int(call["dispatch"])
        work, mint = self._mint(tenant, item, state)
        made, label = brief(MODES[state], work, call, self._config), item_label(tenant, item)
        self._jobs.delete_earlier(label, dispatch)
        self._jobs.launch(
            manifest(
                job_name(tenant, item, dispatch),
                work.lane,
                self._config,
                made["limit_seconds"],
                {ITEM_LABEL: label, DISPATCH_LABEL: str(dispatch)},
            ),
            brief=json.dumps(made),
            token=mint,
            stamp=str(int(self._clock())),
        )

    def observe(self, stay: Payload) -> Payload | None:
        """The outcome of the stay (tenant, item, state, dispatch), once its Job has finished.

        While the Job runs there is no outcome; its token is replaced when it is older than
        the configured age, so a long Job pushes with a live one. When the Job has ended or
        is gone its per-job secret is deleted, every time this is called, and a Job that
        failed, vanished or reported something the state cannot use gives nothing: the
        state's limit and default apply.
        """
        tenant, item, state = str(stay["tenant"]), str(stay["item"]), str(stay["state"])
        name = job_name(tenant, item, int(stay["dispatch"]))
        status = self._jobs.status(name)
        if status is not None and status.phase == RUNNING:
            minted, now = self._jobs.secret_minted(name), int(self._clock())
            if minted is not None and not (
                minted.isdigit() and now - int(minted) < self._config.token_age
            ):
                self._jobs.refresh_secret(name, self._mint(tenant, item, state)[1](), str(now))
            return None
        self._jobs.delete_secret(name)
        if status is None or status.phase != SUCCEEDED:
            return None
        return outcome_of(state, status.message)


def _http_status(url: str, timeout: float) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        with error:
            return error.code


def probes(
    jobs: Jobs,
    config: WorkerConfig,
    *,
    get: Callable[[str, float], int] = _http_status,
    timeout: float = 5.0,
) -> dict[str, Probe]:
    """The `secret`, `service` and `worker-image` probes of the preflight.

    `get` answers the HTTP status of a GET of a URL within a timeout, or raises. No probe
    output holds a secret's value: the secret probe reads metadata only.
    """

    def secret(need: Need, lane: Lane) -> ProbeResult:
        name, _ = config.secret_ref(need.name)
        found = jobs.secret_minted(name) is not None
        return ProbeResult(found, f"Secret {name!r} {'exists' if found else 'does not exist'}")

    def service(need: Need, lane: Lane) -> ProbeResult:
        url = config.services.get(need.name)
        if not url:
            return ProbeResult(False, f"no URL is configured for service {need.name!r}")
        try:
            status = get(url, timeout)
        except Exception as error:
            return ProbeResult(False, f"GET {url} failed: {type(error).__name__}")
        return ProbeResult(status < 500, f"GET {url} answered {status}")

    def worker_image(need: Need, lane: Lane) -> ProbeResult:
        pod = manifest("probe", lane, config, config.deadline)["spec"]["template"]["spec"]
        runs = {c["image"] for c in [*pod["initContainers"], *pod["containers"]]}
        if runs != {lane.worker_image.reference} or not _DIGEST.fullmatch(min(runs)):
            return ProbeResult(False, f"a worker would run {sorted(runs)}, not the lane's digest")
        return ProbeResult(True, f"a worker runs {min(runs)}")

    return {SECRET: secret, SERVICE: service, WORKER_IMAGE: worker_image}
