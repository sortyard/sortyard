# 08 — Operator console

Area: **UI**. The console is the pane of glass: one place where a task and what the agents did
with it are the same record. It grows from the existing harness console
(`k3s-harness:control-plane/console`: React 19, TanStack Router/Query/Virtual, Tailwind 4, Vite,
journeys J1–J13 proven by Playwright, an accessibility spec and a 350 KB bundle budget), not from
Plane's frontend.

Two rules govern it:

1. **A capability is not done until its UI ships.** Each milestone delivers the screens for what
   that milestone adds. There is no late "write surfaces" milestone.
2. **If an operator can do it, the UI can do it; if the UI can do it, the API can do it.**

---

### UI-001 — The console is a client of the public API
**MS1** · WP1.5 · MUST · KEEP

A single-page app served as static files by the API service. It uses only public API operations
and the event stream. There is no console-only endpoint.

- AC1: A test serves the console against a mock built from the OpenAPI document alone and every route renders.
- AC2: A lint forbids request paths outside the generated API client.

Source: DESIGN §6 rule; SY-DEC-001 (Vite SPA, static files served by the API service).

### UI-002 — UI-for-everything is measured
**MS1** · WP1.5 · MUST · NEW

Operations are annotated `operator-facing` in the OpenAPI document. A coverage manifest maps
each to the route and control that invokes it. CI fails when an operator-facing operation has no
UI path, unless it carries a dated exemption.

- AC1: At each milestone exit the exemption list is empty for operations introduced in that milestone or earlier.
- AC2: The manifest is published as a docs page ("where is X in the UI").

Source: Joe's objective ("there is a UI for everything"); CORPUS M5.6 defers every write surface to Phase 5 — see CF-03.

### UI-003 — Board and list
**MS1** · WP1.5 · MUST · NEW

The board shows tasks in columns by state; the list shows them in rows. Both support filters
(TRK-014), reordering of top-level tasks by drag or keyboard (TRK-007), and inline display of
park and hand-back reasons. Dragging changes rank only; state and priority are changed from the
item.

- AC1: Every drag has a keyboard equivalent and an undo.
- AC2: After a drag, every open board and list shows the new order within 5 s without a reload.

Source: DESIGN §6 view 1 ("Dragging is defined, not magic"); task-ready ("To reorder delivery, drag top-level tasks on the board").

### UI-004 — Task detail is one timeline
**MS1** · WP1.5 · MUST · KEEP

One page per task: fields and spec, relations, the filing verdict and reasons, and one ordered
timeline of notes, state changes, decisions and — from MS3 — the chain: stages with attempts,
durations and outcomes, the change request, checks, review verdicts, usage. There is no separate
"pipeline" record to click through to.

- AC1: (WP3.9) From a task, the stage outcome that explains its current state is on the same page (zero navigation).
- AC2: Every timeline entry has a stable deep link.

Source: DESIGN §6.0 ("A task's detail *is* its chain"); Joe 2026-11-06 (the dashboard "connects tickets with the pipeline").

### UI-005 — Creating and editing tasks
**MS1** · WP1.5 · MUST · NEW

A form for the tracker fields and the typed spec with inline readiness feedback, a raw YAML view
of the same spec, and paste-or-upload of a task file with a per-task verdict preview before
filing.

- AC1: Form and YAML views round-trip without loss.
- AC2: Readiness errors appear as the user types, from the server's evaluation.

Source: task-ready "The task item"; `plane_tasks.py file`.

### UI-006 — Pickup Preview and "why"
**MS2** · WP2.7 · MUST · FIX

Per project: the queue in claim order, slot holders with phase and age, the reason code for
every task not claimable now, and the next-N simulation. On every task detail page: a "why is
this not running" panel with the same reasons and the tasks ranked ahead.

- AC1: Each reason code links to its documentation and, where an operator can fix it, to the control that does.
- AC2: The view states the evaluation time and the policy versions it used.

Source: task-pickup §7 (the "Where a reader sees it" column); HARNESS-251, HARNESS-256.

### UI-007 — Owner list and decision inbox
**MS2** · WP2.7 · MUST · KEEP

One view of everything waiting on a person, grouped by route: decisions with their default and
time left, escalated premise-class decisions, needs routed to the viewer's route, items escalated
to a person. Decisions are answered here.

- AC1: Answering a decision records the chosen value and the route that will apply it.
- AC2: A decision past its date that took its default shows as such, not as open.

