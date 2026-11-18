"""Native execution §5: versioned observations survive serialization and deduplicate safely."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from sortyard.lifecycle.contracts import EventKind, EventMode, LifecycleEvent, normalize


def merge_event() -> LifecycleEvent:
    return LifecycleEvent(
        event_id="github:delivery:1",
        kind=EventKind.MERGED,
        mode=EventMode.OBSERVED,
        observed_at=datetime(2026, 11, 18, 12, tzinfo=UTC),
        source="github",
        source_revision="adapter-v1",
        evidence="github:delivery:1",
        board="HARNESS",
        repo="noncelogic/k3s-harness",
        pr_id="10",
    )


def test_wire_version_and_clock_are_validated() -> None:
    event = merge_event()
    wire = event.to_dict()
    assert wire["kind"] == "merged"
    assert wire["schema_version"] == 1
    assert wire["observed_at"] == "2026-11-18T12:00:00+00:00"
    assert LifecycleEvent.from_dict(wire) == event
    with pytest.raises(ValueError, match="schema_version"):
        LifecycleEvent.from_dict({**wire, "schema_version": 2})
    with pytest.raises(ValueError, match="timezone"):
        LifecycleEvent.from_dict({**wire, "observed_at": "2026-11-18T12:00:00"})
    with pytest.raises(ValueError, match="tick"):
        LifecycleEvent.from_dict({**wire, "tick": 1})
    with pytest.raises(ValueError, match="cannot be observed"):
        replace(event, kind=EventKind.WOULD_CLAIM)


def test_duplicates_are_idempotent_and_conflicting_ids_are_quarantined() -> None:
    event = merge_event()
    assert normalize([event, event]) == ((event,), ())
    kept, diagnostics = normalize([event, replace(event, pr_id="11"), event])
    assert kept == ()
    assert len(diagnostics) == 1
    assert event.event_id in diagnostics[0]


def test_dv32_maps_only_committed_stage_entries() -> None:
    from sortyard.lifecycle.dv32 import stage_event

    row = {
        "scope_name": "meta-harness.control-plane",
        "scope_version": "1",
        "span_name": "mh.stage.state",
        "trace_id": "1" * 32,
        "span_id": "2" * 16,
        "observed_at": "2026-11-18T12:00:00.123456789Z",
        "request_id": "mh-req-20261118T120000Z-abcdef",
        "stage_name": "build",
        "stage_sequence": 0,
        "current_state": "running",
    }
    started = stage_event(row)
    assert started is not None
    assert started.kind is EventKind.STAGE_STARTED
    assert started.run_id == row["request_id"]
    assert started.stage == "build:0"
    assert started.board is started.repo is started.task_id is None
    ended = stage_event({**row, "span_id": "3" * 16, "current_state": "failed"})
    assert ended is not None and ended.kind is EventKind.STAGE_ENDED
    assert ended.reason == "failed"
    assert stage_event({**row, "current_state": "collecting"}) is None
    assert stage_event({**row, "span_name": "mh.request.duration"}) is None
    assert stage_event({**row, "scope_version": "2"}) is None
    with pytest.raises(ValueError, match="request identity"):
        stage_event({**row, "request_id": "external-client-id"})
