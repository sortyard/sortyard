"""A fake Kubernetes API server for the jobs port, held to the published OpenAPI.

`FakeCluster` serves, over real HTTP in this process, the operations the jobs port uses, and
nothing else. It is strict in both directions, against `tests/contracts/kubernetes/openapi.json`
(a fragment of the Kubernetes OpenAPI document; see the README there):

- a request must be a vendored operation, carry only that operation's query parameters, and
  have a body that matches the operation's body schema with no unknown field;
- every response is checked against the operation's response schema before it is sent.

Anything else is answered with an error and kept in `violations`, so a test can assert there
were none. Every exchange is kept in `exchanges` for the contract test to check again from
outside.

It also plays the cluster's part: a Job gets a pod, deleting an owner deletes what it owns, a
Secret's `stringData` is stored as `data`, and a pod cannot finish unless the ConfigMap and
Secrets it mounts exist. `finish`, `fail` and `vanish` are how a test ends a Job.
"""

from __future__ import annotations

import base64
import copy
import json
import pathlib
import re
import threading
import urllib.parse
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from jsonschema import Draft4Validator  # type: ignore[import-untyped]

CONTRACT = pathlib.Path(__file__).parent / "contracts" / "kubernetes" / "openapi.json"
METADATA_ONLY = "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1"
STATUS = "io.k8s.apimachinery.pkg.apis.meta.v1.Status"
PARTIAL = "PartialObjectMetadata"
_DNS_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")
_PREFIX = "#/definitions/"


class Contract:
    """The vendored fragment: which operations exist and what each kind looks like."""

    def __init__(self) -> None:
        document = json.loads(CONTRACT.read_text())
        self.version: str = document["version"]
        self.paths: dict[str, Any] = document["paths"]
        definitions: dict[str, Any] = copy.deepcopy(document["definitions"])
        # Not in the OpenAPI document: the metadata-only form any resource can be read as
        # (meta/v1 PartialObjectMetadata; the README gives the source).
        meta = {"$ref": _PREFIX + "io.k8s.apimachinery.pkg.apis.meta.v1.ObjectMeta"}
        text = {"type": "string"}
        definitions[PARTIAL] = {
            "type": "object",
            "required": ["apiVersion", "kind", "metadata"],
            "properties": {"apiVersion": text, "kind": {"enum": [PARTIAL]}, "metadata": meta},
        }
        # The published schemas let unknown fields through; the API server does not keep
        # them. Held strictly here, a misspelt field is refused.
        for definition in definitions.values():
            if "properties" in definition:
                definition.setdefault("additionalProperties", False)
        self.definitions = definitions

    def operation(self, method: str, path: str) -> tuple[dict[str, Any], dict[str, str]] | None:
        """The vendored operation a request names, with its path parameters."""
        for template, methods in self.paths.items():
            pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template)
            match = re.fullmatch(pattern, path)
            if match and method.lower() in methods:
                return methods[method.lower()], match.groupdict()
        return None

    def errors(self, definition: str, body: Any) -> list[str]:
        """How `body` breaks the schema of `definition` (a name or a `$ref`)."""
        name = definition.removeprefix(_PREFIX)
        schema = {"$ref": _PREFIX + name, "definitions": self.definitions}
        return sorted(
            f"{name} {'/'.join(str(part) for part in error.absolute_path)}: {error.message}"
            for error in Draft4Validator(schema).iter_errors(body)
        )


@dataclass(frozen=True)
class Exchange:
    """One request and its answer. `schema` is the definition the response was held to."""

    method: str
    path: str
    query: dict[str, str]
    operation: str
    request: Any
    status: int
    schema: str
    response: Any


