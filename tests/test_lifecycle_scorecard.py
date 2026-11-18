"""Verify scorecard evidence, joins, deduplication and coverage (native execution §5)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sortyard.lifecycle.contracts import EventKind, EventMode, LifecycleEvent
from sortyard.lifecycle.scorecard import Measure, ScorecardWindow, build_scorecard

START = datetime(2026, 11, 9, tzinfo=UTC)
WEEK = ScorecardWindow(START, START + timedelta(days=7), board="OPS", repo="example/repo")


def fact(
    event_id: str,
    kind: EventKind,
    hour: int,
    *,
    task_id: str = "OPS-1",
    revision: str = "revision-a",
    pr_id: str | None = None,
    check_id: str | None = None,
    projection_reason_present: bool | None = None,
    mode: EventMode = EventMode.OBSERVED,
) -> LifecycleEvent:
    return LifecycleEvent(
        event_id=event_id,
        kind=kind,
        observed_at=START + timedelta(hours=hour),
        source="fixture",
        source_revision="source-sha",
        evidence=f"fixture/{event_id}",
        mode=mode,
        board="OPS",
        repo="example/repo",
        task_id=task_id,
        task_revision=revision,
        pr_id=pr_id,
        check_id=check_id,
        owner="queue",
        reason="fixture_reason",
        artifact_revision="artifact-sha",
        binding="fixture-binding",
        projection_reason_present=projection_reason_present,
    )


def test_every_measure_uses_its_own_observed_facts_and_grain() -> None:
    merge = fact("merge", EventKind.MERGED, 2, pr_id="1")
    rows = build_scorecard(
        [
            fact("release-old", EventKind.RELEASED, -2, revision="revision-other"),
            fact("release-first", EventKind.RELEASED, -1),
            fact("release-again", EventKind.RELEASED, 1),
            merge,
            merge,
            replace(merge, event_id="merge-second-observer"),
            replace(merge, event_id="merge-outside-scope", repo="example/other", pr_id="2"),
            replace(merge, event_id="merge-shadow", pr_id="3", mode=EventMode.SHADOW),
            fact("handback", EventKind.HANDBACK, 3),
            fact("hold-aged", EventKind.READINESS_HOLD, 150),
            fact("hold-repeat", EventKind.READINESS_HOLD, 167),
            fact("hold-recent", EventKind.READINESS_HOLD, 164, task_id="OPS-2"),
            fact("hold-cleared", EventKind.READINESS_HOLD, 40, task_id="OPS-3"),
            fact("clear", EventKind.READINESS_CLEARED, 100, task_id="OPS-3"),
            fact("a-green", EventKind.MAIN_GREEN, -5, check_id="a"),
            fact("a-red", EventKind.MAIN_RED, 20, check_id="a"),
            fact("a-red-again", EventKind.MAIN_RED, 22, check_id="a"),
            fact("a-recovered", EventKind.MAIN_GREEN, 24, check_id="a"),
            fact("b-green", EventKind.MAIN_GREEN, 0, check_id="b"),
            fact("b-red", EventKind.MAIN_RED, 23, check_id="b"),
            fact("b-recovered", EventKind.MAIN_GREEN, 27, check_id="b"),
            fact("refused-silent", EventKind.REFUSED, 99, projection_reason_present=False),
            fact("refused-explained", EventKind.REFUSED, 100, projection_reason_present=True),
        ],
        WEEK,
        complete=list(Measure),
        reconciliation_interval=timedelta(hours=4),
    ).rows
    assert {measure: row.value for measure, row in rows.items()} == {
        Measure.MERGED_PRS_PER_DAY: 1 / 7,
        Measure.REAL_HANDBACKS_PER_DAY: 1 / 7,
        Measure.MEDIAN_RELEASE_TO_MERGE_HOURS: 3,
        Measure.RED_MAIN_HOURS_PER_WEEK: 7,
        Measure.OVERDUE_READINESS_HOLDS: 1,
        Measure.SILENT_REFUSALS: 1,
    }
    assert rows[Measure.MERGED_PRS_PER_DAY].samples == 1
    assert rows[Measure.MEDIAN_RELEASE_TO_MERGE_HOURS].samples == 1
    assert rows[Measure.SILENT_REFUSALS].samples == 2


def test_missing_coverage_or_joins_never_become_zero() -> None:
    card = build_scorecard(
        [
            fact("merge", EventKind.MERGED, 2, pr_id="1"),
            fact("handback", EventKind.HANDBACK, 3),
            fact("main-initial", EventKind.MAIN_GREEN, -1, check_id="a"),
            fact("main-red-open", EventKind.MAIN_RED, 10, check_id="a"),
            fact("hold", EventKind.READINESS_HOLD, 8),
            fact("refused-uninspected", EventKind.REFUSED, 9),
        ],
        WEEK,
        complete=[
            Measure.MERGED_PRS_PER_DAY,
            Measure.MEDIAN_RELEASE_TO_MERGE_HOURS,
            Measure.RED_MAIN_HOURS_PER_WEEK,
            Measure.OVERDUE_READINESS_HOLDS,
            Measure.SILENT_REFUSALS,
        ],
    )
    assert card.rows[Measure.MERGED_PRS_PER_DAY].value == 1 / 7
    for measure in set(Measure) - {Measure.MERGED_PRS_PER_DAY}:
        assert card.rows[measure].value is None and card.rows[measure].issues
    assert card.rows[Measure.REAL_HANDBACKS_PER_DAY].samples == 1


def test_conflicting_observed_id_cannot_contribute_to_a_complete_measure() -> None:
    merge = fact("merge", EventKind.MERGED, 2, pr_id="1")
    card = build_scorecard(
        [merge, replace(merge, pr_id="2")],
        WEEK,
        complete=[Measure.MERGED_PRS_PER_DAY],
    )
    assert card.diagnostics
    assert card.rows[Measure.MERGED_PRS_PER_DAY].samples == 0
    assert card.rows[Measure.MERGED_PRS_PER_DAY].value is None


def test_handback_requires_an_observed_return_to_an_identified_owner() -> None:
    handback = fact("handback", EventKind.HANDBACK, 1)
    card = build_scorecard(
        [handback, replace(handback, event_id="unattributed", owner=None)],
        WEEK,
        complete=[Measure.REAL_HANDBACKS_PER_DAY],
    )
    row = card.rows[Measure.REAL_HANDBACKS_PER_DAY]
    assert row.value is None and row.samples == 1 and row.issues


def test_exclusively_replayed_and_shadow_facts_cannot_assert_live_coverage() -> None:
    observed = fact("merge", EventKind.MERGED, 2, pr_id="1")
    card = build_scorecard(
        [
            replace(observed, event_id="shadow", mode=EventMode.SHADOW),
            replace(observed, event_id="replay", mode=EventMode.REPLAY, observed_at=None, tick=2),
        ],
        WEEK,
        complete=list(Measure),
        reconciliation_interval=timedelta(hours=4),
    )
    assert all(row.value is None and row.samples == 0 for row in card.rows.values())
    assert card.diagnostics
    assert (
        build_scorecard([], WEEK, complete=[Measure.MERGED_PRS_PER_DAY])
        .rows[Measure.MERGED_PRS_PER_DAY]
        .value
        == 0
    )


def test_repository_scoped_merge_does_not_assume_board_attribution() -> None:
    merge = replace(fact("merge", EventKind.MERGED, 2, pr_id="1"), board=None)
    complete = [Measure.MERGED_PRS_PER_DAY]
    repo_only = build_scorecard([merge], replace(WEEK, board=None), complete=complete)
    assert repo_only.rows[Measure.MERGED_PRS_PER_DAY].value == 1 / 7
    assert (
        build_scorecard([merge], WEEK, complete=complete).rows[Measure.MERGED_PRS_PER_DAY].value
        is None
    )


def test_conflicting_outside_scope_does_not_invalidate_known_repo_merge() -> None:
    other = replace(fact("other", EventKind.MERGED, 2, pr_id="3"), repo="example/other")
    card = build_scorecard(
        [fact("merge", EventKind.MERGED, 2, pr_id="1"), other, replace(other, pr_id="4")],
        WEEK,
        complete=[Measure.MERGED_PRS_PER_DAY],
    )
    assert card.diagnostics
    assert card.rows[Measure.MERGED_PRS_PER_DAY].value == 1 / 7


def test_readiness_and_refusal_require_traceable_task_evidence() -> None:
    hold = replace(fact("hold", EventKind.READINESS_HOLD, 1), reason=None)
    refusal = replace(
        fact("refusal", EventKind.REFUSED, 2, projection_reason_present=False),
        task_id=None,
    )
    card = build_scorecard(
        [hold, refusal],
        WEEK,
        complete=[Measure.OVERDUE_READINESS_HOLDS, Measure.SILENT_REFUSALS],
        reconciliation_interval=timedelta(hours=4),
    )
    for measure in (Measure.OVERDUE_READINESS_HOLDS, Measure.SILENT_REFUSALS):
        assert card.rows[measure].value is None
        assert card.rows[measure].samples == 0
