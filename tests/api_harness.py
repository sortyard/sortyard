"""A running API service over a fresh, migrated, seeded Postgres database — for the API tests.

``running_api()`` creates a database (tests/pg.py), applies the chart's migrations, seeds one
workspace (``ws-a``) with the objects the §7 scenarios act on plus a second workspace
(``ws-b``), starts ``sortyard-api`` in-process against it and yields an :class:`Api` handle:
an HTTP client plus the tokens of every role. Operator tokens come from the interim operator
credential (``sortyard-api --issue-operator-token``); service-account tokens are issued
through the API itself (``issueServiceAccountToken``), as an admin would.
"""

from __future__ import annotations

import functools
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import psycopg
import psycopg.conninfo
from psycopg.types.json import Jsonb

from sortyard.api import auth
from sortyard.engine import WorkflowNotFound
from sortyard.kernel.item import INPUT_SIGNAL, workflow_id
from sortyard.kernel.ledger import Ledger
from sortyard.services import api
from tests.pg import fresh_database

WS = "ws-a"
OTHER_WS = "ws-b"
HASH0 = "sha256:" + "0" * 64
HASH1 = "sha256:" + "1" * 64

INSTALLATION = {
    "id": "inst-test",
    "cluster": {"name": "kind"},
    "namespaces": {"control_plane": "sortyard", "workers": "sortyard-jobs"},
    "storage": {"storage_class": "standard"},
    "ingress": {"host": "sortyard.invalid"},
    "auth_provider": {"kind": "oidc", "issuer": "https://auth.invalid/", "client_id": "c"},
}


def project(pid: str) -> dict[str, Any]:
    return {
        "id": pid,
        "workspace_id": WS,
        "name": pid,
        "archetype": {"id": "arch-saas-product", "version": "1.0.0"},
        "repos": [],
        "tracker": {"kind": "internal"},
        "state": "active",
    }


def task(tid: str, project_id: str = "proj-a", **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": tid,
        "workspace_id": WS,
        "project_id": project_id,
        "title": f"Task {tid}",
        "outcome": "Something is true afterwards.",
        "priority": {"tier": "normal"},
        "origin": "human",
        "state": "todo",
        "lane_id": "lane-a",
        "workflow": {"id": "wf-job", "version": "1.0.0"},
    }
    doc.update(extra)
    return doc


def stage_run(srid: str, state: str = "running") -> dict[str, Any]:
    return {
        "id": srid,
        "workspace_id": WS,
        "chain_id": "chain-seed",
        "stage": "build",
        "attempt": 1,
        "state": state,
        "execution_binding_id": "eb-seed",
        "inputs_packet_hash": HASH0,
        "inputs_packet_ref": f"packets/{srid}",
    }


def binding(ebid: str, task_id: str, state: str = "bound") -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": ebid,
        "workspace_id": WS,
        "task_id": task_id,
        "stage": "build",
        "state": state,
        "workflow": {"id": "wf-job", "version": "1.0.0"},
        "role": {"id": "role-implementer", "version": "1.0.0"},
        "computed_at": "2026-11-12T00:00:00Z",
    }
    if state == "bound":
        doc["unbound_reasons"] = []
        doc["context"] = {"recipe": {"id": "ctx-build", "version": "1.0.0"}, "packet_hash": HASH0}
        doc["place"] = {
            "lane_id": "lane-a",
            "cluster": "kind",
            "namespace": "sortyard-jobs",
            "agent": {"id": "agent-build", "version": "1.0.0"},
            "model": "claude-opus-5-5",
            "mirror": {
                "mirror_id": "mirror-a",
                "fresh": True,
                "observed_at": "2026-11-12T00:00:00Z",
            },
        }
        doc["resource_envelope"] = {
            "class": "light",
            "requests": {"cpu": "1", "memory": "1Gi"},
            "limits": {"cpu": "1", "memory": "1Gi"},
            "deadline_seconds": 600,
        }
    else:
        doc["unbound_reasons"] = [{"code": "mirror_stale", "subject": "mirror-a"}]
    return doc


def role_binding(rbid: str, kind: str, principal: str, role: str, **scope: Any) -> dict[str, Any]:
    return {
        "id": rbid,
        "workspace_id": WS,
        "principal": {"kind": kind, "id": principal},
        "role": role,
        "scope": scope or {"kind": "workspace"},
    }


