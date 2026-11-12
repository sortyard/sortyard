"""One function per routed operation of spec/openapi.json (see ``permissions.OPERATIONS``).

By the time a handler runs, the caller is authenticated, its role is in the operation's
``x-sortyard-roles`` and its token belongs to the path's workspace; the handler runs inside one
transaction. Handlers enforce what the role set cannot: the scope a token is confined to (a
build worker's stage run, a sensor's or grooming agent's project), the origin a sensor or
grooming agent may file under, the objects' state machines (§3.3), and the §3 schemas (via the
generated models). Every mutation writes an AuditLog entry and a ledger Event.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sortyard import models
from sortyard.api import auth, store
from sortyard.api.auth import Principal
from sortyard.api.store import ApiError, Conn, Doc, conflict, forbidden, not_found, unprocessable


@dataclass
class Request:
    conn: Conn
    principal: Principal
    workspace_id: str
    params: dict[str, str]
    query: dict[str, str]
    body: Any = None
    token_ttl_seconds: int = auth.DEFAULT_TTL_SECONDS

    @property
    def actor(self) -> Doc:
        return self.principal.actor


@dataclass
class Reply:
    status: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)


Handler = Callable[[Request], Reply]
HANDLERS: dict[str, Handler] = {}


def handles(operation_id: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[operation_id] = fn
        return fn

    return register


# --- shared checks --------------------------------------------------------------------------


def validate(model: type[models.Model], doc: Any, workspace_id: str) -> Doc:
    """The document as its §3 schema's model accepts it (422 otherwise)."""
    if not isinstance(doc, dict):
        raise unprocessable("the body must be a JSON object")
    try:
        decoded = model.from_dict(doc)
    except models.ModelError as exc:
        raise unprocessable(str(exc)) from None
    for key in ("id", "workspace_id"):
        if not re.match(store.ID_PATTERN, str(doc.get(key, ""))):
            raise unprocessable(f"{key} is not a valid id")
    if doc["workspace_id"] != workspace_id:
        raise unprocessable("workspace_id must be the workspace in the path", "wrong_workspace")
    return decoded.to_dict()


def object_body(req: Request) -> Doc:
    if not isinstance(req.body, dict):
        raise unprocessable("the body must be a JSON object")
    return req.body


def closed(body: Doc, allowed: set[str], required: Iterable[str] = ()) -> None:
    unknown = set(body) - allowed
    if unknown:
        raise unprocessable(f"unknown properties: {sorted(unknown)}")
    missing = set(required) - set(body)
    if missing:
        raise unprocessable(f"required properties missing: {sorted(missing)}")


def non_empty_string(body: Doc, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise unprocessable(f"{key} must be a non-empty string")
    return value


def in_project_scope(principal: Principal, project_id: Any) -> None:
    """A project-confined token (sensor, grooming agent, project-scoped operator) acts only
    in its own project."""
    if principal.project_id is not None and project_id != principal.project_id:
        raise forbidden(
            f"this token is confined to project {principal.project_id!r}", "project_scope"
        )


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386 JSON merge patch."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def listing(req: Request, table: str, filters: Mapping[str, str | None], **kw: Any) -> Reply:
    paging = store.Page.parse(req.query)
    return Reply(200, store.page(req.conn, table, req.workspace_id, filters, paging, **kw))


def found(doc: Doc | None, kind: str, oid: str) -> Doc:
    if doc is None:
        raise not_found(kind, oid)
    return doc


# --- tasks (§3.3) -------------------------------------------------------------------------

TASK_STATES = ("backlog", "todo", "claimed", "in_progress", "in_review", "merging", "done")
SIDE_STATES = ("blocked", "handed_back", "cancelled")
TERMINAL = ("done", "cancelled")
ACTIVE_CHAIN = ("running", "stalled")
# Fields only the transitions write: a groom (updateTask) may not touch them.
TRANSITION_FIELDS = {
    "id",
    "workspace_id",
    "project_id",
    "origin",
    "state",
    "stage",
    "chain_id",
    "blocked_reason",
    "handback_reason",
    "handback_evidence",
    "self_heal_id",
    "sequence",
}
# Transition fields a new task may not carry: it has no chain, block or hand-back yet.
CREATION_REFUSED = TRANSITION_FIELDS - {
    "id",
    "workspace_id",
    "project_id",
    "origin",
    "state",
    "sequence",
}
# Forward moves of the §3.3 state machine the conductor makes with advanceTask.
ADVANCES = {
    "claimed": {"in_progress"},
    "in_progress": {"in_progress", "in_review"},
    "in_review": {"in_progress", "merging"},
    "merging": {"done"},
}
# The origin a project-confined agent files under.
ORIGIN_FOR = {"sensor": "sensor", "grooming-agent": "grooming"}


def load_task(req: Request, *, lock: bool = False) -> Doc:
    tid = req.params["task_id"]
    doc = found(store.get(req.conn, "task", req.workspace_id, tid, lock=lock), "task", tid)
    in_project_scope(req.principal, doc.get("project_id"))
    return doc


def save_task(
    req: Request,
    before: Doc,
    after: Doc,
    transition: str,
    *,
    reason: str | None = None,
    facts: Doc | None = None,
    refs: tuple[str, ...] = (),
) -> Doc:
    after = validate(models.Task, after, req.workspace_id)
    store.replace(req.conn, "task", after)
    return store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "task",
        after["id"],
        action="update",
        transition=transition,
        before=before,
        after=after,
        reason=reason,
        facts=facts,
        refs=refs,
    )


