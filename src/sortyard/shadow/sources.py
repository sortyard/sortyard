"""Read-only input adapters: the production conductor's input path, replicated (corpus M1.9).

Each adapter produces a ``QueueSnapshot`` and nothing else. They are read-only by
construction: every network read goes through ``ReadOnlyHttp``, which refuses any method but
GET, and files are opened for reading only. The shadow therefore needs only read credentials
(a read-only Plane API key; a read-only mount of the lane registry) — and holds nothing that
could claim, move, comment on or merge anything.

- ``SnapshotSource`` — a board-view document (see ``board``) from a file or an http(s) URL:
  drive.py's board view as exported by the production control plane, or any equivalent.
- ``PlaneSource`` — the board straight from Plane's REST API (what plane_sync and drive.py
  read), joined with the conductor's lane registry (``products.json`` of the
  ``conductor-config`` ConfigMap) and, optionally, the task_ready gating output.
"""

from __future__ import annotations

import datetime
import json
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from sortyard.shadow.board import (
    PRIORITIES,
    STATE_GROUPS,
    BoardItem,
    Gate,
    Lane,
    QueueSnapshot,
    SnapshotError,
    parse_depends,
)


class ReadOnlyViolation(RuntimeError):
    """Something tried to send a request that could change the input path."""


class SourceError(RuntimeError):
    """The input path could not be read (unreachable, refused, malformed)."""


class Source(Protocol):
    def read(self) -> QueueSnapshot: ...


