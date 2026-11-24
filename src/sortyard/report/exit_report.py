"""sortyard-exit-report: the phase 1 exit test, read from the ledger (SY-V3-PHASE1-EXIT).

HARNESS-V3 section 6 ends phase 1 when one item goes from admitted to merged with no hand
action, and then ten in a row. This command reads that from the ledger of one project over a
time window and asserts nothing: for each item that ended in the window it prints the admitted
and ended times and every transition with its owner and cause, says whether any transition
came from a request, and prints the longest run of consecutive merged items with no request
and no operator action.

What counts as a hand (the build team's reading of "no hand action"; no owner words say more):

- **A request.** A transition whose cause is `request` or that carries one, and the decision
  that answers it (its question's cause is `request`). A request is the one way a person moves
  an item: `requestItemChange` is the only operation that is not a read.
- **An operator action.** An Event whose actor is not the system, or an entry of the audit log
  by which a person acted on the item after admitting it (a request the workflow never put to
  a decision included). Admitting the item is how it starts, not a hand.

What is not a hand: fix rounds, passed limits, decisions answered by the policy, the item or
the table, and a wait on a capability gap that closed without a person.

The run: items in the order they ended (merged, or ended without merging, as a withdrawn
item does). A merged item with no hand adds one; any other item that ended restarts the count
at zero, so a run is never counted across an item that needed a hand. Items still open are
listed by count and do not touch the run.

  sortyard-exit-report --workspace WS --project P --since ISO [--until ISO] [--json]

The database is the one the services use (SORTYARD_DATABASE_HOST, _PORT, _NAME, _USER,
_PASSWORD); with no SORTYARD_DATABASE_HOST, the standard libpq variables. The session is
read-only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg

Conn = psycopg.Connection[Any]

_ITEMS = (
    "SELECT id, state, state_kind FROM sortyard.item"
    " WHERE workspace_id = %s AND project_id = %s ORDER BY position"
)
_EVENTS = (
    "SELECT e.object_id, e.seq, e.doc FROM sortyard.event AS e"
    " JOIN sortyard.item AS i ON (i.workspace_id, i.id) = (e.workspace_id, e.object_id)"
    " WHERE e.workspace_id = %s AND e.object_kind = 'item' AND i.project_id = %s ORDER BY e.seq"
)
# A person's acts on an item after admitting it: a request, or any act on the item but its
# creation. Admission audits ("create", "item"); a request audits ("create", "item_request")
# with the item in `after`.
_HANDS = (
    "SELECT doc FROM sortyard.audit_log WHERE workspace_id = %s AND ("
    "  (doc->'object'->>'kind' = 'item_request' AND doc->'after'->>'item_id' = ANY(%s))"
    "  OR (doc->'object'->>'kind' = 'item' AND doc->'object'->>'id' = ANY(%s)"
    "      AND doc->>'action' <> 'create'))"
    " ORDER BY recorded_at, id"
)


def _requested(facts: Mapping[str, Any]) -> bool:
    decision = facts.get("decision")
    question = decision.get("question") if isinstance(decision, Mapping) else None
    return (
        facts.get("cause") == "request"
        or facts.get("request") is not None
        or (isinstance(question, Mapping) and question.get("cause") == "request")
    )


def _transition(event: Mapping[str, Any]) -> dict[str, Any]:
    facts = event.get("facts") or {}
    move = event.get("transition") or {}
    decision = facts.get("decision")
    actor = event.get("actor") or {}
    return {
        "ts": event["ts"],
        "from": move.get("from"),
        "to": move.get("to"),
        "owner": facts.get("owner"),
        "cause": facts.get("cause"),
        "outcome": facts.get("outcome"),
        "decided_by": decision.get("source") if isinstance(decision, Mapping) else None,
        "lifecycle": (facts.get("lifecycle") or {}).get("kind"),
        "requested": _requested(facts),
        "operator": actor.get("kind") != "system",
    }


def _hand_of(entry: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The item an audit entry acted on, and the entry as the report shows it."""
    obj = entry.get("object") or {}
    after = entry.get("after") or {}
    item = after.get("item_id") if obj.get("kind") == "item_request" else obj.get("id")
    actor = entry.get("actor") or {}
    shown = {
        "ts": entry.get("ts"),
        "action": f"{entry.get('action')} {obj.get('kind')}",
        "by": actor.get("id"),
        "reason": entry.get("reason"),
    }
    return str(item), shown


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def report(
    conn: Conn, workspace: str, project: str, since: datetime, until: datetime
) -> dict[str, Any]:
    """The exit report of `project` for the items that ended in [since, until)."""
    items = conn.execute(_ITEMS, (workspace, project)).fetchall()
    events: dict[str, list[tuple[int, dict[str, Any]]]] = {row[0]: [] for row in items}
    for item, seq, doc in conn.execute(_EVENTS, (workspace, project)).fetchall():
        events[item].append((seq, doc))
    ids = list(events)
    hands: dict[str, list[dict[str, Any]]] = {item: [] for item in ids}
    for (entry,) in conn.execute(_HANDS, (workspace, ids, ids)).fetchall():
        item, shown = _hand_of(entry)
        if item in hands:
            hands[item].append(shown)

    ended: list[dict[str, Any]] = []
    still_open = 0
    for item, state, kind in items:
        history = events[item]
        if kind != "terminal" or not history:
            still_open += 1
            continue
        last_seq, last = history[-1]
        ended_at = _moment(last["ts"])
        if not since <= ended_at < until:
            continue
        transitions = [_transition(doc) for _, doc in history]
        requested = any(move["requested"] for move in transitions)
        operator = bool(hands[item]) or any(move["operator"] for move in transitions)
        merged = transitions[-1]["lifecycle"] == "merged"
        ended.append(
            {
                "item": item,
                "state": state,
                "merged": merged,
                "admitted_at": transitions[0]["ts"],
                "ended_at": last["ts"],
                "requested": requested,
                "operator_action": operator,
                "hands_off": merged and not requested and not operator,
                "transitions": transitions,
                "operator_acts": hands[item],
                "_order": (ended_at, last_seq),
            }
        )
    ended.sort(key=lambda entry: entry.pop("_order"))

    best: list[str] = []
    current: list[str] = []
    for entry in ended:
        current = [*current, entry["item"]] if entry["hands_off"] else []
        if len(current) > len(best):
            best = current
    return {
        "workspace": workspace,
        "project": project,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "items": ended,
        "still_open": still_open,
        "longest_hands_off_run": {"length": len(best), "items": best},
    }


