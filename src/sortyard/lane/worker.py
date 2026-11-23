"""The worker launcher: the executor and reviewer owners, on the jobs port (HARNESS-V3 3.3).

The state table gives `building` and `fixing` to the owner `executor` and `reviewing` to the
owner `reviewer`. `Launcher` is both. Each dispatch launches one worker Job and answers nothing;
`Launcher.observe` later turns the finished Job into the state's outcome, for whoever polls the
open stays and sends it on (`sortyard.kernel.item.send_outcome`).

Nothing is remembered between calls. The Job's name is derived from the tenant, the item and
the dispatch (`job_name`), so a repeated call finds the Job it already made and a Job that
outlives this process is observed by the next one.

What a Job gets:

- the lane's worker image, by digest;
- its **brief** (`brief`), mounted as a file: the item spec, the repository, the base branch,
  the branch `sortyard/<item id>`, for a fix the finding, and the agent command to run;
- a GitHub **token** minted for this Job and scoped to the item's one repository
  (`TokenSource`), in a per-job secret that the Job owns and `observe` deletes when it ends;
- the lane's declared secrets, by reference (`secretKeyRef`): the launcher never reads one.

The Job runs `sortyard-worker` (`sortyard.services.worker`), which reports its result as the
container's termination message. `observe` trusts that message only as far as the state can
use it: an outcome the state has, a head commit, and for findings one finding key. Anything
else, a failed Job and a vanished Job are no reply, so the state's limit and default apply.

`probes` gives the preflight its `secret`, `service` and `worker-image` probes.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sortyard.kernel.capabilities import REPOSITORY, SECRET, SERVICE, WORKER_IMAGE, Lane, Need
from sortyard.kernel.item import Owner, Payload
from sortyard.kernel.preflight import Probe, ProbeResult
from sortyard.lane.jobs import (
    BRIEF_KEY,
    JOB_LABEL,
    RUNNING,
    SUCCEEDED,
    TOKEN_KEY,
    WORKER_CONTAINER,
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
BRIEF_DIR, TOKEN_DIR, WORK_DIR = "/var/run/sortyard/brief", "/var/run/sortyard/github", "/work"
BRIEF_ENV, TOKEN_FILE_ENV, WORK_ENV = (
    "SORTYARD_BRIEF",
    "SORTYARD_GITHUB_TOKEN_FILE",
    "SORTYARD_WORKDIR",
)
# A container's termination message is cut at 4096 bytes; the worker keeps its result under it.
TERMINATION_LOG, RESULT_LIMIT = "/dev/termination-log", 4096

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
    declared service name to the URL its probe calls. `deadline` bounds a Job whose call
    names no limit, and `ttl` is how long a finished Job is kept, both in seconds.
    """

    agents: Mapping[str, Sequence[str]]
    git_url: str = "https://github.com/{repository}.git"
    secrets: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    services: Mapping[str, str] = field(default_factory=dict)
    command: Sequence[str] = ("sortyard-worker",)
    deadline: int = 7200
    ttl: int = 86400

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
    digest = hashlib.sha256(f"{len(tenant)}:{tenant}:{item}".encode()).hexdigest()[:24]
    return f"sy-{digest}-{int(dispatch)}"


def branch(item: str) -> str:
    return f"sortyard/{item}"


