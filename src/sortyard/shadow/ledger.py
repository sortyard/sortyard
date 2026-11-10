"""Recording a shadow pass: DecisionLog entries + event ledger, in the shadow's own database.

One pass is written in one transaction:

- one ``sortyard.decision_log`` row per decision (``claim`` = would claim, ``skip`` = would
  refuse), carrying the reason codes, the queue snapshot hash, the policy version and the
  preview position (so "what would it claim, in what order" is ``ORDER BY preview_position``);
- one ledger event per entry (object ``task``, transition ``shadow_would_claim`` /
  ``shadow_would_skip``), linked both ways (``event_id`` / ``refs``);
- one ledger event for the pass itself (object ``conductor_pass``, transition
  ``shadow_pass``) carrying the full snapshot, the ordered would-claims and the refusals — the
  record the claim comparison (SORTYARD-9) diffs against the production conductor's pass.

Every write is marked ``mode: shadow`` and goes only to the ``sortyard`` schema. A pass tied
to a production conductor pass is recorded once: seeing the same production pass again is a
no-op.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sortyard.models import DecisionLogEntry
from sortyard.shadow.board import QueueSnapshot
from sortyard.shadow.evaluate import POLICY_ID, ClaimPolicy, ShadowDecision

ACTOR = {"kind": "system", "id": "shadow-conductor"}
_NOT_ID = re.compile(r"[^A-Za-z0-9._:/-]+")


def pass_id_for(snapshot: QueueSnapshot) -> str:
    """The shadow pass id: derived from the production pass when the input names one (so each
    production pass is recorded once), otherwise from the read time and snapshot hash."""
    base = snapshot.production_pass_id or f"{snapshot.taken_at}-{snapshot.content_hash()[7:19]}"
    return "shadow-" + _NOT_ID.sub("-", base).strip("-")[:150]


def ensure_workspace(
    conn: psycopg.Connection[Any], workspace_id: str, installation: dict[str, Any]
) -> None:
    """Create the workspace the DecisionLog is scoped to (and its installation) if missing."""
    with conn.transaction():
        conn.execute(
            "INSERT INTO sortyard.installation (doc) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            [Jsonb(installation)],
        )
        conn.execute(
            "INSERT INTO sortyard.workspace (doc) VALUES (%s) ON CONFLICT (id) DO NOTHING",
            [
                Jsonb(
                    {
                        "id": workspace_id,
                        "installation_id": installation["id"],
                        "name": workspace_id,
                    }
                )
            ],
        )


def record_pass(
    conn: psycopg.Connection[Any],
    *,
    workspace_id: str,
    snapshot: QueueSnapshot,
    policy: ClaimPolicy,
    decisions: list[ShadowDecision],
    ts: str,
) -> str | None:
    """Write one pass; returns its id, or None when this pass was already recorded."""
    pass_id = pass_id_for(snapshot)
    pass_event_id = f"evt-{pass_id}"
    snapshot_hash = snapshot.content_hash()
    policy_versions = [{"id": POLICY_ID, "version": policy.version}]
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [pass_event_id])
        seen = conn.execute("SELECT 1 FROM sortyard.event WHERE id = %s", [pass_event_id])
        if seen.fetchone() is not None:
            return None
        refs = []
        for n, d in enumerate(decisions):
            entry_id = f"dl-{pass_id}-{n:04d}"
            event_id = f"evt-{pass_id}-{n:04d}"
            refs.append(f"decision-log:{entry_id}")
            entry = DecisionLogEntry.from_dict(
                {
                    "id": entry_id,
                    "workspace_id": workspace_id,
                    "ts": ts,
                    "conductor_pass_id": pass_id,
                    "decision": d.decision,
                    "task_id": d.item_id,
                    "reason_codes": list(d.reason_codes),
                    "inputs": {
                        "policy_versions": policy_versions,
                        "queue_snapshot_hash": snapshot_hash,
                        "preview_position": d.preview_position,
                    },
                    "event_id": event_id,
                }
            ).to_dict()
            conn.execute("INSERT INTO sortyard.decision_log (doc) VALUES (%s)", [Jsonb(entry)])
            verb = "claim" if d.claimed else "skip"
            conn.execute(
                "SELECT sortyard.append_event(%s)",
                [
                    Jsonb(
                        {
                            "id": event_id,
                            "workspace_id": workspace_id,
                            "ts": ts,
                            "actor": ACTOR,
                            "object": {"kind": "task", "id": d.item_id},
                            "transition": {
                                "name": f"shadow_would_{verb}",
                                "from": d.state,
                                "to": d.state,
                            },
                            "facts": {
                                "mode": "shadow",
                                "conductor_pass_id": pass_id,
                                "decision": d.decision,
                                "reason_codes": list(d.reason_codes),
                                "preview_position": d.preview_position,
                                "lane": d.lane_id,
                            },
                            "refs": [f"decision-log:{entry_id}"],
                        }
                    )
                ],
            )
        conn.execute(
            "SELECT sortyard.append_event(%s)",
            [
                Jsonb(
                    {
                        "id": pass_event_id,
                        "workspace_id": workspace_id,
                        "ts": ts,
                        "actor": ACTOR,
                        "object": {"kind": "conductor_pass", "id": pass_id},
                        "transition": {"name": "shadow_pass"},
                        "facts": {
                            "mode": "shadow",
                            "production_pass_id": snapshot.production_pass_id,
                            "source": snapshot.source,
                            "taken_at": snapshot.taken_at,
                            "queue_snapshot_hash": snapshot_hash,
                            "policy_versions": policy_versions,
                            "would_claim": [d.item_id for d in decisions if d.claimed],
                            "would_refuse": {
                                d.item_id: list(d.reason_codes) for d in decisions if not d.claimed
                            },
                            "snapshot": snapshot.to_dict(),
                        },
                        "refs": refs,
                    }
                )
            ],
        )
    return pass_id
