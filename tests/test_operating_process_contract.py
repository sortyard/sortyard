"""Operating seeds cannot impersonate installed governance or self-verify recovery.

These are planning-contract checks, not a runtime recovery engine or migration proof.
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
VALIDATE = cast(
    Callable[[dict[str, Any]], list[str]],
    runpy.run_path(str(ROOT / "tools/gen.py"))["validate_operating_seeds"],
)


def seeds() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((ROOT / "seeds/operating-processes.json").read_text()))


def test_seed_catalog_has_explicit_consumer_coverage_and_valid_process_graphs() -> None:
    bundle = seeds()
    assert VALIDATE(bundle) == []
    for policy in bundle["policy_templates"]:
        jsonschema.Draft202012Validator.check_schema(policy["parameter_schema"])
    assert any(p["classification"] == "unimplemented_proposal" for p in bundle["policy_templates"])


def test_seed_installation_cannot_activate_a_policy_or_issue_actor_grants() -> None:
    bundle = seeds()
    bundle["actor_templates"][0]["grants"] = ["cluster-admin"]
    bundle["policy_templates"][0]["binding_status"] = "effective"
    bundle["policy_templates"][0]["default_mode"] = "refuse"
    errors = VALIDATE(bundle)
    assert any("cannot grant authority" in e for e in errors)
    assert any("remain unbound" in e for e in errors)
    assert any("cannot activate enforcement" in e for e in errors)


def test_declared_policy_field_without_consumer_is_detected() -> None:
    bundle = seeds()
    bundle["policy_templates"][0]["consumer_contract"]["parameter_names"] = []
    assert any("parameter coverage differs" in e for e in VALIDATE(bundle))


def test_unknown_or_self_reported_recovery_cannot_close_a_seed_process() -> None:
    bundle = seeds()
    step = bundle["process_templates"][0]["steps"][0]
    step["on"]["unknown"] = ["recovered"]
    assert any("needs successful verifier" in e for e in VALIDATE(bundle))


def test_process_cannot_reference_an_unregistered_role_or_policy() -> None:
    bundle = seeds()
    process = bundle["process_templates"][0]
    process["steps"][0]["role"] = "unrestricted-repairer"
    process["required_policy_template_ids"].append("imaginary-enforcement")
    errors = VALIDATE(bundle)
    assert any("unbound process seed role" in e for e in errors)
    assert any("unknown process seed policy" in e for e in errors)


def test_process_start_requests_limits_without_controlling_spent_counters() -> None:
    document = json.loads((ROOT / "contracts/operator-api.openapi.json").read_text())
    schema = copy.deepcopy(document["components"]["schemas"]["ProcessStartArguments"])
    schema["components"] = document["components"]
    validator = jsonschema.Draft202012Validator(schema)
    ref = {
        "service": "sortyard",
        "installation_id": "i",
        "workspace_id": "w",
        "kind": "Workspace",
        "id": "w",
    }
    arguments: dict[str, Any] = {
        "subject_refs": [ref],
        "condition_revision": "failure-7",
        "trigger_evidence_ref": ref,
        "budget": {
            "attempt_limit": 2,
            "elapsed_limit_seconds": 300,
            "agent_token_limit": 0,
            "external_effect_limit": 0,
        },
        "reason": "Investigate the observed condition",
    }
    validator.validate(arguments)
    arguments["budget"]["attempts_spent"] = 0
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(arguments)


def test_operating_process_version_reference_must_be_pinned() -> None:
    schema = json.loads((ROOT / "contracts/operator-api.openapi.json").read_text())["components"][
        "schemas"
    ]["ResourceRef"]
    validator = jsonschema.Draft202012Validator(schema)
    ref = {
        "service": "sortyard",
        "installation_id": "i",
        "workspace_id": "w",
        "kind": "OperationalProcessVersion",
        "id": "triage",
    }
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(ref)
    validator.validate({**ref, "version": "1.0.0"})


def test_running_process_retains_actor_snapshot_and_lease_expiry() -> None:
    document = json.loads((ROOT / "contracts/resource-schemas.json").read_text())
    validator = jsonschema.Draft202012Validator(
        {"$ref": "#/$defs/DomainOperationalProcessRun", "$defs": document["$defs"]}
    )

    def ref(kind: str, identity: str) -> dict[str, str]:
        return {
            "service": "sortyard",
            "installation_id": "i",
            "workspace_id": "w",
            "kind": kind,
            "id": identity,
        }

    actor = ref("OperationalActor", "coordinator")
    binding = {
        "actor_ref": actor,
        "configuration_revision": "actor-r7",
        "executor_ref": ref("AgentDefinition", "profile"),
        "executor_revision": "profile-r3",
        "grant_refs": [],
    }
    run: dict[str, Any] = {
        "process_version_ref": {**ref("OperationalProcessVersion", "triage"), "version": "1.0.0"},
        "subject_refs": [ref("Workspace", "w")],
        "condition_revision": "failed-3",
        "correlation_key": "incident-a",
        "actor_bindings": {"coordinator": binding},
        "lease_owner_ref": actor,
        "fence_epoch": 7,
        "lease_expires_at": "2026-11-16T04:00:00Z",
        "current_step": "plan",
        "budget": {
            "attempt_limit": 2,
            "attempts_spent": 1,
            "elapsed_limit_seconds": 300,
            "elapsed_spent_seconds": 30,
            "agent_token_limit": 0,
            "agent_tokens_spent": 0,
            "external_effect_limit": 0,
            "external_effects_spent": 0,
        },
        "case_refs": [],
        "attempt_refs": [],
        "operation_refs": [],
        "policy_decision_refs": [],
        "evidence_refs": [],
        "outcome": "pending",
        "parent_run_ref": None,
        "state": "running",
    }
    validator.validate(run)
    for changes in ({"lease_expires_at": None}, {"actor_bindings": {"coordinator": actor}}):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate({**run, **changes})
