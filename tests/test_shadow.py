"""Acceptance: the shadow conductor (design §8 Phase 1, §4; SORTYARD-8).

The shadow reads the real input path — the board view, the lane registry and the task_ready
gating output — strictly read-only, computes what the conductor WOULD claim (a pure function
over queue snapshot + policy + lane state), and records every would-claim and every refusal,
with reason codes, as DecisionLog entries in the event ledger. It never writes anywhere but
its own database.
"""

from __future__ import annotations

import json
import pathlib
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jsonschema  # type: ignore[import-untyped]
import pytest

from sortyard.models import DecisionLogEntry
from sortyard.services import conductor
from sortyard.shadow import board, evaluate, sources
from tests.pg import Database, fresh_database, requires_postgres
from tests.test_models import registry

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec"


def item(
    id: str,
    state: str = "Todo",
    group: str = "unstarted",
    priority: str = "medium",
    depends_on: tuple[str, ...] = (),
    labels: tuple[str, ...] = (),
    created_at: str = "2026-11-07T00:00:00Z",
) -> dict[str, Any]:
    return {
        "id": id,
        "project": id.rsplit("-", 1)[0],
        "title": f"item {id}",
        "state": state,
        "state_group": group,
        "priority": priority,
        "labels": list(labels),
        "depends_on": list(depends_on),
        "created_at": created_at,
    }


def board_view(**extra: Any) -> dict[str, Any]:
    """A board as drive.py sees it: two products, one lane each."""
    view: dict[str, Any] = {
        "taken_at": "2026-11-10T12:00:00Z",
        "source": "test board",
        "lanes": [
            {"id": "lane-sortyard", "project": "SORTYARD", "capacity": 1},
            {"id": "lane-rove", "project": "ROVE", "capacity": 2},
        ],
        "items": [
            item("SORTYARD-6", state="Done", group="completed"),
            item("SORTYARD-5", state="Done", group="completed"),
            item("SORTYARD-8", priority="high", depends_on=("SORTYARD-6",)),
            item("SORTYARD-9", priority="medium", depends_on=("SORTYARD-8",)),
            item("SORTYARD-13", priority="high", created_at="2026-11-08T00:00:00Z"),
            item("SORTYARD-7", priority="medium", depends_on=("SORTYARD-6", "SORTYARD-3")),
            item("SORTYARD-3", state="Backlog", group="backlog"),
            item("ROVE-1", state="In Progress", group="started"),
            item("ROVE-2", priority="low"),
            item("ROVE-3", priority="urgent"),
            item("ROVE-4", priority="none"),
            item("ROVE-5", labels=("on-hold",)),
            item("LOOP-1", priority="urgent"),
        ],
        "gating": {"ROVE-4": {"ready": False, "reason": "plan task T7 not ready"}},
    }
    view.update(extra)
    return view


# --- the decision function: pure, deterministic --------------------------------------------


def decide(view: dict[str, Any]) -> dict[str, evaluate.ShadowDecision]:
    snap = board.QueueSnapshot.from_dict(view)
    return {d.item_id: d for d in evaluate.evaluate(snap, evaluate.ClaimPolicy())}


def test_would_claim_in_priority_order_within_lane_capacity() -> None:
    snap = board.QueueSnapshot.from_dict(board_view())
    decisions = evaluate.evaluate(snap, evaluate.ClaimPolicy())
    claims = [d.item_id for d in decisions if d.decision == "claim"]
    # SORTYARD lane: one slot; SORTYARD-8 (high, older) beats SORTYARD-13 (high, newer).
    # ROVE lane: two slots, one held by ROVE-1; ROVE-3 (urgent) takes the free one.
    assert claims == ["ROVE-3", "SORTYARD-8"]
    # Every candidate (Todo) item gets exactly one decision; nothing else is decided.
    assert sorted(d.item_id for d in decisions) == sorted(
        i["id"] for i in board_view()["items"] if i["state_group"] == "unstarted"
    )
    positions = [d.preview_position for d in decisions]
    assert positions == sorted(positions) == list(range(len(decisions)))


