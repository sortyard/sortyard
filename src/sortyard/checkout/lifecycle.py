"""Project checkout receipts into shared lifecycle facts on the replay clock (§5)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict

from sortyard.checkout.contracts import Event
from sortyard.checkout.replay import Fixture, Result
from sortyard.lifecycle.contracts import EventKind, EventMode, LifecycleEvent

KINDS = {
    "observe": EventKind.CHECKOUT_OBSERVED,
    "classify": EventKind.CHECKOUT_CLASSIFIED,
    "retry_decision": EventKind.RETRY_DECIDED,
    "owner_wait": EventKind.OWNER_WAIT,
    "retry_wait": EventKind.RETRY_WAIT,
    "retry": EventKind.RETRY_STARTED,
    "verification_refused": EventKind.VERIFICATION_REFUSED,
    "verified": EventKind.CHECKOUT_VERIFIED,
}


def replay_events(fixture: Fixture, result: Result) -> tuple[LifecycleEvent, ...]:
    revision = hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()
    events = []
    occurrences: Counter[Event] = Counter()
    for index, receipt in enumerate(result.events):
        kind = KINDS[receipt.stage]
        reason: str | None
        if kind == EventKind.RETRY_DECIDED:
            # Replay records the policy's immediate disposition after the decision receipt.
            next_stage = result.events[index + 1].stage
            reason = {"retry_wait": "retry_scheduled", "owner_wait": "owner_evidence_required"}[
                next_stage
            ]
        elif kind == EventKind.OWNER_WAIT:
            reason = "checkout_evidence_incomplete" if receipt.reason else "owner_evidence_required"
        elif kind == EventKind.RETRY_WAIT:
            reason = "retry_backoff"
        elif kind == EventKind.VERIFICATION_REFUSED:
            reason = "verification_evidence_rejected"
        else:
            reason = receipt.reason or None

        occurrences[receipt] += 1
        identity = json.dumps([revision, asdict(receipt), occurrences[receipt]], sort_keys=True)
        event_id = f"checkout-replay:{hashlib.sha256(identity.encode()).hexdigest()}"
        events.append(
            LifecycleEvent(
                event_id=event_id,
                kind=kind,
                source="checkout_replay",
                source_revision=revision,
                mode=EventMode.REPLAY,
                repo=receipt.repo,
                run_id=receipt.evidence or None,
                stage="checkout",
                tick=receipt.tick,
                evidence=f"checkout-fixture:{result.incident}:{revision}:{receipt.repo}:{receipt.evidence}",
                policy_version=receipt.policy,
                reason=reason,
            )
        )
    return tuple(events)
