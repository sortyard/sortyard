# 16 — Legacy parity matrix

Every behaviour of the system being replaced that this specification found, with what happens
to it. Read it in the other direction from the capability files: start from something the estate
does today and find where it went.

Dispositions:

- **KEEP** — preserved; the requirement states the same behaviour.
- **FIX** — the intent is preserved and a recorded defect is closed; behaviour changes on purpose.
- **PACK** — preserved as an optional policy pack or integration, off by default.
- **DROP** — not carried, with the reason.
- **OUT** — outside the product; the estate keeps doing it another way.

Each row has a stable id. REC-025 requires a passing scenario before MS5 exits for every KEEP
and FIX row whose requirements are MUST and due by then; the remaining rows gain theirs with
their requirement. MIG-010 requires this table to be re-checked against the legacy system —
which changes weekly — before each cutover, with every KEEP and FIX row the project relies on
covered or waived by the owner.

Sources: see [17-evidence.md](17-evidence.md) for the abbreviations and revisions. This table
was built from the driver log, the conductor README, the process references and a partial read
of the code. It is a seed, not a census: `AGENTS.md`, the templates and `mh.py` after line 5052
were sampled, not read in full.

## Filing, readiness, release

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-001 | A task is a board item with a spec block; the board's own fields win | TR "The task item" | FIX | TRK-002 |
| LP-002 | Kinds: feature, fix, deployment, decision, parent | TR "Kinds" | KEEP | TRK-003 |
| LP-003 | File many tasks from YAML or markdown; dependencies first; ids on the board skipped | TR; CR "Plane tasks" | KEEP | TRK-012, API-015 |
| LP-004 | Ready rules 1–6 | TR "Ready rules" | KEEP | RDY-001 |
| LP-005 | Sizing checks as warnings | TR "One PR's worth" | KEEP | RDY-002 |
| LP-006 | Release once; removing the label sticks | TP §2 | KEEP | RDY-003 |
| LP-007 | Release only with blockers Done, parent not in Backlog, repo matching | TP §2 | KEEP | RDY-004 |
| LP-008 | A failed board read releases and closes nothing that sync | TP §2 | FIX | SCH-015, RDY-004 |
| LP-009 | A parent closes when its children are Done; nested parents close | DRV §3; release note 2026-11-01 | KEEP | TRK-005 |
| LP-010 | Decision default applies at its date; only an explicit value is an answer | CR "Plane tasks" | KEEP | RDY-015, TRK-011 |
| LP-011 | Premise-class decisions never take a default; they escalate once | CR "Plane tasks" | KEEP | RDY-015 |
| LP-012 | Needs routed to devops, owner or agent | K3D "Discharging needs" | KEEP | RDY-007 |
| LP-013 | `outcome_met` closes a deployment whose needs delivered its outcome | K3D; HARNESS-272 | KEEP | RDY-008 |
| LP-014 | Preflight checks 1–9; unverifiable holds like a failure | CR "Preflight"; TR | KEEP | RDY-005, RDY-006 |
| LP-015 | Filing verdicts; 30-minute sweep; one `FILING-INVISIBLE` item | CR "Filing visibility"; TP §9 | KEEP | TRK-013, REC-023 |
| LP-016 | Directly filed items bypass the ready rules | TR (HARNESS-504) | FIX | RDY-010 |
| LP-017 | Retroactive queue audit | CR "Retroactive audit" | KEEP | RDY-011 |
| LP-018 | Intended-use, reference-clone and access-citation rules | CR "Plane tasks" | PACK | RDY-009 |
| LP-019 | Production flips held until estate preconditions are discharged | CR `cutover_readiness`; drive note 173 | PACK | RDY-014, SCH-017 |
| LP-020 | One invalid project entry no longer stops every board | CR "Product configuration failsafe" | KEEP | RDY-013 |
| LP-021 | `build`, `tasks`, `lanes` switches per project; `lanes: 0` pauses | DRV §1 | KEEP | RDY-004, SCH-004, SCH-012 |
| LP-022 | A hand-back owes a new preflight check or a gap filing | TR "De-risking" | KEEP | RDY-012 |