def test_refusals_carry_reason_codes() -> None:
    d = decide(board_view())
    assert d["SORTYARD-9"].decision == "skip"
    assert list(d["SORTYARD-9"].reason_codes) == ["held: dependency SORTYARD-8 not done (Todo)"]
    assert list(d["SORTYARD-7"].reason_codes) == ["held: dependency SORTYARD-3 not done (Backlog)"]
    assert list(d["SORTYARD-13"].reason_codes) == [
        "throttled: lane lane-sortyard full (1/1)",
        "slot held: SORTYARD-8 would-claim",
    ]
    assert list(d["ROVE-2"].reason_codes) == [
        "throttled: lane lane-rove full (2/2)",
        "slot held: ROVE-1 In Progress",
        "slot held: ROVE-3 would-claim",
    ]
    assert list(d["ROVE-4"].reason_codes) == ["held: task_ready: plan task T7 not ready"]
    assert list(d["ROVE-5"].reason_codes) == ["held: label on-hold"]
    assert list(d["LOOP-1"].reason_codes) == ["unbound: no lane for project LOOP"]
    assert list(d["ROVE-3"].reason_codes) == ["eligible: lane lane-rove slot 2/2"]
    for decision in d.values():
        assert decision.reason_codes, decision


def test_occupied_slot_names_its_holder() -> None:
    view = board_view()
    view["items"].append(item("SORTYARD-99", state="In Review", group="started"))
    d = decide(view)
    assert d["SORTYARD-8"].decision == "skip"
    assert list(d["SORTYARD-8"].reason_codes) == [
        "throttled: lane lane-sortyard full (1/1)",
        "slot held: SORTYARD-99 In Review",
    ]


def test_unknown_dependency_holds() -> None:
    view = board_view()
    view["items"].append(item("ROVE-9", priority="urgent", depends_on=("ROVE-404",)))
    assert list(decide(view)["ROVE-9"].reason_codes) == [
        "held: dependency ROVE-404 not on the board"
    ]


def test_snapshot_hash_is_canonical() -> None:
    a = board.QueueSnapshot.from_dict(board_view())
    shuffled = board_view()
    shuffled["items"] = list(reversed(shuffled["items"]))
    shuffled["lanes"] = list(reversed(shuffled["lanes"]))
    b = board.QueueSnapshot.from_dict(shuffled)
    assert a.content_hash() == b.content_hash()
    assert a.content_hash().startswith("sha256:") and len(a.content_hash()) == 71
    changed = board_view()
    changed["items"][2]["priority"] = "low"
    assert board.QueueSnapshot.from_dict(changed).content_hash() != a.content_hash()
    # Same inputs, same answer (§4: a pure function over the snapshot).
    policy = evaluate.ClaimPolicy()
    assert evaluate.evaluate(a, policy) == evaluate.evaluate(b, policy)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Goal: x.\nDepends: HARNESS-311.\nTracking: y", ["HARNESS-311"]),
        ("Depends: SORTYARD-6, SORTYARD-2.", ["SORTYARD-6", "SORTYARD-2"]),
        ("<p>Depends on: SORTYARD-7 and SORTYARD-14</p>", ["SORTYARD-7", "SORTYARD-14"]),
        ("Depends: none — and it must land first", []),
        ("No dependency line; mentions SORTYARD-4 in passing.", []),
    ],
)
def test_description_level_dependencies(text: str, expected: list[str]) -> None:
    assert board.parse_depends(text) == expected


# --- the input path: read-only ---------------------------------------------------------------


