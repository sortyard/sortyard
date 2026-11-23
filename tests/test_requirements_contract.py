"""The planning compiler preserves scope, ownership and executable contract consistency.

These are static contract tests, not runtime feature or Appwrite acceptance evidence.
"""

from __future__ import annotations

import copy
import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import jsonschema  # type: ignore[import-untyped]
import pytest

ROOT = Path(__file__).resolve().parent.parent / "docs" / "requirements"
MODULE = runpy.run_path(str(ROOT / "tools" / "gen.py"))
VALIDATE = cast(Callable[..., list[str]], MODULE["validate"])


def inputs() -> list[dict[str, Any]]:
    names = (
        "requirements-source.json",
        "plan.json",
        "contracts/resource-catalog.json",
        "contracts/action-catalog.json",
        "contracts/operator-api.openapi.json",
        "contracts/resource-schemas.json",
        "history/2026-11-12/requirements.json",
        "legacy-coverage.json",
    )
    return [json.loads((ROOT / name).read_text()) for name in names]


def test_current_baseline_has_no_lost_scope_or_contract_errors() -> None:
    assert VALIDATE(*inputs()) == []


def test_removing_a_legacy_requirement_is_not_silent() -> None:
    values = inputs()
    original_id = values[0]["legacy_requirement_ids"][0]
    values[0]["requirements"] = [r for r in values[0]["requirements"] if r["id"] != original_id]
    assert any("lost legacy requirement" in error for error in VALIDATE(*values))


def test_milestone_cycles_cannot_be_scheduled() -> None:
    values = inputs()
    values[1]["milestones"][0]["depends_on"] = ["MS1"]
    assert any("milestone cycle" in error for error in VALIDATE(*values))


def test_mutable_resource_requires_a_complete_state_machine() -> None:
    values = inputs()
    task = next(r for r in values[2]["resource_types"] if r["kind"] == "Task")
    del task["transitions"]["todo"]
    assert any("state-machine coverage" in error for error in VALIDATE(*values))


def test_actions_cannot_target_unregistered_resource_kinds() -> None:
    values = inputs()
    values[3]["actions"][0]["target_kind"] = "UnregisteredPrivilegedObject"
    assert any("unknown target kind" in error for error in VALIDATE(*values))


def test_operator_api_cannot_silently_drop_authentication() -> None:
    values = inputs()
    values[4]["paths"]["/v1/capabilities"]["get"]["security"] = []
    assert any("unauthenticated control operation" in error for error in VALIDATE(*values))


def test_project_reference_contract_requires_project_scope() -> None:
    document = inputs()[4]
    schema = document["components"]["schemas"]["ResourceRef"]
    validator = jsonschema.Draft202012Validator(schema)
    valid = {
        "service": "sortyard",
        "installation_id": "inst-a",
        "workspace_id": "ws-a",
        "project_id": "proj-a",
        "kind": "Task",
        "id": "task-a",
    }
    validator.validate(valid)
    invalid = copy.deepcopy(valid)
    del invalid["project_id"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid)


