# 09 — Observability: ledger, metrics, dashboards, notifications

Area: **OBS**. This absorbs the factory dashboard backend (`factory*.py`, `cp_insights.py`,
`cp_events.py`), the throughput analysis scripts (`~/throughput-investigation/metrics/`), the
delivery-cost item, the daily pipeline record, the OTLP exporter, and the alerting watches.

The estate's measurement contract sets the tone and is kept: a successful request, a merged
change and a green build are different things and are never reported as each other; every number
has a source time and a coverage state; a blind sensor is `unknown`, and gets a repair task, not a
zero (factory-measurement-contract).

---

### OBS-001 — One ordered ledger, written with the state it describes
**MS1** · WP1.1 · MUST · KEEP

Every state change writes one event `{seq, time, actor, object, transition, facts, refs}` in the
same database transaction as the change. Events are append-only and globally ordered by `seq`.
Scheduling decisions and audit entries are event classes in the same order, so one task's
timeline interleaves all three.

- AC1: There is no code path that changes a state table without an event (enforced by routing all writes through domain commands and a test that diffs tables against events after the scenario suite).
- AC2: Appending the same event twice records it once; reusing an id for different content is refused.
- AC3: Update, delete and truncate on ledger tables are refused by the database.

Source: migration `0001` (append-only triggers, `append_event` idempotency); DESIGN §3.8; FACTORY-DASHBOARD-DESIGN ("A durable event ledger is the follow-up for exact historical series").

### OBS-002 — History of any object
**MS1** · WP1.1 · MUST · KEEP

For any object the API returns its events in order, with who, when, before and after.

- AC1: The current state of a task equals the fold of its events (replay test).

Source: `sortyard.object_history(kind, id)`; harness-console J5.

### OBS-003 — Read models are projections and say so
**MS2** · WP2.5 · MUST · KEEP

Aggregates (queue census, throughput windows, dashboards) are computed from the ledger and
state tables, are recomputable at will, store nothing authoritative, and are labelled with
`as_of`. A read model never feeds a scheduling decision.

- AC1: Dropping and rebuilding every read model changes no API result other than `as_of`.
- AC2: A read endpoint causes no write, no Job and no outbound call.

Source: FACTORY-DASHBOARD-DESIGN ("The read model is a projection of source records, never a second authority"; "No request body, database write, Job creation, or trace span is caused by these reads").

### OBS-004 — The metric catalogue
**MS6** · WP6.1 · MUST · KEEP

Sortyard ships one catalogue in which each metric has an id, an exact definition (numerator,
denominator, clock, window, cohort), a unit and its coverage rule. The v1 catalogue:

| Id | Definition |
|---|---|
| `queue.actionable` | Eligible tasks and admissible stages now, by project and state. Age runs from the release or queued transition to first schedule; open waits use `as_of`. |
| `stage.pickup_latency` | For stages first scheduled in the window: `first_scheduled − eligible_since`, where `eligible_since` is the later of the queued transition and the predecessor's pass. Dependency wait is reported separately and is never called a scheduler delay. |
| `stage.execution` | For attempts terminal in the window: scheduled→running, running→collecting, collecting→terminal. Missing endpoints are counted, not dropped. |
| `chain.outcomes` | Chains that reached a terminal outcome in the window, once each, by outcome (done, parked, handed-back, cancelled), with shares. |
| `chain.cycle_time` | For chains done in the window: done − claimed. Open chains are shown by current age, not included in percentiles. |
| `task.lead_time` | For tasks done in the window: done − created; and time in each board state. |
| `merges` | Change requests merged into a default branch in the window, by host merge time, unique by repo and number. |
| `merge.open_to_first_green` / `merge.green_to_merge` / `merge.open_to_merge` | From the change request's history and its required check runs. |
| `review.rounds` | Reviews with a verdict per task; share of tasks at or over the tripwire. |
| `fix.rounds`, `conflict.rounds` | Per task and per window. |
| `lanes.utilisation` | Slot-seconds held ÷ slot-seconds available, by project; same for each heavy cap. |
| `handback.count`, `park.count` | By reason and blocking-cause kind. |
| `cost.agent_minutes_per_merge` | Agent wall time of every finished stage for a project (builds, reviews, fix rounds, triage, failures) ÷ changes merged in its repos, same window. |
| `cost.stages_per_merge`, `cost.tokens_per_merge` | Same cohort; tokens where recorded. |
| `main.health` | Per repo: latest completed required run on the default branch, its conclusion, and the age of the last success. |

