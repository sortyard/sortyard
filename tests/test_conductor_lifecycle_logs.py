"""The SigNoz lifecycle intake rejects unpinned facts and missing reconciliation slots."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from sortyard.lifecycle.__main__ import _covered_cadence
from sortyard.lifecycle.conductor_logs import Coverage, conductor_log
from sortyard.lifecycle.contracts import EventKind, LifecycleEvent
from sortyard.lifecycle.scorecard import ScorecardWindow

START = datetime(2026, 11, 18, tzinfo=UTC)
WINDOW = ScorecardWindow(START, START + timedelta(minutes=15), "HARNESS", "example/repo")


def log_row(**fields: object) -> dict[str, str]:
    payload: dict[str, object] = {
        "record_type": "harness.lifecycle.v1",
        "schema_version": 1,
        "event_id": "conductor:1",
        "kind": "handback",
        "mode": "observed",
        "source": "harness.conductor.drive",
        "source_revision": "sha256:" + "a" * 64,
        "evidence": "plane:work-item:1",
        "board": "HARNESS",
        "repo": "example/repo",
        "observed_at": START.isoformat(),
        "owner": "self-heal",
        "reason": "execution_stopped",
        "task_id": "1",
    }
    return {"body": json.dumps(payload | fields)}


def test_reads_only_pinned_observed_records() -> None:
    event = conductor_log(log_row())
    assert isinstance(event, LifecycleEvent)
    assert event.kind is EventKind.HANDBACK
    with pytest.raises(ValueError, match="pinned conductor bundle"):
        conductor_log(log_row(source_revision="local-unpinned"))
    with pytest.raises(ValueError, match="observed mode"):
        conductor_log(log_row(mode="replay"))
    with pytest.raises(ValueError, match="producer emission error"):
        conductor_log(log_row(record_type="harness.lifecycle_error.v1"))


def test_coverage_requires_each_scoped_reconciliation_slot() -> None:
    records = []
    for minute in (1, 6, 11):
        record = conductor_log(
            log_row(
                kind="coverage",
                coverage_kind="readiness",
                cadence_seconds=300,
                complete=True,
                observed_at=(START + timedelta(minutes=minute)).isoformat(),
            )
        )
        assert isinstance(record, Coverage)
        records.append(record)
    assert _covered_cadence(records, "readiness", WINDOW) == 300
    assert _covered_cadence(records[1:], "readiness", WINDOW) is None
    assert _covered_cadence(records, "readiness", replace(WINDOW, repo="elsewhere/repo")) is None
    assert (
        _covered_cadence([*records, replace(records[0], complete=False)], "readiness", WINDOW)
        is None
    )


def test_unresolved_read_is_not_a_known_final_main_state() -> None:
    record = conductor_log(
        log_row(
            kind="coverage",
            coverage_kind="red_main",
            cadence_seconds=300,
            complete=True,
            reason="required_checks_unresolved",
        )
    )
    assert isinstance(record, Coverage)
    window = replace(WINDOW, end=START + timedelta(minutes=5))
    assert _covered_cadence([record], "red_main", window) is None
    assert _covered_cadence([replace(record, reason="sample_observed")], "red_main", window) == 300
