"""Intake for incumbent conductor lifecycle records collected by SigNoz."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sortyard.lifecycle.contracts import EventMode, LifecycleEvent

_RECORD_TYPE = "harness.lifecycle.v1"
_REVISION = re.compile(r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True)
class Coverage:
    kind: str
    board: str
    repo: str
    observed_at: datetime
    complete: bool
    cadence_seconds: int | None


def _text(value: Mapping[str, object], key: str) -> str:
    field = value.get(key)
    if not isinstance(field, str) or not field:
        raise ValueError(f"coverage requires {key}")
    return field


def conductor_log(row: Mapping[str, object]) -> LifecycleEvent | Coverage:
    body = row.get("body")
    if not isinstance(body, str):
        raise ValueError("expected JSON log body")
    value = json.loads(body)
    if not isinstance(value, dict) or value.pop("record_type", None) != _RECORD_TYPE:
        raise ValueError("unsupported conductor record or producer emission error")
    revision = value.get("source_revision")
    if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
        raise ValueError("expected a pinned conductor bundle")
    if value.get("mode") != EventMode.OBSERVED:
        raise ValueError("incumbent delivery facts require observed mode")
    if value.get("kind") != "coverage":
        return LifecycleEvent.from_dict(value)

    kind = _text(value, "coverage_kind")
    board = _text(value, "board")
    repo = _text(value, "repo")
    timestamp = _text(value, "observed_at")
    complete = value.get("complete")
    cadence = value.get("cadence_seconds")
    if type(complete) is not bool:
        raise ValueError("coverage must declare complete or incomplete")
    if cadence is not None and (type(cadence) is not int or cadence <= 0):
        raise ValueError("coverage cadence must be positive")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported conductor coverage schema_version")
    observed_at = datetime.fromisoformat(timestamp)
    if observed_at.utcoffset() is None:
        raise ValueError("coverage requires an explicit timezone")
    return Coverage(kind, board, repo, observed_at, complete, cadence)
