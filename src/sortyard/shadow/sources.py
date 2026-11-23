"""Read-only input adapters: the production conductor's input path, replicated (corpus M1.9).

Each adapter produces a ``QueueSnapshot`` and nothing else. They are read-only by
construction: every network read goes through ``ReadOnlyHttp``, which refuses any method but
GET, and files are opened for reading only. The shadow therefore needs only read credentials
(a read-only Plane API key; a read-only mount of the lane registry) — and holds nothing that
could claim, move, comment on or merge anything.

- ``SnapshotSource`` — board views (see ``board``) from a file, a directory or an http(s)
  URL: drive.py's board view as exported by the production control plane, or any equivalent.
  To record *every* production pass the location is a **pass feed** that retains passes the
  shadow has not read yet: ``{"passes": [board view, ...]}`` (or a JSON list), oldest first,
  or a directory with one board-view ``*.json`` per pass (recorded in file-name order). Each
  pass in a feed names its ``production_pass_id``; the shadow records every one it has not
  recorded before, however many arrived since its last read. A single board view still works
  but only observes the pass that is current when it is read.
- ``PlaneSource`` — the board straight from Plane's REST API (what plane_sync and drive.py
  read), joined with the conductor's lane registry (``products.json`` of the
  ``conductor-config`` ConfigMap) and, optionally, the task_ready gating output. It is
  triggered by the production conductor's **pass log**, which retains, per pass, the inputs
  that pass read: each entry is ``{"production_pass_id": ..., "inputs": {"issues":
  {<project id>: [Plane issue rows]}, "gating": {task_ready output}}}`` (``inputs`` may
  instead be the file path or URL of that document). Every new pass is replayed from its own
  retained inputs — through the same Plane-to-board translation as a live read — and
  recorded under its id, however many passes arrived since the last poll. Plane only shows
  the board as it is *now*, so a pass without retained inputs can be read live only while it
  is the newest pass; an older one is refused (nothing is recorded that poll) rather than
  decided against a board it never saw.

HTTP redirects never carry a credential to another origin and never downgrade https to
http: ``ReadOnlyHttp`` refuses such redirects instead of following them.
"""

from __future__ import annotations

import datetime
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import IO, Any, Protocol

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


@dataclass(frozen=True)
class Pending:
    """What one poll of the input path yields: the production passes not recorded yet, oldest
    first, each to be decided and recorded."""

    snapshots: list[QueueSnapshot] = field(default_factory=list)


class Source(Protocol):
    def read(self) -> QueueSnapshot: ...

    def pending(self, is_recorded: Callable[[str], bool]) -> Pending: ...


def now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# Request headers that carry a credential: never sent to an origin other than the one the
# caller addressed.
CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key"})


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    try:
        port = parts.port
    except ValueError as exc:
        raise SourceError(f"{url}: {exc}") from exc
    return scheme, (parts.hostname or "").lower(), port or {"http": 80, "https": 443}.get(scheme)


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if it neither leaks a credential nor downgrades the transport.

    urllib's default handler copies every request header onto the redirected request,
    whatever its destination; this one refuses (``SourceError``) a redirect that
    - leaves http(s) altogether,
    - goes from https to plain http (credential or not: the read would no longer be
      authenticated by TLS), or
    - goes to another origin (scheme, host, port) while the request carries a credential.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        old, new = _origin(req.full_url), _origin(newurl)
        refusal = None
        if new[0] not in ("http", "https"):
            refusal = f"redirect to a non-http(s) URL {newurl}"
        elif old[0] == "https" and new[0] != "https":
            refusal = f"redirect downgrades https to http ({newurl})"
        elif new != old and any(k.lower() in CREDENTIAL_HEADERS for k, _ in req.header_items()):
            refusal = f"redirect would send the credential to another origin ({newurl})"
        if refusal:
            fp.close()
            raise SourceError(f"GET {req.full_url}: refused {code} {refusal}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ReadOnlyHttp:
    """The only HTTP client the shadow has: GET or nothing; redirects guarded."""

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_GuardedRedirects())

    def request(self, method: str, url: str, headers: Mapping[str, str] | None = None) -> bytes:
        if method != "GET":
            raise ReadOnlyViolation(f"the shadow conductor is read-only; refused {method} {url}")
        req = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
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


def _is_url(location: str) -> bool:
    return urllib.parse.urlsplit(location).scheme in ("http", "https")


def _feed_entries(doc: Any) -> list[Any] | None:
    """The passes of a pass feed (``{"passes": [...]}`` or a list), or None for a single
    board view."""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, Mapping) and isinstance(doc.get("passes"), list):
        return list(doc["passes"])
    return None