@dataclass
class FakeCluster:
    namespace: str = "lanes"
    token: str = "cluster-token"
    contract: Contract = field(default_factory=Contract)
    objects: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    exchanges: list[Exchange] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    # Reads of a Secret that asked for more than its metadata.
    secret_data_reads: int = 0
    # Scripted refusals: (method, resource) -> HTTP status, answered instead of acting.
    refuse: dict[tuple[str, str], int] = field(default_factory=dict)
    url: str = ""

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._serial = 0
        self._server: ThreadingHTTPServer | None = None

    # -- serving -------------------------------------------------------------------------

    def __enter__(self) -> FakeCluster:
        cluster = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                status, body = cluster.handle(self.command, self.path, dict(self.headers), raw)
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = _serve

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=10)

    # -- the API -------------------------------------------------------------------------

    def _status(self, code: int, reason: str, message: str = "") -> tuple[int, dict[str, Any]]:
        success = code < 400
        return code, {
            "kind": "Status",
            "apiVersion": "v1",
            "metadata": {},
            "status": "Success" if success else "Failure",
            "message": message,
            "reason": reason,
            "code": code,
        }

    def handle(
        self, method: str, target: str, headers: dict[str, str], raw: bytes
    ) -> tuple[int, dict[str, Any]]:
        with self._lock:
            headers = {name.title(): value for name, value in headers.items()}
            split = urllib.parse.urlsplit(target)
            query = dict(urllib.parse.parse_qsl(split.query, keep_blank_values=True))
            try:
                request = json.loads(raw) if raw else None
            except ValueError:
                request = raw.decode(errors="replace")
            found = self.contract.operation(method, split.path)
            schema = STATUS
            if headers.get("Authorization") != f"Bearer {self.token}":
                status, body = self._status(401, "Unauthorized", "Unauthorized")
            elif found is None:
                self.violations.append(f"{method} {split.path} is not a vendored operation")
                status, body = self._status(404, "NotFound", "no such operation")
            else:
                operation, where = found
                status, body = self._operate(method, operation, where, query, headers, request)
                if status < 300:
                    schema = operation["responses"][str(status)]["schema"]["$ref"]
                    if body.get("kind") == PARTIAL:
                        schema = PARTIAL
                    schema = schema.removeprefix(_PREFIX)
            for error in self.contract.errors(schema, body):
                self.violations.append(f"response to {method} {split.path}: {error}")
            name = found[0]["operationId"] if found else ""
            self.exchanges.append(
                Exchange(method, split.path, query, name, request, status, schema, body)
            )
            return status, body

    def _operate(
        self,
        method: str,
        operation: dict[str, Any],
        where: dict[str, str],
        query: dict[str, str],
        headers: dict[str, str],
        request: Any,
    ) -> tuple[int, dict[str, Any]]:
        what = f"{method} {operation['operationId']}"
        parameters = operation["parameters"]
        allowed = {p["name"] for p in parameters if p["in"] == "query"}
        if set(query) - allowed:
            self.violations.append(f"{what}: undocumented query {sorted(set(query) - allowed)}")
            return self._status(400, "BadRequest", "unknown query parameter")
        body_schema = next((p["schema"]["$ref"] for p in parameters if p["in"] == "body"), None)
        if request is not None:
            consumes = operation.get("consumes") or ["*/*"]
            accepted = ["application/json"] if consumes == ["*/*"] else consumes
            if headers.get("Content-Type", "").split(";")[0].strip() not in accepted:
                self.violations.append(f"{what}: Content-Type {headers.get('Content-Type')!r}")
                return self._status(415, "UnsupportedMediaType", "unsupported media type")
        if request is not None or method == "POST":
            errors = (
                self.contract.errors(body_schema, request) if body_schema else ["a body was sent"]
            )
            if errors:
                self.violations.append(f"{what}: request body: {errors}")
                return self._status(422, "Invalid", "; ".join(errors))
        if where["namespace"] != self.namespace:
            return self._status(404, "NotFound", "no such namespace")
        resource = operation["operationId"].rsplit("Namespaced", 1)[1].lower()  # job, secret...
        if (method, resource) in self.refuse:
            return self._status(self.refuse[(method, resource)], "Forbidden", "refused by script")
        name = where.get("name", "")
        if method == "POST":
            return self._create(resource, request)
        if operation["operationId"].startswith("list"):
            return 200, self._list(resource, query.get("labelSelector", ""))
        current = self.objects.get((resource, name))
        if current is None:
            return self._status(404, "NotFound", f'{resource}s "{name}" not found')
        if method == "DELETE":
            orphan = (request or {}).get("propagationPolicy") == "Orphan"
            self._remove(resource, name, cascade=not orphan)
            return self._status(200, "", "")
        if method == "PATCH":
            # A JSON merge patch (RFC 7386) of a Secret, as far as the port uses one.
            merged = copy.deepcopy(current)
            merged["metadata"].setdefault("annotations", {}).update(
                (request.get("metadata") or {}).get("annotations") or {}
            )
            for key, value in (request.get("stringData") or {}).items():
                merged["data"][key] = base64.b64encode(value.encode()).decode()
            if set(request) - {"metadata", "stringData"} or self.contract.errors(
                "io.k8s.api.core.v1.Secret", merged
            ):
                self.violations.append(f"{what}: the patch is not one the fake applies")
                return self._status(422, "Invalid", "patch refused")
            self._serial += 1
            merged["metadata"]["resourceVersion"] = str(self._serial)
            self.objects[(resource, name)] = merged
            return 200, copy.deepcopy(merged)
        if resource == "secret":
            if headers.get("Accept") == METADATA_ONLY:
                return 200, {
                    "kind": PARTIAL,
                    "apiVersion": "meta.k8s.io/v1",
                    "metadata": copy.deepcopy(current["metadata"]),
                }
            self.secret_data_reads += 1
        return 200, copy.deepcopy(current)

    def _create(self, resource: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        name = (body.get("metadata") or {}).get("name", "")
        if not _DNS_LABEL.fullmatch(name):
            self.violations.append(f"{resource} name {name!r} is not a DNS label")
            return self._status(422, "Invalid", "metadata.name: not a DNS label")
        if (resource, name) in self.objects:
            return self._status(409, "AlreadyExists", f'{resource}s "{name}" already exists')
        stored = copy.deepcopy(body)
        self._serial += 1
        stored["metadata"].update(
            namespace=self.namespace,
            uid=str(uuid.uuid4()),
            resourceVersion=str(self._serial),
            creationTimestamp="2026-01-01T00:00:00Z",
        )
        if resource == "secret":
            data = dict(stored.get("data") or {})
            for key, value in (stored.pop("stringData", None) or {}).items():
                data[key] = base64.b64encode(value.encode()).decode()
            stored["data"] = data
        self.objects[(resource, name)] = stored
        if resource == "job":
            stored["status"] = {"active": 1}
            template = stored["spec"]["template"]
            self._serial += 1
            pod_name = f"{name}-{self._serial:05d}"
            self.objects[("pod", pod_name)] = {
                "kind": "Pod",
                "apiVersion": "v1",
                "metadata": {
                    "name": pod_name,
                    "namespace": self.namespace,
                    "uid": str(uuid.uuid4()),
                    "labels": dict((template.get("metadata") or {}).get("labels") or {}),
                    "ownerReferences": [self._owner(stored)],
                },
                "spec": copy.deepcopy(template["spec"]),
                "status": {"phase": "Pending"},
            }
        return 201, copy.deepcopy(stored)

    def _owner(self, job: dict[str, Any]) -> dict[str, Any]:
        meta = job["metadata"]
        return {"apiVersion": "batch/v1", "kind": "Job", "name": meta["name"], "uid": meta["uid"]}

    def _list(self, resource: str, selector: str) -> dict[str, Any]:
        wanted = dict(part.split("=", 1) for part in selector.split(",") if "=" in part)
        if selector and (len(wanted) != len(selector.split(",")) or "!" in selector):
            self.violations.append(f"label selector {selector!r} is not key=value pairs")
        items = [
            copy.deepcopy(found)
            for (kind, _), found in sorted(self.objects.items())
            if kind == resource
            and all((found["metadata"].get("labels") or {}).get(k) == v for k, v in wanted.items())
        ]
        kind = {"pod": "PodList", "job": "JobList"}[resource]
        version = "v1" if resource == "pod" else "batch/v1"
        return {"kind": kind, "apiVersion": version, "metadata": {}, "items": items}

    def _remove(self, resource: str, name: str, *, cascade: bool = True) -> None:
        gone = self.objects.pop((resource, name), None)
        if gone is None or not cascade:
            return
        for (kind, other), owned in list(self.objects.items()):
            owners = owned["metadata"].get("ownerReferences") or ()
            if any(owner["uid"] == gone["metadata"]["uid"] for owner in owners):
                self._remove(kind, other)

    # -- the test's hands ----------------------------------------------------------------

    def names(self, resource: str) -> list[str]:
        with self._lock:
            return sorted(name for kind, name in self.objects if kind == resource)

    def get(self, resource: str, name: str) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.objects[(resource, name)])

    def secret_value(self, name: str, key: str) -> str:
        return base64.b64decode(self.get("secret", name)["data"][key]).decode()

    def add_secret(self, name: str, data: dict[str, str]) -> None:
        """A Secret that was in the namespace before any Job: one a lane declares."""
        with self._lock:
            encoded = {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}
            self.objects[("secret", name)] = {
                "kind": "Secret",
                "apiVersion": "v1",
                "metadata": {"name": name, "namespace": self.namespace, "uid": str(uuid.uuid4())},
                "type": "Opaque",
                "data": encoded,
            }

    def _pod_of(self, job: str) -> dict[str, Any]:
        uid = self.objects[("job", job)]["metadata"]["uid"]
        return next(
            pod
            for (kind, _), pod in self.objects.items()
            if kind == "pod" and pod["metadata"]["ownerReferences"][0]["uid"] == uid
        )

    def unstartable(self, job: str) -> list[str]:
        """Why the Job's pod could not start: what it mounts or reads that is not there."""
        with self._lock:
            spec = self._pod_of(job)["spec"]
            missing: list[str] = []
            for volume in spec.get("volumes") or ():
                if "configMap" in volume and ("configmap", volume["configMap"]["name"]) not in (
                    self.objects
                ):
                    missing.append(f"configmap {volume['configMap']['name']}")
                if "secret" in volume and ("secret", volume["secret"]["secretName"]) not in (
                    self.objects
                ):
                    missing.append(f"secret {volume['secret']['secretName']}")
            for container in [*spec.get("initContainers", ()), *spec["containers"]]:
                for variable in container.get("env") or ():
                    ref = (variable.get("valueFrom") or {}).get("secretKeyRef")
                    if ref and ref["key"] not in self.objects.get(("secret", ref["name"]), {}).get(
                        "data", {}
                    ):
                        missing.append(f"secret {ref['name']} key {ref['key']}")
            return missing

    def finish(self, job: str, message: str, exit_code: int = 0, container: str = "push") -> None:
        """The Job's pod ran: `container` ended with this exit status and termination message,
        the others with success and none.

        As the kubelet does, the message is cut at 4096 bytes. A pod that mounts something
        that does not exist never starts, so finishing it is a mistake of the test's subject.
        """
        with self._lock:
            assert not self.unstartable(job), f"the pod cannot start: {self.unstartable(job)}"
            pod = self._pod_of(job)
            names = [made["name"] for made in pod["spec"]["containers"]]
            assert container in names, f"the pod has no container {container}: {names}"
            cut = message.encode()[:4096].decode(errors="ignore")

            def ended(made: dict[str, Any]) -> dict[str, Any]:
                code = exit_code if made["name"] == container else 0
                terminated = {"exitCode": code, "reason": "Completed" if code == 0 else "Error"}
                if made["name"] == container:
                    terminated["message"] = cut
                return {
                    "name": made["name"],
                    "image": made["image"],
                    "imageID": made["image"],
                    "ready": False,
                    "restartCount": 0,
                    "state": {"terminated": terminated},
                }

            pod["status"] = {
                "phase": "Succeeded" if exit_code == 0 else "Failed",
                "initContainerStatuses": [
                    ended(made) for made in pod["spec"].get("initContainers", ())
                ],
                "containerStatuses": [ended(made) for made in pod["spec"]["containers"]],
            }
            done = {"type": "Complete", "status": "True"}
            failed = {"type": "Failed", "status": "True", "reason": "BackoffLimitExceeded"}
            self.objects[("job", job)]["status"] = (
                {"succeeded": 1, "conditions": [done]}
                if exit_code == 0
                else {"failed": 1, "conditions": [failed]}
            )

    def fail(self, job: str, reason: str = "DeadlineExceeded") -> None:
        """The Job failed without its worker reporting; its pods are gone."""
        with self._lock:
            uid = self.objects[("job", job)]["metadata"]["uid"]
            self.objects.pop(("pod", self._pod_of(job)["metadata"]["name"]))
            self.objects[("job", job)]["status"] = {
                "failed": 1,
                "conditions": [{"type": "Failed", "status": "True", "reason": reason}],
            }
            assert self.objects[("job", job)]["metadata"]["uid"] == uid

    def vanish(self, job: str) -> None:
        """The Job is gone with its pods (a node was lost, someone deleted it), but what it
        owned by reference is still there: the garbage collector has not come yet."""
        with self._lock:
            self.objects.pop(("pod", self._pod_of(job)["metadata"]["name"]))
            self.objects.pop(("job", job))
