"""Acceptance (SY-V3-WORKER-LAUNCHER): the jobs port and its fake are held to Kubernetes.

The real client (`KubeJobs`) talks over real HTTP to the fake API server in this process
(`tests/fake_jobs.py`). The fake refuses what the vendored Kubernetes OpenAPI fragment does not
document, and these tests check every exchange again from outside: each request is a documented
operation and each response matches the schema Kubernetes publishes for it.
"""

from __future__ import annotations

import json
import pathlib
import re
import socket
import ssl
from typing import Any

import pytest

from sortyard.lane.jobs import (
    BRIEF_KEY,
    DISPATCH_LABEL,
    FAILED,
    ITEM_LABEL,
    MINTED,
    RUNNING,
    SUCCEEDED,
    TOKEN_KEY,
    Jobs,
    JobsError,
    JobStatus,
    KubeJobs,
)
from sortyard.lane.worker import WorkerConfig, job_name, manifest
from tests.fake_jobs import CONTRACT, PARTIAL, STATUS, Contract, FakeCluster
from tests.worker_harness import LANE, TOKEN

CONFIG = WorkerConfig(agents={"build": ["agent"], "fix": ["agent"], "review": ["agent"]})
JOB = "io.k8s.api.batch.v1.Job"
LANE_SECRETS = {"deploy-token": {"DEPLOY_TOKEN": "v"}, "model-api-key": {"MODEL_API_KEY": "v"}}


def client(cluster: FakeCluster, token: str | None = None) -> KubeJobs:
    return KubeJobs(cluster.url, cluster.namespace, token=lambda: token or cluster.token)


def cluster_with_lane_secrets() -> FakeCluster:
    cluster = FakeCluster()
    for name, data in LANE_SECRETS.items():
        cluster.add_secret(name, data)
    return cluster


def job(name: str) -> dict[str, Any]:
    """The launcher's manifest for a Job named sy-<item>-<dispatch>."""
    _, item, dispatch = name.split("-")
    return manifest(name, LANE, CONFIG, 1800, {ITEM_LABEL: item, DISPATCH_LABEL: dispatch})


def mint() -> str:
    return TOKEN


def test_every_fake_response_matches_the_kubernetes_schema_for_its_kind_and_the_client_sends_the_documented_requests() -> (  # noqa: E501
    None
):
    """Every fake response matches the Kubernetes schema for its kind and the client sends the
    documented requests."""
    with cluster_with_lane_secrets() as cluster:
        jobs: Jobs = client(cluster)
        # Every method of the port, through every answer it handles.
        assert jobs.launch(job("sy-one-1"), brief="{}", token=mint, stamp="100") is True
        assert jobs.launch(job("sy-one-1"), brief="{}", token=mint, stamp="100") is False
        assert jobs.status("sy-one-1") == JobStatus(RUNNING)
        assert jobs.secret_minted("sy-one-1") == "100" and jobs.secret_minted("sy-none") is None
        assert jobs.secret_minted("deploy-token") == ""  # a Secret, but not one a launch made
        jobs.refresh_secret("sy-one-1", f"{TOKEN}-new", "200")
        jobs.refresh_secret("sy-none", f"{TOKEN}-new", "200")
        assert jobs.launch(job("sy-one-2"), brief="{}", token=mint, stamp="100") is True
        jobs.delete_earlier("one", 2)
        assert jobs.status("sy-one-1") is None
        cluster.finish("sy-one-2", '{"outcome":"built"}')
        assert jobs.status("sy-one-2") == JobStatus(SUCCEEDED, '{"outcome":"built"}')
        jobs.delete("sy-one-2")
        assert jobs.launch(job("sy-one-1"), brief="{}", token=mint, stamp="100") is True
        cluster.finish("sy-one-1", '{"outcome":"built"}')
        assert jobs.status("sy-one-1") == JobStatus(SUCCEEDED, '{"outcome":"built"}')
        jobs.delete_secret("sy-one-1")
        jobs.delete_secret("sy-one-1")
        assert jobs.launch(job("sy-two-1"), brief="{}", token=mint, stamp="100") is True
        cluster.fail("sy-two-1")
        assert jobs.status("sy-two-1") == JobStatus(FAILED)
        jobs.delete("sy-two-1")
        assert jobs.status("sy-two-1") is None
        exchanges = list(cluster.exchanges)
        # The fake itself found nothing out of contract, and no Secret's data was read.
        assert cluster.violations == []
        assert cluster.secret_data_reads == 0

    # Checked again from outside the fake, against the vendored document read afresh.
    document = json.loads(CONTRACT.read_text())
    contract = Contract()
    documented = {
        operation["operationId"]: (method.upper(), template, operation)
        for template, methods in document["paths"].items()
        for method, operation in methods.items()
    }
    # The client used every vendored operation and nothing else.
    assert {exchange.operation for exchange in exchanges} == set(documented)
    kinds: set[str] = set()
    for exchange in exchanges:
        method, template, operation = documented[exchange.operation]
        assert exchange.method == method
        assert re.fullmatch(re.sub(r"\{\w+\}", "[^/]+", template), exchange.path)
        queries = {p["name"] for p in operation["parameters"] if p["in"] == "query"}
        assert set(exchange.query) <= queries
        body = next((p["schema"]["$ref"] for p in operation["parameters"] if p["in"] == "body"), "")
        if exchange.request is not None:
            assert body and contract.errors(body, exchange.request) == []
        if exchange.status < 300:
            expected = operation["responses"][str(exchange.status)]["schema"]["$ref"]
            if exchange.response["kind"] == PARTIAL:
                assert exchange.schema == PARTIAL and "data" not in exchange.response
            else:
                assert expected.endswith(exchange.schema)
                assert expected.rsplit(".", 1)[1] == exchange.response["kind"]
        else:
            assert exchange.status in (404, 409) and exchange.schema == STATUS
        if exchange.request is not None:
            consumes = operation["consumes"]
            sent = "application/merge-patch+json" if method == "PATCH" else "application/json"
            assert consumes == ["*/*"] or sent in consumes
        assert contract.errors(exchange.schema, exchange.response) == []
        kinds.add(exchange.response["kind"])
    assert kinds == {"Job", "JobList", "ConfigMap", "Secret", "PodList", "Status", PARTIAL}
    # The answers that carry the port's meaning were all seen: created, found, not found,
    # already there.
    seen = {(exchange.method, exchange.status) for exchange in exchanges}
    assert {("POST", 201), ("POST", 409), ("GET", 200), ("GET", 404)} <= seen
    assert {("DELETE", 200), ("DELETE", 404), ("PATCH", 200), ("PATCH", 404)} <= seen