class SnapshotSource:
    """Board views from a file path, a directory or an http(s) URL (module docstring).

    ``gating``, when given, overrides a single board view's own task_ready section. It is
    refused for a pass feed: today's gating output joined onto earlier passes would record
    decisions production never faced — each pass in a feed carries its own gating.
    """

    def __init__(self, location: str, gating: str | None = None) -> None:
        self.location = location
        self.gating = gating
        self.http = ReadOnlyHttp()
        # Whether the last read was a single board view (only the current pass observable).
        self.single_view = False

    def _documents(self) -> tuple[list[Any], bool]:
        if not _is_url(self.location) and os.path.isdir(self.location):
            names = sorted(n for n in os.listdir(self.location) if n.endswith(".json"))
            return [read_json(os.path.join(self.location, n)) for n in names], True
        doc = read_json(self.location, self.http)
        entries = _feed_entries(doc)
        return ([doc], False) if entries is None else (entries, True)

    def read_passes(self) -> list[QueueSnapshot]:
        """Every pass the location currently holds, oldest first."""
        docs, feed = self._documents()
        self.single_view = not feed
        if feed and self.gating:
            raise SourceError(
                f"{self.location}: a pass feed carries each pass's own gating;"
                " SORTYARD_SHADOW_GATING applies to a single board view only"
            )
        gating = parse_gating(read_json(self.gating, self.http)) if self.gating else None
        snaps = []
        for n, doc in enumerate(docs):
            where = f"{self.location} pass {n}" if feed else self.location
            if isinstance(doc, dict):
                doc.setdefault("taken_at", now())
                doc.setdefault("source", self.location)
            try:
                snap = QueueSnapshot.from_dict(doc)
            except SnapshotError as exc:
                raise SourceError(f"{where}: {exc}") from exc
            if feed and not snap.production_pass_id:
                raise SourceError(f"{where}: every pass in a pass feed needs a production_pass_id")
            if gating is not None:
                snap = QueueSnapshot.build(
                    taken_at=snap.taken_at,
                    items=snap.items,
                    lanes=snap.lanes,
                    gating=gating,
                    source=snap.source,
                    production_pass_id=snap.production_pass_id,
                )
            snaps.append(snap)
        return snaps

    def read(self) -> QueueSnapshot:
        """The newest pass."""
        snaps = self.read_passes()
        if not snaps:
            raise SourceError(f"{self.location}: no passes")
        return snaps[-1]

    def pending(self, is_recorded: Callable[[str], bool]) -> Pending:
        """Every pass not recorded yet — all unread passes of a feed, in order."""
        return Pending(
            snapshots=[
                s
                for s in self.read_passes()
                if not (s.production_pass_id and is_recorded(s.production_pass_id))
            ]
        )


@dataclass(frozen=True)
class PassEntry:
    """One production pass in the pass log: its id and the inputs it retained (an inline
    ``{"issues": ..., "gating": ...}`` document, its location, or None)."""

    production_pass_id: str
    inputs: Any = None


def parse_pass_log(doc: Any) -> list[PassEntry]:
    """The production conductor's pass log, oldest first: ``{"passes": [...]}`` or a list,
    each entry a pass id or ``{"production_pass_id": ..., "inputs": ...}``."""
    entries = _feed_entries(doc)
    if entries is None:
        raise SourceError('the production pass log must be {"passes": [...]} or a JSON list')
    passes: dict[str, PassEntry] = {}
    for entry in entries:
        pid = entry.get("production_pass_id") if isinstance(entry, Mapping) else entry
        if not isinstance(pid, str) or not pid:
            raise SourceError(f"production pass log: no pass id in {entry!r}")
        inputs = entry.get("inputs") if isinstance(entry, Mapping) else None
        if inputs is not None and not isinstance(inputs, (str, Mapping)):
            raise SourceError(f"production pass log: {pid}: inputs must be an object or location")
        passes.setdefault(pid, PassEntry(pid, inputs))
    return list(passes.values())


def _results(doc: Any) -> list[Mapping[str, Any]]:
    rows = doc.get("results") if isinstance(doc, Mapping) else doc
    if not isinstance(rows, list):
        raise SourceError(f"unexpected Plane response: {str(doc)[:200]}")
    return [r for r in rows if isinstance(r, Mapping)]