def now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ReadOnlyHttp:
    """The only HTTP client the shadow has: GET or nothing."""

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def request(self, method: str, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        if method != "GET":
            raise ReadOnlyViolation(f"the shadow conductor is read-only; refused {method} {url}")
        req = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body: bytes = resp.read()
                return body
        except OSError as exc:  # URLError, HTTPError, timeouts
            raise SourceError(f"GET {url}: {exc}") from exc

    def get_json(self, url: str, headers: Mapping[str, str] | None = None) -> Any:
        body = self.request("GET", url, headers)
        try:
            return json.loads(body)
        except ValueError as exc:
            raise SourceError(f"GET {url}: not JSON ({exc})") from exc


def read_json(location: str, http: ReadOnlyHttp | None = None) -> Any:
    """JSON from an http(s) URL (GET) or a local file (read-only)."""
    if urllib.parse.urlsplit(location).scheme in ("http", "https"):
        return (http or ReadOnlyHttp()).get_json(location)
    try:
        with open(location, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise SourceError(f"{location}: {exc}") from exc


def parse_gating(doc: Any) -> dict[str, Gate]:
    """task_ready output: {item id: {"ready": bool, "reason": str}} (or {item id: bool})."""
    if not isinstance(doc, Mapping):
        raise SourceError("task_ready gating output must be a JSON object keyed by item id")
    gates: dict[str, Gate] = {}
    for key, value in doc.items():
        if isinstance(value, bool):
            gates[str(key)] = Gate(ready=value)
        elif isinstance(value, Mapping):
            gates[str(key)] = Gate(bool(value.get("ready")), str(value.get("reason") or ""))
    return gates


def parse_lanes(doc: Any) -> list[Lane]:
    """The lane registry: either ``{"lanes": [{id, project, capacity}]}`` or the conductor's
    ``products.json`` — ``{product: {"lanes": N, "identifier": "ROVE", ...}}``, one lane per
    product with N slots; the board identifier defaults to the product key upper-cased."""
    if isinstance(doc, Mapping) and isinstance(doc.get("lanes"), list):
        return [Lane.from_dict(lane) for lane in doc["lanes"]]
    if not isinstance(doc, Mapping):
        raise SourceError("lane registry must be a JSON object")
    lanes = []
    for product, conf in doc.items():
        if not isinstance(conf, Mapping):
            continue
        capacity = conf.get("lanes", 1)
        if not isinstance(capacity, int) or isinstance(capacity, bool):
            capacity = len(capacity) if isinstance(capacity, list) else 1
        project = str(conf.get("identifier") or conf.get("plane_identifier") or product).upper()
        lanes.append(Lane(id=f"lane-{str(product).lower()}", project=project, capacity=capacity))
    return lanes


class SnapshotSource:
    """A board-view document (``board`` module docstring) from a file path or http(s) URL;
    ``gating``, when given, overrides the document's own task_ready section."""

    def __init__(self, location: str, gating: str | None = None) -> None:
        self.location = location
        self.gating = gating
        self.http = ReadOnlyHttp()

    def read(self) -> QueueSnapshot:
        doc = read_json(self.location, self.http)
        if isinstance(doc, dict):
            doc.setdefault("taken_at", now())
            doc.setdefault("source", self.location)
        try:
            snap = QueueSnapshot.from_dict(doc)
        except SnapshotError as exc:
            raise SourceError(f"{self.location}: {exc}") from exc
        if self.gating:
            snap = QueueSnapshot.build(
                taken_at=snap.taken_at,
                items=snap.items,
                lanes=snap.lanes,
                gating=parse_gating(read_json(self.gating, self.http)),
                source=snap.source,
                production_pass_id=snap.production_pass_id,
            )
        return snap


def _results(doc: Any) -> list[Mapping[str, Any]]:
    rows = doc.get("results") if isinstance(doc, Mapping) else doc
    if not isinstance(rows, list):
        raise SourceError(f"unexpected Plane response: {str(doc)[:200]}")
    return [r for r in rows if isinstance(r, Mapping)]


class PlaneSource:
    """The board from Plane's REST API (``X-API-Key``; GET only), with the lane registry and
    optional task_ready gating output joined in."""

    PAGE_SIZE = 100

    def __init__(
        self,
        *,
        base_url: str,
        workspace_slug: str,
        project_ids: Sequence[str],
        api_key: str,
        lanes_path: str,
        gating: str | None = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.workspace = workspace_slug
        self.project_ids = list(project_ids)
        self.headers = {"X-API-Key": api_key, "Accept": "application/json"}
        self.lanes_path = lanes_path
        self.gating = gating
        self.http = ReadOnlyHttp()

    def _get(self, path: str, query: Mapping[str, str] | None = None) -> Any:
        url = f"{self.base}/api/v1/workspaces/{self.workspace}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return self.http.get_json(url, self.headers)

    def _issues(self, project_id: str) -> list[Mapping[str, Any]]:
        issues: list[Mapping[str, Any]] = []
        query = {"per_page": str(self.PAGE_SIZE)}
        for _ in range(10_000):  # a hard stop against a pagination loop
            page = self._get(f"projects/{project_id}/issues/", query)
            issues += _results(page)
            if not (isinstance(page, Mapping) and page.get("next_page_results")):
                return issues
            query = {"per_page": str(self.PAGE_SIZE), "cursor": str(page["next_cursor"])}
        raise SourceError(f"Plane project {project_id}: pagination did not end")

    def _project_items(self, project_id: str) -> list[BoardItem]:
        project = self._get(f"projects/{project_id}/")
        identifier = str(project.get("identifier") or "") if isinstance(project, Mapping) else ""
        if not identifier:
            raise SourceError(f"Plane project {project_id}: no identifier")
        states = {str(s["id"]): s for s in _results(self._get(f"projects/{project_id}/states/"))}
        labels = {
            str(lb["id"]): str(lb.get("name") or lb["id"])
            for lb in _results(self._get(f"projects/{project_id}/labels/"))
        }
        items = []
        for issue in self._issues(project_id):
            state = states.get(str(issue.get("state")))
            if state is None or state.get("group") not in STATE_GROUPS:
                raise SourceError(f"{identifier}-{issue.get('sequence_id')}: unknown state")
            priority = str(issue.get("priority") or "none")
            text = str(issue.get("description_stripped") or issue.get("description_html") or "")
            items.append(
                BoardItem(
                    id=f"{identifier}-{issue['sequence_id']}",
                    project=identifier,
                    title=str(issue.get("name") or ""),
                    state=str(state.get("name")),
                    state_group=str(state["group"]),
                    priority=priority if priority in PRIORITIES else "none",
                    labels=tuple(sorted(labels.get(str(lb), str(lb)) for lb in issue["labels"]))
                    if isinstance(issue.get("labels"), list)
                    else (),
                    depends_on=tuple(parse_depends(text)),
                    created_at=str(issue.get("created_at") or ""),
                )
            )
        return items

    def read(self) -> QueueSnapshot:
        taken_at = now()
        items = [i for pid in self.project_ids for i in self._project_items(pid)]
        lanes = parse_lanes(read_json(self.lanes_path, self.http))
        gating = parse_gating(read_json(self.gating, self.http)) if self.gating else {}
        try:
            return QueueSnapshot.build(
                taken_at=taken_at,
                items=items,
                lanes=lanes,
                gating=gating,
                source=f"plane {self.base} {self.workspace}",
            )
        except SnapshotError as exc:
            raise SourceError(str(exc)) from exc