## Scheduling and admission

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-030 | Eligible = labelled, Todo, driven project, no live record | TP §4 | FIX | SCH-001, TRK-004 |
| LP-031 | Order: urgent, milestone rank, priority, sequence | TP §4 | KEEP | SCH-002 |
| LP-032 | Milestone rank also matches by id prefix | TP §4 | FIX | SCH-003 |
| LP-033 | Lanes per project; a slot is held until done or blocked; urgent holds none | TP §4–§5 | KEEP | SCH-004, SCH-005 |
| LP-034 | A freed slot is reused at the next three-minute pass | TP §3 | FIX | SCH-006 |
| LP-035 | An exception in one claim aborts the pass | TP conformance row 2 | FIX | SCH-014 |
| LP-036 | A failed clone makes the pass order by priority alone | TP conformance row 3 | FIX | SCH-015 |
| LP-037 | A Todo item with a stale live record is skipped for ever | TP conformance row 4 | FIX | SCH-016, TRK-004 |
| LP-038 | Heavy caps: cluster, train, per project; one slot kept for rush | MH `caps_allow`; DRV §5 | KEEP | SCH-007 |
| LP-039 | Rush first, then creation order | MH `_drive_order`; TP §6 | KEEP | SCH-007, SCH-018 |
| LP-040 | `--dry-run` for drive and sync | DRV §4 "Tools" | KEEP | SCH-013, CLI-004 |
| LP-041 | Phase and slot use visible only in `state.json` | TP conformance row 7 | FIX | SCH-008, REC-011 |
| LP-042 | Caps hardcoded in three files; a release needed to change one | DRV §1; HARNESS-246 | FIX | SCH-011, DEF-005 |
| LP-043 | A stale release must not pass cutover gating | drive note 890 | KEEP | SCH-017 |
| LP-044 | Ship items run after planned work; capped per product | CR `unlanded_builds` | KEEP | SCH-019 |

## Execution

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-050 | One Job per stage, no Kubernetes retries, deadline, TTL | MH Job render | KEEP | EXE-002 |
| LP-051 | Stage resources and deadlines; 3-hour builds | MH; DRV §4 | KEEP | EXE-003 |
| LP-052 | Fresh clone and run directory per stage | MH WORKER_TEMPLATE | KEEP | EXE-004 |
| LP-053 | Workers never push; optional read-only token with a leak scan | DRV §5; MH | KEEP | EXE-005 |
| LP-054 | Result document; `execution_ok` versus `pass`; checks run by the wrapper | MH result builder | KEEP | EXE-006, EXE-007 |
| LP-055 | Mirror freshness recorded; base ensured and seeded before dispatch | CR `seed_mirror`, `ensure_base` | KEEP | EXE-008 |
| LP-056 | Mirrors and run output on one shared volume | MH volumes | FIX | EXE-009 |
| LP-057 | Only the new commits are fetched; commit trailers | drive notes 373–375; MH | KEEP | EXE-010 |
| LP-058 | External inputs vendored only when marked; unverifiable is never dispatched | CR `vendor_inputs` | KEEP | EXE-011 |
| LP-059 | File attachments by repo, commit and path | MH attachments | KEEP | EXE-011 |
| LP-060 | Harnesses: claude, codex, none | MH `validate_request` | KEEP | EXE-012 |
| LP-061 | Routing by stage; fallback chain stamped in facts | CR "Harness routing" | KEEP | EXE-013 |
| LP-062 | CLI soak window of six hours | DRV "Worker CLIs" | KEEP | EXE-014 |
| LP-063 | Packet templates; 200,000-character cap | drive.py packets; MH | KEEP | EXE-015 |
| LP-064 | Privileged container sidecar for build, verify and proof | MH dind | FIX | EXE-016 (opt-in) |
| LP-065 | Proof receipts bound to base and candidate | MH proof | KEEP | EXE-017 |
| LP-066 | Per-project proof provisioning (browsers, a systemd executor image) | MH proof worker | DROP | A worker-image concern, not core (EXT-002) |
| LP-067 | Usage recorded per stage | MH ledger row | KEEP | EXE-018 |
| LP-068 | Trajectory capture with `missing`/`error` states | MH `mh_trajectories` | KEEP | EXE-019 |
| LP-069 | Interrupted tasks recovered after a restart | MH `recover_interrupted` | KEEP | EXE-021 |
| LP-070 | Only queued tasks can be cancelled | DRV §5 | FIX | EXE-022 |
| LP-071 | Run-directory retention, faster under disk pressure | DRV §5 | KEEP | REC-022 |
| LP-072 | The control plane is not protected from worker load | DESIGN §3.7b | FIX | EXE-020 |