def test_definition_reference_contract_requires_pinned_version() -> None:
    schema = inputs()[4]["components"]["schemas"]["ResourceRef"]
    validator = jsonschema.Draft202012Validator(schema)
    ref = {
        "service": "sortyard",
        "installation_id": "inst-a",
        "workspace_id": "ws-a",
        "kind": "SkillVersion",
        "id": "skill-a",
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(ref)
    validator.validate({**ref, "version": "1.0.0"})


def domain_validator(name: str) -> jsonschema.Draft202012Validator:
    document = inputs()[5]
    return jsonschema.Draft202012Validator(
        {**document, "$ref": f"#/$defs/{name}"},
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


def wire_validator(name: str) -> jsonschema.Draft202012Validator:
    document = inputs()[4]
    return jsonschema.Draft202012Validator(
        {"$ref": f"#/components/schemas/{name}", "components": document["components"]},
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


def reference(kind: str, identity: str) -> dict[str, str]:
    return {
        "service": "sortyard",
        "installation_id": "inst-a",
        "workspace_id": "ws-a",
        "kind": kind,
        "id": identity,
    }


def test_task_contract_preserves_board_state_and_claim_status_atomically() -> None:
    task: dict[str, Any] = {
        "title": "Fix a defect",
        "outcome": "The defect is corrected",
        "spec_ref": None,
        "depends_on": [],
        "parent_ref": None,
        "milestone_ref": None,
        "priority": "medium",
        "sequence": 1,
        "workflow_ref": None,
        "state": "in_progress",
        "queue_status": "claimed",
        "queue_reason": None,
        "queue_evidence_refs": [],
        "queue_route_refs": [],
    }
    validator = domain_validator("DomainTask")
    validator.validate(task)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({**task, "state": "todo"})
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({**task, "queue_status": "handed_back", "queue_reason": "blocked"})
    validator.validate(
        {
            **task,
            "queue_status": "handed_back",
            "queue_reason": "blocked",
            "queue_evidence_refs": [reference("DocumentArtifact", "evidence-a")],
        }
    )


@pytest.mark.parametrize("priority", ["urgent", "high", "medium", "low", "none"])
def test_every_retained_priority_is_accepted_by_task_edits(priority: str) -> None:
    wire_validator("TaskPatchArguments").validate(
        {"patch": {"priority": priority}, "reason": "Reprioritize the next task"}
    )
    with pytest.raises(jsonschema.ValidationError):
        wire_validator("TaskPatchArguments").validate(
            {"patch": {"priority": "normal"}, "reason": "Undeclared tier"}
        )


def test_compiler_rejects_board_queue_or_priority_semantic_drift() -> None:
    values = inputs()
    values[5]["$defs"]["DomainTask"]["properties"].pop("queue_status")
    assert any("task queue_status conflicts" in error for error in VALIDATE(*values))
    values = inputs()
    values[4]["components"]["schemas"]["EditableTaskFields"]["properties"]["priority"]["enum"] = [
        "urgent",
        "high",
        "normal",
        "low",
    ]
    assert any("editable task priority conflicts" in error for error in VALIDATE(*values))


def test_grant_data_retains_typed_actions_and_non_null_authority() -> None:
    grant: dict[str, Any] = {
        "authority_ref": reference("Operator", "op-a"),
        "executor_ref": reference("AgentDefinition", "agent-a"),
        "scope": [reference("Workspace", "ws-a")],
        "actions": ["task.create"],
        "audience": "sortyard",
        "parent_grant_ref": None,
        "issued_at": "2026-11-16T00:00:00Z",
        "expires_at": "2026-11-17T00:00:00Z",
        "revoked_at": None,
        "limits": {},
        "state": "active",
    }
    validator = domain_validator("DomainCapabilityGrant")
    validator.validate(grant)
    changes: tuple[dict[str, Any], ...] = (
        {"actions": "task.create"},
        {"actions": []},
        {"authority_ref": None},
        {"limits": {"silently_ignored_power": True}},
    )
    for change in changes:
        with pytest.raises(jsonschema.ValidationError):
            validator.validate({**grant, **change})
    arguments = {
        "executor_ref": grant["executor_ref"],
        "scope_refs": grant["scope"],
        "actions": grant["actions"],
        "expires_at": grant["expires_at"],
        "audience": grant["audience"],
        "limits": grant["limits"],
    }
    wire_validator("GrantArguments").validate(arguments)


def test_policy_decision_carries_reason_code_list() -> None:
    decision: dict[str, Any] = {
        "decision_point": "pickup",
        "consumer_ref": None,
        "policy_version_refs": [],
        "input_snapshot_ref": None,
        "verdict": "refuse",
        "reason_codes": ["lane_full", "dependency_held"],
        "fallback": None,
        "conflict_refs": [],
    }
    validator = domain_validator("DomainPolicyDecision")
    validator.validate(decision)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({**decision, "reason_codes": "lane_full"})


def test_approval_decision_and_answer_require_the_exact_plan_binding() -> None:
    plan_ref = reference("ActionPlan", "plan-a")
    binding = {
        "plan_ref": plan_ref,
        "plan_hash": "sha256:" + "1" * 64,
        "plan_revision": "rev-7",
        "expires_at": "2026-11-17T00:00:00Z",
    }
    decision: dict[str, Any] = {
        "question": "Approve this exact action?",
        "default_ref": None,
        "decide_by": "2026-11-17T00:00:00Z",
        "premise_class": True,
        "authority_ref": reference("Operator", "op-a"),
        "application_operation_ref": None,
        "state": "pending",
        "decision_kind": "action_plan_approval",
        "approval_binding": binding,
    }
    validator = domain_validator("DomainDecision")
    validator.validate(decision)
    invalid = copy.deepcopy(decision)
    del invalid["approval_binding"]["plan_hash"]
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid)
    answer = {
        "option": "approve",
        "why": "Within my authority",
        "approval": {k: v for k, v in binding.items() if k != "expires_at"},
    }
    wire_validator("DecisionArguments").validate(answer)
    with pytest.raises(jsonschema.ValidationError):
        wire_validator("DecisionArguments").validate({**answer, "option": "execute_anything"})


def test_compiler_requires_public_approval_action_and_fresh_authority_guards() -> None:
    values = inputs()
    del values[3]["approval_contract"]
    assert any("public plan approval" in error for error in VALIDATE(*values))
    values = inputs()
    values[3]["approval_contract"]["guards"].remove("current_approver_authority")
    assert any("approval guards missing" in error for error in VALIDATE(*values))


def test_retained_operator_capabilities_have_valid_registered_paths() -> None:
    values = inputs()
    actions = values[3]
    coverage = actions["operator_capability_coverage"]
    assert any(row["capability"] == "pause" for row in coverage)
    assert any(row["capability"] == "needs.discharge" for row in coverage)
    assert any(row["capability"] == "plan.approve" for row in coverage)
    actions["operator_capability_coverage"] = [
        row for row in coverage if row["capability"] != "pause"
    ]
    assert any(
        "missing operator capability mapping CLI-002:pause" in error for error in VALIDATE(*values)
    )
    values = inputs()
    values[3]["operator_capability_coverage"][0]["action_ids"] = ["privileged.hidden_shell"]
    assert any("unknown action in operator capability" in error for error in VALIDATE(*values))


def test_workspace_approval_refs_do_not_invent_a_project_scope() -> None:
    validator = wire_validator("ResourceRef")
    validator.validate(reference("ActionPlan", "workspace-plan"))
    validator.validate(reference("Decision", "workspace-approval"))
    validator.validate({**reference("Decision", "project-approval"), "project_id": "proj-a"})
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(reference("Task", "missing-project"))