class FakeUpstream:
    """An HTTP upstream that serves fixed JSON by path and records every request it sees."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def _any(self) -> None:
                upstream.requests.append(
                    (self.command, self.path, {k.lower(): v for k, v in self.headers.items()})
                )
                parts = urlsplit(self.path)
                key = parts.path
                cursor = parse_qs(parts.query).get("cursor")
                if cursor:
                    key = f"{key}?cursor={cursor[0]}"
                if self.command != "GET" or key not in upstream.routes:
                    self.send_response(405 if self.command != "GET" else 404)
                    self.end_headers()
                    return
                body = json.dumps(upstream.routes[key]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _any

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def methods(self) -> set[str]:
        return {method for method, _, _ in self.requests}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def upstream() -> Iterator[FakeUpstream]:
    up = FakeUpstream({"/board.json": board_view(production_pass_id="drive-pass-1")})
    yield up
    up.close()


def test_snapshot_source_reads_a_board_view_over_http(upstream: FakeUpstream) -> None:
    snap = sources.SnapshotSource(f"{upstream.url}/board.json").read()
    assert snap.production_pass_id == "drive-pass-1"
    assert {i.id for i in snap.items} >= {"SORTYARD-8", "ROVE-3"}
    assert upstream.methods() == {"GET"}


def test_snapshot_source_reads_a_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "board.json"
    path.write_text(json.dumps(board_view()))
    snap = sources.SnapshotSource(str(path)).read()
    assert snap.content_hash() == board.QueueSnapshot.from_dict(board_view()).content_hash()


def test_the_http_client_refuses_anything_but_get() -> None:
    client = sources.ReadOnlyHttp()
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(sources.ReadOnlyViolation):
            client.request(method, "http://127.0.0.1:9/")


PLANE_PROJECT = "10d493fb-4cef-4ef1-ab70-a0aefca87d59"


def plane_routes() -> dict[str, Any]:
    base = f"/api/v1/workspaces/noncelogic/projects/{PLANE_PROJECT}"
    states = [
        {"id": "st-todo", "name": "Todo", "group": "unstarted"},
        {"id": "st-prog", "name": "In Progress", "group": "started"},
        {"id": "st-done", "name": "Done", "group": "completed"},
        {"id": "st-back", "name": "Backlog", "group": "backlog"},
    ]
    issues_page_1 = [
        {
            "id": "u6",
            "sequence_id": 6,
            "name": "schema",
            "state": "st-done",
            "priority": "high",
            "labels": [],
            "description_stripped": "Depends: SORTYARD-5.",
            "created_at": "2026-11-07T00:00:00Z",
        },
        {
            "id": "u8",
            "sequence_id": 8,
            "name": "shadow conductor",
            "state": "st-todo",
            "priority": "high",
            "labels": ["lb-heal"],
            "description_html": "<p>Depends: SORTYARD-6.</p>",
            "created_at": "2026-11-07T00:00:01Z",
        },
    ]
    issues_page_2 = [
        {
            "id": "u9",
            "sequence_id": 9,
            "name": "comparator",
            "state": "st-todo",
            "priority": "medium",
            "labels": [],
            "description_stripped": "Depends: SORTYARD-8.",
            "created_at": "2026-11-07T00:00:02Z",
        },
    ]
    return {
        f"{base}/": {"id": PLANE_PROJECT, "identifier": "SORTYARD", "name": "Sortyard"},
        f"{base}/states/": {"results": states},
        f"{base}/labels/": {"results": [{"id": "lb-heal", "name": "self-heal"}]},
        f"{base}/issues/": {
            "results": issues_page_1,
            "next_page_results": True,
            "next_cursor": "100:1:0",
        },
        f"{base}/issues/?cursor=100:1:0": {
            "results": issues_page_2,
            "next_page_results": False,
            "next_cursor": "100:2:0",
        },
    }


def test_plane_source_builds_the_board_view_read_only(tmp_path: pathlib.Path) -> None:
    up = FakeUpstream(plane_routes())
    lanes = tmp_path / "products.json"
    lanes.write_text(json.dumps({"sortyard": {"lanes": 1, "tasks": False}}))
    try:
        snap = sources.PlaneSource(
            base_url=up.url,
            workspace_slug="noncelogic",
            project_ids=[PLANE_PROJECT],
            api_key="read-key",
            lanes_path=str(lanes),
        ).read()
    finally:
        up.close()
    assert up.methods() == {"GET"}
    assert all(headers.get("x-api-key") == "read-key" for _, _, headers in up.requests)
    by_id = {i.id: i for i in snap.items}
    assert set(by_id) == {"SORTYARD-6", "SORTYARD-8", "SORTYARD-9"}
    assert by_id["SORTYARD-8"].state == "Todo"
    assert by_id["SORTYARD-8"].state_group == "unstarted"
    assert by_id["SORTYARD-8"].labels == ("self-heal",)
    assert by_id["SORTYARD-8"].depends_on == ("SORTYARD-6",)
    assert [(lane.id, lane.project, lane.capacity) for lane in snap.lanes] == [
        ("lane-sortyard", "SORTYARD", 1)
    ]
    claims = [d.item_id for d in evaluate.evaluate(snap, evaluate.ClaimPolicy()) if d.claimed]
    assert claims == ["SORTYARD-8"]


# --- the service: DecisionLog entries in the event ledger -------------------------------------


@pytest.fixture
def db() -> Iterator[Database]:
    yield from fresh_database()


def schema_validator() -> Any:
    schema = json.loads((SPEC / "decision-log.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema, registry=registry())


def run_shadow(db: Database, monkeypatch: pytest.MonkeyPatch, snapshot: str, *argv: str) -> int:
    monkeypatch.setenv("SORTYARD_DATABASE_NAME", db.name)
    monkeypatch.setenv("SORTYARD_SHADOW_SOURCE", "snapshot")
    monkeypatch.setenv("SORTYARD_SHADOW_SNAPSHOT", snapshot)
    monkeypatch.setenv("SORTYARD_SHADOW_WORKSPACE", "ws-shadow-test")
    return conductor.main(["--shadow", "--once", *argv])


@requires_postgres
def test_shadow_pass_fills_the_decision_log(
    db: Database, upstream: FakeUpstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert db.migrate().returncode == 0
    assert run_shadow(db, monkeypatch, f"{upstream.url}/board.json") == 0

    entries = db.json(
        "SELECT coalesce(json_agg(doc ORDER BY (doc->'inputs'->>'preview_position')::int), '[]')"
        " FROM sortyard.decision_log"
    )
    snap = board.QueueSnapshot.from_dict(board_view(production_pass_id="drive-pass-1"))
    expected = evaluate.evaluate(snap, evaluate.ClaimPolicy())
    assert [(e["task_id"], e["decision"], e["reason_codes"]) for e in entries] == [
        (d.item_id, d.decision, list(d.reason_codes)) for d in expected
    ]
    validator = schema_validator()
    for entry in entries:
        validator.validate(entry)
        DecisionLogEntry.from_dict(entry)
        assert entry["workspace_id"] == "ws-shadow-test"
        assert entry["conductor_pass_id"] == "shadow-drive-pass-1"
        assert entry["inputs"]["queue_snapshot_hash"] == snap.content_hash()
        assert entry["inputs"]["policy_versions"] == [
            {"id": "shadow-claim-policy", "version": evaluate.ClaimPolicy().version}
        ]
    # The would-claim order is a query: claims by preview position.
    assert [e["task_id"] for e in entries if e["decision"] == "claim"] == ["ROVE-3", "SORTYARD-8"]

    # Each entry is linked to a ledger event, and the pass itself is one ledger event.
    for entry in entries:
        (event,) = db.json(
            "SELECT json_agg(doc) FROM sortyard.event WHERE id = :'id'", {"id": entry["event_id"]}
        )
        assert event["object"] == {"kind": "task", "id": entry["task_id"]}
        assert event["actor"] == {"kind": "system", "id": "shadow-conductor"}
        assert event["facts"]["mode"] == "shadow"
        assert event["refs"] == [f"decision-log:{entry['id']}"]
    (pass_event,) = db.json(
        "SELECT json_agg(h) FROM sortyard.object_history('conductor_pass', 'shadow-drive-pass-1') h"
    )
    facts = pass_event["facts"]
    assert pass_event["transition"]["name"] == "shadow_pass"
    assert facts["mode"] == "shadow"
    assert facts["production_pass_id"] == "drive-pass-1"
    assert facts["would_claim"] == ["ROVE-3", "SORTYARD-8"]
    assert facts["would_refuse"]["LOOP-1"] == ["unbound: no lane for project LOOP"]
    assert facts["queue_snapshot_hash"] == snap.content_hash()
    assert board.QueueSnapshot.from_dict(facts["snapshot"]).content_hash() == snap.content_hash()

    # The same production pass observed again records nothing new.
    before = db.value("SELECT count(*) FROM sortyard.event")
    assert run_shadow(db, monkeypatch, f"{upstream.url}/board.json") == 0
    assert db.value("SELECT count(*) FROM sortyard.event") == before
    assert db.value("SELECT count(*) FROM sortyard.decision_log") == str(len(entries))

    # Read-only against the live input path: only GETs ever reached it.
    assert upstream.methods() == {"GET"}


@requires_postgres
def test_each_production_pass_is_recorded(
    db: Database, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    assert db.migrate().returncode == 0
    path = tmp_path / "board.json"
    for n in (1, 2):
        path.write_text(json.dumps(board_view(production_pass_id=f"drive-pass-{n}")))
        assert run_shadow(db, monkeypatch, str(path)) == 0
    passes = db.value(
        "SELECT string_agg(DISTINCT conductor_pass_id, ',' ORDER BY conductor_pass_id)"
        " FROM sortyard.decision_log"
    )
    assert passes == "shadow-drive-pass-1,shadow-drive-pass-2"


@requires_postgres
def test_an_unreachable_input_records_nothing(
    db: Database, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    assert db.migrate().returncode == 0
    requested: list[str] = []

    def unreachable(
        self: sources.ReadOnlyHttp, method: str, url: str, headers: Any = None
    ) -> bytes:
        requested.append(url)
        raise sources.SourceError(f"GET {url}: connection refused")

    # Deterministic outage: no real socket, so host state cannot change the outcome.
    monkeypatch.setattr(sources.ReadOnlyHttp, "request", unreachable)
    with caplog.at_level("WARNING"):
        # --once reports the failed pass; the long-running loop logs it and tries next cycle.
        assert run_shadow(db, monkeypatch, "http://board.invalid/board.json") == 1
    assert requested == ["http://board.invalid/board.json"]
    assert "input path unavailable" in caplog.text
    assert db.value("SELECT count(*) FROM sortyard.decision_log") == "0"


def test_without_shadow_the_conductor_is_still_the_stub(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        assert conductor.main(["--once"]) == 0
    assert "conductor: stub service started" in caplog.text