## Credentials

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-080 | Pool selection, cooling, three limit requeues | MH pool | KEEP | CRD-003 |
| LP-081 | Auth quarantine and probes tied to credential generation | MH pool probes | KEEP | CRD-004 |
| LP-082 | Sign-in flows for pool accounts | DRV §5; HC J4 | KEEP | CRD-005, UI-012 |
| LP-083 | Credential sync never overwrites a newer copy; one keeper refreshes Codex | DRV §5 | KEEP | CRD-006 |
| LP-084 | Workers use subscription credentials only (API keys unset) | MH WORKER_TEMPLATE | FIX | CRD-002 |
| LP-085 | The owner's personal token in a cluster Secret | DRV §4 | FIX | CRD-007 |
| LP-086 | Account priority as data; task-level `Select:` override | CR "Harness routing" | KEEP | CRD-009 |
| LP-087 | Quota readings and `QUOTA` items | MECH | KEEP | CRD-008 |

## Delivery flow

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-100 | Item phases; one step per pass; observed facts only | TP §2a | KEEP | FLW-002, FLW-004 |
| LP-101 | Ad-hoc jobs: one stage, report posted once | DRV §4 | KEEP | FLW-003 |
| LP-102 | Review verdict protocol, blocking classes, follow-ups, post-merge lines | drive.py `REVIEW_PACKET`; CR "Drive loop" | KEEP | FLW-005, DLV-004 |
| LP-103 | Review scope rules | DRV §4; CR | KEEP | FLW-006 |
| LP-104 | Test-determinism review | TRV | KEEP | FLW-007 |
| LP-105 | Design review of UI changes | DRVW | KEEP | FLW-008 |
| LP-106 | Auto-merge armed only with every verdict on the exact head | TRV; drive note 933 | KEEP | FLW-009 |
| LP-107 | Fix rounds while the failure changes; backstop 10 | DRV §4 | KEEP | FLW-010 |
| LP-108 | Conflict rounds counted apart (5); markers never pushed | DRV §4 | KEEP | FLW-011 |
| LP-109 | Review tripwire at five | CR "Review tripwire" | KEEP | FLW-012 |
| LP-110 | A parked item resumes on its open PR | CR `resume_parked` | KEEP | FLW-013 |
| LP-111 | Outside PRs get one review per head | release note 2026-11-03 | KEEP | FLW-014 |
| LP-112 | Landing sweep | DRV §4 | KEEP | FLW-015 |
| LP-113 | Stranded builds: ship retry or cancel | CR `unlanded_builds` | KEEP | FLW-016 |
| LP-114 | Follow-ups land in Backlog at low priority | DRV §4 | KEEP | TRK-018 |
| LP-115 | Design chains with dual review and self-repair of the dispatcher | MH chains | DROP | Not on the conductor path; self-modifying control plane (FLW-017) |
| LP-116 | Scorecard battery | MH `_chain_battery_score` | DROP | Experiment instrument (MIG-013) |
| LP-117 | A rejected verify records a blocked follow-up request that is never dispatched | DRV §4 "Harness" | DROP | An artefact of two schedulers |

