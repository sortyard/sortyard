"""Acceptance (SY-V3-OPERATOR-BOOTSTRAP): a deployment gets its workspace, projects and first
operator from one command, `sortyard-api --bootstrap FILE`, not from rows written by hand.

The command is run as a deployment runs it (the service's `main`, configured by the
environment) against a migrated, empty Postgres. What it made is proved through the API
service itself, over HTTP, with a token from `--issue-operator-token`; admission runs against a
real engine (its development server), as in tests/test_admission.py.
"""

from __future__ import annotations

import asyncio
import functools
import os
import pathlib
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import psycopg.conninfo
import pytest

from sortyard.api import bootstrap, handlers
from sortyard.engine.blocking import BlockingEngine
from sortyard.engine.testing import local_engine
from sortyard.kernel.item import start_item, workflow_id
from sortyard.services import api as api_service
from sortyard.services.conductor import provisional_installation
from tests.api_harness import Api
from tests.pg import fresh_database, requires_postgres
from tests.worker_harness import LANE

ROOT = pathlib.Path(__file__).resolve().parent.parent
WS = "ws-acme"
TABLES = (
    "installation",
    "workspace",
    "project",
    "operator",
    "role_binding",
    "api_token",
    "audit_log",
    "event",
)

WORKSPACE = """
[workspace]
id = "ws-acme"
name = "Acme"
"""
PROJECT = """
[[projects]]
id = "{id}"
name = "{name}"
archetype = {{ id = "arch-saas-product", version = "1.0.0" }}
repos = []
tracker = {{ kind = "{tracker}" }}
state = "active"
"""
OPERATOR = """
[[operators]]
id = "{id}"
subject = "oidc|{id}"
display_name = "{id}"
state = "{state}"
"""
BINDING = """
[[role_bindings]]
id = "{id}"
principal = {{ kind = "{kind}", id = "{operator}" }}
role = "{role}"
scope = {scope}
"""


def project(pid: str = "proj-app", name: str = "App", tracker: str = "internal") -> str:
    return PROJECT.format(id=pid, name=name, tracker=tracker)


def operator(oid: str, state: str = "active") -> str:
    return OPERATOR.format(id=oid, state=state)


def binding(
    rbid: str,
    op: str,
    role: str,
    scope: str = '{ kind = "workspace" }',
    kind: str = "operator",
) -> str:
    return BINDING.format(id=rbid, operator=op, role=role, scope=scope, kind=kind)


#: One workspace, one project, an operator who may admit and one who may only read.
DECLARED = (
    WORKSPACE
    + project()
    + operator("op-first")
    + operator("op-reader")
    + binding("rb-first", "op-first", "operator")
    + binding("rb-reader", "op-reader", "viewer")
)


