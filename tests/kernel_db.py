"""Shared pieces of the kernel's database tests: a fresh migrated Postgres with two tenants,
admission straight through the kernel, and transitions recorded as the item workflow does."""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import psycopg.conninfo
from psycopg.types.json import Jsonb

from sortyard.kernel.admission import Admission, admit
from sortyard.kernel.capabilities import Lane
from sortyard.kernel.ledger import Ledger
from sortyard.kernel.states import shipped
from tests.api_harness import INSTALLATION, OTHER_WS, WS, project
from tests.pg import fresh_database

Connect = Callable[[], "psycopg.Connection[Any]"]
PROJECTS = {WS: "proj-a", OTHER_WS: "proj-theirs"}  # each tenant's one project
SPEC = {"outcome": "it works", "acceptance": [{"test": "tests/test_it.py", "name": "it works"}]}


def database() -> Iterator[Connect]:
    """A fresh migrated database with two tenants; yields how to connect to it."""
    for made in fresh_database():
        proc = made.migrate()
        assert proc.returncode == 0, proc.stderr
        opener = functools.partial(
            psycopg.connect, psycopg.conninfo.make_conninfo(dbname=made.name)
        )
        with opener(autocommit=True) as conn:
            conn.execute(
                "INSERT INTO sortyard.installation (doc) VALUES (%s)", [Jsonb(INSTALLATION)]
            )
            for tenant in (WS, OTHER_WS):
                doc = {"id": tenant, "installation_id": INSTALLATION["id"], "name": tenant}
                conn.execute("INSERT INTO sortyard.workspace (doc) VALUES (%s)", [Jsonb(doc)])
                mine = {**project(PROJECTS[tenant]), "workspace_id": tenant}
                conn.execute("INSERT INTO sortyard.project (doc) VALUES (%s)", [Jsonb(mine)])
        yield opener


def admitted(
    connect: Connect, lanes: dict[str, Lane], item: str, *, lane: str, tenant: str = WS, **more: Any
) -> None:
    """Admit an item through the kernel's own admission, as the API service does."""
    repository = next(iter(lanes[lane].repositories))
    asked = Admission(
        tenant=tenant,
        item=item,
        project=PROJECTS[tenant],
        title=f"Item {item}",
        lane=lane,
        repository=repository,
        spec=SPEC,
        **more,
    )
    with connect() as conn:
        assert admit(conn, lanes, asked)


def enter(connect: Connect, item: str, state: str, *, tenant: str = WS, **fields: Any) -> int:
    """Record that the item entered `state`, as its workflow's record step would; the
    transition's sequence, which is the stay's dispatch number unless `fields` says otherwise."""
    declared = shipped().state(state)
    with connect() as conn:
        row = conn.execute(
            "SELECT sequence, state, state_kind FROM sortyard.item"
            " WHERE workspace_id = %s AND id = %s",
            (tenant, item),
        ).fetchone()
    assert row is not None
    sequence: int = row[0] + 1
    Ledger(connect).record(
        {
            "item": item,
            "tenant": tenant,
            "sequence": sequence,
            "state": state,
            "state_kind": declared.kind,
            "lifecycle": declared.lifecycle,
            "owner": declared.owner,
            "limit": declared.limit.text if declared.limit else None,
            "reason": declared.reason,
            "entered_at": datetime.now(UTC).isoformat(),
            "from_state": row[1],
            "from_kind": row[2],
            "cause": "start" if sequence == 1 else "outcome",
            "dispatch": sequence,
            "attempt": 1,
            "action": None,
            "detail": {},
            "deadline": None,
            **fields,
        }
    )
    return sequence
