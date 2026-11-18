"""Map incumbent DV-32 committed stage-entry spans (native execution §5)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime

from sortyard.lifecycle.contracts import EventKind, EventMode, LifecycleEvent

_SCOPE = "meta-harness.control-plane"
_REQUEST = re.compile(r"mh-req-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}")
_STATE_KINDS = {
    "running": EventKind.STAGE_STARTED,
    "done": EventKind.STAGE_ENDED,
    "failed": EventKind.STAGE_ENDED,
}


def _hex_id(row: Mapping[str, object], key: str, width: int) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not re.fullmatch(f"[0-9a-f]{{{width}}}", value):
        raise ValueError(f"invalid {key}")
    if int(value, 16) == 0:
        raise ValueError(f"invalid {key}")
    return value


def stage_event(row: Mapping[str, object]) -> LifecycleEvent | None:
    """Read only stage start and terminal transition markers from the reviewed scope."""
    if (row.get("scope_name"), row.get("scope_version"), row.get("span_name")) != (
        _SCOPE,
        "1",
        "mh.stage.state",
    ):
        return None
    state = row.get("current_state")
    if not isinstance(state, str):
        raise ValueError("invalid current_state")
    if state in ("queued", "scheduled", "collecting"):
        return None
    if state not in _STATE_KINDS:
        raise ValueError("unmapped DV-32 stage state")

    request_id = row.get("request_id")
    if not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id):
        raise ValueError("invalid DV-32 request identity")
    stage = row.get("stage_name")
    sequence = row.get("stage_sequence")
    if stage not in ("shape", "build", "verify", "proof"):
        raise ValueError("invalid DV-32 stage name")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence <= 1000000:
        raise ValueError("invalid DV-32 stage sequence")
    timestamp = row.get("observed_at")
    if not isinstance(timestamp, str):
        raise ValueError("DV-32 observed_at requires an ISO 8601 string")
    trace_id = _hex_id(row, "trace_id", 32)
    span_id = _hex_id(row, "span_id", 16)
    return LifecycleEvent(
        event_id=f"otlp:{trace_id}:{span_id}",
        kind=_STATE_KINDS[state],
        mode=EventMode.OBSERVED,
        source=_SCOPE,
        source_revision="dv32-v1",
        evidence=f"sigNoz:trace:{trace_id}:{span_id}",
        observed_at=datetime.fromisoformat(timestamp),
        run_id=request_id,
        stage=f"{stage}:{sequence}",
        reason=state,
    )