class PlaneSource:
    """The board from Plane's REST API (``X-API-Key``; GET only), with the lane registry and
    optional task_ready gating output joined in; one snapshot per new pass in the production
    conductor's pass log (``passes``, file path or URL), replayed from the inputs that pass
    retained (module docstring)."""

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
        passes: str | None = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.workspace = workspace_slug
        self.project_ids = list(project_ids)
        self.headers = {"X-API-Key": api_key, "Accept": "application/json"}
        self.lanes_path = lanes_path
        self.gating = gating
        self.passes = passes
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

    def _project_meta(self, project_id: str) -> tuple[str, dict[str, Any], dict[str, str]]:
        """A project's board identifier, states by id and label names by id."""
        project = self._get(f"projects/{project_id}/")
        identifier = str(project.get("identifier") or "") if isinstance(project, Mapping) else ""
        if not identifier:
            raise SourceError(f"Plane project {project_id}: no identifier")
        states = {str(s["id"]): s for s in _results(self._get(f"projects/{project_id}/states/"))}
        labels = {
            str(lb["id"]): str(lb.get("name") or lb["id"])
            for lb in _results(self._get(f"projects/{project_id}/labels/"))
        }
        return identifier, states, labels

    @staticmethod
    def _board_items(
        meta: tuple[str, Mapping[str, Any], Mapping[str, str]],
        issues: Sequence[Mapping[str, Any]],
    ) -> list[BoardItem]:
        identifier, states, labels = meta
        items = []
        for issue in issues:
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

    def _snapshot(
        self,
        *,
        items: list[BoardItem],
        lanes: list[Lane],
        gating: dict[str, Gate],
        production_pass_id: str | None,
        taken_at: str,
    ) -> QueueSnapshot:
        try:
            return QueueSnapshot.build(
                taken_at=taken_at,
                items=items,
                lanes=lanes,
                gating=gating,
                source=f"plane {self.base} {self.workspace}",
                production_pass_id=production_pass_id,
            )
        except SnapshotError as exc:
            raise SourceError(str(exc)) from exc

    def _live(
        self,
        production_pass_id: str | None,
        meta: Mapping[str, tuple[str, Mapping[str, Any], Mapping[str, str]]],
        lanes: list[Lane],
    ) -> QueueSnapshot:
        """The board as it is now (a live read)."""
        taken_at = now()
        items = [
            item
            for pid in self.project_ids
            for item in self._board_items(meta[pid], self._issues(pid))
        ]
        return self._snapshot(
            items=items,
            lanes=lanes,
            gating=parse_gating(read_json(self.gating, self.http)) if self.gating else {},
            production_pass_id=production_pass_id,
            taken_at=taken_at,
        )

    def read(self, production_pass_id: str | None = None) -> QueueSnapshot:
        """The board as it is now (a live read)."""
        meta = {pid: self._project_meta(pid) for pid in self.project_ids}
        return self._live(
            production_pass_id, meta, parse_lanes(read_json(self.lanes_path, self.http))
        )

    def _replay(
        self,
        entry: PassEntry,
        meta: Mapping[str, tuple[str, Mapping[str, Any], Mapping[str, str]]],
        lanes: list[Lane],
    ) -> QueueSnapshot:
        """A pass decided from the inputs it retained in the pass log."""
        pid = entry.production_pass_id
        doc = read_json(entry.inputs, self.http) if isinstance(entry.inputs, str) else entry.inputs
        issues = doc.get("issues") if isinstance(doc, Mapping) else None
        if not isinstance(issues, Mapping):
            raise SourceError(f"production pass {pid}: retained inputs have no issues by project")
        items = []
        for project_id in self.project_ids:
            rows = issues.get(project_id)
            if not isinstance(rows, list):
                raise SourceError(f"production pass {pid}: no retained issues for {project_id}")
            items += self._board_items(
                meta[project_id], [r for r in rows if isinstance(r, Mapping)]
            )
        if "gating" in doc:
            gating = parse_gating(doc["gating"])
        elif self.gating:
            # Today's gating output joined onto an earlier pass would record decisions that
            # pass never faced.
            raise SourceError(f"production pass {pid}: retained inputs have no gating output")
        else:
            gating = {}
        return self._snapshot(
            items=items,
            lanes=lanes,
            gating=gating,
            production_pass_id=pid,
            taken_at=str(doc.get("taken_at") or now()),
        )

    def pending(self, is_recorded: Callable[[str], bool]) -> Pending:
        """Every production pass not recorded yet, oldest first, each from its own inputs."""
        if not self.passes:
            raise SourceError("plane source: the production pass log (passes) is required")
        log = parse_pass_log(read_json(self.passes, self.http))
        new = [e for e in log if not is_recorded(e.production_pass_id)]
        if not new:
            return Pending()
        for entry in new[:-1]:
            if entry.inputs is None:
                raise SourceError(
                    f"production pass {entry.production_pass_id} retained no inputs in the pass"
                    " log and is no longer the newest pass: its board cannot be replayed"
                )
        lanes = parse_lanes(read_json(self.lanes_path, self.http))
        meta = {pid: self._project_meta(pid) for pid in self.project_ids}
        return Pending(
            snapshots=[
                self._live(entry.production_pass_id, meta, lanes)
                if entry.inputs is None  # the newest pass: the board now is the board it read
                else self._replay(entry, meta, lanes)
                for entry in new
            ]
        )
