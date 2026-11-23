"""Acceptance tests for the frozen Sortyard domain model (design draft §3, Phase 0 §5.1).

Run: python3 -m unittest projects/sortyard/spec/test_schemas.py

The structural checks use only the standard library. The validator checks use the
`jsonschema` package (Draft 2020-12) and are skipped, loudly, when it is not installed.
"""
import json
import pathlib
import unittest

SPEC = pathlib.Path(__file__).resolve().parent
BASE = "https://sortyard.ai/spec/"
DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Every §3 domain object named by the Phase 0 item -> the schema file that freezes it.
REQUIRED = {
    "Installation": "installation",
    "Workspace": "workspace",
    "Project": "project",
    "Archetype": "archetype",
    "Repo": "repo",
    "Task": "task",
    "Milestone": "milestone",
    "Decision": "decision",
    "Chain/Run": "chain",
    "StageRun": "stage-run",
    "Escalation": "escalation",
    "Sequence (SequenceChange)": "sequence-change",
    "SequencingPolicy": "sequencing-policy",
    "Workflow": "workflow",
    "Role/Persona": "role",
    "Lane": "lane",
    "Conductor configuration": "conductor-config",
    "PrioritizationPolicy": "prioritization-policy",
    "GroomingPass": "grooming-pass",
    "Policy": "policy",
    "Agent/Worker": "agent",
    "ContextRecipe": "context-recipe",
    "ExecutionBinding": "execution-binding",
    "ResourceEnvelope": "resource-envelope",
    "Integrator": "integrator",
    "CredentialCustody": "credential-custody",
    "Mirror": "mirror",
    "Extension": "extension",
    "Secret": "secret",
    "Eval": "eval",
    "EvalRun": "eval-run",
    "Scorecard Battery": "scorecard-battery",
    "ThroughputWindow": "throughput-window",
    "Event Ledger": "event",
    "DecisionLog": "decision-log",
    "Self-heal": "self-heal",
    "Alert/Finding": "alert",
    "Operator": "operator",
    "RoleBinding": "role-binding",
    "AuditLog": "audit-log",
    "DeploymentConfig": "deployment-config",
}
STORES = {"definition", "state", "config", "read-model"}
# Objects outside a workspace (the installation, the workspace itself, installation-wide
# config) and embedded value objects with no identity of their own.
NOT_WORKSPACE_SCOPED = {"installation", "workspace", "deployment-config", "resource-envelope"}
POLICY_KINDS = {
    "merge_gate", "pipeline_purity", "replica_required", "secrets", "model_budget",
    "credential_pool", "retention", "runner", "handback", "stall", "escalation",
}


def load(stem):
    return json.loads((SPEC / f"{stem}.schema.json").read_text())


def all_schema_files():
    return sorted(SPEC.glob("*.schema.json"))


