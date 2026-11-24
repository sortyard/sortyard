"""The decision policy: a small data file the decision step consults (HARNESS-V3 3.1).

`load` reads the rules (`decision_policy.toml`, shipped next to the state table, shows the
format) and refuses a file it cannot read in full. `Policy.decide` is the item workflow's
decision step: the first rule that matches the question answers it; when none does it returns
nothing, and the item's own default and then the table's apply. A rule can also match what a
request asked for (`request`) and the role of whoever sent it (`role`).
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from typing import Any

MATCH_KEYS = ("state", "cause", "outcome", "action", "request", "role")
_RULE_KEYS = frozenset({*MATCH_KEYS, "answer", "reverse"})


@dataclass(frozen=True)
class Policy:
    rules: tuple[Mapping[str, str], ...] = ()

    def decide(self, question: Mapping[str, Any]) -> dict[str, str] | None:
        request = question.get("request")
        request = request if isinstance(request, Mapping) else {}
        by = request.get("by")
        role = by.get("role") if isinstance(by, Mapping) else None
        asked = {**question, "request": request.get("answer"), "role": role}
        for rule in self.rules:
            if all(asked.get(key) == rule[key] for key in MATCH_KEYS if key in rule):
                return {"answer": rule["answer"], "reverse": rule["reverse"]}
        return None


def load(text: str) -> Policy:
    """Load a decision policy from its TOML text, or raise `ValueError`."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"the decision policy is not TOML: {error}") from error
    rules = raw.get("rules", [])
    if raw.get("version") != 1 or set(raw) - {"version", "rules"} or not isinstance(rules, list):
        raise ValueError("a decision policy is {version = 1, rules = [...]}")
    for rule in rules:
        if not isinstance(rule, Mapping) or set(rule) - _RULE_KEYS:
            raise ValueError(f"a rule has only the keys {sorted(_RULE_KEYS)}: {rule!r}")
        if not all(isinstance(value, str) and value.strip() for value in rule.values()):
            raise ValueError(f"every value of a rule is a non-empty string: {rule!r}")
        if not {"answer", "reverse"} <= set(rule):
            raise ValueError(f"a rule gives an answer and how to reverse it: {rule!r}")
    return Policy(tuple(dict(rule) for rule in rules))


def shipped() -> Policy:
    """The policy this package ships."""
    return load(resources.files("sortyard.kernel").joinpath("decision_policy.toml").read_text())
