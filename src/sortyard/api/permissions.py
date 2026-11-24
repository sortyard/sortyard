"""The §7 permission matrix, enforced in code (design draft §7; spec/openapi.json).

Every operation the API service routes is declared here with the roles that may invoke it —
the operation's ``x-sortyard-roles`` in the OpenAPI spec — and its capability
(``x-sortyard-capability``). tests/test_api_contract.py holds this table to the spec, so the
code and the contract cannot drift. A role outside an operation's set is refused (403) before
anything is read; scope rules the role set cannot express (a build worker's own stage run, a
sensor's own project) are enforced by the handlers.

Roles: operator accounts carry their RoleBinding role (admin, operator, viewer; §3.9);
service-account tokens carry an agent role (conductor, build-worker, sensor, grooming-agent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HUMAN_ROLES = ("admin", "operator", "viewer")
AGENT_ROLES = ("conductor", "build-worker", "sensor", "grooming-agent")
ROLES = HUMAN_ROLES + AGENT_ROLES

#: The queue-poisoning pair (§7): no token may hold both.
CREATE_AND_CLAIM = frozenset({"task.create", "task.claim"})


@dataclass(frozen=True)
class Operation:
    operation_id: str
    method: str
    #: The spec's path template, e.g. ``/v1/workspaces/{workspace_id}/tasks/{task_id}``.
    path: str
    roles: frozenset[str]
    capability: str | None

    @property
    def pattern(self) -> re.Pattern[str]:
        return re.compile(
            "^" + re.sub(r"\\{(\w+)\\}", r"(?P<\1>[^/]+)", re.escape(self.path)) + "$"
        )


def _op(
    operation_id: str, method: str, path: str, roles: str, capability: str | None = None
) -> Operation:
    return Operation(
        operation_id,
        method,
        "/v1/workspaces/{workspace_id}" + path,
        frozenset(roles.split()),
        capability,
    )


_OPERATIONS = [
    # Work: the kernel's tracker view (HARNESS-V3 §3.2). Three reads of the projection and one
    # request; nothing here writes item state (admission creates an item with none).
    _op(
        "getProjectQueue",
        "GET",
        "/projects/{project_id}/queue",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "getItemTimeline",
        "GET",
        "/items/{item_id}/timeline",
        "admin operator viewer conductor grooming-agent",
    ),
    _op("getItem", "GET", "/items/{item_id}", "admin operator viewer conductor grooming-agent"),
    _op("requestItemChange", "POST", "/items/{item_id}/requests", "admin operator"),
    # Admission (HARNESS-V3 §3.5 step 4): the one way an item enters the kernel.
    _op("admitItem", "POST", "/items", "admin operator grooming-agent"),
    # Work: tasks (§3.3)
    _op("listTasks", "GET", "/tasks", "admin operator viewer conductor grooming-agent"),
    _op("createTask", "POST", "/tasks", "admin operator sensor grooming-agent", "task.create"),
    _op("getTask", "GET", "/tasks/{task_id}", "admin operator viewer conductor grooming-agent"),
    _op("updateTask", "PATCH", "/tasks/{task_id}", "admin operator grooming-agent", "task.groom"),
    _op(
        "markTaskReady",
        "POST",
        "/tasks/{task_id}/ready",
        "admin operator grooming-agent",
        "task.groom",
    ),
    _op("claimTask", "POST", "/tasks/{task_id}/claim", "conductor", "task.claim"),
    _op("advanceTask", "POST", "/tasks/{task_id}/advance", "conductor", "task.advance"),
    _op("handBackTask", "POST", "/tasks/{task_id}/hand-back", "conductor", "task.hand_back"),
    _op(
        "blockTask",
        "POST",
        "/tasks/{task_id}/block",
        "admin operator conductor grooming-agent",
        "task.block",
    ),
    _op(
        "unblockTask",
        "POST",
        "/tasks/{task_id}/unblock",
        "admin operator conductor grooming-agent",
        "task.block",
    ),
    _op("cancelTask", "POST", "/tasks/{task_id}/cancel", "admin operator", "task.cancel"),
    _op("requeueTask", "POST", "/tasks/{task_id}/requeue", "admin operator", "task.requeue"),
    _op(
        "listTaskDecisionLog",
        "GET",
        "/tasks/{task_id}/decision-log",
        "admin operator viewer conductor grooming-agent",
    ),
    # Work: decisions (§3.3)
    _op("listDecisions", "GET", "/decisions", "admin operator viewer conductor"),
    _op("createDecision", "POST", "/decisions", "admin operator conductor", "decision.create"),
    _op("getDecision", "GET", "/decisions/{decision_id}", "admin operator viewer conductor"),
    _op(
        "answerDecision",
        "POST",
        "/decisions/{decision_id}/answer",
        "admin operator",
        "decision.answer",
    ),
    # Tuning: lanes (§3.4)
    _op("listLanes", "GET", "/lanes", "admin operator viewer conductor"),
    _op("createLane", "POST", "/lanes", "admin operator", "lane.edit"),
    _op("getLane", "GET", "/lanes/{lane_id}", "admin operator viewer conductor"),
    _op("updateLane", "PATCH", "/lanes/{lane_id}", "admin operator", "lane.edit"),
    _op("deleteLane", "DELETE", "/lanes/{lane_id}", "admin operator", "lane.edit"),
    # Policies (§3.5, §3.6): read paths, and edits by operator accounts
    _op("listPolicies", "GET", "/policies", "admin operator viewer conductor"),
    _op("createPolicy", "POST", "/policies", "admin operator", "policy.edit"),
    _op("getPolicy", "GET", "/policies/{policy_id}", "admin operator viewer conductor"),
    _op(
        "listPolicyVersions",
        "GET",
        "/policies/{policy_id}/versions",
        "admin operator viewer conductor",
    ),
    _op(
        "proposePolicyVersion",
        "POST",
        "/policies/{policy_id}/versions",
        "admin operator",
        "policy.edit",
    ),
    _op(
        "getPolicyVersion",
        "GET",
        "/policies/{policy_id}/versions/{version}",
        "admin operator viewer conductor",
    ),
    _op(
        "listPrioritizationPolicies",
        "GET",
        "/prioritization-policies",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "getPrioritizationPolicy",
        "GET",
        "/prioritization-policies/{prioritization_policy_id}",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "listPrioritizationPolicyVersions",
        "GET",
        "/prioritization-policies/{prioritization_policy_id}/versions",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "getPrioritizationPolicyVersion",
        "GET",
        "/prioritization-policies/{prioritization_policy_id}/versions/{version}",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "listSequencingPolicies",
        "GET",
        "/sequencing-policies",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "getSequencingPolicy",
        "GET",
        "/sequencing-policies/{sequencing_policy_id}",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "listSequencingPolicyVersions",
        "GET",
        "/sequencing-policies/{sequencing_policy_id}/versions",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "getSequencingPolicyVersion",
        "GET",
        "/sequencing-policies/{sequencing_policy_id}/versions/{version}",
        "admin operator viewer conductor grooming-agent",
    ),
    # Evidence: the DecisionLog (§3.8) and findings
    _op(
        "listDecisionLog",
        "GET",
        "/decision-log",
        "admin operator viewer conductor grooming-agent",
    ),
    _op(
        "getDecisionLogEntry",
        "GET",
        "/decision-log/{decision_log_id}",
        "admin operator viewer conductor grooming-agent",
    ),
    _op("createAlert", "POST", "/alerts", "conductor sensor", "finding.file"),
    # Pipeline: a build worker's two calls, the Integrator instruction (§3.7a)
    _op(
        "getStageRunContextPacket",
        "GET",
        "/stage-runs/{stage_run_id}/context-packet",
        "admin operator viewer conductor build-worker",
    ),
    _op(
        "submitStageRunResult",
        "POST",
        "/stage-runs/{stage_run_id}/result",
        "build-worker",
        "stage_run.submit",
    ),
    _op(
        "instructIntegrator",
        "POST",
        "/integrators/{integrator_id}/landings",
        "conductor",
        "integrator.instruct",
    ),
    # Admin: role bindings and service-account tokens (§3.9, §7)
    _op("createRoleBinding", "POST", "/role-bindings", "admin", "role_binding.edit"),
    _op(
        "issueServiceAccountToken",
        "POST",
        "/role-bindings/{role_binding_id}/tokens",
        "admin",
        "token.issue",
    ),
]

OPERATIONS: dict[str, Operation] = {op.operation_id: op for op in _OPERATIONS}


def capabilities(role: str) -> frozenset[str]:
    """The role's column of the matrix: every capability of an operation it may invoke."""
    return frozenset(
        op.capability for op in OPERATIONS.values() if role in op.roles and op.capability
    )


def roles_with(capability: str) -> frozenset[str]:
    """Every role holding ``capability``."""
    return frozenset(
        r for op in OPERATIONS.values() if op.capability == capability for r in op.roles
    )
