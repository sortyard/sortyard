"""Acceptance: SQL migrations create the §3 object tables and the append-only event ledger.

The static half needs nothing. The database half runs the chart's own migration script
(charts/sortyard/migrations/migrate.sh, the command of the migration Job) against a brand-new
empty Postgres database, then round-trips every §3 example through its generated model and its
table. See tests/pg.py for how a database is provided.
"""

from __future__ import annotations

import copy
import json
import pathlib
import re
import shutil
from collections.abc import Iterator
from typing import Any

import pytest

from sortyard import models
from tests.pg import MIGRATIONS, Database, fresh_database, requires_postgres

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec"
# Embedded value objects with no identity: stored inside their owner's document, no table.
EMBEDDED = {"resource-envelope"}
# Streams that only ever grow: UPDATE, DELETE and TRUNCATE are refused.
APPEND_ONLY = {"event", "decision_log", "audit_log"}
# Rows other rows point at, so they go in first.
FIRST = ["installation", "workspace"]


def schema(kind: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SPEC / f"{kind}.schema.json").read_text())
    return data


def table(kind: str) -> str:
    return kind.replace("-", "_")


def migration_files() -> list[pathlib.Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def created_tables() -> set[str]:
    sql = "\n".join(p.read_text() for p in migration_files())
    return set(re.findall(r"CREATE TABLE sortyard\.(\w+)", sql))


def ordered_examples() -> list[tuple[str, dict[str, Any]]]:
    kinds = FIRST + sorted(set(models.MODELS) - set(FIRST) - EMBEDDED)
    return [(kind, example) for kind in kinds for example in schema(kind)["examples"]]


# --- static -------------------------------------------------------------------------------


def test_migrations_are_ordered_sql_files() -> None:
    names = [p.name for p in migration_files()]
    assert names, "no migrations"
    assert all(re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", n) for n in names), names
    assert len({n[:4] for n in names}) == len(names), "duplicate migration number"


def test_migrations_do_not_manage_their_own_transactions() -> None:
    # migrate.sh applies each file in one transaction together with its bookkeeping row.
    for p in migration_files():
        assert not re.search(r"^\s*(BEGIN|COMMIT|ROLLBACK)\s*;", p.read_text(), re.I | re.M), p


def test_every_section_3_object_has_a_table() -> None:
    expected = {table(kind) for kind in models.MODELS if kind not in EMBEDDED}
    assert created_tables() == expected


def test_generated_columns_name_real_schema_properties() -> None:
    """Indexed columns are projections of the document (doc->>'x'), never a second copy that
    could drift; each one must name a property the schema actually has."""
    sql = "\n".join(p.read_text() for p in migration_files())
    blocks = re.findall(r"CREATE TABLE sortyard\.(\w+) \((.*?)\n\);", sql, re.S)
    assert blocks
    kinds = {table(k): k for k in models.MODELS}
    for name, body in blocks:
        props = set(models.MODELS[kinds[name]].json_fields())
        for key in re.findall(r"GENERATED ALWAYS AS \(doc ->> '(\w+)'\)", body):
            assert key in props, f"{name}: {key}"


# --- database -----------------------------------------------------------------------------


@pytest.fixture
def empty_db() -> Iterator[Database]:
    yield from fresh_database()


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    for database in fresh_database():
        proc = database.migrate()
        assert proc.returncode == 0, proc.stderr
        yield database


def insert(db: Database, kind: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Store a document; return it as the database now holds it."""
    if kind == "event":
        # The ledger, not the writer, assigns an event's position.
        unpositioned = {k: v for k, v in doc.items() if k != "seq"}
        seq = db.value(
            "SELECT sortyard.append_event(:'doc'::jsonb)", {"doc": json.dumps(unpositioned)}
        )
        return {**unpositioned, "seq": int(seq)}
    db.run(
        f"INSERT INTO sortyard.{table(kind)} (doc) VALUES (:'doc'::jsonb)", {"doc": json.dumps(doc)}
    )
    return doc


@requires_postgres
def test_clean_install_on_an_empty_database(empty_db: Database) -> None:
    proc = empty_db.migrate()
    assert proc.returncode == 0, proc.stderr
    applied = empty_db.value(
        "SELECT string_agg(version, ',' ORDER BY version) FROM sortyard.schema_migration"
    )
    assert applied.split(",") == [p.stem for p in migration_files()]
    tables = empty_db.value(
        "SELECT string_agg(table_name, ',') FROM information_schema.tables "
        "WHERE table_schema = 'sortyard' AND table_type = 'BASE TABLE'"
    )
    assert set(tables.split(",")) == created_tables() | {"schema_migration"}


@requires_postgres
def test_migrating_twice_is_a_no_op(empty_db: Database) -> None:
    assert empty_db.migrate().returncode == 0
    again = empty_db.migrate()
    assert again.returncode == 0, again.stderr
    assert "already applied" in again.stdout
    assert empty_db.value("SELECT count(*) FROM sortyard.schema_migration") == str(
        len(migration_files())
    )


@requires_postgres
def test_an_applied_migration_that_changed_is_refused(
    empty_db: Database, tmp_path: pathlib.Path
) -> None:
    assert empty_db.migrate().returncode == 0
    edited = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, edited)
    first = sorted(edited.glob("*.sql"))[0]
    first.write_text(first.read_text() + "\n-- edited after release\n")
    proc = empty_db.migrate(edited)
    assert proc.returncode != 0
    assert "changed after it was applied" in proc.stderr


@requires_postgres
def test_a_failing_migration_leaves_no_trace(empty_db: Database, tmp_path: pathlib.Path) -> None:
    broken = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, broken)
    (broken / "9999_broken.sql").write_text(
        "CREATE TABLE sortyard.half_done (x int);\nSELECT 1/0;\n"
    )
    proc = empty_db.migrate(broken)
    assert proc.returncode != 0
    assert empty_db.value("SELECT to_regclass('sortyard.half_done') IS NULL") == "t"
    assert (
        empty_db.value(
            "SELECT count(*) FROM sortyard.schema_migration WHERE version = '9999_broken'"
        )
        == "0"
    )


@requires_postgres
def test_every_section_3_example_round_trips_through_postgres(db: Database) -> None:
    for kind, example in ordered_examples():
        model = models.MODELS[kind]
        expected = insert(db, kind, model.from_dict(copy.deepcopy(example)).to_dict())
        stored = db.json(
            f"SELECT doc FROM sortyard.{table(kind)} WHERE id = :'id'", {"id": example["id"]}
        )
        assert model.from_dict(stored).to_dict() == expected, kind
        assert {k: v for k, v in expected.items() if k != "seq"} == {
            k: v for k, v in example.items() if k != "seq"
        }, kind


@requires_postgres
def test_rows_are_scoped_to_an_existing_workspace(db: Database) -> None:
    task = copy.deepcopy(schema("task")["examples"][0])
    task.update(id="task-orphan", workspace_id="ws-nowhere")
    err = db.error(
        "INSERT INTO sortyard.task (doc) VALUES (:'doc'::jsonb)", {"doc": json.dumps(task)}
    )
    assert "foreign key" in err


@requires_postgres
def test_documents_without_an_id_are_refused(db: Database) -> None:
    err = db.error('INSERT INTO sortyard.task (doc) VALUES (\'{"workspace_id": "ws-noncelogic"}\')')
    assert "null value" in err


@requires_postgres
def test_definition_versions_are_immutable(db: Database) -> None:
    policy = copy.deepcopy(schema("policy")["examples"][0])
    policy["id"] = "pol-immutable"
    insert(db, "policy", policy)
    err = db.error(
        "UPDATE sortyard.policy SET doc = doc || '{\"name\": \"x\"}' WHERE id = 'pol-immutable'"
    )
    assert "immutable" in err
    # A change is a new version, not an edit.
    insert(db, "policy", {**policy, "version": "1.0.1"})
    assert db.value("SELECT count(*) FROM sortyard.policy WHERE id = 'pol-immutable'") == "2"
    err = db.error(
        "INSERT INTO sortyard.policy (doc) VALUES (:'doc'::jsonb)", {"doc": json.dumps(policy)}
    )
    assert "duplicate key" in err


@requires_postgres
def test_state_objects_are_updated_in_place(db: Database) -> None:
    task = copy.deepcopy(schema("task")["examples"][0])
    task["id"] = "task-mutable"
    insert(db, "task", task)
    db.run(
        "UPDATE sortyard.task SET doc = jsonb_set(doc, '{state}', '\"claimed\"') "
        "WHERE id = 'task-mutable'"
    )
    assert db.value("SELECT state FROM sortyard.task WHERE id = 'task-mutable'") == "claimed"


# --- the event ledger ---------------------------------------------------------------------


def event(event_id: str, object_id: str = "task-ledger", name: str = "claim") -> dict[str, Any]:
    doc: dict[str, Any] = copy.deepcopy(schema("event")["examples"][0])
    del doc["seq"]
    doc.update(id=event_id, object={"kind": "task", "id": object_id})
    doc["transition"] = {"name": name, "from": None, "to": "claimed"}
    return doc


def append(db: Database, doc: dict[str, Any]) -> int:
    return int(db.value("SELECT sortyard.append_event(:'doc'::jsonb)", {"doc": json.dumps(doc)}))


@requires_postgres
def test_the_ledger_assigns_monotonic_positions(db: Database) -> None:
    first = append(db, event("evt-mono-1"))
    second = append(db, event("evt-mono-2"))
    assert second > first
    stored = db.json("SELECT doc FROM sortyard.event WHERE id = 'evt-mono-2'")
    assert stored["seq"] == second
    assert models.Event.from_dict(stored).seq == second


@requires_postgres
def test_append_is_idempotent(db: Database) -> None:
    seq = append(db, event("evt-idem"))
    assert append(db, event("evt-idem")) == seq
    assert db.value("SELECT count(*) FROM sortyard.event WHERE id = 'evt-idem'") == "1"


@requires_postgres
def test_reusing_an_event_id_for_different_content_is_refused(db: Database) -> None:
    append(db, event("evt-reuse"))
    err = db.error(
        "SELECT sortyard.append_event(:'doc'::jsonb)",
        {"doc": json.dumps(event("evt-reuse", name="release"))},
    )
    assert "different content" in err


@requires_postgres
def test_writers_do_not_choose_ledger_positions(db: Database) -> None:
    err = db.error(
        "SELECT sortyard.append_event(:'doc'::jsonb)",
        {"doc": json.dumps({**event("evt-seq"), "seq": 1})},
    )
    assert "assigns seq" in err


@requires_postgres
@pytest.mark.parametrize("name", sorted(APPEND_ONLY))
def test_streams_are_append_only(db: Database, name: str) -> None:
    for statement in (
        f"UPDATE sortyard.{name} SET doc = doc",
        f"DELETE FROM sortyard.{name}",
        f"TRUNCATE sortyard.{name}",
    ):
        assert "append-only" in db.error(statement), statement


@requires_postgres
def test_object_history_is_the_ordered_ledger_of_one_object(db: Database) -> None:
    for i, name in enumerate(["create", "claim", "start"]):
        append(db, event(f"evt-hist-{i}", object_id="task-hist", name=name))
    append(db, event("evt-other", object_id="task-other"))
    history = db.json("SELECT json_agg(h) FROM sortyard.object_history('task', 'task-hist') AS h")
    assert [h["transition"]["name"] for h in history] == ["create", "claim", "start"]
    assert [h["seq"] for h in history] == sorted(h["seq"] for h in history)
    for h in history:
        models.Event.from_dict(h)
