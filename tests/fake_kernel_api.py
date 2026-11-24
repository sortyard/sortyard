"""A strict fake of the kernel's item operations of the Sortyard API, served over real HTTP.

It stands in for the API in tests of a client of it (`sortyard.services.red_main`). It serves
the five item operations of `spec/openapi.json` (admitItem, getProjectQueue, getItem,
getItemTimeline, requestItemChange) from items held in memory, and is held to that contract:

- every request is matched to an operation of the spec; a call to a path or method the spec
  does not document, or to an operation this fake does not serve, is refused and kept in
  `violations`, and so is a request body the documented schema refuses and a token whose role
  the operation's `x-sortyard-roles` does not list;
- every reply is checked before it is sent: its status must be one the operation declares,
  and its body must match the declared schema (the §3 JSON Schemas by `$ref`), else it is kept
  in `violations`.

Its behaviour is what the operations' descriptions say: admitting an id again with the same
content answers 200 and changes nothing, with other content 409, and an id that was withdrawn
422 (`ended-item`); the queue lists the items that are not terminal, oldest first; a request
is put on the item's timeline as a transition into the decision state and back, and the answer
`withdraw` sent by an operator ends the item withdrawn (the shipped decision policy). What the
kernel does to an item (`move`, `merge`) is the test's to arrange.
"""

from __future__ import annotations

import json
import pathlib
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

import jsonschema  # type: ignore[import-untyped]
from referencing import Registry
from referencing.jsonschema import DRAFT202012

SPEC = pathlib.Path(__file__).resolve().parent.parent / "spec"
OPENAPI_ID = "https://sortyard.ai/spec/openapi.json"
OPENAPI = json.loads((SPEC / "openapi.json").read_text())
SERVED = ("admitItem", "getProjectQueue", "getItem", "getItemTimeline", "requestItemChange")
WHEN = "2026-11-24T20:00:00Z"
PROBLEM = "application/problem+json"


def _pointer(*parts: str) -> str:
    return "/".join(p.replace("~", "~0").replace("/", "~1") for p in parts)


def _registry() -> Registry[Any]:
    resources = [(OPENAPI_ID, OPENAPI)]
    for path in sorted(SPEC.glob("*.schema.json")):
        document = json.loads(path.read_text())
        resources.append((document["$id"], document))
    return Registry().with_resources(
        (uri, DRAFT202012.create_resource(doc)) for uri, doc in resources
    )


@dataclass(frozen=True)
class Operation:
    id: str
    method: str
    template: str
    pattern: re.Pattern[str]
    spec: Mapping[str, Any]


class Contract:
    """spec/openapi.json as request and response validators."""

    def __init__(self) -> None:
        self.registry = _registry()
        self.operations: list[Operation] = []
        for template, item in OPENAPI["paths"].items():
            pattern = re.compile(re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template))
            for method, op in item.items():
                if method in ("get", "post", "patch", "put", "delete"):
                    self.operations.append(
                        Operation(op["operationId"], method.upper(), template, pattern, op)
                    )

    def find(self, method: str, path: str) -> tuple[Operation, dict[str, str]] | None:
        for operation in self.operations:
            matched = operation.pattern.fullmatch(path)
            if matched and operation.method == method:
                return operation, {k: unquote(v) for k, v in matched.groupdict().items()}
        return None

    def operation(self, operation_id: str) -> Operation:
        return next(each for each in self.operations if each.id == operation_id)

    def _errors(self, ref: str, value: Any) -> list[str]:
        validator = jsonschema.Draft202012Validator({"$ref": ref}, registry=self.registry)
        return sorted(
            f"{'/'.join(str(p) for p in error.absolute_path) or '.'}: {error.message}"
            for error in validator.iter_errors(value)
        )

    def request_errors(self, operation: Operation, body: Any) -> list[str]:
        declared = operation.spec.get("requestBody")
        if declared is None:
            return [] if body is None else ["a body where none is documented"]
        if body is None:
            return ["no body where one is required"] if declared.get("required") else []
        base = _pointer(operation.template, operation.method.lower(), "requestBody")
        ref = f"{OPENAPI_ID}#/paths/{base}/content/application~1json/schema"
        return [f"body {error}" for error in self._errors(ref, body)]

    def response_errors(
        self, operation: Operation, status: int, media: str, payload: Any
    ) -> list[str]:
        declared = operation.spec["responses"].get(str(status))
        if declared is None:
            return [f"status {status} is not declared"]
        base = f"{OPENAPI_ID}#/paths/" + _pointer(
            operation.template, operation.method.lower(), "responses", str(status)
        )
        if "$ref" in declared:
            base = f"{OPENAPI_ID}{declared['$ref']}"
            declared = OPENAPI["components"]["responses"][declared["$ref"].rsplit("/", 1)[1]]
        content = declared.get("content")
        if not content:
            return [] if payload is None else ["a body where none is declared"]
        if media not in content:
            return [f"media type {media} is not declared for {status}"]
        return self._errors(f"{base}/{_pointer('content', media, 'schema')}", payload)


