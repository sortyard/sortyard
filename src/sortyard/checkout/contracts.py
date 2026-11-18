"""Typed observations, policy decisions and receipts for native checkout recovery (§2, §4)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Signal(StrEnum):
    CHECKOUT_REJECTED = "checkout_rejected"
    CANDIDATE_READY = "candidate_ready"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Observation:
    repo: str
    tree: str
    run: str
    signal: Signal


@dataclass(frozen=True)
class RetryCommand:
    tick: int
    repo: str
    tree: str
    failed_run: str


@dataclass(frozen=True)
class Decision:
    reason: str
    delay: int | None = None


class RetryPolicy(Protocol):
    @property
    def version(self) -> str: ...

    def decide(self, observation: Observation, remaining: int) -> Decision: ...


class GitHubActions(Protocol):
    def retry(self, command: RetryCommand) -> Observation: ...


@dataclass(frozen=True)
class Proof:
    repo: str
    tree: str
    run: str
    checks: frozenset[str]


@dataclass(frozen=True)
class Event:
    tick: int
    repo: str
    stage: str
    evidence: str
    policy: str | None = None
    reason: str = ""