def set_chain_state(req: Request, chain_id: str | None, state: str, transition: str) -> None:
    if not chain_id:
        return
    chain = store.get(req.conn, "chain", req.workspace_id, chain_id, lock=True)
    if chain is None or chain.get("state") not in ACTIVE_CHAIN:
        return
    after = {**chain, "state": state, "finished_at": store.now()}
    store.replace(req.conn, "chain", after)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "chain",
        chain_id,
        action="update",
        transition=transition,
        before=chain,
        after=after,
    )


def decision_log(req: Request, task: Doc, decision: str, reasons: list[str], **inputs: Any) -> Doc:
    """A DecisionLog entry for a conductor decision made through the API, with its ledger
    event (linked both ways)."""
    entry_id = store.new_id("dl")
    event = store.append_event(
        req.conn,
        req.workspace_id,
        req.actor,
        "task",
        task["id"],
        f"decision_{decision}",
        facts={"decision": decision, "reason_codes": reasons},
        refs=[f"decision-log:{entry_id}"],
    )
    entry: Doc = {
        "id": entry_id,
        "workspace_id": req.workspace_id,
        "ts": event["ts"],
        "conductor_pass_id": store.new_id("api-pass"),
        "decision": decision,
        "task_id": task["id"],
        "reason_codes": reasons,
        "inputs": {
            "policy_versions": [],
            "queue_snapshot_hash": store.content_hash(task),
            **inputs,
        },
        "event_id": event["id"],
    }
    store.insert(req.conn, "decision_log", entry)
    return entry


@handles("listTasks")
def list_tasks(req: Request) -> Reply:
    q = req.query
    project = q.get("project_id")
    if req.principal.project_id is not None:
        if project is not None and project != req.principal.project_id:
            raise forbidden(f"this token is confined to project {req.principal.project_id!r}")
        project = req.principal.project_id
    state = q.get("state")
    if state is not None and state not in TASK_STATES + SIDE_STATES:
        raise store.bad_request(f"unknown state {state!r}")
    filters = {
        "project_id": project,
        "state": state,
        "milestone_id": q.get("milestone_id"),
        "lane_id": q.get("lane_id"),
    }
    extra = ("doc ->> 'origin' = %s", [q["origin"]]) if q.get("origin") else None
    return listing(req, "task", filters, extra=extra)


@handles("getTask")
def get_task(req: Request) -> Reply:
    return Reply(200, load_task(req))


