"""Acceptance (SY-V3-WORKER-LAUNCHER): one worker Job per dispatch, and its result observed.

The launcher, the jobs client, the item workflow, the shipped state table and the engine (its
test server) are real. Kubernetes is the strict fake API server of `tests/fake_jobs.py`, reached
over real HTTP. In the end-to-end test each Job the launcher creates is run by the real
`sortyard-worker` entry point against a local git remote, and its result goes back through the
fake as the container's termination message. Nothing reaches a network and no test waits a
fixed time.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from sortyard.engine import Registry
from sortyard.engine.testing import time_skipping_engine
from sortyard.kernel.capabilities import KINDS, CapabilityError, Image, Need
from sortyard.kernel.item import register, send_outcome, start_item, workflow_id
from sortyard.kernel.preflight import InMemoryGapRegistry, Preflight, ProbeResult, TaskNeeds
from sortyard.lane.jobs import BRIEF_KEY, JOB_LABEL, TOKEN_KEY, KubeJobs
from sortyard.lane.worker import (
    BRIEF_DIR,
    BRIEF_ENV,
    TOKEN_DIR,
    TOKEN_FILE_ENV,
    Launcher,
    Work,
    WorkerConfig,
    branch,
    job_name,
    outcome_of,
    probes,
)
from tests.fake_jobs import FakeCluster
from tests.kernel_harness import until
from tests.worker_harness import (
    LANE,
    TOKEN,
    agent_command,
    make_remote,
    remote_head,
    run_worker,
)

TENANT = "acme"
HEAD = "ab" * 20
SPEC = {"outcome": "the widget counts to ten", "acceptance": ["tests/test_widget.py"]}
LANE_SECRET_VALUE = "the-lane-secret-value-no-one-reads"
AGENTS = {"build": ["agent", "--build"], "fix": ["agent", "--fix"], "review": ["reviewer"]}


@dataclass
class Tokens:
    """A strict token source: it mints only for a repository the lane declares."""

    minted: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def __call__(self, repository: str, permissions: Mapping[str, str]) -> str:
        assert repository in LANE.repositories, f"a token was asked for {repository}"
        self.minted.append((repository, dict(permissions)))
        return f"{TOKEN}-{len(self.minted)}"


@dataclass
class World:
    cluster: FakeCluster
    config: WorkerConfig
    tokens: Tokens = field(default_factory=Tokens)
    repositories: dict[str, str] = field(default_factory=dict)

    def lookup(self, tenant: str, item: str) -> Work:
        assert tenant == TENANT, tenant
        return Work(LANE, self.repositories.get(item, "walwarden/app"), SPEC)

    def launcher(self) -> Launcher:
        """A launcher as a new process would build it: a new client, nothing carried over."""
        jobs = KubeJobs(self.cluster.url, self.cluster.namespace, token=lambda: self.cluster.token)
        return Launcher(jobs=jobs, lookup=self.lookup, tokens=self.tokens, config=self.config)

    def posts(self, resource: str) -> list[int]:
        """The status of every create of the resource, in order."""
        return [
            exchange.status
            for exchange in self.cluster.exchanges
            if exchange.method == "POST" and exchange.path.endswith(f"/{resource}s")
        ]

    def job_secrets(self) -> list[str]:
        return [name for name in self.cluster.names("secret") if name.startswith("sy-")]


@contextmanager
def world(config: WorkerConfig | None = None) -> Iterator[World]:
    with FakeCluster() as cluster:
        # The lane's declared secrets, under the names the launcher's default mapping gives.
        cluster.add_secret("deploy-token", {"DEPLOY_TOKEN": LANE_SECRET_VALUE})
        cluster.add_secret("model-api-key", {"MODEL_API_KEY": LANE_SECRET_VALUE})
        made = World(cluster, config or WorkerConfig(agents=AGENTS))
        yield made
        # Whatever a test did, it stayed inside the Kubernetes contract, read no Secret's
        # data, and no lane secret value travelled in a request.
        assert cluster.violations == []
        assert cluster.secret_data_reads == 0
        sent = json.dumps([exchange.request for exchange in cluster.exchanges])
        assert LANE_SECRET_VALUE not in sent


def call(item: str, state: str, dispatch: int, **over: Any) -> dict[str, Any]:
    """An owner call as the item workflow makes it."""
    made: dict[str, Any] = {
        "item": item,
        "tenant": TENANT,
        "state": state,
        "owner": "reviewer" if state == "reviewing" else "executor",
        "dispatch": dispatch,
        "attempt": 1,
        "cause": "outcome",
        "action": None,
        "detail": {},
    }
    return {**made, **over}


def result(outcome: str, **more: Any) -> str:
    """A termination message as the entry point writes one."""
    return json.dumps({"outcome": outcome, "head": HEAD, **more}, separators=(",", ":"))


def test_the_executor_launches_one_job_per_dispatch_and_a_repeated_call_launches_none() -> None:
    """The executor launches one Job per dispatch and a repeated call launches none."""
    with world() as w:
        launcher = w.launcher()
        build = call("ITEM-1", "building", 3, limit_seconds=1800.0)
        assert launcher.owners()["executor"](build) is None  # the outcome arrives later
        name = job_name(TENANT, "ITEM-1", 3)
        assert w.cluster.names("job") == [name]
        job = w.cluster.get("job", name)
        # One attempt, bounded by the state's limit, running the lane's worker image by digest.
        assert job["spec"]["backoffLimit"] == 0
        assert job["spec"]["activeDeadlineSeconds"] == 1800
        pod = job["spec"]["template"]["spec"]
        assert pod["restartPolicy"] == "Never"
        assert job["spec"]["template"]["metadata"]["labels"][JOB_LABEL] == name
        (container,) = pod["containers"]
        assert container["image"] == LANE.worker_image.reference
        assert container["image"].endswith(LANE.worker_image.digest)
        assert container["terminationMessagePath"] == "/dev/termination-log"
        # The lane's secrets are read by reference to their names; no value is in the Job.
        env = {variable["name"]: variable for variable in container["env"]}
        for declared, secret in (
            ("DEPLOY_TOKEN", "deploy-token"),
            ("MODEL_API_KEY", "model-api-key"),
        ):
            assert env[declared] == {
                "name": declared,
                "valueFrom": {"secretKeyRef": {"name": secret, "key": declared}},
            }
        # The brief and the per-job secret are mounted where the entry point is told to look,
        # and both exist, so the pod can start.
        mounts = {mount["name"]: mount["mountPath"] for mount in container["volumeMounts"]}
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        assert volumes["brief"]["configMap"]["name"] == name
        assert volumes["github"]["secret"]["secretName"] == name
        assert (
            env[BRIEF_ENV]["value"]
            == f"{mounts['brief']}/{BRIEF_KEY}"
            == f"{BRIEF_DIR}/{BRIEF_KEY}"
        )
        assert env[TOKEN_FILE_ENV]["value"] == f"{mounts['github']}/{TOKEN_KEY}"
        assert mounts["github"] == TOKEN_DIR
        assert w.cluster.unstartable(name) == []
        # The token: minted once, for the item's one repository, held by a secret the Job owns.
        assert w.tokens.minted == [("walwarden/app", {"contents": "write"})]
        assert w.cluster.secret_value(name, TOKEN_KEY) == f"{TOKEN}-1"
        assert TOKEN not in json.dumps(job) + json.dumps(w.cluster.get("configmap", name))
        for kind in ("secret", "configmap"):
            (owner,) = w.cluster.get(kind, name)["metadata"]["ownerReferences"]
            assert (owner["kind"], owner["uid"]) == ("Job", job["metadata"]["uid"])
        # The brief: the spec, the repository, the base branch, the work branch, the agent.
        brief = json.loads(w.cluster.get("configmap", name)["data"][BRIEF_KEY])
        assert (brief["mode"], brief["item"], brief["dispatch"]) == ("build", "ITEM-1", 3)
        assert (brief["repository"], brief["base"]) == ("walwarden/app", "main")
        assert brief["branch"] == "sortyard/ITEM-1" == branch("ITEM-1")
        assert brief["clone_url"] == "https://github.com/walwarden/app.git"
        assert brief["spec"] == SPEC and brief["agent"] == ["agent", "--build"]
        assert "finding" not in brief
        for told in (SPEC["outcome"], "walwarden/app", "sortyard/ITEM-1", "main"):
            assert told in brief["text"]

        # The same dispatch again, from this launcher and from a new process: no second Job,
        # no second token, nothing replaced.
        launcher.launch(build)
        w.launcher().launch(build)
        assert w.cluster.names("job") == [name]
        assert w.posts("job") == [201, 409, 409]
        assert w.posts("secret") == [201] and w.posts("configmap") == [201, 409, 409]
        assert len(w.tokens.minted) == 1
        assert w.cluster.get("job", name)["metadata"]["uid"] == job["metadata"]["uid"]
        assert len(w.cluster.names("pod")) == 1

        # Another dispatch of the item, and another item, each get their own Job. A call that
        # names no limit is bounded by the configured deadline.
        launcher.launch(call("ITEM-1", "building", 9))
        launcher.launch(call("ITEM-2", "building", 3))
        names = {name, job_name(TENANT, "ITEM-1", 9), job_name(TENANT, "ITEM-2", 3)}
        assert set(w.cluster.names("job")) == names and len(names) == 3
        later = w.cluster.get("job", job_name(TENANT, "ITEM-1", 9))
        assert later["spec"]["activeDeadlineSeconds"] == w.config.deadline


def test_the_brief_of_a_fix_carries_the_finding_and_each_job_gets_the_token_its_work_needs() -> (
    None
):
    """A fix's brief carries the finding; a review's token cannot write; a repository declared
    with workflow files gets the workflows permission; an undeclared one gets no Job."""
    with world() as w:
        launcher = w.launcher()
        finding = {
            "finding": "missing-fix-txt",
            "findings": [{"key": "missing-fix-txt", "text": "The change does not add fix.txt."}],
            "head": HEAD,
        }
        launcher.launch(call("ITEM-1", "fixing", 5, detail=finding))
        fix = json.loads(
            w.cluster.get("configmap", job_name(TENANT, "ITEM-1", 5))["data"][BRIEF_KEY]
        )
        assert (fix["mode"], fix["finding"], fix["agent"]) == ("fix", finding, ["agent", "--fix"])
        assert "missing-fix-txt" in fix["text"] and "does not add fix.txt" in fix["text"]

        assert launcher.owners()["reviewer"](call("ITEM-1", "reviewing", 6)) is None
        review = json.loads(
            w.cluster.get("configmap", job_name(TENANT, "ITEM-1", 6))["data"][BRIEF_KEY]
        )
        assert (review["mode"], review["agent"]) == ("review", ["reviewer"])
        assert '"verdict"' in review["text"]

        w.repositories["ITEM-2"] = "walwarden/infra"
        launcher.launch(call("ITEM-2", "building", 3))
        assert w.tokens.minted == [
            ("walwarden/app", {"contents": "write"}),
            ("walwarden/app", {"contents": "read", "pull_requests": "read"}),
            ("walwarden/infra", {"contents": "write", "workflows": "write"}),
        ]
        # Each Job holds its own token.
        held = {w.cluster.secret_value(name, TOKEN_KEY) for name in w.job_secrets()}
        assert held == {f"{TOKEN}-1", f"{TOKEN}-2", f"{TOKEN}-3"}

        w.repositories["ITEM-3"] = "elsewhere/app"
        with pytest.raises(CapabilityError):
            launcher.launch(call("ITEM-3", "building", 3))
        with pytest.raises(KeyError):
            launcher.launch(call("ITEM-1", "merging", 7))
        assert len(w.cluster.names("job")) == 3 and len(w.tokens.minted) == 3


def test_a_finished_build_is_observed_as_built_with_its_head_commit_and_an_unchanged_branch_as_no_change() -> (  # noqa: E501
    None
):
    """A finished build is observed as built with its head commit and an unchanged branch as
    no-change."""
    with world() as w:
        launcher = w.launcher()
        built = call("ITEM-1", "building", 3)
        unchanged = call("ITEM-2", "building", 3)
        fixed = call("ITEM-1", "fixing", 5)
        for made in (built, unchanged, fixed):
            launcher.launch(made)
        # While a Job runs there is nothing to report, and its secret stays.
        assert launcher.observe(built) is None
        assert len(w.job_secrets()) == 3

        w.cluster.finish(job_name(TENANT, "ITEM-1", 3), result("built"))
        w.cluster.finish(job_name(TENANT, "ITEM-2", 3), result("no-change"))
        w.cluster.finish(job_name(TENANT, "ITEM-1", 5), result("fixed"))
        # A Job that outlived the process that launched it is observed by the next one.
        after_restart = w.launcher()
        assert after_restart.observe(built) == {"outcome": "built", "detail": {"head": HEAD}}
        assert after_restart.observe(unchanged) == {
            "outcome": "no-change",
            "detail": {"head": HEAD},
        }
        assert after_restart.observe(fixed) == {"outcome": "fixed", "detail": {"head": HEAD}}
        assert w.job_secrets() == []  # each Job ended, so its secret is gone
        # Observing again gives the same answer: the poller may ask until the item moves on.
        assert after_restart.observe(built) == {"outcome": "built", "detail": {"head": HEAD}}
        # The poller hands over the stay's names alone.
        stay = {"tenant": TENANT, "item": "ITEM-1", "state": "building", "dispatch": 3}
        assert launcher.observe(stay) == {"outcome": "built", "detail": {"head": HEAD}}

    # A build is never taken as built on the worker's word for a state that has no such
    # outcome, without a head commit, or from a message that is not a result.
    assert outcome_of("fixing", result("built")) is None
    assert outcome_of("fixing", result("no-change")) is None
    assert outcome_of("building", result("fixed")) is None
    assert outcome_of("building", '{"outcome":"built"}') is None
    assert outcome_of("building", '{"outcome":"built","head":"main"}') is None
    assert outcome_of("building", "built") is None
    assert outcome_of("building", "") is None
    assert outcome_of("building", '["built"]') is None
    assert outcome_of("merging", result("merged")) is None


def test_a_finished_review_is_observed_as_approved_or_as_findings_with_a_finding_key() -> None:
    """A finished review is observed as approved or as findings with a finding key."""
    findings = [
        {"key": "missing-fix-txt", "text": "The change does not add fix.txt."},
        {"key": "style", "text": "Second finding."},
    ]
    with world() as w:
        launcher = w.launcher()
        approved, found, keyless, cut = (call("ITEM-1", "reviewing", n) for n in (6, 8, 10, 12))
        for made in (approved, found, keyless, cut):
            launcher.launch(made)
        w.cluster.finish(job_name(TENANT, "ITEM-1", 6), result("approved"))
        w.cluster.finish(
            job_name(TENANT, "ITEM-1", 8),
            result("findings", finding="missing-fix-txt", findings=findings),
        )
        # Findings with no finding key, and a result so long the kubelet cut it.
        w.cluster.finish(job_name(TENANT, "ITEM-1", 10), result("findings", findings=findings))
        long = [{"key": "k", "text": "x" * 5000}]
        w.cluster.finish(
            job_name(TENANT, "ITEM-1", 12), result("findings", finding="k", findings=long)
        )
        # Approved names the head that was reviewed: the merge adapter refuses a moved one.
        assert launcher.observe(approved) == {"outcome": "approved", "detail": {"head": HEAD}}
        assert launcher.observe(found) == {
            "outcome": "findings",
            "detail": {"head": HEAD, "finding": "missing-fix-txt", "findings": findings},
        }
        assert launcher.observe(keyless) is None
        assert launcher.observe(cut) is None
        assert w.job_secrets() == []
    for blank in ("", "   ", None, 7):
        assert outcome_of("reviewing", result("findings", finding=blank, findings=findings)) is None
    assert outcome_of("reviewing", result("findings", finding="k")) is None
    assert outcome_of("reviewing", '{"outcome":"approved"}') is None
    assert outcome_of("reviewing", result("built")) is None


def test_a_failed_job_gives_no_reply_and_its_per_job_secret_is_deleted() -> None:
    """A failed Job gives no reply and its per-job secret is deleted."""
    with world() as w:
        launcher = w.launcher()
        deadline, crashed, vanished, wrong = (call("ITEM-1", "building", n) for n in (3, 5, 7, 9))
        for made in (deadline, crashed, vanished, wrong):
            launcher.launch(made)
        assert len(w.job_secrets()) == 4
        # Past its deadline with no result; a worker that reported failure; a worker that
        # exited non-zero while claiming success; a Job that is gone.
        w.cluster.fail(job_name(TENANT, "ITEM-1", 3))
        w.cluster.finish(job_name(TENANT, "ITEM-1", 5), '{"outcome":"failed","reason":"x"}', 1)
        w.cluster.finish(job_name(TENANT, "ITEM-1", 9), result("built"), 1)
        w.cluster.vanish(job_name(TENANT, "ITEM-1", 7))
        assert job_name(TENANT, "ITEM-1", 7) in w.job_secrets()  # left behind by the cluster
        for made in (deadline, crashed, vanished, wrong):
            assert launcher.observe(made) is None
        assert w.job_secrets() == []
        # Asked again (the stay is still open until its limit passes): still nothing, no error.
        for made in (deadline, crashed, vanished, wrong):
            assert launcher.observe(made) is None
        # A stay whose Job was never launched is the same as a vanished one.
        assert launcher.observe(call("ITEM-9", "building", 3)) is None
        assert len(w.tokens.minted) == 4


def test_the_probes_exercise_a_named_secret_a_named_service_and_the_worker_image() -> None:
    """The secret, service and worker-image probes pass and fail on what is there, and the
    preflight takes them."""
    seen: list[tuple[str, float]] = []
    answers: dict[str, int | Exception] = {"http://cluster-api.test/healthz": 200}

    def get(url: str, timeout: float) -> int:
        seen.append((url, timeout))
        answer = answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    services = {"cluster-api": "http://cluster-api.test/healthz"}
    with world(WorkerConfig(agents=AGENTS, services=services)) as w:
        jobs = KubeJobs(w.cluster.url, w.cluster.namespace, token=lambda: w.cluster.token)
        made = probes(jobs, w.config, get=get, timeout=2.5)
        assert set(made) == {"secret", "service", "worker-image"}

        present = made["secret"](Need("secret", "DEPLOY_TOKEN"), LANE)
        assert present.passed and LANE_SECRET_VALUE not in present.output
        w.cluster._remove("secret", "model-api-key")
        absent = made["secret"](Need("secret", "MODEL_API_KEY"), LANE)
        assert not absent.passed and "model-api-key" in absent.output
        mapped = replace(w.config, secrets={"DEPLOY_TOKEN": ("elsewhere", "token")})
        assert not probes(jobs, mapped)["secret"](Need("secret", "DEPLOY_TOKEN"), LANE).passed

        service = Need("service", "cluster-api")
        assert made["service"](service, LANE).passed
        assert seen == [("http://cluster-api.test/healthz", 2.5)]
        for status, passes in ((404, True), (499, True), (500, False), (503, False)):
            answers[services["cluster-api"]] = status
            assert made["service"](service, LANE).passed is passes, status
        answers[services["cluster-api"]] = TimeoutError("timed out")
        assert not made["service"](service, LANE).passed
        assert not made["service"](Need("service", "unmapped"), LANE).passed
        # The opener the probe uses when none is given, against a real listener: the fake
        # API server answers an anonymous GET 401, which is below 500.
        real = probes(jobs, replace(w.config, services={"cluster-api": f"{w.cluster.url}/x"}))
        assert real["service"](service, LANE).passed
        closed = probes(jobs, replace(w.config, services={"cluster-api": "http://127.0.0.1:1/"}))
        assert not closed["service"](service, LANE).passed

        image = made["worker-image"](Need("worker-image"), LANE)
        assert image.passed and LANE.worker_image.digest in image.output
        for reference in ("registry.test/walwarden/worker:latest", "worker@sha256:abc"):
            loose = replace(LANE, worker_image=Image(reference, ""))
            assert not made["worker-image"](Need("worker-image"), loose).passed

        # The preflight takes them beside the probes of the other kinds.
        every = {**dict.fromkeys(KINDS, lambda need, lane: ProbeResult(True, "ok")), **made}
        answers[services["cluster-api"]] = 200
        preflight = Preflight(
            lookup=lambda tenant, item: TaskNeeds(
                LANE, ("secret:DEPLOY_TOKEN", "service:cluster-api")
            ),
            probes=every,
            gaps=InMemoryGapRegistry(),
        )
        checked = preflight.check(call("ITEM-1", "preflight", 2))
        assert checked["outcome"] == "ready", checked
        w.cluster._remove("secret", "deploy-token")
        gap = preflight.check(call("ITEM-1", "preflight", 4))
        assert (gap["outcome"], gap["detail"]["need"]) == ("gap", "secret:DEPLOY_TOKEN")
        # Put back so the Job-side checks of the world still hold.
        w.cluster.add_secret("deploy-token", {"DEPLOY_TOKEN": LANE_SECRET_VALUE})


def test_an_item_goes_from_building_to_merged_on_real_jobs_with_one_fix_round(
    tmp_path: pathlib.Path,
) -> None:
    """Through the real workflow: each launched Job is run by the real entry point against a
    local remote, observed, and its outcome sent on; a review finding becomes a fix."""
    bare = make_remote(tmp_path)
    agents = {
        "build": agent_command(tmp_path, "commit:feature.txt", "build"),
        "fix": agent_command(tmp_path, "commit:fix.txt", "fix"),
        "review": agent_command(tmp_path, "review", "review"),
    }
    config = WorkerConfig(agents=agents, git_url=f"{tmp_path.as_uri()}/{{repository}}.git")
    events: list[Mapping[str, Any]] = []
    scripted = {
        "scheduler": "dispatched",
        "capability-checker": "ready",
        "ci-adapter": "green",
        "merge-adapter": "merged",
    }

    def other(made: Mapping[str, Any]) -> Mapping[str, Any] | None:
        return {"outcome": scripted[made["owner"]]} if made["owner"] in scripted else None

    async def scenario(w: World) -> list[Mapping[str, Any]]:
        launcher = w.launcher()
        registry = Registry()
        owners = {**dict.fromkeys([*scripted, "need"], other), **launcher.owners()}
        register(registry, owners=owners, decide=lambda question: None, record=events.append)
        async with time_skipping_engine() as skipping:
            engine = skipping.engine
            worker = asyncio.create_task(engine.run_worker(registry))
            try:
                identifier = await start_item(engine, "ITEM-1", tenant=TENANT)
                reported: list[Mapping[str, Any]] = []
                for state in ("building", "reviewing", "fixing", "reviewing"):
                    await until(
                        lambda: engine.recorded(identifier),
                        lambda recorded, state=state: (  # type: ignore[misc]
                            recorded.idle and events[-1]["state"] == state
                        ),
                        f"idle in {state}",
                    )
                    stay = {key: events[-1][key] for key in ("tenant", "item", "state", "dispatch")}
                    assert launcher.observe(stay) is None  # the Job is running
                    # What the cluster would do: start the pod with its brief and its token,
                    # and keep the container's termination message.
                    name = job_name(TENANT, "ITEM-1", stay["dispatch"])
                    brief = json.loads(w.cluster.get("configmap", name)["data"][BRIEF_KEY])
                    token = w.cluster.secret_value(name, TOKEN_KEY)
                    status, text = await asyncio.to_thread(
                        run_worker, tmp_path / name, brief, token
                    )
                    w.cluster.finish(name, text, status)
                    outcome = w.launcher().observe(stay)
                    assert outcome is not None, text
                    reported.append(outcome)
                    await send_outcome(
                        engine,
                        identifier,
                        state=state,
                        outcome=outcome["outcome"],
                        detail=outcome["detail"],
                        dispatch=stay["dispatch"],
                    )
                done = await asyncio.wait_for(engine.result(workflow_id(TENANT, "ITEM-1")), 60)
                assert done["state"] == "merged"
                return reported
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    with world(config) as w:
        reported = asyncio.run(scenario(w))
        assert [event["state"] for event in events] == [
            "admitted",
            "preflight",
            "building",
            "checking",
            "reviewing",
            "fixing",
            "checking",
            "reviewing",
            "merging",
            "merged",
        ]
        assert [outcome["outcome"] for outcome in reported] == [
            "built",
            "findings",
            "fixed",
            "approved",
        ]
        # The branch on the remote is what the workers pushed: the build, then the fix on it.
        head = remote_head(bare, "sortyard/ITEM-1")
        assert head is not None and reported[2]["detail"]["head"] == head
        assert reported[0]["detail"]["head"] != head
        # The review that approved read that head, and the item entered merging with it.
        assert reported[3]["detail"] == {"head": head}
        merging = next(event for event in events if event["state"] == "merging")
        assert merging["detail"] == {"head": head}
        # The finding entered fixing as one key, and the fix's brief carried it to the agent.
        fixing = next(event for event in events if event["state"] == "fixing")
        assert fixing["detail"]["finding"] == "missing-fix-txt"
        assert fixing["detail"]["head"] == reported[0]["detail"]["head"]
        told = json.loads((tmp_path / "fix.json").read_text())
        assert "missing-fix-txt" in told["stdin"] and SPEC["outcome"] in told["stdin"]
        # One Job per dispatch, one token each, and no per-job secret left when all had ended.
        assert len(w.cluster.names("job")) == 4 and w.job_secrets() == []
        assert [permissions["contents"] for _, permissions in w.tokens.minted] == [
            "write",
            "read",
            "write",
            "read",
        ]
        # No agent saw a token.
        for name in ("build", "fix", "review"):
            assert TOKEN not in (tmp_path / f"{name}.json").read_text()