## Landing

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-120 | Branch per item; PR body is the item's text with a link note | DRV §4; CR `pr_body` | KEEP | MRG-002, TRK-017 |
| LP-121 | A pushed head resumes at PR creation | DRV "Recovery" | KEEP | MRG-002, REC-012 |
| LP-122 | Auto-merge on the matched head; never a direct merge | DRV §4 "Hard rules" | KEEP | MRG-003 |
| LP-123 | Admin merge past a quarantined job, once per head | JQ | PACK | MRG-004 (off by default; OD-9) |
| LP-124 | Behind or conflicting: merge main in; review before re-arming | DRV §4; drive notes 196–197 | KEEP | MRG-005 |
| LP-125 | Only required checks drive rounds; policy never guessed; missing check after 30 min | CR `ci_round`, `missing_checks` | KEEP | MRG-006 |
| LP-126 | Auto-merge for the earlier head is dropped before a fix head | DRV §4 | KEEP | MRG-007 |
| LP-127 | Merged and closed observed; a landed squash is proved by tree | TP §5; drive note 122 | KEEP | MRG-008 |
| LP-128 | A stalled merge is re-triggered once, then parked | TP §5; HARNESS-242 | KEEP | MRG-009 |
| LP-129 | A merged PR's own runs are cancelled | release note 2026-11-04 | KEEP | MRG-010 |
| LP-130 | The shipping fence: receipt for the pair, approval of the head, tree identity | DESIGN §3.7a | KEEP | MRG-011 |
| LP-131 | Internal pushes bypass repository hooks | DRV "Recovery" | KEEP | MRG-012 |
| LP-132 | Branch names are shell-quoted | drive note 376 | KEEP | MRG-013 |

## CI and main-branch health

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-140 | Red main, red scheduled runs and `workflow_run` deploys sensed; hand runs count | DRV §3; HARNESS-241 | KEEP | CIH-001 |
| LP-141 | One item per incident; three triage attempts; re-run attempts told apart | CR `queue_triage` | KEEP | CIH-002 |
| LP-142 | Infrastructure, estate-access, zero-job and unrunnable failures are not sent to a build | CR `infra_cause`, `estate_access`, `zero_jobs`, `queue_unrunnable` | KEEP | CIH-003 |
| LP-143 | Only live workflows and runs after onboarding | CR `live_workflows`, `first_sync` | KEEP | CIH-001 |
| LP-144 | Red-main items close when main goes green | CR `close_green` | KEEP | CIH-004 |
| LP-145 | Causal proof; confirming on main; verdict events; no-verdict runs; 24-hour limit | DRV §4 "Red main"; CR incident notes | KEEP | CIH-005 |
| LP-146 | Lock-in regression item | DRV §4 | KEEP | CIH-006 |
| LP-147 | Inherited main red is held, not fixed | CR `inherited` | KEEP | CIH-007 |
| LP-148 | CI log excerpts in the packet; "could not read the log" refused once | CR `ci_round` | KEEP | CIH-008, REC-007 |
| LP-149 | A runner- or estate-stopped job is re-run once, then goes to self-heal | CR `ci_round` | KEEP | CIH-009 |
| LP-150 | Flaky-job quarantine; per-test flake ledger | JQ; CI-FLAKES | KEEP | CIH-010 |
| LP-151 | Flake re-run when failing tests are outside the change | CR `flake_rerun` | KEEP | CIH-011 |
| LP-152 | Triage may not move jobs to hosted runners or change labels | release note 2026-11-03 | KEEP | CIH-012 |
| LP-153 | Issues and PRs projected onto the board as items | CR "Plane sync" | DROP | A PR is part of its task (TRK-017); outside PRs become review tasks (FLW-014) |
| LP-154 | Health summary and delivery-cost items on the board | CR `cost_item` | FIX | OBS-006, UI-009 |
| LP-155 | Daily reconciliation flags | CR `queue_reconciliation` | FIX | GRM-007 |
| LP-156 | Drift consolidation across plan, board, STATUS.md and registers | CR "Drift consolidation" | DROP | Those copies no longer exist |