@handles("createTask")
def create_task(req: Request) -> Reply:
    doc = validate(models.Task, req.body, req.workspace_id)
    role = req.principal.role
    if role in ORIGIN_FOR and doc["origin"] != ORIGIN_FOR[role]:
        raise forbidden(
            f"a {role} token files only origin {ORIGIN_FOR[role]!r} tasks", "origin_scope"
        )
    in_project_scope(req.principal, doc["project_id"])
    if doc["state"] not in ("backlog", "todo"):
        raise conflict("a task starts in backlog or todo", "initial_state")
    managed = sorted(set(doc) & CREATION_REFUSED)
    if managed:
        raise conflict(f"set by transitions, not at creation: {managed}", "transition_field")
    if not store.exists(req.conn, "project", req.workspace_id, doc["project_id"]):
        raise unprocessable(f"no project {doc['project_id']!r} in this workspace", "unknown_ref")
    if store.exists(req.conn, "task", req.workspace_id, doc["id"]):
        raise conflict(f"task {doc['id']!r} exists", "exists")
    store.insert(req.conn, "task", doc)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "task",
        doc["id"],
        action="create",
        transition="create",
        before=None,
        after=doc,
    )
    return Reply(201, doc)


@handles("updateTask")
def update_task(req: Request) -> Reply:
    patch = object_body(req)
    touched = sorted(set(patch) & TRANSITION_FIELDS)
    if touched:
        raise conflict(f"changed only by transitions: {touched}", "transition_field")
    before = load_task(req, lock=True)
    if before["state"] in TERMINAL:
        raise conflict(f"task is {before['state']}", "terminal")
    after = merge_patch(before, patch)
    save_task(req, before, after, "groom")
    return Reply(200, after)


@handles("markTaskReady")
def mark_task_ready(req: Request) -> Reply:
    before = load_task(req, lock=True)
    if before["state"] != "backlog":
        raise conflict(f"only a backlog task is made ready (task is {before['state']})", "state")
    missing = [k for k in ("lane_id", "workflow") if k not in before]
    if missing:
        raise conflict(
            f"not schedulable from its recorded state alone: no {', '.join(missing)}",
            "not_schedulable",
        )
    after = {**before, "state": "todo"}
    save_task(req, before, after, "ready")
    return Reply(200, after)


@handles("claimTask")
def claim_task(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"lane_id", "execution_binding_id"}, {"lane_id", "execution_binding_id"})
    lane_id = non_empty_string(body, "lane_id")
    binding_id = non_empty_string(body, "execution_binding_id")
    task = load_task(req, lock=True)
    if task["state"] != "todo":
        raise conflict(f"only a todo task is claimed (task is {task['state']})", "state")
    if "workflow" not in task:
        raise conflict("the task names no workflow to pin", "no_workflow")
    lane = found(store.get(req.conn, "lane", req.workspace_id, lane_id, lock=True), "lane", lane_id)
    binding = found(
        store.get(req.conn, "execution_binding", req.workspace_id, binding_id),
        "execution binding",
        binding_id,
    )
    if binding.get("task_id") != task["id"]:
        raise conflict("the execution binding is for another task", "binding_mismatch")
    if binding.get("state") != "bound":
        codes = [r.get("code", "?") for r in binding.get("unbound_reasons", [])]
        raise ApiError(409, "Conflict", f"unbound: {', '.join(codes)}", "unbound")
    eligible = lane.get("eligible_projects")
    if eligible and task["project_id"] not in eligible:
        raise conflict(f"lane {lane_id!r} does not take this project", "lane_ineligible")
    held = req.conn.execute(
        "SELECT count(*) FROM sortyard.chain WHERE workspace_id = %s AND lane_id = %s"
        " AND state = ANY(%s)",
        [req.workspace_id, lane_id, list(ACTIVE_CHAIN)],
    ).fetchone()
    if held is not None and held[0] >= lane["max_concurrent_chains"]:
        raise conflict(f"lane {lane_id!r} is full", "lane_full")

    attempt = req.conn.execute(
        "SELECT count(*) FROM sortyard.chain WHERE workspace_id = %s AND task_id = %s",
        [req.workspace_id, task["id"]],
    ).fetchone()
    chain: Doc = {
        "id": f"chain-{task['id']}-{(attempt[0] if attempt else 0) + 1}"[:200],
        "workspace_id": req.workspace_id,
        "task_id": task["id"],
        "workflow": task["workflow"],
        "state": "running",
        "stage_runs": [],
        "revision_round": 0,
        "lane_id": lane_id,
        "started_at": store.now(),
    }
    chain = validate(models.Chain, chain, req.workspace_id)
    store.insert(req.conn, "chain", chain)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "chain",
        chain["id"],
        action="create",
        transition="create",
        before=None,
        after=chain,
    )
    entry = decision_log(req, task, "claim", [], execution_binding_id=binding_id)
    after = {**task, "state": "claimed", "chain_id": chain["id"], "lane_id": lane_id}
    save_task(
        req,
        task,
        after,
        "claim",
        facts={"lane": lane_id, "execution_binding_id": binding_id},
        refs=(f"decision-log:{entry['id']}", f"chain:{chain['id']}"),
    )
    return Reply(201, chain)


