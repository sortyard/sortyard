"""Admit one item through the API, from inside the replica's API pod (replica/replica.sh lane).

    kubectl exec -i deployment/sortyard-api -- \\
        python - ITEM REPOSITORY LANE WORKSPACE PROJECT ROLE_BINDING < replica/admit.py

It does what an operator does and nothing else: it gets an operator token for ROLE_BINDING from
the interim credential (`sortyard-api --issue-operator-token`'s function) and sends
`POST /v1/workspaces/WORKSPACE/items` to the API's own port. The workspace, the project, the
operator and its role binding are there already: `sortyard-api --bootstrap` made them from
replica/bootstrap.toml. The item, its checks at admission and its workflow are the API's doing,
not this script's. Prints the HTTP status and the reply; exits 1 unless the item was admitted.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

import psycopg

from sortyard.api import auth
from sortyard.services.api import Config


def operator_token(config: Config, role_binding: str) -> str:
    with psycopg.connect(config.conninfo(), autocommit=True) as conn:
        return auth.issue_operator_token(conn, role_binding, 600).token


def main(argv: list[str]) -> int:
    item, repository, lane, workspace, project, role_binding = argv[1:7]
    config = Config.from_env()
    body = {
        "id": item,
        "project_id": project,
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
        f"http://127.0.0.1:{config.port}/v1/workspaces/{workspace}/items",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {operator_token(config, role_binding)}",
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
