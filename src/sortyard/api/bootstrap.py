"""A deployment's first workspace, projects, operators and role bindings, from one file.

``sortyard-api --bootstrap FILE`` is the interim way a deployment gets what an operator's first
call needs, until OIDC sessions exist (design §3.9, §7): it reads a declaration and creates
what is missing. Then ``--issue-operator-token`` prints a credential for a declared binding.

The declaration is TOML and holds no credential::

    [workspace]                 # a Workspace (spec/workspace.schema.json)
    id = "ws-acme"
    name = "Acme"

    [[projects]]                # Project objects (spec/project.schema.json)
    [[operators]]               # Operator objects (spec/operator.schema.json)
    [[role_bindings]]           # RoleBinding objects (spec/role-binding.schema.json)

Each entry is the object as its schema defines it, without ``workspace_id`` (it is the declared
workspace's). ``workspace.installation_id`` may be left out: it is then the deployment's
installation, which is created as the provisional record when the database has none.

Every entry goes through the validation the API applies to a body (``handlers.validate``: the
generated model and the full JSON Schema). Everything is decided and written in one
transaction: a declaration with any refused entry writes nothing. An object that exists with
the declared content is left alone; one that exists with different content is refused and
named, never overwritten. Each object created gets the AuditLog entry and ledger event an API
mutation writes, with the actor ``system/bootstrap``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from typing import Any

from sortyard import models
from sortyard.api import handlers, store
from sortyard.api.store import ApiError, Conn, Doc
from sortyard.models import schema

ACTOR: Doc = {"kind": "system", "id": "bootstrap"}
#: Declaration section -> (table, model).
SECTIONS: dict[str, tuple[str, type[models.Model]]] = {
    "projects": ("project", models.Project),
    "operators": ("operator", models.Operator),
    "role_bindings": ("role_binding", models.RoleBinding),
}
#: Properties the service may stamp on a stored object; a declaration that does not state
#: one does not differ from a stored object that has it.
STAMPED = frozenset({"granted_by", "created_at", "updated_at"})


class Refused(Exception):
    """The declaration is not applied; nothing was written. `reasons` name each cause."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class Declaration:
    workspace: Doc
    #: (table, document) in the order they are written.
    objects: tuple[tuple[str, Doc], ...]

    @property
    def workspace_id(self) -> str:
        return str(self.workspace["id"])


@dataclass
class Outcome:
    """What a run did, as `kind id` names; a created role binding also says what it grants."""

    created: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


def parse(text: str, installation_id: str) -> Declaration:
    """The declaration of a file, every object validated; `Refused` with every reason."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise Refused([f"the declaration is not TOML: {exc}"]) from None
    reasons = [f"{key}: not a section of a declaration" for key in raw if key not in _TOP]
    if _has_nul(raw):
        # Postgres stores no NUL in text; refused here, by name, not by the driver later.
        reasons.append("a string holds a NUL character")
    workspace = raw.get("workspace")
    if not isinstance(workspace, dict):
        raise Refused([*reasons, "workspace: a [workspace] table is required"])
    workspace = {"installation_id": installation_id, **workspace}
    try:
        workspace = _workspace(workspace)
    except ApiError as refused:
        raise Refused([*reasons, f"workspace: {refused.detail}"]) from None
    objects: list[tuple[str, Doc]] = []
    for section, (table, model) in SECTIONS.items():
        entries = raw.get(section, [])
        if not isinstance(entries, list):
            reasons.append(f"{section}: must be an array of tables ([[{section}]])")
            continue
        seen: set[str] = set()
        for n, entry in enumerate(entries):
            where = f"{section}[{n}]"
            if not isinstance(entry, dict):
                reasons.append(f"{where}: must be a table")
                continue
            try:
                doc = handlers.validate(
                    model, {"workspace_id": workspace["id"], **entry}, workspace["id"]
                )
            except ApiError as refused:
                reasons.append(f"{where} ({entry.get('id', 'no id')}): {refused.detail}")
                continue
            if table == "role_binding" and (
                doc["role"] == "agent-service-account" or doc["principal"]["kind"] != "operator"
            ):
                # The file declares operators and their bindings. An agent has no object here
                # to check the binding against; an admin grants those through the API.
                reasons.append(
                    f"{where} ({doc['id']}): a declaration binds operators only, with the"
                    " role admin, operator or viewer"
                )
                continue
            if doc["id"] in seen:
                reasons.append(f"{where}: {table} {doc['id']!r} is declared twice")
            seen.add(doc["id"])
            objects.append((table, doc))
    if reasons:
        raise Refused(reasons)
    return Declaration(workspace, tuple(objects))


_TOP = ("workspace", *SECTIONS)


def _has_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    return isinstance(value, list) and any(_has_nul(v) for v in value)


def describe(table: str, doc: Doc) -> str:
    """An object's name in the output: `kind id`, and for a role binding what it grants."""
    if table != "role_binding":
        return f"{table} {doc['id']}"
    scope = doc["scope"]
    where = f"project {scope.get('ref')}" if scope["kind"] == "project" else "workspace"
    principal = doc["principal"]
    return (
        f"{table} {doc['id']} ({doc['role']} for {principal['kind']} {principal['id']},"
        f" scope {where})"
    )


