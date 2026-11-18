"""Versioned checkout retry policies, independently bound by the replay host (§2, §4)."""

from __future__ import annotations

from dataclasses import dataclass

from sortyard.checkout.contracts import Decision, Observation, RetryPolicy, Signal


@dataclass(frozen=True)
class OwnerFirst:
    version: str = "owner-first@1"

    def decide(self, observation: Observation, remaining: int) -> Decision:
        return Decision("Checkout access needs fresh evidence from the repository owner")


@dataclass(frozen=True)
class WaitAndRetry:
    version: str = "wait-and-retry@1"

    def decide(self, observation: Observation, remaining: int) -> Decision:
        if observation.signal == Signal.CHECKOUT_REJECTED and remaining > 0:
            return Decision("Allow one bounded diagnostic retry", delay=7)
        return Decision("Diagnostic retry budget spent; wait for owner evidence")


POLICIES: dict[str, RetryPolicy] = {
    "owner-first": OwnerFirst(),
    "wait-and-retry": WaitAndRetry(),
}