Source: driver §6 (the owner "answers `decision` items; defaults apply on their date"); conductor README (depends-on-Joe list, `needs-human`, `route:owner`).

### UI-008 — Lanes and tuning
**MS2** · WP2.7 · MUST · FIX

Edit lanes per project, pause and resume, admission caps and the scheduling policy values, with
the current value, the default, who last changed it and when. Saving shows the diff and its
effect on the Pickup Preview before it applies.

- AC1: A lane change needs no deploy and no file edit.
- AC2: Every value shows the legacy constant it replaces where there is one (DEF-005).

Source: driver §1 (knobs in `repos.yaml`, hardcoded copies in three files); DESIGN §5.3.

### UI-009 — Overview: glance at the floor
**MS3** · WP3.9 · MUST · KEEP

The landing page: health state and what drives it; per project running, waiting, parked and
handed-back counts with oldest ages; slots and heavy-cap use; recent merges; the attention list.
It updates live and renders within 2 seconds on the reference fixture.

- AC1: A source that is unknown or stale renders `unknown`, never 0.
- AC2: Every number links to the list that produces it.

Source: harness-console J1; FACTORY-DASHBOARD-DESIGN "Screen and feedback loop".

### UI-010 — Chains and actions
**MS3** · WP3.9 · MUST · KEEP

For a chain: the stage timeline with attempts, durations, the reason a stage is waiting or
failed, and the binding. Actions — requeue, cancel, stop, resume — are offered only where the
API says they are legal, behind a dialog that states the effect; the result and its audit entry
appear inline.

- AC1: An action the API would refuse is not offered.
- AC2: A run detail page never returns an error for an existing run; ids are unique.

Source: harness-console J3, J5; VISION ("run detail currently 502s").

### UI-011 — Logs and traces
**MS3** · WP3.9 · MUST · KEEP

A stage's log and, where captured, its agent trace: live tail with follow mode, virtualised for
multi-megabyte content, searchable, with deep-linkable lines. The basic log view ships in MS3;
search, trace filtering and deep links are complete by MS6 (WP6.3).

- AC1: A 5 MB log or trace opens without freezing the page (frame time budget in the e2e test).

Source: harness-console J3; DESIGN §6 view 4.

### UI-012 — Credentials
**MS4** · WP4.3 · MUST · KEEP

Accounts and keys with health, expiry and last use; add and re-authenticate through a stepper
that survives refresh and navigation, shows progress on slow steps, retries transient errors and
can be cancelled. Values are never shown and never entered except through the provider's own
flow or a paste-once field.

- AC1: Viewing the page triggers no paid probe.
- AC2: A stuck flow can be cancelled for any provider.

Source: harness-console J4; console routes `credentials`, components `add-account`, `sign-in`.

### UI-013 — Parked and self-heal queues
**MS5** · WP5.2 · MUST · KEEP

Lists of parked and handed-back work with reason, blocking cause, age and what would bring each
back; the resolution actions of the self-heal contract (REC-009).

- AC1: Items older than 24 h are marked and match the `SELF-HEAL-STALLED` condition's list.

Source: conductor README "Self-heal drain", "Blocking causes".

### UI-014 — Health
**MS5** · WP5.6 · MUST · KEEP

Mechanisms with cadence, window, last success and last error; credential quotas with burn rate;
open conditions. The page shows the four-state health (REC-019) and exactly which entries cause
it.

- AC1: A silent mechanism is findable from the Overview in two clicks.

Source: MECHANISMS.md; `GET /api/mh/factory/mechanisms`.

### UI-015 — Dashboards
**MS6** · WP6.2 · MUST · KEEP

Throughput by window; lead time and time in each state; stage pickup latency and execution time;
delivery cost; lane and heavy-cap utilisation; review churn; CI and main-branch health;
credential health. Each tile shows its definition, its `as_of` and its coverage, and drills into
the records behind it.

- AC1: Every tile's value matches a hand-computed fixture.
- AC2: No dashboard requires Grafana or any service beyond Sortyard and Postgres.

Source: [09-observability.md](09-observability.md) metric catalogue; console route `delivery`, components `stage-timing`, `insights`.

### UI-016 — Decision log and audit explorers
**MS2** · WP2.7 · MUST · KEEP

Search scheduling decisions by task, reason code, time and policy version, and open one
evaluation to see its inputs; browse the audit log by actor, object and time. A basic version
ships in MS2; saved searches and replay of an evaluation are complete by MS6.

- AC1: "Why was X not claimed at T" is answerable from the UI without the CLI.

