# Sortyard API permission matrix (design §7)

Which roles may invoke each operation of `openapi.json`. The source of truth is each
operation's `x-sortyard-roles` (and its alternative `security` requirements); this table is a
readable summary of it, held to the spec by `spec/test_openapi.py`
(`test_matrix_document_matches_the_spec`). Human roles (`admin`, `operator`, `viewer`) authenticate
with an operator session; agent roles (`conductor`, `build-worker`, `sensor`, `grooming-agent`)
with a service-account token, and their operations are MCP tools. No role may both create and
claim tasks (§7).

| Operation | Method | Path | MCP tool | admin | operator | viewer | conductor | build-worker | sensor | grooming-agent |
|---|---|---|---|---|---|---|---|---|---|---|
| `getInstallation` | GET | `/v1/installation` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `updateInstallation` | PATCH | `/v1/installation` |  | ✓ |  |  |  |  |  |  |
| `getDeploymentConfig` | GET | `/v1/deployment-config` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `listWorkspaces` | GET | `/v1/workspaces` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `createWorkspace` | POST | `/v1/workspaces` |  | ✓ |  |  |  |  |  |  |
| `getWorkspace` | GET | `/v1/workspaces/{workspace_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `updateWorkspace` | PATCH | `/v1/workspaces/{workspace_id}` |  | ✓ |  |  |  |  |  |  |
| `listProjects` | GET | `/v1/workspaces/{workspace_id}/projects` | `list_projects` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createProject` | POST | `/v1/workspaces/{workspace_id}/projects` |  | ✓ | ✓ |  |  |  |  |  |
| `getProject` | GET | `/v1/workspaces/{workspace_id}/projects/{project_id}` | `get_project` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `updateProject` | PATCH | `/v1/workspaces/{workspace_id}/projects/{project_id}` |  | ✓ | ✓ |  |  |  |  |  |
| `transitionProject` | POST | `/v1/workspaces/{workspace_id}/projects/{project_id}/transition` |  | ✓ | ✓ |  |  |  |  |  |
| `upgradeProjectArchetype` | POST | `/v1/workspaces/{workspace_id}/projects/{project_id}/archetype-upgrade` |  | ✓ | ✓ |  |  |  |  |  |
| `listRepos` | GET | `/v1/workspaces/{workspace_id}/repos` | `list_repos` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createRepo` | POST | `/v1/workspaces/{workspace_id}/repos` |  | ✓ | ✓ |  |  |  |  |  |
| `getRepo` | GET | `/v1/workspaces/{workspace_id}/repos/{repo_id}` | `get_repo` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `updateRepo` | PATCH | `/v1/workspaces/{workspace_id}/repos/{repo_id}` |  | ✓ | ✓ |  |  |  |  |  |
| `deleteRepo` | DELETE | `/v1/workspaces/{workspace_id}/repos/{repo_id}` |  | ✓ | ✓ |  |  |  |  |  |
| `listTasks` | GET | `/v1/workspaces/{workspace_id}/tasks` | `list_tasks` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createTask` | POST | `/v1/workspaces/{workspace_id}/tasks` | `create_task` | ✓ | ✓ |  |  |  | ✓ | ✓ |
| `getTask` | GET | `/v1/workspaces/{workspace_id}/tasks/{task_id}` | `get_task` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `updateTask` | PATCH | `/v1/workspaces/{workspace_id}/tasks/{task_id}` | `update_task` | ✓ | ✓ |  |  |  |  | ✓ |
| `markTaskReady` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/ready` | `mark_task_ready` | ✓ | ✓ |  |  |  |  | ✓ |
| `claimTask` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/claim` | `claim_task` |  |  |  | ✓ |  |  |  |
| `advanceTask` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/advance` | `advance_task` |  |  |  | ✓ |  |  |  |
| `handBackTask` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/hand-back` | `hand_back_task` |  |  |  | ✓ |  |  |  |
| `blockTask` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/block` | `block_task` | ✓ | ✓ |  | ✓ |  |  | ✓ |
| `unblockTask` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/unblock` | `unblock_task` | ✓ | ✓ |  | ✓ |  |  | ✓ |
| `cancelTask` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/cancel` |  | ✓ | ✓ |  |  |  |  |  |
| `requeueTask` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/requeue` |  | ✓ | ✓ |  |  |  |  |  |
| `resequenceTask` | POST | `/v1/workspaces/{workspace_id}/tasks/{task_id}/sequence` | `resequence_task` | ✓ | ✓ |  |  |  |  | ✓ |
| `listTaskDecisionLog` | GET | `/v1/workspaces/{workspace_id}/tasks/{task_id}/decision-log` | `list_task_decision_log` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `getProjectQueue` | GET | `/v1/workspaces/{workspace_id}/projects/{project_id}/queue` | `get_project_queue` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `admitItem` | POST | `/v1/workspaces/{workspace_id}/items` | `admit_item` | ✓ | ✓ |  |  |  |  | ✓ |
| `getItem` | GET | `/v1/workspaces/{workspace_id}/items/{item_id}` | `get_item` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `getItemTimeline` | GET | `/v1/workspaces/{workspace_id}/items/{item_id}/timeline` | `get_item_timeline` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `requestItemChange` | POST | `/v1/workspaces/{workspace_id}/items/{item_id}/requests` |  | ✓ | ✓ |  |  |  |  |  |
| `listMilestones` | GET | `/v1/workspaces/{workspace_id}/milestones` | `list_milestones` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createMilestone` | POST | `/v1/workspaces/{workspace_id}/milestones` | `create_milestone` | ✓ | ✓ |  |  |  |  | ✓ |
| `getMilestone` | GET | `/v1/workspaces/{workspace_id}/milestones/{milestone_id}` | `get_milestone` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `updateMilestone` | PATCH | `/v1/workspaces/{workspace_id}/milestones/{milestone_id}` | `update_milestone` | ✓ | ✓ |  |  |  |  | ✓ |
| `resequenceMilestone` | POST | `/v1/workspaces/{workspace_id}/milestones/{milestone_id}/sequence` | `resequence_milestone` | ✓ | ✓ |  |  |  |  | ✓ |
| `listSequenceChanges` | GET | `/v1/workspaces/{workspace_id}/sequence-changes` | `list_sequence_changes` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `getSequenceChange` | GET | `/v1/workspaces/{workspace_id}/sequence-changes/{sequence_change_id}` | `get_sequence_change` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `listDecisions` | GET | `/v1/workspaces/{workspace_id}/decisions` | `list_decisions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createDecision` | POST | `/v1/workspaces/{workspace_id}/decisions` | `create_decision` | ✓ | ✓ |  | ✓ |  |  |  |
| `getDecision` | GET | `/v1/workspaces/{workspace_id}/decisions/{decision_id}` | `get_decision` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `answerDecision` | POST | `/v1/workspaces/{workspace_id}/decisions/{decision_id}/answer` |  | ✓ | ✓ |  |  |  |  |  |
| `applyDecisionDefault` | POST | `/v1/workspaces/{workspace_id}/decisions/{decision_id}/apply-default` | `apply_decision_default` |  |  |  | ✓ |  |  |  |
| `listChains` | GET | `/v1/workspaces/{workspace_id}/chains` | `list_chains` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `getChain` | GET | `/v1/workspaces/{workspace_id}/chains/{chain_id}` | `get_chain` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `advanceChain` | POST | `/v1/workspaces/{workspace_id}/chains/{chain_id}/advance` | `advance_chain` |  |  |  | ✓ |  |  |  |
| `requeueChain` | POST | `/v1/workspaces/{workspace_id}/chains/{chain_id}/requeue` |  | ✓ | ✓ |  |  |  |  |  |
| `cancelChain` | POST | `/v1/workspaces/{workspace_id}/chains/{chain_id}/cancel` |  | ✓ | ✓ |  |  |  |  |  |
| `listStageRuns` | GET | `/v1/workspaces/{workspace_id}/stage-runs` | `list_stage_runs` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createStageRun` | POST | `/v1/workspaces/{workspace_id}/stage-runs` | `create_stage_run` |  |  |  | ✓ |  |  |  |
| `getStageRun` | GET | `/v1/workspaces/{workspace_id}/stage-runs/{stage_run_id}` | `get_stage_run` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `getStageRunContextPacket` | GET | `/v1/workspaces/{workspace_id}/stage-runs/{stage_run_id}/context-packet` | `claim_context_packet` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |
| `submitStageRunResult` | POST | `/v1/workspaces/{workspace_id}/stage-runs/{stage_run_id}/result` | `submit_stage_result` |  |  |  |  | ✓ |  |  |
| `listEscalations` | GET | `/v1/workspaces/{workspace_id}/escalations` | `list_escalations` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createEscalation` | POST | `/v1/workspaces/{workspace_id}/escalations` | `create_escalation` |  |  |  | ✓ |  |  |  |
| `getEscalation` | GET | `/v1/workspaces/{workspace_id}/escalations/{escalation_id}` | `get_escalation` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `recordEscalationRepairAttempt` | POST | `/v1/workspaces/{workspace_id}/escalations/{escalation_id}/repair-attempts` | `record_escalation_repair_attempt` |  |  |  | ✓ |  |  |  |
| `resolveEscalation` | POST | `/v1/workspaces/{workspace_id}/escalations/{escalation_id}/resolve` | `resolve_escalation` | ✓ | ✓ |  | ✓ |  |  |  |
| `listExecutionBindings` | GET | `/v1/workspaces/{workspace_id}/execution-bindings` | `list_execution_bindings` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createExecutionBinding` | POST | `/v1/workspaces/{workspace_id}/execution-bindings` | `create_execution_binding` |  |  |  | ✓ |  |  |  |
| `getExecutionBinding` | GET | `/v1/workspaces/{workspace_id}/execution-bindings/{execution_binding_id}` | `get_execution_binding` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listGroomingPasses` | GET | `/v1/workspaces/{workspace_id}/grooming-passes` | `list_grooming_passes` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createGroomingPass` | POST | `/v1/workspaces/{workspace_id}/grooming-passes` | `create_grooming_pass` | ✓ | ✓ |  | ✓ |  |  |  |
| `getGroomingPass` | GET | `/v1/workspaces/{workspace_id}/grooming-passes/{grooming_pass_id}` | `get_grooming_pass` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `submitGroomingPassResult` | POST | `/v1/workspaces/{workspace_id}/grooming-passes/{grooming_pass_id}/result` | `submit_grooming_pass_result` |  |  |  |  |  |  | ✓ |
| `listSelfHeals` | GET | `/v1/workspaces/{workspace_id}/self-heals` | `list_self_heals` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createSelfHeal` | POST | `/v1/workspaces/{workspace_id}/self-heals` | `create_self_heal` |  |  |  | ✓ |  |  |  |
| `getSelfHeal` | GET | `/v1/workspaces/{workspace_id}/self-heals/{self_heal_id}` | `get_self_heal` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `updateSelfHeal` | PATCH | `/v1/workspaces/{workspace_id}/self-heals/{self_heal_id}` |  | ✓ | ✓ |  |  |  |  |  |
| `listAlerts` | GET | `/v1/workspaces/{workspace_id}/alerts` | `list_alerts` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createAlert` | POST | `/v1/workspaces/{workspace_id}/alerts` | `file_finding` |  |  |  | ✓ |  | ✓ |  |
| `getAlert` | GET | `/v1/workspaces/{workspace_id}/alerts/{alert_id}` | `get_alert` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `updateAlert` | PATCH | `/v1/workspaces/{workspace_id}/alerts/{alert_id}` | `update_alert` | ✓ | ✓ |  |  |  |  | ✓ |
| `acknowledgeAlert` | POST | `/v1/workspaces/{workspace_id}/alerts/{alert_id}/acknowledge` |  | ✓ | ✓ |  |  |  |  |  |
| `resolveAlert` | POST | `/v1/workspaces/{workspace_id}/alerts/{alert_id}/resolve` |  | ✓ | ✓ |  |  |  |  |  |
| `listEvalRuns` | GET | `/v1/workspaces/{workspace_id}/eval-runs` | `list_eval_runs` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `getEvalRun` | GET | `/v1/workspaces/{workspace_id}/eval-runs/{eval_run_id}` | `get_eval_run` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createEvalRun` | POST | `/v1/workspaces/{workspace_id}/evals/{eval_id}/runs` | `run_eval` | ✓ | ✓ |  | ✓ |  |  |  |
| `listThroughputWindows` | GET | `/v1/workspaces/{workspace_id}/throughput-windows` | `list_throughput_windows` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `getThroughputWindow` | GET | `/v1/workspaces/{workspace_id}/throughput-windows/{throughput_window_id}` | `get_throughput_window` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listEvents` | GET | `/v1/workspaces/{workspace_id}/events` | `list_events` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `streamEvents` | GET | `/v1/workspaces/{workspace_id}/events/stream` | `stream_events` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `getEvent` | GET | `/v1/workspaces/{workspace_id}/events/{seq}` | `get_event` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listDecisionLog` | GET | `/v1/workspaces/{workspace_id}/decision-log` | `read_decision_log` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `getDecisionLogEntry` | GET | `/v1/workspaces/{workspace_id}/decision-log/{decision_log_id}` | `get_decision_log_entry` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `getPickupPreview` | GET | `/v1/workspaces/{workspace_id}/pickup-preview` | `get_pickup_preview` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `listAuditLog` | GET | `/v1/workspaces/{workspace_id}/audit-log` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `getAuditLogEntry` | GET | `/v1/workspaces/{workspace_id}/audit-log/{audit_log_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `listMirrors` | GET | `/v1/workspaces/{workspace_id}/mirrors` | `list_mirrors` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `getMirror` | GET | `/v1/workspaces/{workspace_id}/mirrors/{mirror_id}` | `get_mirror` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `refreshMirror` | POST | `/v1/workspaces/{workspace_id}/mirrors/{mirror_id}/refresh` | `refresh_mirror` | ✓ | ✓ |  | ✓ |  |  |  |
| `listArchetypes` | GET | `/v1/workspaces/{workspace_id}/archetypes` | `list_archetypes` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createArchetype` | POST | `/v1/workspaces/{workspace_id}/archetypes` |  | ✓ | ✓ |  |  |  |  |  |
| `getArchetype` | GET | `/v1/workspaces/{workspace_id}/archetypes/{archetype_id}` | `get_archetype` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listArchetypeVersions` | GET | `/v1/workspaces/{workspace_id}/archetypes/{archetype_id}/versions` | `list_archetype_versions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `proposeArchetypeVersion` | POST | `/v1/workspaces/{workspace_id}/archetypes/{archetype_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getArchetypeVersion` | GET | `/v1/workspaces/{workspace_id}/archetypes/{archetype_id}/versions/{version}` | `get_archetype_version` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listWorkflows` | GET | `/v1/workspaces/{workspace_id}/workflows` | `list_workflows` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createWorkflow` | POST | `/v1/workspaces/{workspace_id}/workflows` |  | ✓ | ✓ |  |  |  |  |  |
| `getWorkflow` | GET | `/v1/workspaces/{workspace_id}/workflows/{workflow_id}` | `get_workflow` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `listWorkflowVersions` | GET | `/v1/workspaces/{workspace_id}/workflows/{workflow_id}/versions` | `list_workflow_versions` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `proposeWorkflowVersion` | POST | `/v1/workspaces/{workspace_id}/workflows/{workflow_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getWorkflowVersion` | GET | `/v1/workspaces/{workspace_id}/workflows/{workflow_id}/versions/{version}` | `get_workflow_version` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `listRoles` | GET | `/v1/workspaces/{workspace_id}/roles` | `list_roles` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createRole` | POST | `/v1/workspaces/{workspace_id}/roles` |  | ✓ | ✓ |  |  |  |  |  |
| `getRole` | GET | `/v1/workspaces/{workspace_id}/roles/{role_id}` | `get_role` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listRoleVersions` | GET | `/v1/workspaces/{workspace_id}/roles/{role_id}/versions` | `list_role_versions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `proposeRoleVersion` | POST | `/v1/workspaces/{workspace_id}/roles/{role_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getRoleVersion` | GET | `/v1/workspaces/{workspace_id}/roles/{role_id}/versions/{version}` | `get_role_version` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listPolicies` | GET | `/v1/workspaces/{workspace_id}/policies` | `list_policies` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createPolicy` | POST | `/v1/workspaces/{workspace_id}/policies` |  | ✓ | ✓ |  |  |  |  |  |
| `getPolicy` | GET | `/v1/workspaces/{workspace_id}/policies/{policy_id}` | `get_policy` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listPolicyVersions` | GET | `/v1/workspaces/{workspace_id}/policies/{policy_id}/versions` | `list_policy_versions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `proposePolicyVersion` | POST | `/v1/workspaces/{workspace_id}/policies/{policy_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getPolicyVersion` | GET | `/v1/workspaces/{workspace_id}/policies/{policy_id}/versions/{version}` | `get_policy_version` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `simulatePolicy` | POST | `/v1/workspaces/{workspace_id}/policies/{policy_id}/simulate` |  | ✓ | ✓ |  |  |  |  |  |
| `listPrioritizationPolicies` | GET | `/v1/workspaces/{workspace_id}/prioritization-policies` | `list_prioritization_policies` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createPrioritizationPolicy` | POST | `/v1/workspaces/{workspace_id}/prioritization-policies` |  | ✓ | ✓ |  |  |  |  |  |
| `getPrioritizationPolicy` | GET | `/v1/workspaces/{workspace_id}/prioritization-policies/{prioritization_policy_id}` | `get_prioritization_policy` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `listPrioritizationPolicyVersions` | GET | `/v1/workspaces/{workspace_id}/prioritization-policies/{prioritization_policy_id}/versions` | `list_prioritization_policy_versions` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `proposePrioritizationPolicyVersion` | POST | `/v1/workspaces/{workspace_id}/prioritization-policies/{prioritization_policy_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getPrioritizationPolicyVersion` | GET | `/v1/workspaces/{workspace_id}/prioritization-policies/{prioritization_policy_id}/versions/{version}` | `get_prioritization_policy_version` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `listSequencingPolicies` | GET | `/v1/workspaces/{workspace_id}/sequencing-policies` | `list_sequencing_policies` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `createSequencingPolicy` | POST | `/v1/workspaces/{workspace_id}/sequencing-policies` |  | ✓ | ✓ |  |  |  |  |  |
| `getSequencingPolicy` | GET | `/v1/workspaces/{workspace_id}/sequencing-policies/{sequencing_policy_id}` | `get_sequencing_policy` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `listSequencingPolicyVersions` | GET | `/v1/workspaces/{workspace_id}/sequencing-policies/{sequencing_policy_id}/versions` | `list_sequencing_policy_versions` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `proposeSequencingPolicyVersion` | POST | `/v1/workspaces/{workspace_id}/sequencing-policies/{sequencing_policy_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getSequencingPolicyVersion` | GET | `/v1/workspaces/{workspace_id}/sequencing-policies/{sequencing_policy_id}/versions/{version}` | `get_sequencing_policy_version` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |
| `listContextRecipes` | GET | `/v1/workspaces/{workspace_id}/context-recipes` | `list_context_recipes` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createContextRecipe` | POST | `/v1/workspaces/{workspace_id}/context-recipes` |  | ✓ | ✓ |  |  |  |  |  |
| `getContextRecipe` | GET | `/v1/workspaces/{workspace_id}/context-recipes/{context_recipe_id}` | `get_context_recipe` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listContextRecipeVersions` | GET | `/v1/workspaces/{workspace_id}/context-recipes/{context_recipe_id}/versions` | `list_context_recipe_versions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `proposeContextRecipeVersion` | POST | `/v1/workspaces/{workspace_id}/context-recipes/{context_recipe_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getContextRecipeVersion` | GET | `/v1/workspaces/{workspace_id}/context-recipes/{context_recipe_id}/versions/{version}` | `get_context_recipe_version` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `previewContextRecipe` | GET | `/v1/workspaces/{workspace_id}/context-recipes/{context_recipe_id}/preview` | `preview_context_recipe` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listAgents` | GET | `/v1/workspaces/{workspace_id}/agents` | `list_agents` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createAgent` | POST | `/v1/workspaces/{workspace_id}/agents` |  | ✓ | ✓ |  |  |  |  |  |
| `getAgent` | GET | `/v1/workspaces/{workspace_id}/agents/{agent_id}` | `get_agent` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listAgentVersions` | GET | `/v1/workspaces/{workspace_id}/agents/{agent_id}/versions` | `list_agent_versions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `proposeAgentVersion` | POST | `/v1/workspaces/{workspace_id}/agents/{agent_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getAgentVersion` | GET | `/v1/workspaces/{workspace_id}/agents/{agent_id}/versions/{version}` | `get_agent_version` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listExtensions` | GET | `/v1/workspaces/{workspace_id}/extensions` | `list_extensions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createExtension` | POST | `/v1/workspaces/{workspace_id}/extensions` |  | ✓ | ✓ |  |  |  |  |  |
| `getExtension` | GET | `/v1/workspaces/{workspace_id}/extensions/{extension_id}` | `get_extension` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listExtensionVersions` | GET | `/v1/workspaces/{workspace_id}/extensions/{extension_id}/versions` | `list_extension_versions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `proposeExtensionVersion` | POST | `/v1/workspaces/{workspace_id}/extensions/{extension_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getExtensionVersion` | GET | `/v1/workspaces/{workspace_id}/extensions/{extension_id}/versions/{version}` | `get_extension_version` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `enableExtension` | POST | `/v1/workspaces/{workspace_id}/extensions/{extension_id}/enable` |  | ✓ | ✓ |  |  |  |  |  |
| `disableExtension` | POST | `/v1/workspaces/{workspace_id}/extensions/{extension_id}/disable` |  | ✓ | ✓ |  |  |  |  |  |
| `listEvals` | GET | `/v1/workspaces/{workspace_id}/evals` | `list_evals` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createEval` | POST | `/v1/workspaces/{workspace_id}/evals` |  | ✓ | ✓ |  |  |  |  |  |
| `getEval` | GET | `/v1/workspaces/{workspace_id}/evals/{eval_id}` | `get_eval` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listEvalVersions` | GET | `/v1/workspaces/{workspace_id}/evals/{eval_id}/versions` | `list_eval_versions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `proposeEvalVersion` | POST | `/v1/workspaces/{workspace_id}/evals/{eval_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getEvalVersion` | GET | `/v1/workspaces/{workspace_id}/evals/{eval_id}/versions/{version}` | `get_eval_version` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listScorecardBatteries` | GET | `/v1/workspaces/{workspace_id}/scorecard-batteries` | `list_scorecard_batteries` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createScorecardBattery` | POST | `/v1/workspaces/{workspace_id}/scorecard-batteries` |  | ✓ | ✓ |  |  |  |  |  |
| `getScorecardBattery` | GET | `/v1/workspaces/{workspace_id}/scorecard-batteries/{scorecard_battery_id}` | `get_scorecard_battery` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listScorecardBatteryVersions` | GET | `/v1/workspaces/{workspace_id}/scorecard-batteries/{scorecard_battery_id}/versions` | `list_scorecard_battery_versions` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `proposeScorecardBatteryVersion` | POST | `/v1/workspaces/{workspace_id}/scorecard-batteries/{scorecard_battery_id}/versions` |  | ✓ | ✓ |  |  |  |  |  |
| `getScorecardBatteryVersion` | GET | `/v1/workspaces/{workspace_id}/scorecard-batteries/{scorecard_battery_id}/versions/{version}` | `get_scorecard_battery_version` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `listLanes` | GET | `/v1/workspaces/{workspace_id}/lanes` | `list_lanes` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createLane` | POST | `/v1/workspaces/{workspace_id}/lanes` |  | ✓ | ✓ |  |  |  |  |  |
| `getLane` | GET | `/v1/workspaces/{workspace_id}/lanes/{lane_id}` | `get_lane` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `updateLane` | PATCH | `/v1/workspaces/{workspace_id}/lanes/{lane_id}` |  | ✓ | ✓ |  |  |  |  |  |
| `deleteLane` | DELETE | `/v1/workspaces/{workspace_id}/lanes/{lane_id}` |  | ✓ | ✓ |  |  |  |  |  |
| `getConductorConfig` | GET | `/v1/workspaces/{workspace_id}/conductor-config` | `get_conductor_config` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `updateConductorConfig` | PATCH | `/v1/workspaces/{workspace_id}/conductor-config` |  | ✓ | ✓ |  |  |  |  |  |
| `listCredentialCustodies` | GET | `/v1/workspaces/{workspace_id}/credential-custodies` | `list_credential_custodies` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createCredentialCustody` | POST | `/v1/workspaces/{workspace_id}/credential-custodies` |  | ✓ |  |  |  |  |  |  |
| `getCredentialCustody` | GET | `/v1/workspaces/{workspace_id}/credential-custodies/{credential_custody_id}` | `get_credential_custody` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `updateCredentialCustody` | PATCH | `/v1/workspaces/{workspace_id}/credential-custodies/{credential_custody_id}` |  | ✓ |  |  |  |  |  |  |
| `deleteCredentialCustody` | DELETE | `/v1/workspaces/{workspace_id}/credential-custodies/{credential_custody_id}` |  | ✓ |  |  |  |  |  |  |
| `listIntegrators` | GET | `/v1/workspaces/{workspace_id}/integrators` | `list_integrators` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createIntegrator` | POST | `/v1/workspaces/{workspace_id}/integrators` |  | ✓ |  |  |  |  |  |  |
| `getIntegrator` | GET | `/v1/workspaces/{workspace_id}/integrators/{integrator_id}` | `get_integrator` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `updateIntegrator` | PATCH | `/v1/workspaces/{workspace_id}/integrators/{integrator_id}` |  | ✓ |  |  |  |  |  |  |
| `instructIntegrator` | POST | `/v1/workspaces/{workspace_id}/integrators/{integrator_id}/landings` | `instruct_integrator` |  |  |  | ✓ |  |  |  |
| `listSecrets` | GET | `/v1/workspaces/{workspace_id}/secrets` | `list_secrets` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `createSecret` | POST | `/v1/workspaces/{workspace_id}/secrets` |  | ✓ |  |  |  |  |  |  |
| `getSecret` | GET | `/v1/workspaces/{workspace_id}/secrets/{secret_id}` | `get_secret` | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `updateSecret` | PATCH | `/v1/workspaces/{workspace_id}/secrets/{secret_id}` |  | ✓ |  |  |  |  |  |  |
| `deleteSecret` | DELETE | `/v1/workspaces/{workspace_id}/secrets/{secret_id}` |  | ✓ |  |  |  |  |  |  |
| `listOperators` | GET | `/v1/workspaces/{workspace_id}/operators` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `createOperator` | POST | `/v1/workspaces/{workspace_id}/operators` |  | ✓ |  |  |  |  |  |  |
| `getOperator` | GET | `/v1/workspaces/{workspace_id}/operators/{operator_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `updateOperator` | PATCH | `/v1/workspaces/{workspace_id}/operators/{operator_id}` |  | ✓ |  |  |  |  |  |  |
| `listRoleBindings` | GET | `/v1/workspaces/{workspace_id}/role-bindings` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `createRoleBinding` | POST | `/v1/workspaces/{workspace_id}/role-bindings` |  | ✓ |  |  |  |  |  |  |
| `getRoleBinding` | GET | `/v1/workspaces/{workspace_id}/role-bindings/{role_binding_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |
| `updateRoleBinding` | PATCH | `/v1/workspaces/{workspace_id}/role-bindings/{role_binding_id}` |  | ✓ |  |  |  |  |  |  |
| `deleteRoleBinding` | DELETE | `/v1/workspaces/{workspace_id}/role-bindings/{role_binding_id}` |  | ✓ |  |  |  |  |  |  |
| `issueServiceAccountToken` | POST | `/v1/workspaces/{workspace_id}/role-bindings/{role_binding_id}/tokens` |  | ✓ |  |  |  |  |  |  |
