"""The canonical queue snapshot: the board as the production conductor sees it, in one shape.

Every input adapter (``sources``) produces a ``QueueSnapshot``; the evaluator reads nothing
else. Its JSON form is the *board-view document* a snapshot source serves:

    {
      "taken_at": "2026-11-10T12:00:00Z",          # when the board was read
      "source": "drive.py board view",              # free text: where it came from
      "production_pass_id": "drive-2026-11-10T12:00Z",  # optional: the production pass
      "items": [{
          "id": "SORTYARD-8", "project": "SORTYARD", "title": "...",
          "state": "Todo",                          # the board state's display name
          "state_group": "unstarted",               # backlog|unstarted|started|completed|cancelled
          "priority": "high",                       # urgent|high|medium|low|none
          "labels": ["self-heal"],
          "depends_on": ["SORTYARD-6"],             # or omit and give "description"
          "description": "... Depends: SORTYARD-6 ...",
          "created_at": "2026-11-07T00:00:00Z"}],
      "lanes": [{"id": "lane-sortyard", "project": "SORTYARD", "capacity": 1}],
      "gating": {"ROVE-4": {"ready": false, "reason": "plan task T7 not ready"}}  # task_ready
    }

The content hash covers everything the decision depends on and nothing else (not
``taken_at``/``source``/``production_pass_id``), in a canonical order, so two reads of an
unchanged board hash the same — the ``queue_snapshot_hash`` of every DecisionLog entry.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

STATE_GROUPS = ("backlog", "unstarted", "started", "completed", "cancelled")
PRIORITIES = ("urgent", "high", "medium", "low", "none")

# Description-level dependencies (the HARNESS/SORTYARD board convention): a line
# "Depends: SORTYARD-6, SORTYARD-2." or "Depends on: ...". "Depends: none" means none.
_DEPENDS_LINE = re.compile(r"\bDepends(?:\s+on)?\s*:\s*([^\n]*)", re.IGNORECASE)
_ITEM_REF = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")
_TAG = re.compile(r"<[^>]+>")


class SnapshotError(ValueError):
    """A board-view document does not describe a usable snapshot."""


def parse_depends(text: str) -> list[str]:
    """The item ids named on the description's ``Depends:`` line(s), in order, deduplicated."""
    plain = html.unescape(_TAG.sub("\n", text))
    found: list[str] = []
    for line in _DEPENDS_LINE.findall(plain):
        for ref in _ITEM_REF.findall(line):
            if ref not in found:
                found.append(ref)
    return found


def _str(doc: Mapping[str, Any], key: str, default: str | None = None) -> str:
    value = doc.get(key, default)
    if not isinstance(value, str) or not value:
        raise SnapshotError(f"{key!r} must be a non-empty string, got {value!r}")
    return value


def _strs(value: Any, what: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SnapshotError(f"{what} must be a list of strings, got {value!r}")
    return tuple(value)


@dataclass(frozen=True)
class BoardItem:
    id: str
    project: str
    state: str
    state_group: str
    priority: str = "none"
    title: str = ""
    labels: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    created_at: str = ""

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> BoardItem:
        item_id = _str(doc, "id")
        group = _str(doc, "state_group")
        if group not in STATE_GROUPS:
            raise SnapshotError(f"{item_id}: state_group {group!r} not one of {STATE_GROUPS}")
        priority = doc.get("priority") or "none"
        if priority not in PRIORITIES:
            raise SnapshotError(f"{item_id}: priority {priority!r} not one of {PRIORITIES}")
        if "depends_on" in doc:
            depends = _strs(doc["depends_on"], f"{item_id}: depends_on")
        else:
            depends = tuple(parse_depends(str(doc.get("description") or "")))
        return cls(
            id=item_id,
            project=_str(doc, "project", item_id.rsplit("-", 1)[0]),
            state=_str(doc, "state"),
            state_group=group,
            priority=priority,
            title=str(doc.get("title") or ""),
            labels=tuple(sorted(_strs(doc.get("labels"), f"{item_id}: labels"))),
            depends_on=depends,
            created_at=str(doc.get("created_at") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project": self.project,
            "title": self.title,
            "state": self.state,
            "state_group": self.state_group,
            "priority": self.priority,
            "labels": list(self.labels),
            "depends_on": list(self.depends_on),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Lane:
    id: str
    project: str
    capacity: int

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> Lane:
        project = _str(doc, "project")
        capacity = doc.get("capacity", 1)
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 0:
            raise SnapshotError(f"lane for {project}: capacity must be an integer >= 0")
        return cls(
            id=_str(doc, "id", f"lane-{project.lower()}"), project=project, capacity=capacity
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "project": self.project, "capacity": self.capacity}


@dataclass(frozen=True)
class Gate:
    """One task_ready gating verdict for an item."""

    ready: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "reason": self.reason}


@dataclass(frozen=True)
class QueueSnapshot:
    taken_at: str
    items: tuple[BoardItem, ...]
    lanes: tuple[Lane, ...]
    gating: Mapping[str, Gate] = field(default_factory=dict)
    source: str = ""
    production_pass_id: str | None = None

    @classmethod
    def build(
        cls,
        *,
        taken_at: str,
        items: Iterable[BoardItem],
        lanes: Iterable[Lane],
        gating: Mapping[str, Gate] | None = None,
        source: str = "",
        production_pass_id: str | None = None,
    ) -> QueueSnapshot:
        ordered = tuple(sorted(items, key=lambda i: i.id))
        ids = [i.id for i in ordered]
        if len(set(ids)) != len(ids):
            raise SnapshotError("duplicate item ids on the board")
        return cls(
            taken_at=taken_at,
            items=ordered,
            lanes=tuple(sorted(lanes, key=lambda lane: (lane.project, lane.id))),
            gating=dict(sorted((gating or {}).items())),
            source=source,
            production_pass_id=production_pass_id,
        )

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> QueueSnapshot:
        if not isinstance(doc, Mapping):
            raise SnapshotError("a board view must be a JSON object")
        items = doc.get("items")
        lanes = doc.get("lanes")
        if not isinstance(items, list) or not isinstance(lanes, list):
            raise SnapshotError("a board view needs 'items' and 'lanes' lists")
        gating_doc = doc.get("gating") or {}
        if not isinstance(gating_doc, Mapping):
            raise SnapshotError("'gating' must map item ids to {ready, reason}")
        gating = {
            str(key): Gate(ready=bool(v.get("ready")), reason=str(v.get("reason") or ""))
            for key, v in gating_doc.items()
            if isinstance(v, Mapping)
        }
        pass_id = doc.get("production_pass_id")
        return cls.build(
            taken_at=_str(doc, "taken_at"),
            items=[BoardItem.from_dict(i) for i in items],
            lanes=[Lane.from_dict(lane) for lane in lanes],
            gating=gating,
            source=str(doc.get("source") or ""),
            production_pass_id=str(pass_id) if pass_id else None,
        )

    def decision_inputs(self) -> dict[str, Any]:
        """Everything the claim decision reads, in canonical form."""
        return {
            "items": [i.to_dict() for i in self.items],
            "lanes": [lane.to_dict() for lane in self.lanes],
            "gating": {key: gate.to_dict() for key, gate in self.gating.items()},
        }

    def to_dict(self) -> dict[str, Any]:
        doc: dict[str, Any] = {"taken_at": self.taken_at, "source": self.source}
        if self.production_pass_id:
            doc["production_pass_id"] = self.production_pass_id
        return doc | self.decision_inputs()

    def content_hash(self) -> str:
        canonical = json.dumps(self.decision_inputs(), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
