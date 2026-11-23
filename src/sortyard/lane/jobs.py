"""The jobs port: one worker Job per dispatch, on Kubernetes (HARNESS-V3 section 3.3).

A lane's work runs in Jobs. This module is the one place that knows how: `Jobs` is the port the
worker launcher (`sortyard.lane.worker`) stands on, and `KubeJobs` is its client over the
Kubernetes HTTP API, on the standard library alone. The port does four things:

- **launch** a Job with what it needs to start: its brief (a ConfigMap) and its per-job secret
  (a Secret holding a token the caller mints only when the secret is not there yet). Both carry
  the Job's name and an ownerReference to it, so the cluster removes them with the Job. A
  launch for a name that already has a Job creates no second Job (the API server refuses the
  name); it only puts back a brief or a secret a died launch left out, and touches nothing
  once the Job has ended.
- read a Job's **status**: its phase and the worker container's termination message, which is
  how a worker reports its result (no log scraping, no side channel).
- **delete** the per-job secret alone, or the Job with everything it created.
- say whether a named Secret exists, reading its metadata only (never its data).

Nothing here keeps state: every answer is read from the cluster, so a Job launched by one
process is observed by the next. An error (`JobsError`) names the request and the status the
server gave, and never a request or response body, so no secret value can reach a log.
"""

from __future__ import annotations

import json
import pathlib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

RUNNING, SUCCEEDED, FAILED = "running", "succeeded", "failed"
# The label a Job's pods carry, so they can be found by the Job's name on any cluster version.
JOB_LABEL = "sortyard.dev/job"
WORKER_CONTAINER = "worker"
# The keys of the brief ConfigMap and the per-job Secret.
BRIEF_KEY, TOKEN_KEY = "brief.json", "token"
# Asks the API server for an object's metadata and nothing else.
METADATA_ONLY = "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1"
_IN_CLUSTER = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount")


class JobsError(Exception):
    """A request to the cluster failed. The message never holds a request or response body."""


@dataclass(frozen=True)
class JobStatus:
    """A Job's phase (`RUNNING`, `SUCCEEDED`, `FAILED`) and its worker's termination message."""

    phase: str
    message: str = ""


class Jobs(Protocol):
    def launch(self, job: Mapping[str, Any], *, brief: str, token: Callable[[], str]) -> bool:
        """Create the Job (a batch/v1 manifest), its brief and its per-job secret.

        True when this call created the Job, false when it was already there.
        """
        ...

    def status(self, name: str) -> JobStatus | None:
        """The Job's status, or nothing when no Job has the name."""
        ...

    def delete_secret(self, name: str) -> None:
        """Delete the per-job secret of the Job; one that is gone already is not an error."""
        ...

    def delete(self, name: str) -> None:
        """Delete the Job with its pods, brief and per-job secret."""
        ...

    def secret_exists(self, name: str) -> bool:
        """Whether a Secret has the name, from its metadata only."""
        ...


def _phase(job: Mapping[str, Any]) -> str:
    for condition in (job.get("status") or {}).get("conditions") or ():
        if condition.get("status") == "True" and condition.get("type") in ("Complete", "Failed"):
            return SUCCEEDED if condition["type"] == "Complete" else FAILED
    return RUNNING