## Delivery verification

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-160 | Running-system changes are Done only when deployed and run | K3D "Running-system delivery" | KEEP | DLV-001, DLV-002 |
| LP-161 | Release verification with shield, revert, re-groom and lift | CR "Release verification" | PACK | DLV-003 |
| LP-162 | Post-merge deployment items close when a release carries them out | CR "Self-heal drain" | KEEP | DLV-004 |

## Recovery

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-170 | Infrastructure retries: 3, then 30 minutes × 2; repeated reason shortcut | DRV §4 | KEEP | REC-002 |
| LP-171 | Failed checks are not infrastructure; a build rebuilds at most twice | DRV §4 | KEEP | REC-003 |
| LP-172 | A missing mirror base is deterministic | DRV §4 | KEEP | REC-004 |
| LP-173 | Five consecutive errors park an item; six cluster-API retries | DRV "Recovery" | KEEP | REC-005 |
| LP-174 | API rollouts are waited out; nothing is recorded as failed | CR "API rollouts" | KEEP | REC-016 |
| LP-175 | Version skew skips the pass without writing | CR `api_skew` | KEEP | REC-015 |
| LP-176 | Parking: Backlog, label dropped, comment; requeue resumes | DRV §4 | KEEP | REC-006 |
| LP-177 | No change → self-heal with the worker's account | DRV "Recovery" | KEEP | REC-007 |
| LP-178 | Blocking causes; automatic return | CR "Blocking causes" | KEEP | REC-008 |
| LP-179 | Self-heal outcomes and restrictions | SH | KEEP | REC-009 |
| LP-180 | `SELF-HEAL-STALLED` after 24 hours | CR "Self-heal drain" | KEEP | REC-010 |
| LP-181 | One stall comment at four hours; in-flight items logged each pass | DRV §4 "Visibility" | KEEP | REC-011 |
| LP-182 | Writes recorded once accepted; toggles persisted first | drive notes 242, 416, 422 | KEEP | REC-012 |
| LP-183 | Idempotent submit; a 409 moves to a fresh key | DRV §5, "Recovery" | KEEP | REC-013 |
| LP-184 | Single writer by CronJob `Forbid` and `Recreate` | TP §3; `k8s/deployment.yaml` | FIX | REC-014 |
| LP-185 | Mechanism registry; `SILENT` and `UNREGISTERED` items | MECH | KEEP | REC-017, REC-018 |
| LP-186 | Four sensor states | MECH | KEEP | REC-019 |
| LP-187 | No stop in flight; steering is a prose procedure | DRV §7; in-flight-steering | FIX | REC-020, REC-021 |
| LP-188 | Alarm items updated in place and closed by the system | CR (several) | KEEP | REC-023 |
| LP-189 | The owner is never a step; Slack only for owner-only or factory-down | DRV §6 | KEEP | REC-024, OBS-013 |

## Grooming

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-200 | An exhausted queue triggers grooming of known work | CR (grooming) | KEEP | GRM-001 |
| LP-201 | Frontier model only, except a stamped fallback | CR (grooming) | KEEP | GRM-002 |
| LP-202 | Output validation, in-place repair, no duplicates | CR (grooming) | KEEP | GRM-003 |
| LP-203 | Inputs by hash; packets filled newest-first; deferrals | CR (grooming) | KEEP | GRM-004 |
| LP-204 | `GROOMING-STALLED` | CR (grooming) | KEEP | GRM-005 |
| LP-205 | Shaping: one pass, no reviews | TR | KEEP | GRM-006 |
| LP-206 | Premises reconciled against observed product state | CR (grooming) | PACK | GRM-008 (later) |

