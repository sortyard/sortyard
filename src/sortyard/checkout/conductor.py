"""Advance checkout observations through explicit decision and verification seams (§2, §4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sortyard.checkout.contracts import (
    Event,
    GitHubActions,
    Observation,
    Proof,
    RetryCommand,
    RetryPolicy,
    Signal,
)
from sortyard.checkout.verifier import Verifier

Schedule = Callable[[int, Callable[[], None]], None]


@dataclass
class Case:
    initial: Observation
    outcome: str = "awaiting_verification"
    retries_left: int = 1
    failed_runs: set[str] = field(default_factory=set)


class Conductor:
    """One independent checkout case per repository in the replay window."""

    def __init__(
        self,
        github: GitHubActions,
        verifier: Verifier,
        policy: RetryPolicy,
        schedule: Schedule,
    ) -> None:
        self.github = github
        self.verifier = verifier
        self.policy = policy
        self.schedule = schedule
        self.cases: dict[str, Case] = {}
        self.events: list[Event] = []

    def record(
        self,
        tick: int,
        repo: str,
        stage: str,
        evidence: str,
        reason: str = "",
        *,
        policy: str | None = None,
    ) -> None:
        self.events.append(Event(tick, repo, stage, evidence, policy, reason))

    def start(self, tick: int, observation: Observation) -> None:
        if observation.repo in self.cases:
            raise ValueError(f"duplicate starting observation for {observation.repo}")
        case = self.cases[observation.repo] = Case(observation)
        self.observe(tick, case, observation)

    def observe(self, tick: int, case: Case, observation: Observation) -> None:
        self.record(tick, observation.repo, "observe", observation.run, observation.signal)
        if observation.signal == Signal.UNKNOWN:
            case.outcome = "owner_wait"
            self.record(
                tick, observation.repo, "owner_wait", observation.run, "evidence incomplete"
            )
            return
        if observation.signal != Signal.CHECKOUT_REJECTED:
            case.outcome = "awaiting_verification"
            return
        case.failed_runs.add(observation.run.split("/", 1)[0])
        self.record(tick, observation.repo, "classify", observation.run, "checkout_access_rejected")
        decision = self.policy.decide(observation, case.retries_left)
        self.record(
            tick,
            observation.repo,
            "retry_decision",
            observation.run,
            decision.reason,
            policy=self.policy.version,
        )
        if decision.delay is None or not case.retries_left:
            case.outcome = "owner_wait"
            self.record(tick, observation.repo, "owner_wait", observation.run)
            return
        if type(decision.delay) is not int or decision.delay < 1:
            raise ValueError("retry decisions require a positive whole tick delay")
        due = tick + decision.delay
        case.outcome = "retry_wait"
        self.record(tick, observation.repo, "retry_wait", observation.run, f"due at tick {due}")
        self.schedule(
            due,
            lambda: self.retry(
                case, RetryCommand(due, observation.repo, observation.tree, observation.run)
            ),
        )

    def retry(self, case: Case, command: RetryCommand) -> None:
        if case.outcome != "retry_wait":
            return  # independent proof can resolve the case before the command is due
        case.retries_left -= 1
        self.record(command.tick, command.repo, "retry", command.failed_run)
        outcome = self.github.retry(command)
        if (outcome.repo, outcome.tree) != (command.repo, command.tree):
            raise ValueError("retry observation does not match the checkout subject")
        self.observe(command.tick, case, outcome)

    def verify(self, tick: int, proof: Proof) -> None:
        case = self.cases.get(proof.repo)
        if case is None or case.outcome in {"completed", "recovered"}:
            return
        if not self.verifier.confirms(case.initial, case.failed_runs, proof):
            self.record(tick, proof.repo, "verification_refused", proof.run)
            return
        case.outcome = "recovered" if case.failed_runs else "completed"
        self.record(tick, proof.repo, "verified", proof.run, case.outcome)
