"""Acceptance tests for the Sortyard API spec and its MCP permission matrix (design §4, §7).

Run: python3 -m unittest projects/sortyard/spec/test_openapi.py

The structural and permission checks use only the standard library. The lint check runs
`redocly lint` (a standard OpenAPI 3.1 validator, configured by redocly.yaml) when the `redocly` CLI is on PATH or named
by SORTYARD_OPENAPI_LINT, and is skipped, loudly, otherwise.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import unittest

SPEC = pathlib.Path(__file__).resolve().parent
API = SPEC / "openapi.json"
MATRIX = SPEC / "PERMISSIONS.md"
NOTES = SPEC / "NOTES.md"

HUMAN_ROLES = ["admin", "operator", "viewer"]          # RoleBinding roles of operators (§3.9)
AGENT_ROLES = ["conductor", "build-worker", "sensor", "grooming-agent"]  # §7 service accounts
ROLES = HUMAN_ROLES + AGENT_ROLES
SCHEME_FOR = {**{r: "operatorSession" for r in HUMAN_ROLES},
              **{r: "serviceAccountToken" for r in AGENT_ROLES}}
METHODS = {"get", "put", "post", "patch", "delete"}
# The MCP tools §7 names, each of which must be an operation.
MCP_TOOLS_NAMED_IN_DESIGN = {
    "create_task", "claim_context_packet", "submit_stage_result", "file_finding", "run_eval",
    "read_decision_log",
}


def load_api():
    return json.loads(API.read_text())


def operations(api):
    for path, item in api["paths"].items():
        for method, op in item.items():
            if method in METHODS:
                yield path, method, op


def walk(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from walk(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, key)


def resolve_pointer(doc, pointer):
    for part in [p for p in pointer.split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        doc = doc[int(part)] if isinstance(doc, list) else doc[part]
    return doc


def roles_with(api, capability):
    return {r for _, _, op in operations(api)
            if op.get("x-sortyard-capability") == capability for r in op["x-sortyard-roles"]}


class SpecStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = load_api()
        cls.ops = list(operations(cls.api))

    def test_is_openapi_3_1_with_both_security_schemes(self):
        self.assertTrue(self.api["openapi"].startswith("3.1."))
        schemes = self.api["components"]["securitySchemes"]
        self.assertEqual(set(schemes), {"operatorSession", "serviceAccountToken"})
        self.assertEqual(self.api["security"], [], "no global default: every op names its roles")

    def test_every_operation_names_its_roles_and_security(self):
        ids = [op["operationId"] for _, _, op in self.ops]
        self.assertEqual(len(ids), len(set(ids)), "duplicate operationId")
        for path, method, op in self.ops:
            with self.subTest(op=op["operationId"]):
                roles = op["x-sortyard-roles"]
                self.assertTrue(roles)
                self.assertLessEqual(set(roles), set(ROLES))
                self.assertEqual(op["security"], [{SCHEME_FOR[r]: [r]} for r in roles])
                self.assertTrue(op.get("summary"))
                self.assertIn("401", op["responses"])
                self.assertIn("403", op["responses"])

    def test_every_domain_schema_is_served(self):
        # Resource shapes are the frozen §3 schemas, referenced, never re-declared. Embedded
        # value objects (ResourceEnvelope) are served through the object that embeds them.
        direct = {r.partition("#")[0] for r in walk(self.api, "$ref") if not r.startswith("#")}
        reached, todo = set(), list(direct)
        while todo:
            name = todo.pop()
            if name not in reached:
                reached.add(name)
                doc = json.loads((SPEC / name).read_text())
                todo += [r.partition("#")[0] for r in walk(doc, "$ref") if not r.startswith("#")]
        files = {p.name for p in SPEC.glob("*.schema.json")}
        self.assertEqual(files - reached, set(), "§3 schemas no operation serves")
        self.assertGreater(len(direct), 40, "objects are served directly, not only embedded")

    def test_every_external_ref_resolves(self):
        for ref in set(walk(self.api, "$ref")):
            with self.subTest(ref=ref):
                target, _, pointer = ref.partition("#")
                doc = self.api if not target else json.loads((SPEC / target).read_text())
                resolve_pointer(doc, pointer)

    def test_field_names_come_from_the_schemas(self):
        # An inline body field either is a §3 schema property of the same name or is marked
        # API-defined and explained in NOTES.md.
        notes = NOTES.read_text()
        for _, _, op in self.ops:
            body = op.get("requestBody", {}).get("content", {})
            for media in body.values():
                for name, prop in media["schema"].get("properties", {}).items():
                    with self.subTest(op=op["operationId"], field=name):
                        if prop.get("x-sortyard-api-defined"):
                            self.assertTrue(f"`{name}`" in notes, f"API-defined `{name}` not in NOTES.md")
                        else:
                            self.assertRegex(prop.get("$ref", ""),
                                             rf"\.schema\.json#/(properties|\$defs)/{name}$")

    def test_console_surfaces_exist(self):
        paths = self.api["paths"]
        ws = "/v1/workspaces/{workspace_id}"
        for p in ("/pickup-preview", "/decision-log", "/decision-log/{decision_log_id}",
                  "/events", "/events/{seq}", "/events/stream", "/tasks/{task_id}/decision-log"):
            with self.subTest(path=p):
                self.assertIn("get", paths[ws + p])
        stream = paths[ws + "/events/stream"]["get"]["responses"]["200"]["content"]
        self.assertIn("text/event-stream", stream)

    def test_ledgers_are_read_only(self):
        for path, method, op in self.ops:
            if re.search(r"/(events|decision-log|audit-log|sequence-changes|throughput-windows)",
                         path):
                with self.subTest(op=op["operationId"]):
                    self.assertEqual(method, "get")

    def test_viewer_never_mutates(self):
        for _, method, op in self.ops:
            if "viewer" in op["x-sortyard-roles"]:
                with self.subTest(op=op["operationId"]):
                    self.assertEqual(method, "get")


class PermissionMatrixTest(unittest.TestCase):
    """§7: the permission matrix *is* the design."""

    @classmethod
    def setUpClass(cls):
        cls.api = load_api()
        cls.by_role = {r: set() for r in ROLES}
        for _, _, op in operations(cls.api):
            for r in op["x-sortyard-roles"]:
                cls.by_role[r].add(op["operationId"])

    def test_build_worker_reads_its_packet_and_submits_its_result_nothing_else(self):
        self.assertEqual(self.by_role["build-worker"],
                         {"getStageRunContextPacket", "submitStageRunResult"})

    def test_sensor_files_findings_and_tasks_nothing_else(self):
        self.assertEqual(self.by_role["sensor"], {"createTask", "createAlert"})

    def test_only_the_conductor_claims_hands_back_or_instructs_the_integrator(self):
        for capability in ("task.claim", "task.hand_back", "integrator.instruct"):
            with self.subTest(capability=capability):
                self.assertEqual(roles_with(self.api, capability), {"conductor"})

    def test_grooming_creates_and_grooms_but_never_claims_or_merges(self):
        self.assertIn("grooming-agent", roles_with(self.api, "task.create"))
        self.assertIn("grooming-agent", roles_with(self.api, "task.groom"))
        for capability in ("task.claim", "integrator.instruct"):
            self.assertNotIn("grooming-agent", roles_with(self.api, capability))

    def test_only_operator_accounts_edit_policies_lanes_or_answer_decisions(self):
        for capability in ("policy.edit", "lane.edit", "decision.answer"):
            with self.subTest(capability=capability):
                self.assertEqual(roles_with(self.api, capability), {"admin", "operator"})

    def test_creating_a_decision_cannot_answer_it(self):
        # §7: only operator accounts answer Decisions. createDecision (open to the conductor)
        # must refuse an already-answered or defaulted Decision, or the conductor could forge
        # an operator answer at creation time.
        op = next(op for _, _, op in operations(self.api) if op["operationId"] == "createDecision")
        ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        create = resolve_pointer(self.api, ref.partition("#")[2])
        self.assertEqual(create["allOf"], [{"$ref": "decision.schema.json"}])
        forbidden = {req for alt in create["not"]["anyOf"] for req in alt["required"]}
        base = json.loads((SPEC / "decision.schema.json").read_text())
        valid = dict(base["examples"][0])
        forged = dict(valid, state="answered", resolution="fork", resolved_at="2026-11-10T13:00:00Z",
                      answered_by={"kind": "operator", "id": "op-joe"}, answer_channel="ui")

        def accepted(body):
            return (body.get("state") == create["properties"]["state"]["const"]
                    and not forbidden & set(body))

        self.assertTrue(accepted(valid))
        self.assertFalse(accepted(forged))
        self.assertFalse(accepted(dict(valid, state="defaulted")))
        for field in ("resolution", "answered_by", "answer_channel", "resolved_at"):
            with self.subTest(field=field):
                self.assertIn(field, forbidden)
                self.assertIn(field, base["properties"], "forbidden fields are §3 fields")
        try:
            import jsonschema
            import referencing
        except ImportError:
            return  # the structural checks above stand; full validation needs jsonschema
        docs = {p.name: json.loads(p.read_text()) for p in SPEC.glob("*.schema.json")}
        registry = referencing.Registry().with_resources(
            (uri, referencing.Resource.from_contents(doc))
            for name, doc in docs.items() for uri in (name, doc["$id"]))
        schema = dict(create, **{"$schema": "https://json-schema.org/draft/2020-12/schema"})
        validator = jsonschema.Draft202012Validator(schema, registry=registry)
        self.assertTrue(validator.is_valid(valid))
        self.assertFalse(validator.is_valid(forged))
        self.assertTrue(jsonschema.Draft202012Validator(
            base, registry=registry).is_valid(forged), "the bypass the create schema closes")

    def test_no_role_may_both_create_and_claim_tasks(self):
        # The queue-poisoning vector, refused at token issuance (§7).
        self.assertEqual(roles_with(self.api, "task.create") & roles_with(self.api, "task.claim"),
                         set())

    def test_mcp_tools(self):
        tools = {}
        for _, _, op in operations(self.api):
            agent = set(op["x-sortyard-roles"]) & set(AGENT_ROLES)
            tool = op.get("x-sortyard-mcp-tool")
            with self.subTest(op=op["operationId"]):
                self.assertEqual(bool(agent), bool(tool), "agent ops, and only they, are MCP tools")
            if tool:
                self.assertNotIn(tool, tools, "MCP tool names are unique")
                tools[tool] = op["operationId"]
        self.assertLessEqual(MCP_TOOLS_NAMED_IN_DESIGN, set(tools))

    def test_matrix_document_matches_the_spec(self):
        rows = {}
        header = None
        for line in MATRIX.read_text().splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("| Operation"):
                header = cells
            elif header and line.startswith("| `") and len(cells) == len(header):
                op_id = cells[0].strip("`")
                rows[op_id] = {header[i] for i, c in enumerate(cells) if c == "✓"}
        self.assertEqual(header[-len(ROLES):], ROLES)
        expected = {op["operationId"]: set(op["x-sortyard-roles"])
                    for _, _, op in operations(self.api)}
        self.assertEqual(rows, expected)


def lint_command():
    explicit = os.environ.get("SORTYARD_OPENAPI_LINT")
    if explicit:
        return explicit.split()
    found = shutil.which("redocly")
    return [found] if found else None


@unittest.skipIf(lint_command() is None, "redocly not installed: OpenAPI lint NOT run")
class LintTest(unittest.TestCase):
    def test_redocly_lint_is_clean(self):
        command = lint_command() + ["lint", "--format=stylish",
                                    "--config", str(SPEC / "redocly.yaml"), str(API)]
        result = subprocess.run(command, capture_output=True, text=True, cwd=SPEC, timeout=300)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotRegex(output, r"(?i)\b[1-9]\d* (warning|error)s?\b", output)


if __name__ == "__main__":
    unittest.main()