def test_a_response_or_request_that_does_not_match_the_schema_is_refused() -> None:
    """The check can fail: a body off the schema is named, and the fake refuses requests the
    document does not have."""
    contract = Contract()
    good = job("sy-good-1")
    assert contract.errors(JOB, good) == []
    misspelt = json.loads(json.dumps(good))
    misspelt["spec"]["backofLimit"] = misspelt["spec"].pop("backoffLimit")
    mistyped = json.loads(json.dumps(good))
    mistyped["spec"]["activeDeadlineSeconds"] = "1800"
    no_template = json.loads(json.dumps(good))
    del no_template["spec"]["template"]
    condition = {**good, "status": {"conditions": [{"type": "Complete"}]}}
    for bad in (misspelt, mistyped, no_template, condition):
        assert contract.errors(JOB, bad) != []
    pods = {"kind": "PodList", "apiVersion": "v1", "metadata": {}}
    assert contract.errors("io.k8s.api.core.v1.PodList", pods) != []  # no items
    assert contract.errors(PARTIAL, {"kind": "Secret", "apiVersion": "v1", "metadata": {}}) != []

    with FakeCluster() as cluster:
        jobs = client(cluster)
        with pytest.raises(JobsError, match="422"):
            jobs.launch(misspelt, brief="{}", token=mint, stamp="100")
        assert cluster.names("job") == [] and len(cluster.violations) == 1
        long_name = {**good, "metadata": {"name": "x" * 64}}
        with pytest.raises(JobsError, match="422"):
            jobs.launch(long_name, brief="{}", token=mint, stamp="100")
        auth = {"Authorization": f"Bearer {cluster.token}", "Content-Type": "application/json"}
        base = f"/api/v1/namespaces/{cluster.namespace}"
        # Listing Secrets and watching pods are not operations the port has.
        assert cluster.handle("GET", f"{base}/secrets", auth, b"")[0] == 404
        assert cluster.handle("GET", f"{base}/pods?watch=1&bogus=1", auth, b"")[0] == 400
        assert cluster.handle("POST", f"{base}/configmaps", auth, b'{"data": 7}')[0] == 422
        # A body must say what it is: JSON for a create, a patch type for a patch.
        plain = {**auth, "Content-Type": "text/plain"}
        config = b'{"metadata": {"name": "c"}}'
        assert cluster.handle("POST", f"{base}/configmaps", plain, config)[0] == 415
        cluster.add_secret("s", {"k": "v"})
        assert cluster.handle("PATCH", f"{base}/secrets/s", auth, b'{"stringData": {}}')[0] == 415
        merge = {**auth, "Content-Type": "application/merge-patch+json"}
        assert cluster.handle("PATCH", f"{base}/secrets/s", merge, b'{"type": "x"}')[0] == 422
        assert cluster.handle("PATCH", f"{base}/secrets/s", merge, b'{"stringData": {}}')[0] == 200
        assert cluster.handle("GET", f"{base}/pods?labelSelector=a!=b", auth, b"")[0] == 200
        assert len(cluster.violations) == 9 and cluster.names("configmap") == []


