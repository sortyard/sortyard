"""Admit one item through the API, from inside the replica's API pod (replica/replica.sh lane).

    kubectl exec -i deployment/sortyard-api -- python - ITEM REPOSITORY LANE < replica/admit.py

The replica has no operator yet, so this first makes what an operator's call needs, once: a
workspace, a project, an operator and its role binding, written the way the tests seed them,
and an operator token from the interim credential (`sortyard-api --issue-operator-token`'s
function). Then it does what an operator does: `POST /v1/workspaces/<id>/items` on the API's
own port. The item, its checks at admission and its workflow are the API's doing, not this
script's. Prints the HTTP status and the reply; exits 1 unless the item was admitted.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sortyard.api import auth
from sortyard.services.api import Config
from sortyard.services.conductor import provisional_installation
from sortyard.shadow.ledger import ensure_workspace

WORKSPACE, PROJECT, OPERATOR, BINDING = (
    "ws-replica-lane",
    "proj-replica",
    "op-replica",
    "rb-replica",
)
SEED: list[tuple[str, dict[str, Any]]] = [
    (
        "project",
        {
            "id": PROJECT,
            "workspace_id": WORKSPACE,
            "name": PROJECT,
            "archetype": {"id": "arch-saas-product", "version": "1.0.0"},
            "repos": [],
            "tracker": {"kind": "internal"},
            "state": "active",
        },
    ),
    (
        "operator",
        {
            "id": OPERATOR,
            "workspace_id": WORKSPACE,
            "subject": "replica|operator",
            "display_name": "replica operator",
            "state": "active",
        },
    ),
    (
        "role_binding",
        {
            "id": BINDING,
            "workspace_id": WORKSPACE,
            "principal": {"kind": "operator", "id": OPERATOR},
            "role": "operator",
            "scope": {"kind": "workspace"},
        },
    ),
]


def operator_token(config: Config) -> str:
    with psycopg.connect(config.conninfo(), autocommit=True) as conn:
        ensure_workspace(conn, WORKSPACE, provisional_installation(os.environ))
        for table, doc in SEED:
            # The table names are the three constants above.
            if not conn.execute(
                f"SELECT 1 FROM sortyard.{table} WHERE id = %s", [doc["id"]]
            ).fetchone():
                conn.execute(f"INSERT INTO sortyard.{table} (doc) VALUES (%s)", [Jsonb(doc)])
        return auth.issue_operator_token(conn, BINDING, 600).token


def main(argv: list[str]) -> int:
    item, repository, lane = argv[1:4]
    config = Config.from_env()
    body = {
        "id": item,
        "project_id": PROJECT,
        "title": f"Replica item {item}",
        "lane": lane,
        "repository": repository,
        "risk_tier": "low",
        "spec": {
            "outcome": "The repository holds a change made for this item.",
            "acceptance": [{"test": "tests/test_replica.py", "name": f"item {item} is merged"}],
        },
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{config.port}/v1/workspaces/{WORKSPACE}/items",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {operator_token(config)}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, reply = response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        with error:
            status, reply = error.code, error.read().decode()
    print(status, reply)
    return 0 if status in (200, 201) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