Source: DESIGN §6 (DecisionLog explorer); harness-console `audit-trail` component.

### UI-017 — Administration
**MS1** · WP1.5 · MUST · NEW

Users, role bindings, service accounts and tokens; projects and repositories with an onboarding
wizard; system information (version, schema, image digest). Integrations, definitions and backup
controls join as their capabilities land; the page is complete at MS6 (WP6.4).

- AC1: A new project can be created and its first task filed without leaving the UI.

Source: DESIGN §6 view 12; onboarding.md (today: edit `repos.yaml`, push, wait for the onboarding check).

### UI-018 — Performance budgets
**MS1** · WP1.5 · MUST · KEEP

Initial JavaScript at most 350 KB gzipped, enforced in CI. Grids are virtualised (about 50 rows
mounted) and scroll 10,000 fixture rows smoothly. Lists use server cursors. Route code is
lazy-loaded.

- AC1: The budget check fails the build when exceeded.
- AC2: An e2e test asserts the mounted-row bound on a 10,000-row fixture.

Source: `console/check_budget.py` (`BUDGET_BYTES = 350 * 1024`); harness-console J2; decided D4.

### UI-019 — Accessibility
**MS1** · WP1.5 · MUST · KEEP

Target WCAG 2.2 AA. CI runs an automated accessibility scan on every route with zero serious or
critical violations, and every journey test is also run keyboard-only. Focus is managed on route
change and in dialogs; live updates are announced politely.

- AC1: The accessibility and keyboard specs are required checks.
- AC2: Colour is never the only carrier of state.

Source: harness-console journeys preamble ("keyboard-only, with zero serious/critical axe violations"); `console/e2e/tests/a11y.spec.ts`, `keyboard.spec.ts`; components `route-focus`, `announce`.

### UI-020 — Responsive
**MS1** · WP1.5 · MUST · KEEP

Every journey passes at 390, 834 and 1440 pixels wide.

- AC1: The e2e matrix runs the journeys at the three widths.

Source: harness-console journeys preamble; VISION ("on a laptop or a phone").

### UI-021 — Live without reload
**MS1** · WP1.5 · MUST · KEEP

Views update from the event stream, falling back to polling. A stale or disconnected view says
so.

- AC1: Killing the stream connection shows a "reconnecting" state and recovers without a reload.

Source: harness-console J1; decided D5; console `lib/live.ts`.

### UI-022 — Command palette
**MS6** · WP6.3 · SHOULD · KEEP

A keyboard palette jumps to any task, chain or run by id or text and runs common actions.

- AC1: Typing `ROVE-12` and Enter opens that task from any page.

Source: harness-console J2 ("⌘K palette jumps to any request/chain/run by id"); console `command-palette` component.

### UI-023 — Design tokens and brand
**MS1** · WP1.5 · SHOULD · KEEP

One token set (colour, type, spacing) with light and dark themes, using the Sortyard brand kit.

- AC1: No component hard-codes a colour.

Source: meta-harness `projects/sortyard/branding/`; harness-console decided D3.

### UI-024 — Empty, error and unknown states are designed
**MS1** · WP1.5 · MUST · KEEP

Every view has a designed state for: nothing yet, loading, failed to load, and value unknown.
An absent value is never rendered as zero, a blank or a spinner that never ends.

- AC1: Storybook (or equivalent) has a story per state per view, and the e2e suite visits the failed and unknown states.

Source: AGENTS.md "Testing model" (one story per machine state; every gate defines its absent state); harness-console J1.

### UI-025 — Strings are externalised; English only
**MS1** · WP1.5 · MUST · NEW

All user-visible strings go through a message catalogue with locale-aware dates and numbers.
1.0 ships English only and documents how a locale is added.

- AC1: A lint fails on a hard-coded user-visible string in a component.
- AC2: A pseudo-locale build renders every route without clipped or missing text.

Source: Plane benchmark (22 locales, an i18n sync check in CI); see [12-quality-bar.md](12-quality-bar.md) for the stance.

### UI-026 — Embedded concierge
**LATER** · — · LATER · KEEP

The embedded chat agent of the existing console (ask a question, get an answer grounded in live
state with citations, approve proposed actions) is not part of 1.0. Its ambient half — the
attention list — is (OBS-014). Operators reach the same capability from their own agent through
MCP.

- AC1: The read tools the concierge used are present in the operator-agent MCP set (MCP-002), so the feature can return without new API work.

Source: harness-console J6–J8, decided D7–D9, D14–D15; console `components/concierge/*`. Owner decision OD-3.