@handles("advanceTask")
def advance_task(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"state", "stage"}, {"state"})
    state = body["state"]
    if state not in TASK_STATES + SIDE_STATES:
        raise unprocessable(f"unknown state {state!r}")
    if "stage" in body:
        non_empty_string(body, "stage")
    task = load_task(req, lock=True)
    if state not in ADVANCES.get(task["state"], set()):
        raise conflict(f"no advance from {task['state']} to {state}", "state")
    if state == "in_progress" and "stage" not in body:
        raise unprocessable("in_progress needs the stage")
    after = {**task, "state": state}
    if "stage" in body:
        after["stage"] = body["stage"]
    chain_id = task.get("chain_id")
    if chain_id and "stage" in body:
        chain = store.get(req.conn, "chain", req.workspace_id, chain_id, lock=True)
        if chain is not None and chain.get("state") in ACTIVE_CHAIN:
            store.replace(req.conn, "chain", {**chain, "current_stage": body["stage"]})
    if state == "done":
        set_chain_state(req, chain_id, "succeeded", "succeed")
    save_task(req, task, after, "advance")
    return Reply(200, after)


@handles("handBackTask")
def hand_back_task(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"handback_reason", "handback_evidence"}, {"handback_reason", "handback_evidence"})
    reason = non_empty_string(body, "handback_reason")
    evidence = body["handback_evidence"]
    if (
        not isinstance(evidence, list)
        or not evidence
        or not all(isinstance(e, str) and e for e in evidence)
    ):
        raise unprocessable("handback_evidence must be a non-empty list of non-empty strings")
    task = load_task(req, lock=True)
    if task["state"] not in ("claimed", "in_progress", "in_review", "merging"):
        raise conflict(f"only claimed work is handed back (task is {task['state']})", "state")
    heal: Doc = {
        "id": store.new_id("sh"),
        "workspace_id": req.workspace_id,
        "task_id": task["id"],
        "worker_account": reason,
        "evidence": evidence,
        "assignee": {"kind": "system", "id": "self-heal"},
        "state": "open",
        "opened_at": store.now(),
    }
    heal = validate(models.SelfHeal, heal, req.workspace_id)
    store.insert(req.conn, "self_heal", heal)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "self_heal",
        heal["id"],
        action="create",
        transition="open",
        before=None,
        after=heal,
    )
    set_chain_state(req, task.get("chain_id"), "handed_back", "hand_back")
    entry = decision_log(req, task, "hand_back", [f"handed back: {reason}"])
    after = {
        **task,
        "state": "handed_back",
        "handback_reason": reason,
        "handback_evidence": evidence,
        "self_heal_id": heal["id"],
    }
    save_task(req, task, after, "hand_back", reason=reason, refs=(f"decision-log:{entry['id']}",))
    return Reply(200, after)


@handles("blockTask")
def block_task(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"blocked_reason"}, {"blocked_reason"})
    reason = non_empty_string(body, "blocked_reason")
    task = load_task(req, lock=True)
    if task["state"] in (*TERMINAL, "blocked"):
        raise conflict(f"a {task['state']} task cannot be blocked", "state")
    after = {**task, "state": "blocked", "blocked_reason": reason}
    save_task(req, task, after, "block", reason=reason)
    return Reply(200, after)


@handles("unblockTask")
def unblock_task(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"reason"}, {"reason"})
    reason = non_empty_string(body, "reason")
    task = load_task(req, lock=True)
    if task["state"] != "blocked":
        raise conflict(f"task is {task['state']}, not blocked", "state")
    # Back to the state it was blocked from, as the ledger recorded it.
    previous = store.last_transition_from(req.conn, "task", task["id"], "block") or "todo"
    if previous == "in_progress" and "stage" not in task:
        previous = "claimed"
    after = {k: v for k, v in task.items() if k != "blocked_reason"}
    after["state"] = previous
    save_task(req, task, after, "unblock", reason=reason)
    return Reply(200, after)