# Operator accounts (RoleBinding roles, §3.9) and the agent service accounts (§7).
OPERATOR_BINDINGS = {
    "admin": role_binding("rb-admin", "operator", "op-admin", "admin"),
    "operator": role_binding("rb-operator", "operator", "op-operator", "operator"),
    "viewer": role_binding("rb-viewer", "operator", "op-viewer", "viewer"),
}
AGENT_BINDINGS = {
    "conductor": role_binding("rb-conductor", "agent", "sa-conductor", "agent-service-account"),
    "build-worker": role_binding("rb-builder", "agent", "sa-builder", "agent-service-account"),
    "sensor": role_binding("rb-sensor", "agent", "sa-sensor", "agent-service-account"),
    "grooming-agent": role_binding("rb-groomer", "agent", "sa-groomer", "agent-service-account"),
}
# The scope each agent token is issued for.
AGENT_SCOPE: dict[str, dict[str, str]] = {
    "conductor": {},
    "build-worker": {"stage_run_id": "sr-1"},
    "sensor": {"project_id": "proj-a"},
    "grooming-agent": {"project_id": "proj-a"},
}


def seed_rows() -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = [
        ("installation", INSTALLATION),
        ("workspace", {"id": WS, "installation_id": "inst-test", "name": "A"}),
        ("workspace", {"id": OTHER_WS, "installation_id": "inst-test", "name": "B"}),
        ("project", project("proj-a")),
        ("project", project("proj-b")),
    ]
    for name in ("admin", "operator", "viewer"):
        rows.append(
            (
                "operator",
                {
                    "id": f"op-{name}",
                    "workspace_id": WS,
                    "subject": f"oidc|{name}",
                    "display_name": name,
                    "state": "active",
                },
            )
        )
    rows += [("role_binding", rb) for rb in OPERATOR_BINDINGS.values()]
    rows += [("role_binding", rb) for rb in AGENT_BINDINGS.values()]
    rows += [
        (
            "lane",
            {
                "id": "lane-a",
                "workspace_id": WS,
                "name": "a",
                "scope": "conductor",
                "max_concurrent_chains": 1,
                "eligible_projects": ["proj-a"],
            },
        ),
        ("task", task("task-1")),
        ("task", task("task-2")),
        ("task", task("task-b", project_id="proj-b")),
        ("task", task("task-backlog", state="backlog")),
        ("execution_binding", binding("eb-1", "task-1")),
        ("execution_binding", binding("eb-2", "task-2")),
        ("execution_binding", binding("eb-unbound", "task-2", state="unbound")),
        ("stage_run", stage_run("sr-1")),
        ("stage_run", stage_run("sr-2")),
        (
            "integrator",
            {
                "id": "integrator-default",
                "workspace_id": WS,
                "fence": {
                    "proof_receipt": "passed_for_exact_base_candidate_pair",
                    "verify_approval": "exact_head",
                    "tree_identity": "asserted",
                },
                "landing": {"method": "git_data_api", "signed_commits": "recreated_byte_exact"},
                "credential_custody_ref": "cust-github-write",
                "runs": "operator-side",
            },
        ),
        (
            "decision",
            {
                "id": "dec-1",
                "workspace_id": WS,
                "project_id": "proj-a",
                "question": "Bundle, fork or native?",
                "options": ["bundle", "fork", "native"],
                "default": "native",
                "decide_by": "2026-12-01T00:00:00Z",
                "state": "open",
            },
        ),
        (
            "decision_log",
            {
                "id": "dl-1",
                "workspace_id": WS,
                "ts": "2026-11-12T00:00:00Z",
                "conductor_pass_id": "pass-1",
                "decision": "skip",
                "task_id": "task-1",
                "reason_codes": ["slot held: merging"],
                "inputs": {"policy_versions": [], "queue_snapshot_hash": HASH1},
            },
        ),
        (
            "policy",
            {
                "id": "pol-1",
                "workspace_id": WS,
                "version": "1.0.0",
                "scope": "global",
                "kind": "merge_gate",
                "parameters": {
                    "regime": "conductor_product_pr",
                    "review_count": 1,
                    "red_never_merges": True,
                    "force_merge": False,
                },
                "enforcement": "refuse",
                "absent_state": {"behaviour": "record", "reason_code": "coverage_gap"},
            },
        ),
        (
            "prioritization_policy",
            {
                "id": "prio-1",
                "workspace_id": WS,
                "version": "1.0.0",
                "scope": "global",
                "keys": ["urgent_flag", "priority_tier", "age"],
            },
        ),
        (
            "sequencing_policy",
            {
                "id": "seqp-1",
                "workspace_id": WS,
                "version": "1.0.0",
                "scope": "installation",
                "mode": "strict_global",
            },
        ),
    ]
    return rows