def resolve_pointer(doc, pointer):
    node = doc
    for part in [p for p in pointer.split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def walk_refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            elif key not in ("examples", "enum", "const", "default"):
                yield from walk_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_refs(item)


class StructureTest(unittest.TestCase):
    def test_every_required_object_has_a_schema(self):
        missing = [name for name, stem in REQUIRED.items()
                   if not (SPEC / f"{stem}.schema.json").is_file()]
        self.assertEqual(missing, [], "domain objects with no schema")

    def test_notes_file_records_ambiguities(self):
        notes = SPEC / "NOTES.md"
        self.assertTrue(notes.is_file())
        self.assertIn("Ambiguit", notes.read_text())

    def test_every_schema_parses_and_carries_contract_metadata(self):
        files = all_schema_files()
        self.assertGreater(len(files), len(REQUIRED))
        for path in files:
            with self.subTest(schema=path.name):
                doc = json.loads(path.read_text())
                self.assertEqual(doc["$schema"], DIALECT)
                self.assertEqual(doc["$id"], BASE + path.name)
                self.assertTrue(doc.get("title"))
                self.assertTrue(doc.get("description"))
                self.assertTrue(doc.get("x-sortyard-design-ref", "").startswith("§"))
                if path.name != "common.schema.json":
                    self.assertIn(doc.get("x-sortyard-store"), STORES)
                    self.assertTrue(doc.get("examples"), "needs at least one example")

    def test_every_ref_resolves(self):
        for path in all_schema_files():
            doc = json.loads(path.read_text())
            for ref in walk_refs(doc):
                with self.subTest(schema=path.name, ref=ref):
                    target, _, pointer = ref.partition("#")
                    target_doc = doc if not target else json.loads((SPEC / target).read_text())
                    resolve_pointer(target_doc, pointer)

    def test_workspace_field_on_every_object(self):
        # §3.1: the workspace field exists on every object from day one.
        for stem in REQUIRED.values():
            if stem in NOT_WORKSPACE_SCOPED:
                continue
            with self.subTest(schema=stem):
                for example in load(stem)["examples"]:
                    self.assertIn("workspace_id", example)

    def test_draft_enums_are_transcribed(self):
        task = load("task")["properties"]
        self.assertEqual(task["state"]["enum"], [
            "backlog", "todo", "claimed", "in_progress", "in_review", "merging", "done",
            "blocked", "handed_back", "cancelled"])
        self.assertEqual(task["origin"]["enum"],
                         ["human", "sensor", "grooming", "eval-finding", "chain"])
        stage = load("workflow")["$defs"]["stage"]["properties"]
        self.assertEqual(stage["executor"]["enum"], ["agent", "deterministic"])
        self.assertEqual(set(load("policy")["properties"]["kind"]["enum"]), POLICY_KINDS)
        self.assertEqual(load("policy")["properties"]["enforcement"]["enum"],
                         ["refuse", "warn", "record"])
        self.assertEqual(load("credential-custody")["properties"]["custody"]["enum"],
                         ["store", "cli-owned-files", "operator-side"])
        self.assertEqual(load("agent")["properties"]["harness"]["enum"],
                         ["claude-code", "codex", "hermes", "custom"])
        self.assertEqual(load("eval")["properties"]["posture"]["enum"], ["advisory", "gating"])
        self.assertEqual(load("eval")["properties"]["posture"]["default"], "advisory")


try:
    import jsonschema
    from referencing import Registry, Resource
except ImportError:  # pragma: no cover - exercised only without the validator
    jsonschema = None


@unittest.skipIf(jsonschema is None, "jsonschema not installed: validator checks NOT run")
class ValidatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {p.name: json.loads(p.read_text()) for p in all_schema_files()}
        cls.registry = Registry().with_resources(
            (doc["$id"], Resource.from_contents(doc)) for doc in cls.docs.values())

    def validator(self, stem):
        cls = jsonschema.Draft202012Validator
        return cls(self.docs[f"{stem}.schema.json"], registry=self.registry,
                   format_checker=cls.FORMAT_CHECKER)

    def assert_invalid(self, stem, instance):
        errors = list(self.validator(stem).iter_errors(instance))
        self.assertTrue(errors, f"{stem} accepted an instance it must refuse")

    def test_every_schema_is_a_valid_2020_12_schema(self):
        for name, doc in self.docs.items():
            with self.subTest(schema=name):
                jsonschema.Draft202012Validator.check_schema(doc)

    def test_every_example_validates(self):
        for name, doc in self.docs.items():
            for i, example in enumerate(doc.get("examples", [])):
                with self.subTest(schema=name, example=i):
                    self.validator(name.removesuffix(".schema.json")).validate(example)

    def test_secret_never_carries_a_value(self):
        good = dict(self.docs["secret.schema.json"]["examples"][0])
        self.assert_invalid("secret", {**good, "value": "hunter2"})

    def test_no_human_gate_executor(self):
        wf = json.loads(json.dumps(self.docs["workflow.schema.json"]["examples"][0]))
        wf["stages"][0]["executor"] = "human-gate"
        self.assert_invalid("workflow", wf)

    def test_decision_requires_default_and_decide_by(self):
        good = self.docs["decision.schema.json"]["examples"][0]
        for field in ("question", "default", "decide_by"):
            with self.subTest(field=field):
                self.assert_invalid("decision", {k: v for k, v in good.items() if k != field})

    def test_handback_and_block_need_a_reason(self):
        good = self.docs["task.schema.json"]["examples"][0]
        self.assert_invalid("task", {**good, "state": "blocked"})
        self.assert_invalid("task", {**good, "state": "handed_back", "handback_reason": "x"})

    def test_policy_parameters_are_checked_per_kind(self):
        good = self.docs["policy.schema.json"]["examples"][0]
        self.assertEqual(good["kind"], "merge_gate")
        self.assert_invalid("policy", {**good, "parameters": {"force_merge": True}})

    def test_eval_requires_absent_state(self):
        good = self.docs["eval.schema.json"]["examples"][0]
        self.assert_invalid("eval", {k: v for k, v in good.items() if k != "absent_state"})

    def test_conditional_rules_from_the_draft(self):
        ex = lambda stem, i=0: dict(self.docs[f"{stem}.schema.json"]["examples"][i])  # noqa: E731
        # A product with no green deploy is reported as DOWN, in those words.
        self.assert_invalid("alert", {**ex("alert"), "summary": "Rove has no green deploy."})
        # An in-cluster GitHub write credential needs an explicit approval Decision.
        self.assert_invalid("credential-custody",
                            {**ex("credential-custody"), "custody": "store", "secret_ref": "sec-gh"})
        # Grooming on a non-frontier model must stop, never complete.
        self.assert_invalid("grooming-pass", {**ex("grooming-pass", 1), "state": "completed"})
        # A bound binding carries no unbound reasons; an unbound one names at least one.
        self.assert_invalid("execution-binding",
                            {**ex("execution-binding"), "unbound_reasons": [{"code": "mirror_stale"}]})
        self.assert_invalid("execution-binding", {**ex("execution-binding", 1), "unbound_reasons": []})
        # Merge-gate review counts are scoped by regime.
        pol = ex("policy")
        self.assert_invalid("policy", {**pol, "parameters": {"regime": "design_record", "review_count": 1}})
        # Revision rounds cap at four.
        self.assert_invalid("chain", {**ex("chain"), "revision_round": 5})

    def test_objects_are_closed(self):
        good = self.docs["task.schema.json"]["examples"][0]
        self.assert_invalid("task", {**good, "acceptance_tests": ["x"]})


if __name__ == "__main__":
    unittest.main()