def test_a_launch_that_died_is_completed_by_the_next_and_an_ended_job_gets_nothing_back() -> None:
    """A second launch creates no second Job; it puts back only what a died launch left out,
    mints no token when the secret is there, and touches nothing once the Job has ended."""
    minted: list[str] = []

    def token() -> str:
        minted.append(f"{TOKEN}-{len(minted)}")
        return minted[-1]

    with cluster_with_lane_secrets() as cluster:
        jobs = client(cluster)
        # The first launch dies after the Job and the brief exist: the secret is refused.
        cluster.refuse[("POST", "secret")] = 403
        with pytest.raises(JobsError) as refused:
            jobs.launch(job("sy-one-1"), brief='{"n":1}', token=token, stamp="100")
        assert minted[0] not in str(refused.value) and "403" in str(refused.value)
        assert cluster.names("job") == ["sy-one-1"] and "sy-one-1" not in cluster.names("secret")
        assert cluster.unstartable("sy-one-1") == ["secret sy-one-1"]
        cluster.refuse.clear()
        # The next launch completes it: still one Job, and now it can start.
        assert jobs.launch(job("sy-one-1"), brief='{"n":1}', token=token, stamp="100") is False
        assert cluster.names("job") == ["sy-one-1"] and cluster.unstartable("sy-one-1") == []
        uid = cluster.get("job", "sy-one-1")["metadata"]["uid"]
        for kind in ("configmap", "secret"):
            owner = cluster.get(kind, "sy-one-1")["metadata"]["ownerReferences"]
            assert [(o["kind"], o["name"], o["uid"]) for o in owner] == [("Job", "sy-one-1", uid)]
        assert cluster.get("configmap", "sy-one-1")["data"] == {BRIEF_KEY: '{"n":1}'}
        assert cluster.secret_value("sy-one-1", TOKEN_KEY) == minted[1]
        # With everything there, another launch mints nothing.
        assert jobs.launch(job("sy-one-1"), brief='{"n":1}', token=token, stamp="100") is False
        assert len(minted) == 2
        # Once the Job has ended and its secret is deleted, a late launch does not bring the
        # secret back.
        cluster.finish("sy-one-1", "{}")
        jobs.delete_secret("sy-one-1")
        assert jobs.launch(job("sy-one-1"), brief='{"n":1}', token=token, stamp="100") is False
        assert "sy-one-1" not in cluster.names("secret") and len(minted) == 2
        assert cluster.secret_data_reads == 0


def test_a_running_jobs_token_is_replaced_in_place_and_an_absent_secret_is_not_made() -> None:
    """Refreshing a per-job secret replaces its token and mint stamp and nothing else; a
    secret that is gone is not brought back."""
    with cluster_with_lane_secrets() as cluster:
        jobs = client(cluster)
        jobs.launch(job("sy-one-1"), brief="{}", token=mint, stamp="100")
        before = cluster.get("secret", "sy-one-1")
        assert before["metadata"]["annotations"] == {MINTED: "100"}
        assert before["metadata"]["labels"][ITEM_LABEL] == "one"
        jobs.refresh_secret("sy-one-1", f"{TOKEN}-new", "1900")
        after = cluster.get("secret", "sy-one-1")
        assert cluster.secret_value("sy-one-1", TOKEN_KEY) == f"{TOKEN}-new"
        assert jobs.secret_minted("sy-one-1") == "1900"
        for kept in ("uid", "ownerReferences", "labels", "name"):
            assert after["metadata"][kept] == before["metadata"][kept]
        jobs.delete_secret("sy-one-1")
        jobs.refresh_secret("sy-one-1", f"{TOKEN}-late", "2000")
        assert "sy-one-1" not in cluster.names("secret")
        assert cluster.violations == [] and cluster.secret_data_reads == 0


def test_the_earlier_dispatches_of_an_item_are_deleted_by_label_with_what_they_created() -> None:
    """Deleting an item's earlier dispatches removes their Jobs, pods, briefs and secrets, and
    leaves the current dispatch, later ones and other items alone."""
    with cluster_with_lane_secrets() as cluster:
        jobs = client(cluster)
        for name in ("sy-one-1", "sy-one-2", "sy-one-10", "sy-one-11", "sy-two-1"):
            jobs.launch(job(name), brief="{}", token=mint, stamp="100")
        cluster.finish("sy-one-1", "{}")  # ended or still running: both go
        jobs.delete_earlier("one", 10)
        left = ["sy-one-10", "sy-one-11", "sy-two-1"]
        assert cluster.names("job") == left and cluster.names("configmap") == left
        assert cluster.names("secret") == ["deploy-token", "model-api-key", *left]
        assert sorted(name.rsplit("-", 1)[0] for name in cluster.names("pod")) == left
        jobs.delete_earlier("three", 10)  # an item with no Jobs: nothing to do
        assert cluster.names("job") == left and cluster.violations == []