class KubeJobs:
    """`Jobs` over the Kubernetes HTTP API of one namespace.

    `token` gives the bearer token for each request (a service-account token is rotated on
    disk, so it is read again every time); `context` is the TLS context for an https server.
    """

    def __init__(
        self,
        base_url: str,
        namespace: str,
        *,
        token: Callable[[], str],
        context: ssl.SSLContext | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._context = context
        self._timeout = timeout
        self._core = f"/api/v1/namespaces/{namespace}"
        self._batch = f"/apis/batch/v1/namespaces/{namespace}"

    @classmethod
    def in_cluster(cls, namespace: str | None = None) -> KubeJobs:
        """The client a pod gets from its service account."""
        import os

        host, port = os.environ["KUBERNETES_SERVICE_HOST"], os.environ["KUBERNETES_SERVICE_PORT"]
        host = f"[{host}]" if ":" in host else host
        return cls(
            f"https://{host}:{port}",
            namespace or (_IN_CLUSTER / "namespace").read_text().strip(),
            token=lambda: (_IN_CLUSTER / "token").read_text().strip(),
            context=ssl.create_default_context(cafile=str(_IN_CLUSTER / "ca.crt")),
        )

    def _call(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        absent: int | None = None,
        accept: str = "application/json",
    ) -> dict[str, Any] | None:
        """One request. The status `absent` (404 on a read, 409 on a create) answers nothing."""
        request = urllib.request.Request(
            self._base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Accept": accept, "Authorization": f"Bearer {self._token()}"},
        )
        if body is not None:
            request.add_header("Content-Type", "application/json")
        what = f"{method} {path.split('?')[0]}"
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout, context=self._context
            ) as response:
                answer = json.loads(response.read())
        except urllib.error.HTTPError as error:
            with error:
                if error.code == absent:
                    return None
                raise JobsError(f"{what} answered {error.code} {error.reason}") from None
        except (OSError, ValueError) as error:
            raise JobsError(f"{what} failed: {type(error).__name__}") from None
        if not isinstance(answer, dict):
            raise JobsError(f"{what} answered something that is not an object")
        return answer

    def launch(self, job: Mapping[str, Any], *, brief: str, token: Callable[[], str]) -> bool:
        name = job["metadata"]["name"]
        created = self._call("POST", f"{self._batch}/jobs", job, absent=409)
        current = created or self._call("GET", f"{self._batch}/jobs/{name}", absent=404)
        if current is None or _phase(current) != RUNNING:
            return created is not None  # ended (or gone again): nothing is put back
        owner = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "name": name,
            "uid": current["metadata"]["uid"],
            "controller": True,
            "blockOwnerDeletion": True,
        }
        metadata = {
            "name": name,
            "labels": dict(job["metadata"].get("labels") or {}),
            "ownerReferences": [owner],
        }
        config = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": metadata}
        self._call(
            "POST", f"{self._core}/configmaps", {**config, "data": {BRIEF_KEY: brief}}, absent=409
        )
        if not self.secret_exists(name):
            secret = {"apiVersion": "v1", "kind": "Secret", "metadata": metadata, "type": "Opaque"}
            self._call(
                "POST",
                f"{self._core}/secrets",
                {**secret, "stringData": {TOKEN_KEY: token()}},
                absent=409,
            )
        return created is not None

    def status(self, name: str) -> JobStatus | None:
        job = self._call("GET", f"{self._batch}/jobs/{name}", absent=404)
        if job is None:
            return None
        phase = _phase(job)
        if phase == RUNNING:
            return JobStatus(RUNNING)
        selector = urllib.parse.quote(f"{JOB_LABEL}={name}")
        pods = self._call("GET", f"{self._core}/pods?labelSelector={selector}") or {}
        for pod in pods.get("items") or ():
            for container in (pod.get("status") or {}).get("containerStatuses") or ():
                terminated = (container.get("state") or {}).get("terminated")
                if container.get("name") == WORKER_CONTAINER and terminated:
                    return JobStatus(phase, str(terminated.get("message") or ""))
        return JobStatus(phase)

    def _delete(self, path: str) -> None:
        self._call("DELETE", path, {"propagationPolicy": "Background"}, absent=404)

    def delete_secret(self, name: str) -> None:
        self._delete(f"{self._core}/secrets/{name}")

    def delete(self, name: str) -> None:
        # The secret first and by name: it must not outlive a failed delete of the Job, nor
        # wait for the cluster's garbage collector.
        self.delete_secret(name)
        self._delete(f"{self._batch}/jobs/{name}")
        self._delete(f"{self._core}/configmaps/{name}")

    def secret_exists(self, name: str) -> bool:
        found = self._call("GET", f"{self._core}/secrets/{name}", absent=404, accept=METADATA_ONLY)
        return found is not None