class Refused(Exception):
    def __init__(self, status: int, detail: str, reason: str = "") -> None:
        super().__init__(detail)
        self.status, self.detail, self.reason = status, detail, reason


@dataclass
class FakeItem:
    admitted: dict[str, Any]
    position: int
    state: str | None = "admitted"
    state_kind: str | None = "queue"
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Seen:
    operation: str
    method: str
    path: str
    body: Any
    role: str


class FakeKernelApi:
    def __init__(self, workspace: str, lanes: Mapping[str, set[str]]) -> None:
        self.contract = Contract()
        self.workspace = workspace
        self.lanes = {name: set(repos) for name, repos in lanes.items()}  # lane -> repositories
        self.tokens: dict[str, tuple[str, str | None]] = {}  # token -> (role, project)
        self.items: dict[str, FakeItem] = {}
        self.requests: list[Seen] = []
        self.replies: list[tuple[str, int, Any]] = []
        self.violations: list[str] = []
        # Changes a reply before it is checked and sent: how a test makes the fake wrong.
        self.mutate: Callable[[str, Any], Any] | None = None
        self.url = "http://fake.invalid"
        self._lock = threading.Lock()
        self._seq = 0

    # What a test arranges.

    def token(self, role: str = "operator", project: str | None = None) -> str:
        value = f"sy_fake_{len(self.tokens)}"
        self.tokens[value] = (role, project)
        return value

    def move(self, item: str, state: str, kind: str = "work") -> None:
        """The kernel takes the item to a state."""
        self._transition(self.items[item], "outcome", state, kind, {})

    def merge(self, item: str) -> None:
        self.move(item, "merged", "terminal")

    def verify(self) -> None:
        assert not self.violations, self.violations

    def seen(self, operation: str) -> list[Seen]:
        return [each for each in self.requests if each.operation == operation]

    def open_ids(self) -> list[str]:
        return [i for i, item in self.items.items() if item.state_kind != "terminal"]

    # The API.

    def handle(
        self, method: str, target: str, headers: Mapping[str, str], raw: bytes
    ) -> tuple[int, str, Any]:
        with self._lock:
            path = urlsplit(target).path
            found = self.contract.find(method, path)
            if found is None:
                self.violations.append(f"undocumented call: {method} {path}")
                return 404, PROBLEM, self._problem(404, "no such operation")
            operation, params = found
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = raw.decode(errors="replace")
            role = ""
            try:
                if operation.id not in SERVED:
                    self.violations.append(f"unserved operation: {operation.id}")
                    raise Refused(404, f"{operation.id} is not served by this fake")
                scheme, _, credential = headers.get("authorization", "").partition(" ")
                if scheme != "Bearer" or credential not in self.tokens:
                    raise Refused(401, "no valid bearer token")
                role, project = self.tokens[credential]
                if params["workspace_id"] != self.workspace:
                    raise Refused(404, "no such workspace")
                if role not in operation.spec["x-sortyard-roles"]:
                    self.violations.append(f"{operation.id}: role {role} is not allowed")
                    raise Refused(403, f"role {role} may not {operation.id}")
                problems = self.contract.request_errors(operation, body)
                if problems:
                    self.violations += [f"{operation.id}: {each}" for each in problems]
                    raise Refused(400, "; ".join(problems))
                handler = getattr(self, "_" + re.sub(r"([A-Z])", r"_\1", operation.id).lower())
                status, payload = handler(params, body, role, project)
                media = "application/json"
            except Refused as refused:
                status, media = refused.status, PROBLEM
                payload = self._problem(refused.status, refused.detail, refused.reason)
            self.requests.append(Seen(operation.id, method, path, body, role))
            if self.mutate is not None:
                payload = self.mutate(operation.id, payload)
            self.violations += [
                f"{operation.id} {status} reply: {problem}"
                for problem in self.contract.response_errors(operation, status, media, payload)
            ]
            self.replies.append((operation.id, status, payload))
            return status, media, payload

    def _problem(self, status: int, detail: str, reason: str = "") -> dict[str, Any]:
        found: dict[str, Any] = {"type": "about:blank", "title": "Refused", "status": status}
        found["detail"] = detail
        if reason:
            found["reason_code"] = reason
        return found

    def _in_scope(self, project: str | None, item: FakeItem) -> None:
        if project is not None and item.admitted["project_id"] != project:
            raise Refused(403, "the item is outside the token's project")

    def _item(self, params: Mapping[str, str], project: str | None) -> FakeItem:
        item = self.items.get(params["item_id"])
        if item is None:
            raise Refused(404, f"no item {params['item_id']!r}")
        self._in_scope(project, item)
        return item

    def _transition(
        self,
        item: FakeItem,
        cause: str,
        state: str,
        kind: str,
        facts: Mapping[str, Any],
    ) -> None:
        self._seq += 1
        item.events.append(
            {
                "id": f"evt-{self._seq}",
                "workspace_id": self.workspace,
                "seq": self._seq,
                "ts": WHEN,
                "actor": {"kind": "system", "id": "sortyard-kernel"},
                "object": {"kind": "item", "id": item.admitted["id"]},
                "transition": {"name": cause, "from": item.state, "to": state},
                "facts": {"cause": cause, **facts},
                "refs": [],
            }
        )
        item.state, item.state_kind = state, kind

    def _admitted(self, item: FakeItem) -> dict[str, Any]:
        body = item.admitted
        return {
            "id": body["id"],
            "project_id": body["project_id"],
            "lane": body["lane"],
            "repository": body["repository"],
            "base": body.get("base", "main"),
            "needs": [f"repository:{body['repository']}", *body.get("needs", [])],
            "blocked_by": sorted(set(body.get("blocked_by", []))),
            "workflow_id": f"item/{self.workspace}/{body['id']}",
        }

    def _admit_item(
        self, params: Any, body: dict[str, Any], role: str, project: str | None
    ) -> tuple[int, Any]:
        if project is not None and body["project_id"] != project:
            raise Refused(403, "the project is outside the token's scope")
        reasons = []
        spec = body["spec"]
        if not isinstance(spec.get("outcome"), str) or not spec["outcome"].strip():
            reasons.append("no-outcome: the spec states no outcome")
        tests = spec.get("acceptance")
        if (
            not isinstance(tests, list)
            or not tests
            or not all(isinstance(t, dict) and t.get("test") and t.get("name") for t in tests)
        ):
            reasons.append("no-acceptance-test: the spec names no acceptance test")
        if body["repository"] not in self.lanes.get(body["lane"], set()):
            reasons.append(f"undeclared-need: lane {body['lane']!r} lacks {body['repository']}")
        if reasons:
            raise Refused(422, "; ".join(reasons), "admission")
        known = self.items.get(body["id"])
        if known is not None:
            if known.state == "withdrawn":
                raise Refused(422, f"ended-item: {body['id']!r} is withdrawn", "admission")
            if known.admitted != body:
                raise Refused(409, "admitted before with other content", "different_item")
            return 200, self._admitted(known)
        item = self.items[body["id"]] = FakeItem(dict(body), len(self.items))
        self._transition(item, "start", "admitted", "queue", {})
        return 201, self._admitted(item)

    def _get_project_queue(
        self, params: Mapping[str, str], body: Any, role: str, project: str | None
    ) -> tuple[int, Any]:
        if project is not None and params["project_id"] != project:
            raise Refused(403, "the project is outside the token's scope")
        listed = sorted(
            (
                item
                for item in self.items.values()
                if item.admitted["project_id"] == params["project_id"]
                and item.state_kind != "terminal"
            ),
            key=lambda item: item.position,
        )
        return 200, {
            "items": [
                {
                    "id": item.admitted["id"],
                    "title": item.admitted["title"],
                    "milestone_id": None,
                    "risk_tier": item.admitted.get("risk_tier", "medium"),
                    "state": item.state,
                    "owner": None,
                    "limit": None,
                    "reason": None,
                    "entered_at": WHEN,
                    "age_seconds": 0,
                    "blocked_by": [],
                    "ended_blockers": {},
                }
                for item in listed
            ]
        }

    def _get_item(
        self, params: Mapping[str, str], body: Any, role: str, project: str | None
    ) -> tuple[int, Any]:
        item = self._item(params, project)
        admitted = self._admitted(item)
        return 200, {
            **admitted,
            "milestone_id": None,
            "title": item.admitted["title"],
            "risk_tier": item.admitted.get("risk_tier", "medium"),
            "spec": item.admitted["spec"],
            "blocks": [],
            "state": item.state,
            "state_kind": item.state_kind,
            "owner": None,
            "limit": None,
            "reason": None,
            "entered_at": WHEN,
            "detail": {},
        }

    def _get_item_timeline(
        self, params: Mapping[str, str], body: Any, role: str, project: str | None
    ) -> tuple[int, Any]:
        return 200, {"items": list(self._item(params, project).events)}

    def _request_item_change(
        self, params: Mapping[str, str], body: dict[str, Any], role: str, project: str | None
    ) -> tuple[int, Any]:
        item = self._item(params, project)
        if item.state_kind == "terminal":
            raise Refused(409, "the item has no running workflow", "no_workflow")
        self._seq += 1
        request = {
            "id": f"req-{self._seq}",
            "answer": body["answer"],
            "reason": body["reason"],
            "by": {"kind": "operator", "id": "op", "role": role},
        }
        before, kind = item.state, item.state_kind
        assert before is not None and kind is not None
        self._transition(item, "request", "decision", "decision", {"request": request})
        if body["answer"] == "withdraw" and role == "operator":
            self._transition(item, "decision", "withdrawn", "terminal", {})
        else:
            self._transition(item, "decision", before, kind, {})
        return 202, {
            "id": request["id"],
            "item_id": item.admitted["id"],
            "answer": body["answer"],
            "reason": body["reason"],
        }


class _Handler(BaseHTTPRequestHandler):
    fake: FakeKernelApi

    def _serve(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        status, media, payload = self.fake.handle(
            self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, raw
        )
        data = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

    def log_message(self, format: str, *args: Any) -> None:
        return


@contextmanager
def serving(fake: FakeKernelApi) -> Iterator[str]:
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