def test_the_in_cluster_client_reads_the_service_account_files(tmp_path: pathlib.Path) -> None:
    """In a pod the client takes the server from the environment and the namespace, CA and
    token from the service-account directory, reading the token again for every request."""
    ca = pathlib.Path(CONTRACT).with_name("test-ca.crt")
    (tmp_path / "ca.crt").write_text(ca.read_text())
    (tmp_path / "namespace").write_text("lanes\n")
    (tmp_path / "token").write_text("first\n")
    environ = {"KUBERNETES_SERVICE_HOST": "fd00::1", "KUBERNETES_SERVICE_PORT": "6443"}
    jobs = KubeJobs.in_cluster(root=tmp_path, environ=environ)
    assert (jobs.base_url, jobs.namespace) == ("https://[fd00::1]:6443", "lanes")
    assert jobs.token() == "first"
    (tmp_path / "token").write_text("rotated\n")
    assert jobs.token() == "rotated"
    assert jobs.context is not None and jobs.context.verify_mode == ssl.CERT_REQUIRED
    assert jobs.context.check_hostname and len(jobs.context.get_ca_certs()) == 1
    named = KubeJobs.in_cluster(
        "other", root=tmp_path, environ={**environ, "KUBERNETES_SERVICE_HOST": "10.0.0.1"}
    )
    assert (named.base_url, named.namespace) == ("https://10.0.0.1:6443", "other")


def test_deleting_a_job_deletes_what_it_created_and_nothing_else() -> None:
    """Deleting a Job removes its pod, brief and per-job secret, and leaves the lane's own."""
    with cluster_with_lane_secrets() as cluster:
        jobs = client(cluster)
        jobs.launch(job("sy-one-1"), brief="{}", token=mint, stamp="100")
        jobs.launch(job("sy-two-1"), brief="{}", token=mint, stamp="100")
        jobs.delete("sy-one-1")
        assert cluster.names("job") == ["sy-two-1"]
        assert cluster.names("configmap") == ["sy-two-1"]
        assert cluster.names("secret") == ["deploy-token", "model-api-key", "sy-two-1"]
        assert [name.rsplit("-", 1)[0] for name in cluster.names("pod")] == ["sy-two-1"]
        jobs.delete("sy-one-1")  # gone already: not an error
        assert cluster.violations == []


def test_an_error_names_the_request_and_never_a_token() -> None:
    """A refused or failed request raises JobsError without the cluster token or a body."""
    with FakeCluster() as cluster:
        wrong = client(cluster, token="not-the-cluster-token")
        with pytest.raises(JobsError) as denied:
            wrong.status("sy-one-1")
        assert "401" in str(denied.value) and "not-the-cluster-token" not in str(denied.value)
        assert denied.value.__cause__ is None and denied.value.__suppress_context__
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
    down = KubeJobs(f"http://127.0.0.1:{port}", "lanes", token=lambda: "cluster-token")
    with pytest.raises(JobsError) as unreachable:
        down.secret_minted("deploy-token")
    assert "cluster-token" not in str(unreachable.value)


def test_a_job_name_is_a_dns_label_derived_from_the_tenant_the_item_and_the_dispatch() -> None:
    """The Job name is a DNS label whatever the ids hold, stable, and distinct per dispatch."""
    label = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")
    odd = [("acme", "ITEM-1"), ("a:b", "c"), ("a", "b:c"), ("T" * 300, "Ünïcode/ITEM_" * 40)]
    names = {job_name(tenant, item, dispatch) for tenant, item in odd for dispatch in (1, 2, 99999)}
    assert len(names) == len(odd) * 3
    assert all(label.fullmatch(name) and len(name) <= 63 for name in names)
    assert job_name("acme", "ITEM-1", 7) == job_name("acme", "ITEM-1", 7)


def test_the_vendored_fragment_names_its_source_and_version() -> None:
    """The contract directory says where the fragment came from and which version it is."""
    document = json.loads(CONTRACT.read_text())
    readme = (pathlib.Path(CONTRACT).parent / "README.md").read_text()
    assert document["version"] in document["source"] and document["source"] in readme
    assert {
        "io.k8s.api.batch.v1.Job",
        "io.k8s.api.core.v1.Pod",
        "io.k8s.api.core.v1.Secret",
    } <= set(document["definitions"])
    assert "io.k8s.api.core.v1.ConfigMap" in document["definitions"]