@handles("cancelTask")
def cancel_task(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"reason"}, {"reason"})
    reason = non_empty_string(body, "reason")
    task = load_task(req, lock=True)
    if task["state"] in TERMINAL:
        raise conflict(f"task is {task['state']}", "terminal")
    set_chain_state(req, task.get("chain_id"), "cancelled", "cancel")
    after = {**task, "state": "cancelled"}
    save_task(req, task, after, "cancel", reason=reason)
    return Reply(200, after)


@handles("requeueTask")
def requeue_task(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"reason"}, {"reason"})
    reason = non_empty_string(body, "reason")
    task = load_task(req, lock=True)
    if task["state"] not in ("claimed", "blocked", "handed_back"):
        raise conflict(f"a {task['state']} task is not requeued", "state")
    set_chain_state(req, task.get("chain_id"), "cancelled", "requeue")  # releases the slot
    dropped = {"chain_id", "stage", "blocked_reason", "handback_reason", "handback_evidence"}
    after = {k: v for k, v in task.items() if k not in dropped}
    after["state"] = "todo"
    save_task(req, task, after, "requeue", reason=reason)
    return Reply(200, after)


@handles("listTaskDecisionLog")
def list_task_decision_log(req: Request) -> Reply:
    task = load_task(req)
    return listing(req, "decision_log", {"task_id": task["id"]}, order="recorded_at, id")


# --- decisions (§3.3) ---------------------------------------------------------------------


@handles("listDecisions")
def list_decisions(req: Request) -> Reply:
    q = req.query
    filters = {
        "project_id": q.get("project_id"),
        "state": q.get("state"),
        "task_id": q.get("task_id"),
    }
    return listing(req, "decision", filters)


@handles("getDecision")
def get_decision(req: Request) -> Reply:
    did = req.params["decision_id"]
    return Reply(
        200, found(store.get(req.conn, "decision", req.workspace_id, did), "decision", did)
    )


@handles("createDecision")
def create_decision(req: Request) -> Reply:
    doc = validate(models.Decision, req.body, req.workspace_id)
    # DecisionCreate: created open, with no resolution — no creator can record an answer.
    answered = sorted({"resolution", "answered_by", "answer_channel", "resolved_at"} & set(doc))
    if doc["state"] != "open" or answered:
        raise unprocessable("a decision is created open and unanswered", "decision_create")
    if store.exists(req.conn, "decision", req.workspace_id, doc["id"]):
        raise conflict(f"decision {doc['id']!r} exists", "exists")
    store.insert(req.conn, "decision", doc)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "decision",
        doc["id"],
        action="create",
        transition="open",
        before=None,
        after=doc,
    )
    return Reply(201, doc)


@handles("answerDecision")
def answer_decision(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"resolution", "answer_channel"}, {"resolution"})
    resolution = non_empty_string(body, "resolution")
    channel = body.get("answer_channel", "api")
    if channel not in ("ui", "integration_comment", "api"):
        raise unprocessable(f"unknown answer_channel {channel!r}")
    did = req.params["decision_id"]
    before = found(
        store.get(req.conn, "decision", req.workspace_id, did, lock=True), "decision", did
    )
    if before["state"] != "open":
        raise conflict(f"decision is {before['state']}", "state")
    if before.get("options") and resolution not in before["options"]:
        raise unprocessable(f"resolution must be one of {before['options']}")
    after = {
        **before,
        "state": "answered",
        "resolution": resolution,
        "answered_by": req.actor,
        "answer_channel": channel,
        "resolved_at": store.now(),
    }
    after = validate(models.Decision, after, req.workspace_id)
    store.replace(req.conn, "decision", after)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "decision",
        did,
        action="update",
        transition="answer",
        before=before,
        after=after,
    )
    return Reply(200, after)


# --- lanes (§3.4) -------------------------------------------------------------------------


@handles("listLanes")
def list_lanes(req: Request) -> Reply:
    scope = req.query.get("scope")
    if scope is not None and scope not in ("conductor", "dispatcher"):
        raise store.bad_request(f"unknown scope {scope!r}")
    return listing(req, "lane", {"scope": scope})