def render(found: Mapping[str, Any]) -> str:
    """The report as text, one block per item that ended in the window."""
    lines = [
        f"exit report: workspace {found['workspace']}, project {found['project']},"
        f" ended in [{found['since']}, {found['until']})",
        "",
    ]
    for entry in found["items"]:
        verdict = "hands-off" if entry["hands_off"] else "needed a hand"
        if not entry["merged"]:
            verdict = f"ended {entry['state']} without merging (breaks the run)"
        lines += [
            f"{entry['item']}: {verdict}",
            f"  admitted {entry['admitted_at']}",
            f"  {'merged' if entry['merged'] else 'ended':<8} {entry['ended_at']}",
            f"  from a request: {'yes' if entry['requested'] else 'no'};"
            f" operator action: {'yes' if entry['operator_action'] else 'no'}",
            "  transitions (ts  from -> to  owner  cause):",
        ]
        for move in entry["transitions"]:
            notes = [
                note
                for note in (
                    move["outcome"] and f"outcome {move['outcome']}",
                    move["decided_by"] and f"decided by {move['decided_by']}",
                    move["requested"] and "REQUEST",
                    move["operator"] and "OPERATOR",
                )
                if note
            ]
            lines.append(
                f"    {move['ts']}  {move['from'] or '-'} -> {move['to']}"
                f"  {move['owner'] or '-'}  {move['cause']}"
                + (f"  [{', '.join(notes)}]" if notes else "")
            )
        for act in entry["operator_acts"]:
            lines.append(f"  operator act: {act['ts']} {act['action']} by {act['by']}")
        lines.append("")
    run = found["longest_hands_off_run"]
    merged = [entry for entry in found["items"] if entry["merged"]]
    lines += [
        f"merged: {len(merged)}; hands-off: {sum(e['hands_off'] for e in merged)};"
        f" ended without merging: {len(found['items']) - len(merged)};"
        f" still open: {found['still_open']}",
        f"longest run of merged items with no request and no operator action: {run['length']}"
        + (f" ({', '.join(run['items'])})" if run["items"] else ""),
    ]
    return "\n".join(lines) + "\n"


def _connect() -> Conn:
    env = os.environ
    if env.get("SORTYARD_DATABASE_HOST"):
        conn = psycopg.connect(
            host=env["SORTYARD_DATABASE_HOST"],
            port=env.get("SORTYARD_DATABASE_PORT", "5432"),
            dbname=env["SORTYARD_DATABASE_NAME"],
            user=env["SORTYARD_DATABASE_USER"],
            password=env["SORTYARD_DATABASE_PASSWORD"],
        )
    else:
        conn = psycopg.connect("")
    return conn


def _when(value: str) -> datetime:
    moment = _moment(value)
    if moment.utcoffset() is None:
        raise argparse.ArgumentTypeError(f"give the offset: {value!r}")
    return moment


def main(argv: Sequence[str] | None = None, connect: Callable[[], Conn] = _connect) -> int:
    parser = argparse.ArgumentParser(
        prog="sortyard-exit-report", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--since", required=True, type=_when, help="ISO time with its offset")
    parser.add_argument("--until", type=_when, help="ISO time with its offset (default: now)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    until = args.until or datetime.now(UTC)
    with connect() as conn:
        conn.read_only = True
        found = report(conn, args.workspace, args.project, args.since, until)
    sys.stdout.write(json.dumps(found, indent=2) + "\n" if args.json else render(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
