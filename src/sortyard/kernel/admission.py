"""Admission: the one way an item enters the kernel (HARNESS-V3 section 3.5, step 4).

A machine check before anything is created: the id can be part of a branch name, the project
(and the milestone, if one is named) exists, the spec has an outcome and at least one named
acceptance test, the lane is known, names the item's project if it names any, and declares the
item's repository and every need, every blocked_by link resolves to an item of the same tenant,
and the risk tier is one the state table has limits for. `check` gives every reason an item
fails, not the first. `admit` writes the item, its links and its spec in the caller's
transaction, or nothing: a refused item leaves no row. Admitting an id again with the same
content changes nothing; with other content it is refused, since a spec is written once; so is
an id that was withdrawn.

Starting the item's workflow is the caller's next step (`sortyard.kernel.item.start_item`),
inside the same transaction, so an item is never stored without one being started.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sortyard.kernel.capabilities import REPOSITORY, CapabilityError, Lane, Need
from sortyard.kernel.states import StateTable, merged_states, shipped

Conn = psycopg.Connection[Any]


@dataclass(frozen=True)
class Admission:
    """An item as asked for. `needs` are references into the lane's capability file."""

    tenant: str
    item: str
    project: str
    title: str
    lane: str
    repository: str
    spec: Mapping[str, Any]
    base: str = "main"
    needs: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()
    risk_tier: str = "medium"
    milestone: str | None = None


class Refused(ValueError):
    """The item fails admission. `reasons` gives every failure as `rule: what`."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class Different(Refused):
    """The id is already admitted, with other content. A spec is written once."""


_REF_BAD = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]|\.\.|@\{|//")


def ref_safe(item: str) -> bool:
    """Whether `sortyard/<item>` is a branch name git accepts (git-check-ref-format), and one
    no command takes for an option."""
    parts = item.split("/")
    return not (
        _REF_BAD.search(item)
        or item.startswith("-")
        or item.endswith(".")
        or any(not p or p.startswith(".") or p.endswith(".lock") for p in parts)
    )


def _named(test: Any) -> bool:
    return isinstance(test, Mapping) and all(
        isinstance(test.get(key), str) and test[key].strip() for key in ("test", "name")
    )


def check(
    conn: Conn, lanes: Mapping[str, Lane], asked: Admission, table: StateTable | None = None
) -> list[str]:
    """Every reason the item cannot be admitted; empty when it can."""
    reasons: list[str] = []
    if not ref_safe(asked.item):
        reasons.append(f"unsafe-id: sortyard/{asked.item} is not a branch name git accepts")
    for kind, wanted in (("project", asked.project), ("milestone", asked.milestone)):
        if (
            wanted is not None
            and not conn.execute(
                f"SELECT 1 FROM sortyard.{kind} WHERE workspace_id = %s AND id = %s",
                (asked.tenant, wanted),
            ).fetchone()
        ):
            reasons.append(f"unknown-{kind}: no {kind} {wanted!r} in this workspace")
    outcome, acceptance = asked.spec.get("outcome"), asked.spec.get("acceptance")
    if not isinstance(outcome, str) or not outcome.strip():
        reasons.append("no-outcome: the spec states no outcome")
    if not isinstance(acceptance, list) or not acceptance or not all(map(_named, acceptance)):
        reasons.append(
            "no-acceptance-test: the spec names no acceptance test (each is {test, name})"
        )
    tiers = [
        set(state.limit.by_tier)
        for state in (table or shipped()).states.values()
        if state.limit and state.limit.by_tier
    ]
    if any(asked.risk_tier not in known for known in tiers):
        reasons.append(f"unknown-risk-tier: the state table has no limit for {asked.risk_tier!r}")
    lane = lanes.get(asked.lane)
    if lane is None:
        reasons.append(f"unknown-lane: no lane {asked.lane!r} (known: {sorted(lanes)})")
    else:
        if lane.projects and asked.project not in lane.projects:
            reasons.append(
                f"unknown-lane-project: lane {asked.lane!r} takes no item of project "
                f"{asked.project!r} (its projects: {list(lane.projects)})"
            )
        needs: list[Need | str] = [Need(REPOSITORY, asked.repository), *asked.needs]
        for need in needs:
            try:
                lane.check(need)
            except CapabilityError as error:
                reasons.append(str(error))
    known = conn.execute(
        "SELECT id FROM sortyard.item WHERE workspace_id = %s AND id = ANY(%s)",
        (asked.tenant, list(asked.blocked_by)),
    ).fetchall()
    found = {row[0] for row in known} - {asked.item}
    for link in asked.blocked_by:
        if link not in found:
            reasons.append(f"unresolved-link: blocked_by {link!r} is not an item it can wait on")
    return reasons


def admit(
    conn: Conn, lanes: Mapping[str, Lane], asked: Admission, table: StateTable | None = None
) -> bool:
    """Create the item, its links and its spec; true when created, false when the same item
    was admitted before. `Refused` when it fails the check, `Different` when it differs from
    what is stored.

    Runs in the caller's transaction. The repository is stored as a need too, so preflight
    exercises it.
    """
    reasons = check(conn, lanes, asked, table)
    if reasons:
        raise Refused(reasons)
    needs = list(dict.fromkeys([f"{REPOSITORY}:{asked.repository}", *asked.needs]))
    wanted = (
        asked.project,
        asked.title,
        asked.risk_tier,
        asked.milestone,
        asked.lane,
        asked.repository,
        asked.base,
        needs,
        dict(asked.spec),
        sorted(set(asked.blocked_by)),
    )
    # One admission of an id at a time, so two cannot both find it absent.
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"admit:{asked.tenant}:{asked.item}",)
    )
    stored = conn.execute(
        "SELECT i.project_id, i.title, i.risk_tier, i.milestone_id, s.lane, s.repository,"
        "       s.base, s.needs, s.spec, ARRAY(SELECT l.blocked_by FROM sortyard.item_link AS l"
        "         WHERE (l.workspace_id, l.item_id) = (i.workspace_id, i.id) ORDER BY 1),"
        "       i.state_kind = 'terminal' AND NOT i.state = ANY(%s), i.state"
        " FROM sortyard.item AS i LEFT JOIN sortyard.item_spec AS s"
        "   ON (s.workspace_id, s.item_id) = (i.workspace_id, i.id)"
        " WHERE i.workspace_id = %s AND i.id = %s",
        (merged_states(table), asked.tenant, asked.item),
    ).fetchone()
    if stored is not None:
        if stored[10]:
            raise Refused([f"ended-item: {asked.item!r} is {stored[11]}; admit it under a new id"])
        if tuple(stored[:10]) != wanted:
            raise Different(
                [f"different-item: {asked.item!r} is already admitted with other content"]
            )
        return False
    conn.execute(
        "INSERT INTO sortyard.item (workspace_id, id, project_id, title, risk_tier, milestone_id)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (asked.tenant, asked.item, *wanted[:4]),
    )
    for blocker in wanted[9]:
        conn.execute(
            "INSERT INTO sortyard.item_link (workspace_id, item_id, blocked_by)"
            " VALUES (%s, %s, %s)",
            (asked.tenant, asked.item, blocker),
        )
    conn.execute(
        "INSERT INTO sortyard.item_spec (workspace_id, item_id, lane, repository, base, needs,"
        " spec) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (asked.tenant, asked.item, *wanted[4:7], Jsonb(needs), Jsonb(wanted[8])),
    )
    return True
