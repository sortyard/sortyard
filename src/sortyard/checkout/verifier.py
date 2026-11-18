"""Verify owner-supplied results independently of the retry adapter (§2, §4)."""

from __future__ import annotations

from dataclasses import dataclass

from sortyard.checkout.contracts import Observation, Proof


@dataclass(frozen=True)
class Verifier:
    required: frozenset[str]

    def confirms(self, subject: Observation, failed_runs: set[str], proof: Proof) -> bool:
        return (
            bool(self.required)
            and proof.repo == subject.repo
            and proof.tree == subject.tree
            and bool(proof.run)
            and proof.run.split("/", 1)[0] not in failed_runs
            and self.required <= proof.checks
        )