def _workspace(doc: Doc) -> Doc:
    """A Workspace as the API's validation takes any object: the generated model, then the
    full schema. (`handlers.validate` also checks a `workspace_id`, which a Workspace, the
    one object that is not inside a workspace, does not have.)"""
    try:
        decoded = models.Workspace.from_dict(doc)
    except models.ModelError as exc:
        raise store.unprocessable(str(exc)) from None
    violations = schema.errors(models.Workspace, doc)
    if violations:
        raise store.unprocessable("; ".join(violations), "schema")
    return decoded.to_dict()


def _differs(declared: Doc, stored: Doc) -> list[str]:
    """The properties in which a stored object is not the declared one."""
    missing = object()
    return sorted(
        key
        for key in {*declared, *stored}
        if declared.get(key, missing) != stored.get(key, missing)
        and not (key in STAMPED and key not in declared)
    )


def _stored(conn: Conn, table: str, oid: str) -> Doc | None:
    """The object with this id, whichever workspace holds it (ids are unique per table)."""
    row: Any = conn.execute(
        # `table` is one of this module's constants.
        f"SELECT doc FROM sortyard.{table} WHERE id = %s",
        [oid],
    ).fetchone()
    return None if row is None else dict(row[0])


def apply(conn: Conn, declaration: Declaration, installation: Doc) -> Outcome:
    """Create what the declaration names and the database lacks, in one transaction.

    `installation` is the record created when the declared workspace's installation is the
    deployment's own and the database does not hold it yet. Raises `Refused`, having written
    nothing, when an object exists with different content or a binding names an operator or a
    project that is neither declared nor stored."""
    workspace_id = declaration.workspace_id
    outcome = Outcome()
    reasons: list[str] = []
    create: list[tuple[str, Doc]] = []
    with conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"sortyard.bootstrap:{workspace_id}"],
        )
        planned = [("workspace", declaration.workspace), *declaration.objects]
        for table, doc in planned:
            stored = _stored(conn, table, doc["id"])
            name = f"{table} {doc['id']}"
            if stored is None:
                create.append((table, doc))
            elif differs := _differs(doc, stored):
                reasons.append(
                    f"{name} exists with different content (differs in: {', '.join(differs)});"
                    " it is not overwritten"
                )
            else:
                outcome.unchanged.append(name)

        def known(table: str, oid: Any) -> bool:
            declared = any(t == table and d["id"] == oid for t, d in declaration.objects)
            return declared or store.exists(conn, table, workspace_id, str(oid))

        for table, doc in declaration.objects:
            if table != "role_binding":
                continue
            principal, scope = doc["principal"], doc["scope"]
            if principal["kind"] == "operator" and not known("operator", principal["id"]):
                reasons.append(
                    f"role_binding {doc['id']}: operator {principal['id']!r} is neither"
                    " declared nor in the workspace"
                )
            if scope["kind"] == "project" and not known("project", scope.get("ref")):
                reasons.append(
                    f"role_binding {doc['id']}: its scope names project {scope.get('ref')!r},"
                    " which is neither declared nor in the workspace"
                )
        installation_id = declaration.workspace["installation_id"]
        make_installation = (
            any(table == "workspace" for table, _ in create)
            and _stored(conn, "installation", installation_id) is None
        )
        if make_installation and installation_id != installation["id"]:
            reasons.append(f"workspace {workspace_id}: no installation {installation_id!r}")
        if reasons:
            raise Refused(reasons)
        if make_installation:
            store.insert(conn, "installation", installation)
            outcome.created.append(f"installation {installation_id}")
        for table, doc in create:
            granting = table == "role_binding"
            if granting:
                doc = {"granted_by": ACTOR, **doc}  # as createRoleBinding stamps it
            store.insert(conn, table, doc)
            store.record(
                conn,
                workspace_id,
                ACTOR,
                table,
                doc["id"],
                action="create",
                transition="grant" if granting else "create",
                before=None,
                after=doc,
                channel="system",
            )
            outcome.created.append(describe(table, doc))
    return outcome
