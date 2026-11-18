"""Prove policy replacement and independent checkout recovery with the native chain."""

from __future__ import annotations

import json
from pathlib import Path

from sortyard.checkout.replay import run_replay

FIXTURE = Path(__file__).parent / "fixtures" / "checkout-incident.json"
SORTYARD = "sortyard/sortyard"
OTHER = "fixture/unrelated"


def test_switching_retry_policy_preserves_unrelated_progress() -> None:
    fixture = json.loads(FIXTURE.read_text())
    owner = run_replay(fixture, "owner-first")
    retry = run_replay(fixture, "wait-and-retry")

    assert not owner.retries
    assert [(r.repo, r.tick, r.failed_run) for r in retry.retries] == [
        (SORTYARD, 7, "43799510804/1")
    ]
    assert [(e.tick, e.evidence) for e in retry.events if e.stage == "classify"] == [
        (0, "43799510804/1"),
        (7, "43799510804/2"),
    ]
    assert [e.tick for e in retry.events if e.stage == "owner_wait"] == [7]
    assert [e.tick for e in owner.events if e.stage == "owner_wait"] == [0]
    assert [e.policy for e in owner.events if e.stage == "retry_decision"] == ["owner-first@1"]
    assert [e.policy for e in retry.events if e.stage == "retry_decision"] == [
        "wait-and-retry@1"
    ] * 2
    for result in (owner, retry):
        assert result.outcomes == {SORTYARD: "recovered", OTHER: "completed"}
        assert [(e.tick, e.evidence) for e in result.events if e.stage == "verified"] == [
            (1, "fixture/run"),
            (20, "43961502003"),
        ]
    assert [e for e in owner.events if e.repo == OTHER] == [
        e for e in retry.events if e.repo == OTHER
    ]


def test_unrelated_or_incomplete_evidence_cannot_close_the_checkout_incident() -> None:
    fixture = json.loads(FIXTURE.read_text())
    recovery = fixture["verification"].pop()
    fixture["verification"].extend(
        [
            dict(recovery, tree="different-tree"),
            dict(recovery, repo="fixture/unrelated"),
            dict(recovery, checks=recovery["checks"][:-1]),
            dict(recovery, run="43799510804"),
        ]
    )
    result = run_replay(fixture, "wait-and-retry")
    assert result.outcomes == {SORTYARD: "owner_wait", OTHER: "completed"}
    assert not any(e.stage == "verified" and e.repo == SORTYARD for e in result.events)


def test_verified_recovery_cancels_a_pending_retry_at_its_deadline() -> None:
    fixture = json.loads(FIXTURE.read_text())
    fixture["verification"][-1]["tick"] = 7
    result = run_replay(fixture, "wait-and-retry")
    assert result.outcomes[SORTYARD] == "recovered"
    assert not result.retries
    assert [e.tick for e in result.events if e.stage == "verified"] == [1, 7]


def test_repository_not_found_outside_checkout_cannot_trigger_a_retry() -> None:
    fixture = json.loads(FIXTURE.read_text())
    fixture["start"][0]["step"] = "product test"
    fixture["verification"].pop()
    result = run_replay(fixture, "wait-and-retry")
    assert result.outcomes == {SORTYARD: "owner_wait", OTHER: "completed"}
    assert not result.retries
    assert not any(e.stage in {"classify", "retry_decision"} for e in result.events)