- AC1: Each metric has a fixture with a hand-computed expected value.
- AC2: A metric whose source is incomplete returns `null` with a reason (API-012).
- AC3: Percentiles use nearest-rank and state `n`.

Source: factory-measurement-contract "Metric definitions"; `metrics/analyze.py` (merged per day, open→first green, last green→merge, open→merge, review rounds, auto-merge use); conductor README `cost_item`.

### OBS-005 — Throughput windows
**MS6** · WP6.1 · MUST · KEEP

Catalogue metrics are available per hour, day and week, by project, lane and workflow. Windows
describe the past and gate nothing.

- AC1: Window boundaries are half-open and in UTC; a record is counted in exactly one window.

Source: DESIGN §3.8 ThroughputWindow; Joe 2026-11-05 (time survives only as looking back at throughput).

### OBS-006 — Delivery cost
**MS6** · WP6.1 · MUST · KEEP

For each project and window: agent-minutes per merged change and stages per merged change,
computed from recorded stage usage. Stages whose usage is unreadable are named, not guessed.

- AC1: The published number and the list of excluded stages always appear together.

Source: driver §3 "Delivery cost" (k3s-harness #186: "Unreadable requests are named, not guessed").

### OBS-007 — Wait versus work
**MS6** · WP6.1 · MUST · KEEP

For any chain and any window the time is decomposed into: waiting on dependencies, waiting for a
slot, waiting for admission, executing, waiting on CI, waiting on review, waiting on a person.

- AC1: The components sum to the cycle time within one second.
- AC2: Each component maps to reason codes (SCH-009), so the dashboard and the Pickup Preview agree.

Source: factory-measurement-contract ("Stage timing waterfall and wait-vs-execution decomposition"); FACTORY-STAGE-ATTEMPTS-DESIGN.

### OBS-008 — Queue census
**MS3** · WP3.9 · MUST · KEEP

A cheap, bounded endpoint returns current counts: eligible, held by reason, claimed by phase,
stages queued, running and collecting, slots and caps in use. Downstream stages of an open chain
are future work, not queue depth.

- AC1: The census never counts a stage under a terminal chain as runnable.

Source: `GET /api/mh/queue-census`; FACTORY-DASHBOARD-DESIGN (`eligible_queued_stages` rule).

### OBS-009 — Daily record
**MS6** · WP6.1 · SHOULD · KEEP

One generated record per day and project: what merged, what did not and why, what is parked or
handed back, incidents on main, quarantined jobs, cost. Generated from the ledger; nobody writes
it by hand.

- AC1: The record for a past day is reproducible byte for byte.

Source: DESIGN §6 view 13 ("no hand-written status ever again"); JOB-QUARANTINE.md (`ledger/pipeline-daily/YYYY-MM-DD.md`).

### OBS-010 — System metrics endpoint
**MS3** · WP3.9 · MUST · NEW

Each component serves Prometheus metrics: reconcile duration and lag, claim latency, queue
depth, Job counts by phase, API latency and error rate, database pool use, mirror age, ledger
append rate.

- AC1: The metric names and labels are documented and covered by a snapshot test.
- AC2: Scraping needs no credential beyond network reach, or a token when configured.

Source: inference — the legacy system exposes `/api/health` and OTLP only; the standard for Kubernetes installs is a scrape endpoint.

### OBS-011 — Structured logs with correlation ids
**MS1** · WP1.2 · MUST · NEW

Logs are JSON lines with level, component, request id and — where they apply — project, task,
chain, stage and attempt.

- AC1: One `grep` by a correlation id — request or task id in MS1, chain id from MS3 — across component logs yields the whole story.
- AC2: Error output from child processes is captured, not discarded.

Source: 2026-11-12 release stall ("stderr is discarded, so it was reproduced with a server-side dry run").

### OBS-012 — OpenTelemetry export
**MS6** · WP6.3 · SHOULD · KEEP

Optional export of lifecycle spans over OTLP, with W3C trace context carried from task to chain
to stage. Export uses an outbox with a bounded backlog; drops are counted and reported. The
ledger stays the record: telemetry never overwrites state.

- AC1: With the collector down, nothing blocks and the gap is visible in health.

Source: `mh.py` trace outbox (notes: trim pending over 5,000, prune delivered after 7 days); OTLP-TRACE-DESIGN; factory-measurement-contract ("Never overwrite authoritative business state with telemetry").

### OBS-013 — Notifications
**MS5** · WP5.8 · MUST · KEEP

Routing rules send events to channels (webhook, Slack-compatible webhook, email). Shipped
defaults notify a person only for owner-list items (REC-024) and for a factory-down state with
nothing acting on it. Everything else goes to the pipeline: a task, a condition, a queue.
Notifications are de-duplicated per condition and their delivery is logged.

- AC1: A red main with an active triage chain sends no notification.
- AC2: A notification that could not be delivered is itself a condition after its retry budget.

Source: driver §6 ("Findings go to the pipeline, not to the owner … The stall watch stays quiet about a red that has an active conductor item"); DV40-ALERT-READBACK-DESIGN.

### OBS-014 — Attention list
**MS5** · WP5.8 · MUST · KEEP

A computed list of what needs a look now: chains past their phase bound, credentials expiring or
quarantined, red main with nothing acting, silent mechanisms, low quota, open conditions. Each
entry carries its evidence links. An entry can be dismissed with a reason and restored.

- AC1: The list is the same through API, MCP (`get_attention`) and UI.
- AC2: Dismissal is audited and expires when the underlying condition changes.

Source: harness-console J8; API.md "Needs-attention insights (HC-14)"; console calls `/api/insights`, `/dismiss`, `/restore`.

### OBS-015 — No phone-home
**MS1** · WP1.6 · MUST · NEW

Sortyard sends nothing to its authors or any third party. There is no usage telemetry in 1.0;
any later telemetry is opt-in and documented field by field.

- AC1: A network-policy test runs the full scenario suite with egress limited to the configured Git host and model provider.

Source: Plane benchmark (instance telemetry defaults to enabled).

### OBS-016 — Retention
**MS6** · WP6.5 · MUST · NEW

Retention is configuration with documented defaults: ledger events (keep), traces and stage
logs (90 days), run directories (REC-022), webhook delivery logs (30 days). Expiry is a
registered mechanism.

- AC1: Expired blobs are removed and their references say "expired", not "missing".

Source: `mh.py` retention (notes); DESIGN §3.6 `retention` policy kind (parameters left open in the frozen schema).

### OBS-017 — Main-branch release health
**MS5** · WP5.4 · SHOULD · KEEP

Per repo: the latest completed required run on the default branch and the age of the last
success. A failing required run is a factory-down signal until a later success; an owner-accepted
hold changes its disposition, not its colour.

- AC1: Green change-request checks never dilute this state.

Source: factory-measurement-contract "Mainline release health".

### OBS-018 — Improvement ledger
**LATER** · — · LATER · KEEP

A record per tuning intervention with hypothesis, pre and post cohort values and a verdict
(`improved`, `regressed`, `inconclusive`, `not_live`).

- AC1: Until it ships, the audit of policy changes (SCH-011) plus the windowed metrics give the raw material.

Source: factory-measurement-contract "Sense → respond → improve loop".
