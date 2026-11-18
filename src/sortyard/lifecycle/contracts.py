"""Versioned facts shared by evidence producers and the scorecard (native execution §5)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from enum import StrEnum

SCHEMA_VERSION = 1
_REASON_CODE = re.compile(r"[a-z][a-z0-9_-]*")


class EventMode(StrEnum):
    OBSERVED = "observed"
    SHADOW = "shadow"
    REPLAY = "replay"


class EventKind(StrEnum):
    RELEASED = "released"
    CLAIMED = "claimed"
    STAGE_STARTED = "stage_started"
    STAGE_ENDED = "stage_ended"
    REVIEW_VERDICT = "review_verdict"
    PR_OPENED = "pr_opened"
    CHECK_RESULT = "check_result"
    HANDBACK = "handback"
    READINESS_HOLD = "readiness_hold"
    READINESS_CLEARED = "readiness_cleared"
    MERGED = "merged"
    DEPLOYED = "deployed"
    ROLLED_BACK = "rolled_back"
    GATE_VERDICT = "gate_verdict"
    REFUSED = "refused"
    MAIN_RED = "main_red"
    MAIN_GREEN = "main_green"
    WOULD_CLAIM = "would_claim"
    CHECKOUT_OBSERVED = "checkout_observed"
    CHECKOUT_CLASSIFIED = "checkout_classified"
    RETRY_DECIDED = "retry_decided"
    OWNER_WAIT = "owner_wait"
    RETRY_WAIT = "retry_wait"
    RETRY_STARTED = "retry_started"
    VERIFICATION_REFUSED = "verification_refused"
    CHECKOUT_VERIFIED = "checkout_verified"


@dataclass(frozen=True, kw_only=True)
class LifecycleEvent:
    event_id: str
    kind: EventKind
    mode: EventMode
    source: str
    source_revision: str
    evidence: str
    observed_at: datetime | None = None
    board: str | None = None
    repo: str | None = None
    task_id: str | None = None
    task_revision: str | None = None
    pr_id: str | None = None
    run_id: str | None = None
    stage: str | None = None
    check_id: str | None = None
    reason: str | None = None
    owner: str | None = None
    policy_version: str | None = None
    artifact_revision: str | None = None
    binding: str | None = None
    projection_reason_present: bool | None = None
    tick: int | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported lifecycle schema_version")
        if not isinstance(self.kind, EventKind) or not isinstance(self.mode, EventMode):
            raise ValueError("invalid event kind or mode")
        for key in ("event_id", "source", "source_revision", "evidence"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a nonblank string")
        for key in (
            "board",
            "repo",
            "task_id",
            "task_revision",
            "pr_id",
            "run_id",
            "stage",
            "check_id",
            "reason",
            "owner",
            "policy_version",
            "artifact_revision",
            "binding",
        ):
            value = getattr(self, key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{key} must be a nonblank string when supplied")
        if self.reason is not None and not _REASON_CODE.fullmatch(self.reason):
            raise ValueError("reason must be a stable lowercase code")
        if self.projection_reason_present is not None and (
            type(self.projection_reason_present) is not bool
        ):
            raise ValueError("projection_reason_present must be true, false or null")
        if self.kind is EventKind.WOULD_CLAIM and self.mode is EventMode.OBSERVED:
            raise ValueError("would_claim cannot be observed")
        if self.mode is EventMode.REPLAY:
            if self.observed_at is not None or type(self.tick) is not int or self.tick < 0:
                raise ValueError("replay requires a nonnegative tick and no observed_at")
            return
        if self.tick is not None:
            raise ValueError("only replay events carry a tick")
        if not isinstance(self.observed_at, datetime) or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at requires an explicit timezone")

    def to_dict(self) -> dict[str, object]:
        data = {field.name: getattr(self, field.name) for field in fields(self)}
        data["kind"] = self.kind.value
        data["mode"] = self.mode.value
        if self.observed_at is not None:
            data["observed_at"] = self.observed_at.astimezone(UTC).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> LifecycleEvent:
        if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported lifecycle schema_version")
        values = dict(data)
        kind, mode = data.get("kind"), data.get("mode")
        if not isinstance(kind, str) or not isinstance(mode, str):
            raise ValueError("kind and mode must be strings")
        values["kind"] = EventKind(kind)
        values["mode"] = EventMode(mode)
        timestamp = data.get("observed_at")
        if timestamp is not None:
            if not isinstance(timestamp, str):
                raise ValueError("observed_at must be an ISO 8601 string")
            values["observed_at"] = datetime.fromisoformat(timestamp)
        try:
            return cls(**values)  # type: ignore[arg-type]  # Validated in __post_init__.
        except TypeError as exc:
            raise ValueError(f"invalid lifecycle event fields: {exc}") from exc


def normalize(
    events: Iterable[LifecycleEvent],
) -> tuple[tuple[LifecycleEvent, ...], tuple[str, ...]]:
    """Deduplicate one identity domain and quarantine every copy of a contradictory ID."""
    by_id: dict[str, LifecycleEvent] = {}
    conflicts: set[str] = set()
    for event in events:
        if event.observed_at is not None:
            event = replace(event, observed_at=event.observed_at.astimezone(UTC))
        if by_id.setdefault(event.event_id, event) != event:
            conflicts.add(event.event_id)
    kept = tuple(event for event_id, event in by_id.items() if event_id not in conflicts)
    return kept, tuple(f"conflicting event ID {event_id}" for event_id in sorted(conflicts))
