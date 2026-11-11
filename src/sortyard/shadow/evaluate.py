"""The claim decision (design §4): a pure function over (queue snapshot, policy, lane state).

No I/O, no clock, no randomness: the same snapshot and policy always give the same decisions,
which is what makes a shadow decision comparable with the production conductor's.

The rules, applied to every candidate — a board item in a ``unstarted`` (Todo) state:

1. Order. Candidates are ranked by priority (urgent, high, medium, low, none), then by age
   (``created_at``), then by id. The rank is the item's ``preview_position``.
2. Holds, each with its reason code; any hold refuses the item (``skip``):
   - ``unbound: no lane for project P``          — the project has no registered lane;
   - ``held: task_ready: <reason>``                — the task_ready gate says not ready;
   - ``held: label <l>``                           — the item carries a hold label;
   - ``held: dependency X not done (<state>)``     — a ``Depends:`` item is not completed;
   - ``held: dependency X not on the board``       — a ``Depends:`` item cannot be found.
3. Lane capacity. Walking candidates in order, an unheld item is claimed when its project's
   lane has a free slot (``eligible: lane L slot k/cap``); otherwise it is refused with
   ``throttled: lane L full (n/cap)`` followed by one ``slot held: <item> <state>`` per item
   holding a slot: items in a ``started`` state hold their project's lane, and an item this
   pass would claim holds it as ``would-claim``.

The policy is versioned; its version is written into every DecisionLog entry, so a change to
these rules is visible in the record rather than read as a divergence (corpus R5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sortyard.shadow.board import PRIORITIES, BoardItem, QueueSnapshot

POLICY_ID = "shadow-claim-policy"


@dataclass(frozen=True)
class ClaimPolicy:
    version: str = "1.0.0"
    hold_labels: frozenset[str] = field(
        default_factory=lambda: frozenset({"blocked", "on-hold", "hold"})
    )


@dataclass(frozen=True)
class ShadowDecision:
    item_id: str
    decision: str  # "claim" | "skip"
    reason_codes: tuple[str, ...]
    preview_position: int
    lane_id: str | None
    state: str

    @property
    def claimed(self) -> bool:
        return self.decision == "claim"


def _rank(item: BoardItem) -> tuple[int, str, str]:
    return (PRIORITIES.index(item.priority), item.created_at, item.id)


def _holds(item: BoardItem, snapshot: QueueSnapshot, policy: ClaimPolicy) -> list[str]:
    by_id = {i.id: i for i in snapshot.items}
    reasons: list[str] = []
    gate = snapshot.gating.get(item.id)
    if gate is not None and not gate.ready:
        reasons.append(f"held: task_ready: {gate.reason or 'not ready'}")
    reasons += [f"held: label {label}" for label in item.labels if label in policy.hold_labels]
    for dep in item.depends_on:
        target = by_id.get(dep)
        if target is None:
            reasons.append(f"held: dependency {dep} not on the board")
        elif target.state_group != "completed":
            reasons.append(f"held: dependency {dep} not done ({target.state})")
    return reasons


def evaluate(snapshot: QueueSnapshot, policy: ClaimPolicy) -> list[ShadowDecision]:
    """One decision per candidate, in preview order: what the conductor would claim and refuse."""
    lanes = {lane.project: lane for lane in snapshot.lanes}
    holders: dict[str, list[BoardItem]] = {project: [] for project in lanes}
    for item in snapshot.items:
        if item.state_group == "started" and item.project in holders:
            holders[item.project].append(item)

    candidates = sorted((i for i in snapshot.items if i.state_group == "unstarted"), key=_rank)
    decisions: list[ShadowDecision] = []
    for position, item in enumerate(candidates):
        lane = lanes.get(item.project)
        if lane is None:
            reasons = [f"unbound: no lane for project {item.project}"]
        else:
            reasons = _holds(item, snapshot, policy)
        if not reasons and lane is not None:
            held = holders[item.project]
            if len(held) < lane.capacity:
                held.append(item)
                decisions.append(
                    ShadowDecision(
                        item_id=item.id,
                        decision="claim",
                        reason_codes=(
                            f"eligible: lane {lane.id} slot {len(held)}/{lane.capacity}",
                        ),
                        preview_position=position,
                        lane_id=lane.id,
                        state=item.state,
                    )
                )
                continue
            reasons = [f"throttled: lane {lane.id} full ({len(held)}/{lane.capacity})"]
            reasons += [
                f"slot held: {h.id} {h.state if h.state_group == 'started' else 'would-claim'}"
                for h in held
            ]
        decisions.append(
            ShadowDecision(
                item_id=item.id,
                decision="skip",
                reason_codes=tuple(reasons),
                preview_position=position,
                lane_id=lane.id if lane is not None else None,
                state=item.state,
            )
        )
    return decisions