class Deployment:
    """A migrated, empty database and the service's commands configured for it."""

    def __init__(self, name: str, tmp: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.name = name
        self.conninfo = psycopg.conninfo.make_conninfo(dbname=name)
        self.connect = functools.partial(psycopg.connect, self.conninfo)
        self.file = tmp / "bootstrap.toml"
        self.capsys = capsys

    def run(self, *argv: str) -> tuple[int, str, str]:
        """`sortyard-api ARGV`: its exit code, standard output and standard error."""
        self.capsys.readouterr()
        code = api_service.main(list(argv))
        captured = self.capsys.readouterr()
        return code, captured.out, captured.err

    def bootstrap(self, declaration: str) -> tuple[int, list[str], str]:
        self.file.write_text(declaration)
        code, out, err = self.run("--bootstrap", str(self.file))
        return code, out.splitlines(), err

    def token(self, role_binding: str) -> str:
        code, out, err = self.run("--issue-operator-token", role_binding)
        assert code == 0, err
        return out.strip()

    def rows(self) -> dict[str, list[str]]:
        """Every row of every table the command could write, whole (with its record time)."""
        with self.connect() as conn:
            return {
                table: [
                    row[0]
                    for row in conn.execute(
                        f"SELECT to_jsonb(t)::text FROM sortyard.{table} AS t ORDER BY 1"
                    )
                ]
                for table in TABLES
            }

    @contextmanager
    def serving(self, kernel: handlers.Kernel | None = None, signal: Any = None) -> Iterator[Api]:
        """The API service on this database."""
        config = api_service.Config(host="127.0.0.1", port=0, database_name=self.name)
        server = api_service.make_server(
            config, connect=self.connect, signal_item=signal, kernel=kernel
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield Api(f"http://127.0.0.1:{server.server_address[1]}", self.conninfo, {})
        finally:
            server.shutdown()
            server.server_close()


@pytest.fixture
def deployment(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Iterator[Deployment]:
    for database in fresh_database():
        proc = database.migrate()
        assert proc.returncode == 0, proc.stderr
        for name, value in {
            "SORTYARD_DATABASE_HOST": os.environ["PGHOST"],
            "SORTYARD_DATABASE_PORT": os.environ.get("PGPORT", "5432"),
            "SORTYARD_DATABASE_NAME": database.name,
        }.items():
            monkeypatch.setenv(name, value)
        yield Deployment(database.name, tmp_path, capsys)


def item(iid: str, project_id: str = "proj-app") -> dict[str, Any]:
    return {
        "id": iid,
        "project_id": project_id,
        "title": "Count to ten",
        "lane": LANE.name,
        "repository": "walwarden/app",
        "spec": {
            "outcome": "the widget counts to ten",
            "acceptance": [{"test": "tests/test_widget.py", "name": "the widget counts to ten"}],
        },
    }


@requires_postgres
def test_bootstrap_creates_what_a_file_declares_and_a_token_for_a_declared_binding_admits_an_item(
    deployment: Deployment,
) -> None:
    """bootstrap creates the workspace, projects, operators and role bindings a file declares,
    and an operator token issued for a declared binding admits an item."""
    code, lines, err = deployment.bootstrap(DECLARED)
    assert code == 0, err
    assert sorted(lines) == sorted(
        f"created {name}"
        for name in (
            "installation inst-sortyard",
            f"workspace {WS}",
            "project proj-app",
            "operator op-first",
            "operator op-reader",
            # A created binding says what it grants, so a new admin shows in the output.
            "role_binding rb-first (operator for operator op-first, scope workspace)",
            "role_binding rb-reader (viewer for operator op-reader, scope workspace)",
        )
    )
    made = deployment.rows()
    # It issues no credential, and every object it made is in the audit log and the ledger.
    assert made["api_token"] == []
    assert len(made["audit_log"]) == len(made["event"]) == 6

    async def scenario() -> None:
        async with local_engine() as local:
            blocking = BlockingEngine(local.target)

            def start(tenant: str, iid: str, risk_tier: str) -> None:
                blocking.call(lambda e: start_item(e, iid, tenant=tenant, risk_tier=risk_tier))

            kernel = handlers.Kernel({LANE.name: LANE}, start)
            try:
                with deployment.serving(kernel, blocking.signal) as api:
                    first = deployment.token("rb-first")
                    reader = deployment.token("rb-reader")
                    items = f"/v1/workspaces/{WS}/items"
                    # The declared viewer is a viewer: the API refuses its admission.
                    assert api.call("POST", items, body=item("ITEM-0"), token=reader).status == 403
                    # The declared project is the only one the workspace has.
                    stray = api.call("POST", items, body=item("ITEM-0", "proj-none"), token=first)
                    assert stray.status == 422 and stray.body["reason_code"] == "admission"
                    admitted = api.call("POST", items, body=item("ITEM-1"), token=first)
                    assert admitted.status == 201, admitted.body
                    assert admitted.body["project_id"] == "proj-app"
                    # The item's workflow is in the engine, and the reader reads its timeline.
                    await local.engine.recorded(workflow_id(WS, "ITEM-1"))
                    seen = api.call("GET", f"{items}/ITEM-1/timeline", token=reader)
                    assert seen.status == 200, seen.body
                    # The token is of this workspace alone.
                    other = api.call("POST", "/v1/workspaces/ws-other/items", token=first)
                    assert other.status in (403, 404)
            finally:
                blocking.close()

    asyncio.run(scenario())


@requires_postgres
def test_running_bootstrap_twice_changes_nothing_the_second_time(deployment: Deployment) -> None:
    """Running bootstrap twice changes nothing the second time."""
    code, first, err = deployment.bootstrap(DECLARED)
    assert code == 0, err
    before = deployment.rows()

    code, second, err = deployment.bootstrap(DECLARED)
    assert code == 0, err
    assert second and all(line.startswith("unchanged ") for line in second)
    assert {line.split(" ", 1)[1] for line in second} == {
        line.split(" ", 1)[1].split(" (")[0] for line in first if " installation " not in line
    }
    assert deployment.rows() == before

    # Adding a project, an operator and its binding to the file later creates those alone.
    more = (
        DECLARED
        + project("proj-site", "Site")
        + operator("op-second")
        + binding("rb-second", "op-second", "admin", '{ kind = "project", ref = "proj-site" }')
    )
    code, third, err = deployment.bootstrap(more)
    assert code == 0, err
    assert sorted(line for line in third if line.startswith("created ")) == [
        "created operator op-second",
        "created project proj-site",
        "created role_binding rb-second (admin for operator op-second, scope project proj-site)",
    ]
    after = deployment.rows()
    for table in ("installation", "workspace", "api_token"):
        assert after[table] == before[table]
    for table in ("project", "operator", "role_binding"):
        assert set(before[table]) < set(after[table])
        assert len(after[table]) == len(before[table]) + 1

    # A binding the new admin grants through the API (the service stamps who granted it) is
    # the same object when the file declares it afterwards: it is left alone.
    with deployment.serving() as api:
        granted = api.call(
            "POST",
            f"/v1/workspaces/{WS}/role-bindings",
            token=deployment.token("rb-second"),
            body={
                "id": "rb-site-reader",
                "workspace_id": WS,
                "principal": {"kind": "operator", "id": "op-reader"},
                "role": "viewer",
                "scope": {"kind": "project", "ref": "proj-site"},
            },
        )
        assert granted.status == 201, granted.body
    settled = deployment.rows()
    code, fourth, err = deployment.bootstrap(
        more
        + binding(
            "rb-site-reader", "op-reader", "viewer", '{ kind = "project", ref = "proj-site" }'
        )
    )
    assert code == 0, err
    assert "unchanged role_binding rb-site-reader" in fourth
    assert not [line for line in fourth if line.startswith("created ")]
    assert deployment.rows() == settled


#: Declarations refused for what they say, whatever the database holds. Each has valid
#: objects before the refused one, so a partial write would show.
INVALID = {
    "not TOML": DECLARED + "\n[[projects]\n",
    "no workspace": project() + operator("op-first"),
    "an unknown section": DECLARED + '\n[[tokens]]\nid = "tok-1"\n',
    "a workspace id that is not an id": DECLARED.replace('"ws-acme"', '"ws acme"'),
    "a workspace with an unknown property": WORKSPACE + 'owner = "someone"\n' + project(),
    "an operator state outside the schema": DECLARED + operator("op-late", state="retired"),
    "a credential in an operator": DECLARED + operator("op-late") + 'token = "not-a-token"\n',
    "a project missing a required property": DECLARED + '\n[[projects]]\nid = "proj-bare"\n',
    # A rule only the full schema holds (if/then): an external tracker names its integration.
    "an external tracker with no integration": DECLARED + project("proj-ext", "Ext", "external"),
    "an operator role binding an agent": DECLARED
    + binding("rb-agent", "sa-agent", "admin", kind="agent"),
    # Valid for the API (an admin grants it there), but not something a declaration makes:
    # the file has no agents, so nothing says this one exists.
    "a service-account binding": DECLARED
    + binding("rb-agent", "sa-agent", "agent-service-account", kind="agent"),
    # Postgres stores no NUL; refused as a reason, not as the driver's error.
    "a NUL character in a string": DECLARED.replace('"Acme"', '"Ac\\u0000me"'),
    "an object of another workspace": DECLARED + operator("op-late") + 'workspace_id = "ws-b"\n',
    "an id that is not an id": DECLARED + operator("op late"),
    "an id declared twice": DECLARED + operator("op-first"),
    "a binding for an operator nobody declared": DECLARED
    + binding("rb-ghost", "op-ghost", "admin"),
    "a binding scoped to a project nobody declared": DECLARED
    + binding("rb-lost", "op-first", "admin", '{ kind = "project", ref = "proj-lost" }'),
    "a project scope that names no project": DECLARED
    + binding("rb-lost", "op-first", "admin", '{ kind = "project" }'),
    "an installation the database does not hold": DECLARED.replace(
        'name = "Acme"', 'name = "Acme"\ninstallation_id = "inst-elsewhere"'
    ),
}


@requires_postgres
def test_an_invalid_declaration_or_a_conflicting_existing_object_is_refused_and_nothing_is_written(
    deployment: Deployment,
) -> None:
    """An invalid declaration or a conflicting existing object is refused and nothing is
    written."""
    empty = deployment.rows()
    assert all(rows == [] for rows in empty.values())
    for what, declaration in INVALID.items():
        code, lines, err = deployment.bootstrap(declaration)
        assert code == 1 and lines == [] and err, what
        assert err.count("refused: ") >= 1 and "psycopg" not in err, (what, err)
        assert deployment.rows() == empty, what

    code, _, err = deployment.bootstrap(DECLARED)
    assert code == 0, err
    # Another workspace holds an operator; ids are the database's, not a workspace's.
    other = WORKSPACE.replace("ws-acme", "ws-other") + operator("op-theirs")
    code, _, err = deployment.bootstrap(other)
    assert code == 0, err
    before = deployment.rows()

    # Each names one existing object with different content, and adds a new valid object
    # after it: the existing one is not overwritten and the new one is not written.
    addition = operator("op-new") + binding("rb-new", "op-new", "viewer")
    conflicts = {
        "workspace ws-acme": DECLARED.replace('"Acme"', '"Acme Corp"'),
        "project proj-app": DECLARED.replace('name = "App"', 'name = "Application"'),
        "operator op-reader": DECLARED.replace(
            operator("op-reader"), operator("op-reader", state="disabled")
        ),
        # The reader's binding raised to admin: a declaration does not change who may do what.
        "role_binding rb-reader": DECLARED.replace('role = "viewer"', 'role = "admin"'),
        "operator op-theirs": DECLARED + operator("op-theirs"),
    }
    for name, declaration in conflicts.items():
        code, lines, err = deployment.bootstrap(declaration + addition)
        assert code == 1 and lines == [], name
        assert name in err, (name, err)
        assert deployment.rows() == before, name
    # Every invalid declaration is refused on a database that holds the objects, too.
    for what, declaration in INVALID.items():
        assert deployment.bootstrap(declaration)[0] == 1, what
        assert deployment.rows() == before, what
    # The reader is still a viewer for the API.
    with deployment.serving() as api:
        refused = api.call(
            "POST",
            f"/v1/workspaces/{WS}/role-bindings",
            token=deployment.token("rb-reader"),
            body={},
        )
        assert refused.status == 403


@requires_postgres
def test_the_same_file_under_another_installation_id_is_refused(
    deployment: Deployment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that leaves installation_id out takes it from SORTYARD_INSTALLATION_ID; under
    another value it is not the stored workspace's declaration, and nothing is written."""
    assert deployment.bootstrap(DECLARED)[0] == 0
    before = deployment.rows()
    monkeypatch.setenv("SORTYARD_INSTALLATION_ID", "inst-renamed")
    code, lines, err = deployment.bootstrap(DECLARED + operator("op-new"))
    assert code == 1 and lines == [] and f"workspace {WS}" in err
    assert deployment.rows() == before


@requires_postgres
def test_the_two_commands_are_separate_runs_and_an_empty_value_is_refused(
    deployment: Deployment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--bootstrap ""` (an unset variable in a Job) and `--issue-operator-token ""` are usage
    errors, not a reason to start serving; both flags at once are refused before either runs."""

    def serving(*_: object, **__: object) -> None:
        raise AssertionError("the service was started")

    monkeypatch.setattr(api_service, "make_server", serving)
    deployment.file.write_text(DECLARED)
    for argv in (
        ["--bootstrap", ""],
        ["--issue-operator-token", ""],
        ["--bootstrap", str(deployment.file), "--issue-operator-token", "rb-first"],
    ):
        with pytest.raises(SystemExit) as stopped:
            api_service.main(argv)
        assert stopped.value.code == 2, argv
    assert all(rows == [] for rows in deployment.rows().values())


@requires_postgres
def test_two_runs_at_once_create_each_object_once(deployment: Deployment) -> None:
    """Two runs of one declaration at the same time (a Job retried while the first still runs)
    both succeed, and each object is created by exactly one of them."""
    declaration = bootstrap.parse(DECLARED, "inst-sortyard")
    installation = provisional_installation({})
    outcomes: list[bootstrap.Outcome] = []
    start = threading.Barrier(4)

    def run() -> None:
        with deployment.connect() as conn:
            start.wait(timeout=30)
            outcomes.append(bootstrap.apply(conn, declaration, installation))

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(outcomes) == 4
    created = [name for outcome in outcomes for name in outcome.created]
    assert "role_binding rb-first (operator for operator op-first, scope workspace)" in created
    assert len(created) == len(set(created)) == 7
    assert sorted(len(outcome.created) for outcome in outcomes) == [0, 0, 0, 7]
    rows = deployment.rows()
    assert [len(rows[t]) for t in ("workspace", "project", "operator", "role_binding")] == [
        1,
        1,
        2,
        2,
    ]


def test_the_readme_says_how_a_deployment_gets_its_first_operator_token() -> None:
    """The README's example declaration is one the command takes, and the README names the two
    steps: bootstrap, then --issue-operator-token."""
    readme = (ROOT / "README.md").read_text()
    section = readme.split("### First operator", 1)[1].split("\n## ", 1)[0]
    (example,) = re.findall(r"```toml\n(.*?)```", section, re.DOTALL)
    declaration = bootstrap.parse(example, "inst-sortyard")
    bindings = [doc["id"] for table, doc in declaration.objects if table == "role_binding"]
    assert bindings
    assert section.index("--bootstrap") < section.index("--issue-operator-token")
    assert any(f"--issue-operator-token {rbid}" in section for rbid in bindings)