@handles("getLane")
def get_lane(req: Request) -> Reply:
    lid = req.params["lane_id"]
    return Reply(200, found(store.get(req.conn, "lane", req.workspace_id, lid), "lane", lid))


@handles("createLane")
def create_lane(req: Request) -> Reply:
    doc = validate(models.Lane, req.body, req.workspace_id)
    if store.exists(req.conn, "lane", req.workspace_id, doc["id"]):
        raise conflict(f"lane {doc['id']!r} exists", "exists")
    store.insert(req.conn, "lane", doc)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "lane",
        doc["id"],
        action="create",
        transition="create",
        before=None,
        after=doc,
    )
    return Reply(201, doc)


@handles("updateLane")
def update_lane(req: Request) -> Reply:
    patch = object_body(req)
    if {"id", "workspace_id"} & set(patch):
        raise conflict("a lane's id and workspace are fixed", "immutable_field")
    lid = req.params["lane_id"]
    before = found(store.get(req.conn, "lane", req.workspace_id, lid, lock=True), "lane", lid)
    after = validate(models.Lane, merge_patch(before, patch), req.workspace_id)
    store.replace(req.conn, "lane", after)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "lane",
        lid,
        action="update",
        transition="update",
        before=before,
        after=after,
    )
    return Reply(200, after)


@handles("deleteLane")
def delete_lane(req: Request) -> Reply:
    lid = req.params["lane_id"]
    before = found(store.get(req.conn, "lane", req.workspace_id, lid, lock=True), "lane", lid)
    busy = req.conn.execute(
        "SELECT count(*) FROM sortyard.chain WHERE workspace_id = %s AND lane_id = %s"
        " AND state = ANY(%s)",
        [req.workspace_id, lid, list(ACTIVE_CHAIN)],
    ).fetchone()
    if busy is not None and busy[0]:
        raise conflict(f"lane {lid!r} holds {busy[0]} running chain(s)", "lane_busy")
    store.delete(req.conn, "lane", req.workspace_id, lid)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "lane",
        lid,
        action="delete",
        transition="delete",
        before=before,
        after=None,
    )
    return Reply(204)


# --- policies (§3.5, §3.6): definitions, versioned and content-hashed (§5.1) -----------------

DEFINITIONS: dict[str, tuple[str, str, type[models.Model]]] = {
    # operationId suffix -> (table, path parameter, model)
    "Policy": ("policy", "policy_id", models.Policy),
    "PrioritizationPolicy": (
        "prioritization_policy",
        "prioritization_policy_id",
        models.PrioritizationPolicy,
    ),
    "SequencingPolicy": ("sequencing_policy", "sequencing_policy_id", models.SequencingPolicy),
}
PLURAL = {
    "Policy": "Policies",
    "PrioritizationPolicy": "PrioritizationPolicies",
    "SequencingPolicy": "SequencingPolicies",
}


def _definition_handlers(name: str, table: str, param: str) -> None:
    kind = table.replace("_", " ")

    def list_latest(req: Request) -> Reply:
        return listing(req, table, {}, latest_definitions=True)

    def get_latest(req: Request) -> Reply:
        oid = req.params[param]
        return Reply(
            200, found(store.get_definition(req.conn, table, req.workspace_id, oid), kind, oid)
        )

    def list_versions(req: Request) -> Reply:
        oid = req.params[param]
        if store.get_definition(req.conn, table, req.workspace_id, oid) is None:
            raise not_found(kind, oid)
        return listing(req, table, {"id": oid}, order="recorded_at, version")

    def get_version(req: Request) -> Reply:
        oid, version = req.params[param], req.params["version"]
        doc = store.get_definition(req.conn, table, req.workspace_id, oid, version)
        return Reply(200, found(doc, f"{kind} version", f"{oid}@{version}"))

    handles(f"list{PLURAL[name]}")(list_latest)
    handles(f"get{name}")(get_latest)
    handles(f"list{name}Versions")(list_versions)
    handles(f"get{name}Version")(get_version)


for _name, (_table, _param, _model) in DEFINITIONS.items():
    _definition_handlers(_name, _table, _param)