@dataclass
class Response:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)


ITEM = "item-1"


class FakeSignals:
    """The workflow engine's signal call, as the API service uses it: a strict fake.

    It accepts what the real engine accepts from this service and nothing else: the item input
    signal, for a workflow that exists. An unknown workflow raises `WorkflowNotFound`, as
    `Engine.signal` does (tests/test_engine_failure.py holds the real engine to that).
    """

    def __init__(self, running: set[str]) -> None:
        self.running = running
        self.sent: list[tuple[str, Any]] = []

    def __call__(self, workflow: str, name: str, payload: Any) -> None:
        assert name == INPUT_SIGNAL, f"the API service sends only {INPUT_SIGNAL}, not {name}"
        if workflow not in self.running:
            raise WorkflowNotFound(workflow)
        self.sent.append((workflow, payload))


@dataclass
class Api:
    base: str
    conninfo: str
    tokens: dict[str, str]

    def call(
        self,
        method: str,
        path: str,
        role: str | None = None,
        body: Any = None,
        *,
        token: str | None = None,
        content_type: str = "application/json",
    ) -> Response:
        """One request. ``role`` picks a seeded token; ``token`` overrides it."""
        bearer = token if token is not None else (self.tokens[role] if role else None)
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if bearer is not None:
            req.add_header("Authorization", f"Bearer {bearer}")
        if data is not None:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                status, headers = resp.status, dict(resp.headers)
        except urllib.error.HTTPError as err:
            raw = err.read()
            status, headers = err.code, dict(err.headers)
        return Response(status, json.loads(raw) if raw else None, headers)

    def ws(self, method: str, rest: str, role: str | None = None, body: Any = None) -> Response:
        return self.call(method, f"/v1/workspaces/{WS}{rest}", role, body)

    def db(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.conninfo, autocommit=True)

    def doc(self, table: str, oid: str) -> dict[str, Any] | None:
        with self.db() as conn:
            row = conn.execute(
                f"SELECT doc FROM sortyard.{table} WHERE id = %s ORDER BY recorded_at DESC",
                [oid],
            ).fetchone()
        return None if row is None else dict(row[0])

    def insert(self, table: str, doc: dict[str, Any]) -> None:
        with self.db() as conn:
            conn.execute(f"INSERT INTO sortyard.{table} (doc) VALUES (%s)", [Jsonb(doc)])

    def issue(self, agent_role: str, binding: str | None = None, **scope: str) -> Response:
        rb = binding or AGENT_BINDINGS[agent_role]["id"]
        return self.ws(
            "POST", f"/role-bindings/{rb}/tokens", "admin", {"agent_role": agent_role, **scope}
        )


def running_api(signal_item: Any = None) -> Iterator[Api]:
    """A migrated, seeded database and the API service on it.

    `signal_item` is how the service reaches the workflow engine. By default it is a
    `FakeSignals` that knows one running workflow, the seeded item's.
    """
    for database in fresh_database():
        proc = database.migrate()
        assert proc.returncode == 0, proc.stderr
        conninfo = psycopg.conninfo.make_conninfo(dbname=database.name)
        with psycopg.connect(conninfo, autocommit=True) as conn:
            for table, doc in seed_rows():
                conn.execute(f"INSERT INTO sortyard.{table} (doc) VALUES (%s)", [Jsonb(doc)])
            tokens = {
                role: auth.issue_operator_token(conn, rb["id"]).token
                for role, rb in OPERATOR_BINDINGS.items()
            }
        connect = functools.partial(psycopg.connect, conninfo)
        # One kernel item, not yet started, for the tracker view's operations.
        Ledger(connect).create_item(tenant=WS, item=ITEM, project="proj-a", title="An item")
        signals = signal_item or FakeSignals({workflow_id(WS, ITEM)})
        config = api.Config(host="127.0.0.1", port=0, database_name=database.name)
        server = api.make_server(config, connect=connect, signal_item=signals)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        handle = Api(f"http://127.0.0.1:{server.server_address[1]}", conninfo, tokens)
        try:
            for role, scope in AGENT_SCOPE.items():
                issued = handle.issue(role, **scope)
                assert issued.status == 201, issued.body
                tokens[role] = issued.body["token"]
            yield handle
        finally:
            server.shutdown()
            server.server_close()