## Interfaces and console

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-220 | Operator tools: `add_item`, `requeue`, `pickup_status`, `plane_tasks file`, `queue_audit`, `repos_check` | DRV §4; CR | KEEP | CLI-005 |
| LP-221 | Read-only MCP server with a curated tool set | API.md "MCP server" | KEEP | MCP-002 |
| LP-222 | Operator tokens and logins for mutations; audit rows | DRV §5; HC J5 | KEEP | IAM-004, IAM-011 |
| LP-223 | Identity from a proxy header that in-cluster pods can forge | HC decided D2, D16 | FIX | IAM-002 |
| LP-224 | Console journeys J1–J5 and J8 | HC journeys | KEEP | UI-009 to UI-014, OBS-014 |
| LP-225 | Concierge (J6, J7) | HC journeys | DROP | UI-026 (OD-3) |
| LP-226 | Bundle budget, accessibility, keyboard and viewport tests | console `check_budget.py`, e2e specs | KEEP | UI-018, UI-019, UI-020 |
| LP-227 | Live updates over SSE | HC decided D5 | KEEP | API-008, UI-021 |
| LP-228 | Bounded, redacted read model with `as_of` and coverage | FD | KEEP | API-011, API-012, OBS-003 |
| LP-229 | Needs-attention insights with dismiss and restore | API.md HC-14 | KEEP | OBS-014 |
| LP-230 | Request landing and sentence-to-tasks decomposition | API.md "Write side" | DROP | Intake agents file through the API (TRK-012) |

## Observability

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-240 | Metric definitions with cohorts, clocks and missingness | measurement contract | KEEP | OBS-004 |
| LP-241 | Delivery cost: agent-minutes per merged change | DRV §3 | KEEP | OBS-006 |
| LP-242 | OTLP export through an outbox with counted drops | MH trace outbox | KEEP | OBS-012 |
| LP-243 | Daily pipeline record | JQ "Record" | KEEP | OBS-009 |
| LP-244 | Queue census | DRV §5 | KEEP | OBS-008 |

## Releasing the control plane

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-260 | Pull-based release controller; digest compare-and-swap; no cluster credential in CI | RC | FIX | Guarantees kept by QLT-024 and DEP-020, with signing added at 1.0 (QLT-023); the controller is not carried |
| LP-261 | Releases keep the suspend state | DRV §4 | KEEP | SCH-012 |
| LP-262 | Merged is not released; releases were manual | TP conformance row 8 | FIX | QLT-024; DLV-002 for self-hosting |
| LP-263 | A hand-applied Role blocked every release | release note 2026-11-12 | FIX | DEP-002 |
| LP-264 | A bundle size cap pushed comments out of the code | CR; MECH "Release bundle" | DROP | An artefact of shipping code in a ConfigMap |
| LP-265 | `Recreate` leaves 30–40 seconds with nothing listening | CR "API rollouts" | FIX | DEP-009, DEP-010 |
| LP-266 | The running revision is visible only as a cluster annotation | TP conformance row 7 | FIX | API-014 |

## Around the product

| Id | Legacy behaviour | Source | Disp. | Requirement |
|---|---|---|---|---|
| LP-280 | Estate mechanisms beyond the pipeline are watched (runners, certificates, backups) | `mechanisms.yaml` | OUT | REC-018, MIG-012 |
| LP-281 | An agent writes throughput reports and Slack cards | DRV §6 | FIX | OBS-009, OBS-013 |
| LP-282 | Experiment rig sharing the control plane | DESIGN §0 | OUT | MIG-013 |
| LP-283 | Template workflows, roles, skills, `dispatch`/`validate`/`emit` | meta-harness templates, scripts | DROP | CF-04, CF-05 |
| LP-284 | Task registers and STATUS.md | meta-harness | DROP | Already history since 2026-11-08 |