def materialise(req: Request, model: type[models.Model], table: str) -> Doc:
    """A new immutable definition version from the API (DB mode, §5.1): validated, stamped
    with its content hash, recorded."""
    doc = validate(model, req.body, req.workspace_id)
    doc.setdefault("source", "db")
    computed = store.content_hash(doc)
    if doc.get("content_hash", computed) != computed:
        raise unprocessable("content_hash does not match the document", "content_hash")
    doc["content_hash"] = computed
    store.insert(req.conn, table, doc)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        table,
        doc["id"],
        action="create",
        transition="version",
        before=None,
        after=doc,
        facts={"version": doc["version"], "content_hash": computed},
    )
    return doc


@handles("createPolicy")
def create_policy(req: Request) -> Reply:
    body = object_body(req)
    if store.get_definition(req.conn, "policy", req.workspace_id, str(body.get("id"))):
        raise conflict(f"policy {body.get('id')!r} exists; propose a new version", "exists")
    return Reply(201, materialise(req, models.Policy, "policy"))


@handles("proposePolicyVersion")
def propose_policy_version(req: Request) -> Reply:
    body = object_body(req)
    pid = req.params["policy_id"]
    if body.get("id") != pid:
        raise unprocessable("the version's id must be the policy in the path")
    if store.get_definition(req.conn, "policy", req.workspace_id, pid) is None:
        raise not_found("policy", pid)
    version = body.get("version")
    if isinstance(version, str) and store.get_definition(
        req.conn, "policy", req.workspace_id, pid, version
    ):
        raise conflict(f"policy {pid}@{version} exists; versions are immutable", "exists")
    return Reply(201, materialise(req, models.Policy, "policy"))


# --- the DecisionLog (§3.8) ---------------------------------------------------------------


@handles("listDecisionLog")
def list_decision_log(req: Request) -> Reply:
    q = req.query
    decision = q.get("decision")
    if decision is not None and decision not in ("claim", "skip", "hand_back", "merge", "stall"):
        raise store.bad_request(f"unknown decision {decision!r}")
    filters = {
        "task_id": q.get("task_id"),
        "conductor_pass_id": q.get("conductor_pass_id"),
        "decision": decision,
    }
    return listing(req, "decision_log", filters, order="recorded_at, id")


@handles("getDecisionLogEntry")
def get_decision_log_entry(req: Request) -> Reply:
    did = req.params["decision_log_id"]
    doc = store.get(req.conn, "decision_log", req.workspace_id, did)
    return Reply(200, found(doc, "decision log entry", did))


# --- findings (§3.8) ----------------------------------------------------------------------


@handles("createAlert")
def create_alert(req: Request) -> Reply:
    doc = validate(models.Alert, req.body, req.workspace_id)
    source = doc.setdefault("source", req.actor)
    if source != req.actor:
        raise forbidden("a finding is filed under the caller's own identity", "source")
    if req.principal.project_id is not None:
        subject = doc["subject"]
        if subject["kind"] == "project":
            project = subject["ref"]
        elif subject["kind"] == "task":
            task = store.get(req.conn, "task", req.workspace_id, subject["ref"])
            project = None if task is None else task.get("project_id")
        else:
            project = None
        in_project_scope(req.principal, project)
    if doc["state"] != "open":
        raise conflict("a finding is filed open", "initial_state")
    if store.exists(req.conn, "alert", req.workspace_id, doc["id"]):
        raise conflict(f"alert {doc['id']!r} exists", "exists")
    store.insert(req.conn, "alert", doc)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "alert",
        doc["id"],
        action="create",
        transition="open",
        before=None,
        after=doc,
    )
    return Reply(201, doc)


# --- a build worker's two calls (§7) ------------------------------------------------------


def load_stage_run(req: Request, *, lock: bool = False) -> Doc:
    srid = req.params["stage_run_id"]
    if req.principal.role == "build-worker" and req.principal.stage_run_id != srid:
        raise forbidden(
            "a build-worker token reaches only the stage run it was issued for", "stage_run_scope"
        )
    return found(
        store.get(req.conn, "stage_run", req.workspace_id, srid, lock=lock), "stage run", srid
    )


