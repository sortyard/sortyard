"""Compose the native checkout chain with a local queue and recorded provider evidence (§4)."""

from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from itertools import count
from typing import TypedDict

from sortyard.checkout.conductor import Conductor
from sortyard.checkout.contracts import Event, Proof, RetryCommand
from sortyard.checkout.policy import POLICIES
from sortyard.checkout.recorded_github import RecordedGitHub, RecordedObservation, observation
from sortyard.checkout.verifier import Verifier


class TimedObservation(RecordedObservation):
    tick: int


class TimedProof(TypedDict):
    tick: int
    repo: str
    tree: str
    run: str
    checks: list[str]


class Fixture(TypedDict):
    incident: str
    required_checks: list[str]
    start: list[TimedObservation]
    retry: RecordedObservation
    verification: list[TimedProof]


@dataclass(frozen=True)
class Result:
    incident: str
    outcomes: dict[str, str]
    events: list[Event]
    retries: list[RetryCommand]


def run_replay(fixture: Fixture, policy: str) -> Result:
    queue: list[tuple[int, int, Callable[[], None]]] = []
    order = count()

    def schedule(tick: int, action: Callable[[], None]) -> None:
        heapq.heappush(queue, (tick, next(order), action))

    github = RecordedGitHub(fixture["retry"])
    verifier = Verifier(frozenset(fixture["required_checks"]))
    conductor = Conductor(github, verifier, POLICIES[policy], schedule)
    for entry in fixture["start"]:
        schedule(entry["tick"], partial(conductor.start, entry["tick"], observation(entry)))
    for entry_proof in fixture["verification"]:
        proof = Proof(
            entry_proof["repo"],
            entry_proof["tree"],
            entry_proof["run"],
            frozenset(entry_proof["checks"]),
        )
        schedule(entry_proof["tick"], partial(conductor.verify, entry_proof["tick"], proof))
    while queue:
        _, _, action = heapq.heappop(queue)
        action()
    return Result(
        fixture["incident"],
        {repo: case.outcome for repo, case in conductor.cases.items()},
        conductor.events,
        github.commands,
    )