def brief(mode: str, work: Work, call: Payload, config: WorkerConfig) -> dict[str, Any]:
    """The brief of one Job: what the entry point needs, and `text`, what the agent is told."""
    item, detail = str(call["item"]), dict(call.get("detail") or {})
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
    }
    lines = [
        f"Item {item} in repository {work.repository}.",
        f"Base branch: {work.base}. Work branch: {made['branch']} (checked out here).",
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


def manifest(name: str, lane: Lane, config: WorkerConfig, deadline: int) -> dict[str, Any]:
    """The batch/v1 Job the launcher creates under `name` for a task of `lane`."""
    env: list[dict[str, Any]] = [
        {"name": BRIEF_ENV, "value": f"{BRIEF_DIR}/{BRIEF_KEY}"},
        {"name": TOKEN_FILE_ENV, "value": f"{TOKEN_DIR}/{TOKEN_KEY}"},
        {"name": WORK_ENV, "value": WORK_DIR},
    ]
    for declared in lane.secrets:
        secret, key = config.secret_ref(declared)
        env.append({"name": declared, "valueFrom": {"secretKeyRef": {"name": secret, "key": key}}})
    labels = {"app.kubernetes.io/managed-by": "sortyard", JOB_LABEL: name}
    container = {
        "name": WORKER_CONTAINER,
        "image": lane.worker_image.reference,
        "command": list(config.command),
        "env": env,
        "terminationMessagePath": TERMINATION_LOG,
        "terminationMessagePolicy": "File",
        "volumeMounts": [
            {"name": "brief", "mountPath": BRIEF_DIR, "readOnly": True},
            {"name": "github", "mountPath": TOKEN_DIR, "readOnly": True},
            {"name": "work", "mountPath": WORK_DIR},
        ],
    }
    pod = {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "containers": [container],
        "volumes": [
            {"name": "brief", "configMap": {"name": name}},
            {"name": "github", "secret": {"secretName": name}},
            {"name": "work", "emptyDir": {}},
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
    if not isinstance(result, Mapping) or result.get("outcome") not in OUTCOMES.get(state, ()):
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
    """The `executor` and `reviewer` owners and their observer."""

    def __init__(
        self, *, jobs: Jobs, lookup: WorkLookup, tokens: TokenSource, config: WorkerConfig
    ) -> None:
        self._jobs = jobs
        self._lookup = lookup
        self._tokens = tokens
        self._config = config

    def owners(self) -> dict[str, Owner]:
        """The two owners by the names the state table gives them, for `item.register`."""
        return {EXECUTOR_OWNER: self.launch, REVIEWER_OWNER: self.launch}

    def launch(self, call: Payload) -> None:
        """Launch the Job of this dispatch, unless it is there already. The outcome comes
        later, from `observe`. Safe to call again for the same dispatch."""
        tenant, item, mode = str(call["tenant"]), str(call["item"]), MODES[str(call["state"])]
        work = self._lookup(tenant, item)
        repository = work.lane.repositories[work.lane.check(Need(REPOSITORY, work.repository)).name]
        permissions = {"contents": "read" if mode == REVIEW else "write"}
        if mode == REVIEW:
            permissions["pull_requests"] = "read"
        elif repository.workflow_files:
            permissions["workflows"] = "write"
        limit = call.get("limit_seconds")
        deadline = int(limit) if isinstance(limit, int | float) and limit >= 1 else 0
        self._jobs.launch(
            manifest(
                job_name(tenant, item, int(call["dispatch"])),
                work.lane,
                self._config,
                deadline or self._config.deadline,
            ),
            brief=json.dumps(brief(mode, work, call, self._config)),
            token=lambda: self._tokens(work.repository, permissions),
        )

    def observe(self, stay: Payload) -> Payload | None:
        """The outcome of the stay (tenant, item, state, dispatch), once its Job has finished.

        Nothing while the Job runs. When it has ended or is gone its per-job secret is deleted,
        every time this is called, and a Job that failed, vanished or reported something the
        state cannot use gives nothing: the state's limit and default apply.
        """
        name = job_name(str(stay["tenant"]), str(stay["item"]), int(stay["dispatch"]))
        status = self._jobs.status(name)
        if status is not None and status.phase == RUNNING:
            return None
        self._jobs.delete_secret(name)
        if status is None or status.phase != SUCCEEDED:
            return None
        return outcome_of(str(stay["state"]), status.message)


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
        found = jobs.secret_exists(name)
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
        spec = manifest("probe", lane, config, config.deadline)["spec"]["template"]["spec"]
        runs = spec["containers"][0]["image"]
        if not _DIGEST.fullmatch(runs) or runs != lane.worker_image.reference:
            return ProbeResult(
                False, f"a worker would run {runs!r}, not the lane's image by digest"
            )
        return ProbeResult(True, f"a worker runs {runs}")

    return {SECRET: secret, SERVICE: service, WORKER_IMAGE: worker_image}