@handles("getStageRunContextPacket")
def get_stage_run_context_packet(req: Request) -> Reply:
    run = load_stage_run(req)
    packet: Doc = {"packet_hash": run["inputs_packet_hash"], "items": []}
    if run.get("inputs_packet_ref"):
        packet["packet_ref"] = run["inputs_packet_ref"]
    binding = store.get(
        req.conn, "execution_binding", req.workspace_id, run["execution_binding_id"]
    )
    if binding is not None and isinstance(binding.get("context"), dict):
        packet["recipe"] = binding["context"]["recipe"]
    # Packet content lives in the packet store the Context Assembler fills (Phase 3A); until
    # then the API serves the packet's identity, and says so.
    packet["warnings"] = [
        "packet content is not held by this installation yet: items are served once the "
        "context assembler stores packets; packet_hash identifies the inputs"
    ]
    return Reply(200, packet)


@handles("submitStageRunResult")
def submit_stage_run_result(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"state", "outputs", "observed_facts", "cost", "duration_seconds"}, {"state"})
    if body["state"] not in ("succeeded", "failed"):
        raise unprocessable("a result's state is succeeded or failed")
    before = load_stage_run(req, lock=True)
    if before["state"] not in ("pending", "running"):
        raise conflict(f"the stage run is already {before['state']}: one result per run", "state")
    after = validate(
        models.StageRun, {**before, **body, "finished_at": store.now()}, req.workspace_id
    )
    store.replace(req.conn, "stage_run", after)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "stage_run",
        after["id"],
        action="update",
        transition="result",
        before=before,
        after=after,
    )
    return Reply(200, after)


# --- the Integrator (§3.7a) ---------------------------------------------------------------


@handles("instructIntegrator")
def instruct_integrator(req: Request) -> Reply:
    body = object_body(req)
    closed(body, {"task_id", "chain_id"}, {"task_id", "chain_id"})
    task_id = non_empty_string(body, "task_id")
    chain_id = non_empty_string(body, "chain_id")
    iid = req.params["integrator_id"]
    integrator = found(store.get(req.conn, "integrator", req.workspace_id, iid), "integrator", iid)
    task = found(store.get(req.conn, "task", req.workspace_id, task_id, lock=True), "task", task_id)
    chain = found(store.get(req.conn, "chain", req.workspace_id, chain_id), "chain", chain_id)
    if chain.get("task_id") != task_id or task.get("chain_id") != chain_id:
        raise conflict("the chain is not the task's current chain", "chain_mismatch")
    if task["state"] != "merging":
        raise conflict(f"only a merging task is landed (task is {task['state']})", "state")
    # The landing itself happens behind the Integrator's fence (proof receipt, verify approval,
    # tree identity); the instruction is a ledger event the Integrator consumes.
    event = store.append_event(
        req.conn,
        req.workspace_id,
        req.actor,
        "chain",
        chain_id,
        "landing_instructed",
        before=chain.get("state"),
        after=chain.get("state"),
        facts={"integrator_id": iid, "task_id": task_id, "fence": integrator["fence"]},
        refs=[f"integrator:{iid}", f"task:{task_id}"],
    )
    store.audit(
        req.conn,
        req.workspace_id,
        req.actor,
        "create",
        "landing",
        event["id"],
        None,
        {"integrator_id": iid, "task_id": task_id, "chain_id": chain_id},
    )
    return Reply(202, event)


# --- admin: role bindings and service-account tokens (§3.9, §7) ----------------------------


@handles("createRoleBinding")
def create_role_binding(req: Request) -> Reply:
    doc = validate(models.RoleBinding, req.body, req.workspace_id)
    agent = doc["role"] == "agent-service-account"
    if (doc["principal"]["kind"] == "agent") != agent:
        raise unprocessable(
            "agent-service-account binds an agent principal; the other roles bind operators"
        )
    if store.exists(req.conn, "role_binding", req.workspace_id, doc["id"]):
        raise conflict(f"role binding {doc['id']!r} exists", "exists")
    doc.setdefault("granted_by", req.actor)
    store.insert(req.conn, "role_binding", doc)
    store.record(
        req.conn,
        req.workspace_id,
        req.actor,
        "role_binding",
        doc["id"],
        action="create",
        transition="grant",
        before=None,
        after=doc,
    )
    return Reply(201, doc)


@handles("issueServiceAccountToken")
def issue_service_account_token(req: Request) -> Reply:
    issued = auth.issue_service_account_token(
        req.conn,
        req.workspace_id,
        req.params["role_binding_id"],
        object_body(req),
        req.actor,
        req.token_ttl_seconds,
    )
    return Reply(201, issued.body())
