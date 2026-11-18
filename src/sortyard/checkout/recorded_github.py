"""Adapt recorded GitHub job results to typed observations without network effects (§4)."""

from __future__ import annotations

from typing import TypedDict

from sortyard.checkout.contracts import Observation, RetryCommand, Signal


class RecordedObservation(TypedDict):
    repo: str
    tree: str
    run: str
    step: str
    git_exit: int | None
    log: str


def observation(row: RecordedObservation) -> Observation:
    signal = Signal.UNKNOWN
    if row["step"] == "checkout":
        if row["git_exit"] == 0:
            signal = Signal.CANDIDATE_READY
        elif row["git_exit"] == 128 and any(
            line.strip().removesuffix(".") == "remote: Repository not found"
            for line in row["log"].splitlines()
        ):
            signal = Signal.CHECKOUT_REJECTED
    return Observation(row["repo"], row["tree"], row["run"], signal)


class RecordedGitHub:
    """Capture the retry command and return the recorded second attempt."""

    def __init__(self, response: RecordedObservation) -> None:
        self.response = response
        self.commands: list[RetryCommand] = []

    def retry(self, command: RetryCommand) -> Observation:
        self.commands.append(command)
        return observation(self.response)
