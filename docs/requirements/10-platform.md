# 10 — Platform: definitions, extensibility, deployment, migration

Areas: **DEF** (definitions and configuration), **EXT** (extension points), **DEP** (install,
upgrade, operate), **MIG** (moving the estate onto Sortyard). These replace the markdown control
plane's role as configuration, the bespoke release controller and `deploy.sh`, and the one-off
import scripts.

---

## DEF — definitions and configuration

### DEF-001 — A small set of definition kinds, all versioned
**MS2** · WP2.6 · MUST · KEEP

Definitions in 1.0: `policy` (rules and thresholds), `lane` settings, `project` configuration,
`workflow`, `packet-template`, `harness-profile`, `checklist`. Each version is immutable and
content-hashed; the newest valid version is current. Policies, lanes and project configuration
arrive in MS2; the rest in MS3.

- AC1: Editing a definition creates a new version; an existing version can never change (database-enforced).
- AC2: Applying identical content twice creates no new version.
- AC3: Archetypes, context recipes, roles, skills and eval packs are not definition kinds in 1.0 (CF-05).

Source: `definitions/README.md` (immutable content-hashed versions); DESIGN §5.1; CF-05 for the cut.

### DEF-002 — The database is authoritative; files are how definitions travel
**MS3** · WP3.8 · MUST · FIX

All definitions live in the database. `sortyardctl apply -f <dir|file|git-url@ref>` creates
versions from files through the API; `sortyardctl export` writes the current versions as files.
Export then apply is a no-op. There is no sync controller and no "definitions: stale" state.

- AC1: Round-trip test: export → apply on a second install yields identical content hashes.
- AC2: A UI edit and an `apply` of the same content produce the same version.

Source: DESIGN §5.1 (git and database both, with a sync controller); CF-06 for why this is changed. Owner decision OD-5.

### DEF-003 — Source lock
**MS6** · WP6.4 · MUST · NEW

An installation can lock definitions to a source: only `apply` from the configured repository
and ref (run by a token with the `definitions-source` role, typically from CI) may create
versions; the UI shows definitions read-only and links to the source.

- AC1: With the lock on, a UI or API edit by an operator is refused with a message naming the source.
- AC2: The NonceLogic installation runs locked, which keeps "definition edits go through git review".

Source: INTENDED-USE.md standing default ("definition edits via git PRs").

### DEF-004 — A running chain keeps the versions it started with
**MS3** · WP3.1 · MUST · KEEP

A chain pins its workflow, packet-template and checklist versions at claim. New versions apply
to new chains. Policy thresholds, by contrast, are read at decision time.

- AC1: Editing a workflow mid-chain changes nothing for that chain.
- AC2: The task detail shows the pinned versions.

Source: DESIGN §5.1 (a) "pinning wins"; DESIGN §3.6 (policies read at decision time).

### DEF-005 — Every legacy constant is a named policy key with a documented default
**MS2** · WP2.6 · MUST · KEEP

No tunable is a literal in code. The table below is the starting key set; each row ships in the
milestone that introduces its behaviour, and a test asserts the code reads the key.

| Legacy constant | Value today | Policy key |
|---|---|---|
| `lanes` per project | 3 / 3 / 2 / 1 … | `project.lanes` |
| `MH_HEAVY_CAP` / `MH_TRAIN_HEAVY_CAP` / `MH_PROJECT_HEAVY_CAP` | 4–6 / 3–5 / 2 (deployment-specific) | `admission.heavy_cap`, `.train_cap`, `.project_heavy_cap` |
| stage deadlines | 45 / 60 / 60 / 120 min; max 3 h | `stage.<class>.deadline_seconds` |
| `BUILD_DEADLINE_S` | 3 h | `workflow.change.build_deadline_seconds` |
| `FIX_ROUNDS` | 10 (backstop) | `fix.backstop_rounds` |
| `CONFLICT_ROUNDS` | 5 | `fix.conflict_rounds` |
| `REVIEW_TRIPWIRE` | 5 | `review.tripwire` |
| `INFRA_RETRIES` / `INFRA_WAIT` / `INFRA_WAITS` | 3 / 30 min / 2 | `infra.retries`, `.wait_seconds`, `.waits` |
| consecutive step errors | 5 | `infra.consecutive_errors` |
| cluster-API retries | 6 | `infra.cluster_api_retries` |
| `API_WAIT` | 90 s | `infra.dependency_wait_seconds` |
| `STALL` | 4 h | `stall.phase_seconds` |
| `CHECKS_GRACE` | 30 min | `merge.missing_check_grace_seconds` |
| `TRIAGE_TRIES` / `TRIAGE_ROUNDS` | 3 / 2 | `triage.attempts`, `triage.merged_fix_rounds` |
| `DISPATCH_GRACE` / `PROOF_WAIT` / `CONFIRM_LIMIT` | 20 min / 3 h / 24 h | `triage.dispatch_grace_seconds`, `.run_wait_seconds`, `.confirm_limit_seconds` |
| causes `POLL` / `RETURNS` | 30 min / 2 | `causes.poll_seconds`, `causes.infra_returns` |
| self-heal drain | 24 h | `selfheal.stalled_after_seconds` |
| grooming alarm | 2 failures / 60 min | `grooming.failed_attempts`, `grooming.empty_queue_seconds` |
| filing sweep | 30 min | `filing.will_release_limit_seconds` |
| `QUEUED_AFTER` | 30 min | `ci.unrunnable_after_seconds` |
| job quarantine exit | 7 days / 20 clean runs | `quarantine.max_days`, `quarantine.clean_runs` |
| `MAX_SURFACES` | 8 | `preflight.max_surfaces` |
| test review deadlines | 10 / 15 min | `review.test.execution_seconds`, `.outer_seconds` |
| design review deadlines | 20 / 30 min | `review.design.execution_seconds`, `.outer_seconds` |
| pool window / cooling / requeues | 5 h / 5 h / 3 | `pool.usage_window_seconds`, `.cooling_seconds`, `.limit_requeues` |
| pool probe interval / deadline | 15 min / 900 s | `pool.probe_interval_seconds`, `.probe_deadline_seconds` |
| CLI soak | 6 h | `harness.cli_soak_hours` |
| packet cap | 200,000 chars | `packet.max_chars` |
| run retention / pressure | 24 h / 85% / 4 h | `retention.run_seconds`, `.pressure_percent`, `.pressure_seconds` |
| mirror freshness | 300 s | `mirror.stale_after_seconds` |
| mechanism check cadence / quota floor | 10 min / 20% | `health.check_seconds`, `quota.low_fraction` |
| release-verify limits | 15 min pod / 1 h unverifiable | `releaseverify.pod_seconds`, `.unverifiable_after_seconds` |

- AC1: The policy reference page is generated from the key registry and shows key, default, legacy name and the requirement that uses it.
- AC2: A key with no reader, or a reader of an unregistered key, fails CI.

Source: `drive.py` constants and their notes; `mh.py` constants (notes); conductor README; MECHANISMS.md; DESIGN §5.3 ("If a knob exists in code as a literal, that's a bug against this design").

### DEF-006 — Definitions are validated when applied
**MS3** · WP3.8 · MUST · KEEP

`apply` validates schema and meaning and refuses with a message naming the definition and the
rule: an unbounded phase (REC-001), a gate with no absent-state (FLW-009), a stage that breaks
pipeline purity (FLW-001), a reference to a missing template or profile, a threshold outside its
allowed range.

- AC1: `apply --validate` runs the same checks without writing and is usable in CI.
- AC2: A partially valid bundle applies nothing.

Source: meta-harness tradition of script refusals (DESIGN §3.6 "prose rule → script refusal"); `repos_check.py`.

### DEF-007 — See the effect before saving
**MS2** · WP2.6 · SHOULD · NEW

Changing a policy, lane or project setting shows a diff and a what-if: how the Pickup Preview
would differ.

- AC1: The what-if uses the scheduler's own evaluator with the proposed values.

Source: DESIGN §6 view 7 (simulate); UI-008.

### DEF-008 — A default bundle ships with every release
**MS3** · WP3.8 · MUST · NEW

Each release carries a default bundle: the `change` and `job` workflows, their packet templates,
the review checklists, harness profiles for the shipped harnesses, and default policies. A fresh
install applies it. On upgrade, changed defaults are offered as a diff the operator accepts; an
installation's edits are never overwritten.

- AC1: A fresh install can run the demo with no definition authored by the user.
- AC2: An upgrade never changes behaviour by silently replacing a definition the operator edited.

Source: `definitions/seed/` (9 workflows, 4 roles, 2 archetypes, 4 context recipes, 8 lanes, 10 policies — to be re-cut to the kinds in DEF-001); CORPUS M1.2.

### DEF-009 — Onboarding a project is one object and one check
**MS4** · WP4.9 · MUST · KEEP

A project is onboarded by creating it with its repositories, lanes, build and release switches.
An onboarding check then verifies and reports: the landing credential can push; auto-merge is
allowed; at least one required check exists (or the plain-git adapter is chosen); the mirror is
created. Claims start only when the check passes.

- AC1: A project whose check fails shows exactly which item failed and stays unbuilt.
- AC2: Onboarding needs no edit to any file outside Sortyard.

Source: onboarding.md (one `repos.yaml` entry; the onboarding check; "GitHub requirements per repo"); SY-DEC-003 (registration sequence: build registry first, driver last).

---

## EXT — extension points

### EXT-001 — Three ways to extend, none of them in-process
**MS3** · WP3.8 · MUST · NEW

Sortyard is extended by (1) **definitions** applied as bundles, (2) **containers** that honour a
published contract (worker images, sensors), and (3) **HTTP** (the API, MCP, the event stream,
webhooks). 1.0 loads no third-party code into the control plane and has no plugin registry.

- AC1: The architecture page lists every extension point with its contract version.
- AC2: A change that would require third-party code inside the API or controller process is out of scope for 1.0.

Source: DESIGN §11.1 ("Small core, everything else an extension"); CF-05 for why the six-kind registry and SDK are cut.

### EXT-002 — Worker image contract and conformance kit
**MS8** · WP8.4 · MUST · NEW

The stage contract (EXE-006) is published with a conformance kit: a container that plays the
controller's side against a candidate worker image and reports pass or fail per clause. The
shipped harness images pass it in CI.

- AC1: A third party can build a harness image and verify it with one command and no Sortyard install.

Source: CORPUS M5.7 (conformance test kit); EXE-012.

### EXT-003 — Git host adapters
**MS3** · WP3.4 · MUST · NEW

Everything Sortyard needs from a Git host is one interface: fetch, push a branch, open or update
a change request, read its state and checks, arm and disarm auto-merge, comment, read protection
rules, mint a read-only token. 1.0 ships `plain-git` and `github`.

- AC1: The scenario suite is written against the interface and runs on both a fake and `plain-git`.
- AC2: A capability an adapter lacks is declared, and dependent features say so (plain-git has no hosted checks, so CIH features are inactive).

Source: DESIGN §5.2 ("GitHub Issues and Linear … integrations, never dependencies"); AGENTS.md "pipeline purity".

### EXT-004 — Sensors are scheduled jobs that call the API
**MS5** · WP5.8 · SHOULD · KEEP

A sensor is a container run on a schedule by the same Job machinery as stages, in its own lane
outside the delivery pipeline, with a sensor token. It files findings and heartbeats through the
API. Sensors may reach live systems; delivery stages may not.

- AC1: A sensor's schedule is a registered mechanism with a freshness window (REC-017).
- AC2: A finding is de-duplicated by a stable key: repeats update its last-seen time.

Source: DESIGN §3.7 (Sensor), §1.4; factory-measurement-contract ("repeat sweeps update age instead of duplicating incidents").

### EXT-005 — Bundles from a repository at a pinned ref
**MS8** · WP8.4 · SHOULD · NEW

`apply` accepts a Git URL and a commit or tag; the bundle's source and content hash are recorded
on every version it creates.

- AC1: An unpinned ref (a branch name) is refused unless explicitly allowed.

Source: DESIGN §3.7 (registry "git-backed in v1"); CORPUS M3.2.

### EXT-006 — Tracker import adapters
**MS2** · WP2.8 · MUST · NEW

Importing from an external tracker is an interface with one shipped implementation (Plane):
list projects, items, relations, states, order and comments read-only.

- AC1: The adapter holds a read-only credential and issues only read requests (asserted by the HTTP fake).

Source: `src/sortyard/shadow/sources.py` (GET only; refuses redirects that would carry the key elsewhere); MIG-003.

### EXT-007 — Contracts are versioned
**MS8** · WP8.3 · MUST · NEW

The stage contract, the adapter interfaces and the bundle format carry versions. A release
states which versions it supports; a contract version is supported for at least two minor
releases after its successor ships.

- AC1: A worker image built for the previous contract version still runs on the current release.

Source: DESIGN §11.2 ("an API-stability/versioning commitment").

---

## DEP — install, upgrade, operate

### DEP-001 — One chart, one image, three control-plane workloads
**MS1** · WP1.6 · MUST · KEEP

One Helm chart and one image. Control-plane workloads: `api` (HTTP, console, MCP), `controller`
(scheduler, chain advancement, mirrors, schedules, health checks) and `integrator` (Git host
writes). Workers are Jobs. MS1 installs `api` and Postgres; `controller` and `integrator` join in
MS3. A single-pod profile for evaluation may run all three in one pod.

- AC1: The default install renders at most: three Deployments, one StatefulSet (bundled Postgres), their Services, Secrets, ConfigMaps, NetworkPolicies and one migration Job.
- AC2: The eval-runner, sensor-runner and context-assembler stub services in the repo are removed (CF-10).

Source: SY-DEC-001 (one codebase, entry points, all-in-one profile); DESIGN §4 (six services); CF-10. Plane benchmark: 13 containers.

### DEP-002 — Installable by a namespace admin
**MS1** · WP1.6 · MUST · NEW

The chart needs no CustomResourceDefinitions and no cluster-scoped objects by default. Optional
cluster-scoped extras (a PriorityClass, a second namespace for workers) are flags, each
documented with what is lost without it.

- AC1: `helm install` succeeds with a ServiceAccount that has admin on one namespace only.
- AC2: From MS3, when the controller ships: its Role is limited to Jobs, Pods, Pods/log, ConfigMaps and Secrets in the worker namespace.

Source: 2026-11-12 release stall (a new CronJob could not be applied because a hand-maintained Role did not name it); `k8s/mh-rbac.yaml`.

### DEP-003 — Postgres and one blob location, nothing else
**MS1** · WP1.6 · MUST · KEEP

State, ledger and work queue are in Postgres. Blobs (packets, logs, traces, mirrors) go to a blob
store with two backends: a PersistentVolume (default) or S3-compatible storage. There is no
Redis, no message broker and no required object store.

- AC1: The default install has exactly one database and one PersistentVolumeClaim besides Postgres's own.
- AC2: Switching the blob backend is a values change plus a documented copy step.

Source: SY-DEC-001 ("Postgres is the only database … no Redis, no message broker"); DESIGN §4 storage choices (which adds an S3 store — see CF-11).

### DEP-004 — Bundled or external Postgres
**MS1** · WP1.6 · MUST · KEEP

The chart can run Postgres for evaluation or use an existing server. Supported major versions
are stated (16 and 17 at 1.0) and tested in CI. Production guidance says to use an external,
backed-up Postgres.

- AC1: The install test runs against both modes.
- AC2: A wrong credential fails readiness (API-014).

Source: README quickstart (`postgres.enabled=false`); goldfish GF1-07.

### DEP-005 — Install time
**MS1** · WP1.6 · MUST · NEW

From a clean kind cluster with the prerequisites present: a running Sortyard with the first task
filed in at most 15 minutes (MS1); the demo chain finished in at most 30 minutes (MS3). Both are
scripted and timed in CI on every release candidate, using published artefacts only.

- AC1: The CI job fails when either bar is exceeded on the reference runner.
- AC2: The documented path has at most 8 commands and no step that requires editing a file.

Source: DESIGN §1.9 ("`helm install` it on a fresh cluster in an afternoon") — tightened; goldfish GF1-05 (no prerequisite check, no one-command replica).

### DEP-006 — Values are few, documented and schema-checked
**MS1** · WP1.6 · MUST · NEW

The chart ships a `values.schema.json`; every value has a comment and a default; a default
install requires no values. The values reference page is generated.

- AC1: `helm install` with an unknown or mistyped value fails with the schema's message.
- AC2: Fewer than 10 values need a decision for a production install; they are listed on one page.

Source: `charts/sortyard/values.yaml`; Plane benchmark (58 variables in the self-host env file).

### DEP-007 — Migrations
**MS1** · WP1.6 · MUST · FIX

Numbered, forward-only SQL migrations, each applied in one transaction with its record; a
released migration is immutable and the runner refuses a changed file. The migration Job runs
**before** new application pods start (a pre-upgrade hook; post-install on first install).
Migrations follow expand-then-contract so the previous application version keeps working on the
new schema. The runner refuses to run against a schema newer than the release knows.

- AC1: CI applies every migration to a database at the previous release's schema while the previous release's test suite runs against it.
- AC2: Each release documents whether its migrations are online-safe and their expected duration on the reference data set.

Source: `charts/sortyard/migrations/migrate.sh` (immutability check); `templates/migrations.yaml` (currently `post-install,post-upgrade`); Plane benchmark (a migrator container and a migration check workflow).

### DEP-008 — Upgrade guarantees
**MS8** · WP8.3 · MUST · NEW

From 1.0: any 1.x upgrades directly to any later 1.y; this is tested in CI from the last patch
of every earlier minor, with data. Rolling back the application by one minor without restoring
the database is supported. Before 1.0: each 0.x upgrades from 0.(x−1), tested, with any
exception in the upgrade notes.

- AC1: The upgrade matrix job seeds data with the old version, upgrades, and runs the new version's scenario suite.
- AC2: Every release has upgrade notes even when they say "nothing to do".

Source: CORPUS M6.3; Plane benchmark (an upgrade option in `setup.sh` and a one-off `migration-0.13-0.14.sh`; no stated guarantee found in the repo).

### DEP-009 — Work in flight survives upgrades and restarts
**MS3** · WP3.7 · MUST · FIX

Upgrading or restarting the control plane does not fail running stages. Jobs keep running;
their results are accepted afterwards; chains resume. The stage contract of the previous minor
is accepted by the current one.

- AC1: Upgrade during 20 running chains: all complete with no extra attempt caused by the upgrade.

Source: conductor README "API rollouts" (strategy Recreate leaves 30–40 s with nothing listening; 11 rollouts in a day failed reviews and grooming).

### DEP-010 — Availability during upgrade
**MS3** · WP3.7 · SHOULD · FIX

The API rolls without downtime with two replicas; the controller and integrator hand over
leadership within 60 seconds. With one replica each, the documented gap is under 60 seconds and
harmless (REC-016).

- AC1: A continuous read probe during upgrade sees no failed request with two API replicas.

Source: `k8s/deployment.yaml` (`replicas: 1`, `strategy: Recreate` because of a single-writer SQLite database).

### DEP-011 — Backup and restore
**MS6** · WP6.5 · MUST · NEW

Documented and scripted backup of the database and blobs (`sortyardctl backup create`), and
restore into a fresh install. A restore drill runs in CI: back up a seeded install, restore
elsewhere, run the scenario suite's read checks.

- AC1: The restored install has identical ledger sequence and content hashes.
- AC2: The docs state the recovery point for each backup method.

Source: Plane benchmark (backup option and `restore.sh`, `restore-airgapped.sh` scripts); DESIGN §6 view 12.

### DEP-012 — Uninstall is documented
**MS1** · WP1.6 · MUST · FIX

The docs say exactly what survives `helm uninstall` (the database Secret and volume) and how to
remove it.

- AC1: The uninstall section is exercised by the install test.

Source: goldfish GF1-08.

### DEP-013 — Footprint
**MS1** · WP1.6 · SHOULD · NEW

An idle control plane with bundled Postgres requests at most 0.5 CPU and 1 GiB of memory in
total.

- AC1: The chart test sums the default requests and fails above the bar.

Source: `values.yaml` today (API 50m/64Mi, Postgres 100m/256Mi); Plane benchmark (minimum 2 vCPU / 4 GB).

### DEP-014 — Pod security and network policy
**MS1** · WP1.6 · MUST · NEW

Every Sortyard pod runs as non-root with a read-only root filesystem, no added capabilities and
the default seccomp profile, and passes the Kubernetes `restricted` pod security standard — the
only exception being the opt-in container sidecar (EXE-016). The chart ships NetworkPolicies:
the API is reachable only from the ingress and Sortyard's own pods; workers reach only what
EXE-005 lists.

- AC1: The chart test validates manifests against the `restricted` standard.
- AC2: A pod in another namespace cannot reach the API port when policies are enforced.

Source: `Dockerfile` (`USER 10001`); `k8s/networkpolicy.yaml` (`control-plane-ingress-node-only`); HC02-BACKEND-LOCKDOWN-DESIGN; Plane benchmark (no `USER` directive in its API, web and live Dockerfiles).

### DEP-015 — Air-gapped install
**MS8** · WP8.6 · SHOULD · NEW

The control plane needs no outbound network at runtime beyond the configured Git host and model
provider. The release lists every image by digest; worker images can have agent CLIs baked in so
that nothing is downloaded at stage start.

- AC1: The install test passes with a registry mirror and no other egress.

Source: DESIGN §4 ("Air-gapped-ish install possible"); `mh.py` worker init container installs CLIs from npm at start (notes).

### DEP-016 — GitOps-friendly
**MS3** · WP3.7 · MUST · KEEP

The chart renders deterministically, keeps generated secrets stable across upgrades, and works
under Argo CD and Flux, including its migration hook.

- AC1: `helm template` twice gives identical output; an Argo CD sync of the chart in CI ends Healthy and Synced.

Source: DESIGN §4 ("GitOps-friendly"); `postgres-secret.yaml` (password kept across upgrades).

### DEP-017 — Supported Kubernetes versions
**MS8** · WP8.3 · MUST · NEW

Each release states the Kubernetes minors it supports (the current and two previous at release
time) and CI runs the install and demo on each, on kind and on k3s.

- AC1: The matrix is in the release notes and the CI configuration.

Source: the estate runs k3s; the quickstart uses kind.

### DEP-018 — One-command local replica
**MS0** · WP0.1 · MUST · KEEP

One command on a machine with Docker checks prerequisites and their versions, creates a local
cluster, builds and loads the image, installs the chart in the deployment's own shape, and
prints how to reach it. The same environment runs the scenario suite.

- AC1: A zero-context agent goes from a fresh clone to a passing `verify` with two commands.
- AC2: The replica uses the scripted harness and the plain-git adapter; it needs no account anywhere.

Source: goldfish GF1-05; CORPUS M1.1; AGENTS.md "Local-first delivery" (the local replica is the deployment shape); SORTYARD-13 (open).

### DEP-019 — Multi-architecture images
**MS8** · WP8.6 · SHOULD · NEW

Images are published for `amd64` and `arm64`.

- AC1: The demo passes on an arm64 kind cluster in CI.

Source: inference (contributors on Apple-silicon laptops).

### DEP-020 — A release has one identity
**MS1** · WP1.6 · MUST · FIX

Chart version, image tag and application version are tied; the image is referenced by digest in
the rendered manifests of a release; `/v1/info` and the console footer show version, commit and
digest.

- AC1: The quickstart never asks the reader to build an image or match a tag by hand.

Source: README quickstart (build locally, "the tag must match `appVersion`"); goldfish "Not verified: whether the image is published"; k3s driver (digest annotations on the deployment).

### DEP-021 — Sizing guidance
**MS8** · WP8.6 · SHOULD · KEEP

The docs give cap and envelope defaults by node size, with the reasoning, starting from the
estate's experience.

- AC1: The guidance includes a worked example for a 16 vCPU / 64 GiB node.

Source: DESIGN §3.7b (proof-class sizing on D8s_v6 versus D16s_v6); driver §5.

---

## MIG — moving the estate

Migration is a separate track that consumes product releases. Its tooling is not part of the
core package.

### MIG-001 — Freeze the legacy evidence now
**MS0** · WP0.3 · MUST · KEEP

Before any legacy component changes because of Sortyard: capture the control-plane ledger, the
scorecard battery corpus and baselines, and a Plane export; hash them; publish the manifest
digest.

- AC1: `legacy_evidence.py verify` passes on the snapshot, and its digest is recorded on the tracking item.
- AC2: This is the first item worked in MS0.

Source: `legacy-evidence/README.md`; CORPUS M1.15 ("the only corpus item that becomes impossible later"). Status 2026-11-12: the tool is merged (SORTYARD-11 Done) but no snapshot exists; the capture items SORTYARD-70 and SORTYARD-71 are still Todo.

### MIG-002 — Record the legacy conductor's inputs, pass by pass
**MS0** · WP0.3 · MUST · NEW

The legacy conductor's per-pass inputs (board view, project configuration, gating output) and
its claims are retained with the legacy revision that produced them, as a replay corpus.

- AC1: At least 7 consecutive days are retained before MS2's comparison, and retention continues until the last cutover.
- AC2: Each recorded pass names the legacy bundle digest it ran on.

Source: README "Shadow conductor" (pass feed; "A pass with no retained inputs can only be read live while it is the newest"); CORPUS R5 (the baseline moves); SORTYARD-79 (still Todo).

### MIG-003 — Plane importer
**MS2** · WP2.8 · MUST · NEW

Import one Plane project into a Sortyard project: tasks with their spec blocks parsed into typed
fields, parents, blocked-by relations, states, manual order, priorities, due dates, notes, and
the control labels mapped to typed fields (TRK-009). A dry run prints an object-class difference
report and changes nothing.

- AC1: For each driven board, the dry-run report shows zero unmapped control labels and zero dropped relations.
- AC2: The eligible set and its order after import equal the legacy conductor's for the same instant (checked by MIG-005).
- AC3: Importing twice is idempotent.

Source: 2026-11-08 release note (the registers→Plane import: counts per board, 252 relations, order could not be set through Plane's API); conductor README "Plane tasks".

### MIG-004 — Read-only mirror mode
**MS2** · WP2.8 · MUST · NEW

A Sortyard project can mirror an external board continuously and read-only. Mirrored projects
run the scheduler in observe mode only (SCH-013) and are labelled as mirrors everywhere.

- AC1: A mirrored project cannot be switched to active without the cutover action (MIG-007).
- AC2: Sortyard issues no write to the mirrored tracker.

Source: README "Shadow conductor" ("It never claims, merges, comments or writes anywhere but its own database").

### MIG-005 — Replay comparison
**MS2** · WP2.8 · MUST · KEEP

Run Sortyard's real evaluator over the recorded legacy passes (MIG-002) and compare claim
decisions. Every divergence is stored and classified: input difference, policy mismatch,
implementation defect, side effect the replay cannot know, or unclassified with the reason.

- AC1: Over at least 2,000 recorded passes: claim agreement of at least 99%, and 100% of divergences classified, with no open implementation defect.
- AC2: The comparison is a repeatable offline job (minutes, not weeks) and runs in CI on a fixed sample.

Source: `claim-comparison/README.md` (pairing, classification); DESIGN §8 Phase 1; CF-13 for replacing the live soak.

### MIG-006 — Migration code stays out of the core
**MS0** · WP0.2 · MUST · FIX

Everything specific to the legacy estate (the Plane/`products.json`/gating adapters, the
comparator, the evidence tool, the cutover kit) lives under a `migration/` tree with its own
tests and is not imported by the `sortyard` package. The core has no NonceLogic project names,
hosts or file formats.

- AC1: An import-graph test fails if `sortyard.*` imports from `migration.*`.
- AC2: A grep gate fails on estate-specific names (`noncelogic`, internal hostnames, `products.json`) in `src/`, `charts/` and the public docs. `migration/` is exempt; `docs/requirements/` is exempt until the publication step in [README.md](README.md) ("Before this directory is public").

Source: `src/sortyard/shadow/` and `charts/…/shadow-conductor.yaml` are in the core today; DESIGN §1.9 ("no NonceLogic-specific assumptions in the core"); goldfish GF1-04 (internal hosts in the README).

### MIG-007 — Cutover kit
**MS7** · WP7.1 · MUST · KEEP

One scripted procedure per project: dry-run report; freeze the legacy side (build off);
snapshot; import; verify counts, order and eligible set; switch the Sortyard project to active;
hypercare window; verdict. Each step is recorded and resumable.

- AC1: The kit is first executed end to end in the replica against a copy of the project.
- AC2: Running a step twice is safe.

Source: CORPUS M4.1; SY-DEC-003 (the proven registration sequence).

### MIG-008 — One authority at a time
**MS7** · WP7.1 · MUST · KEEP

For any project at any moment exactly one system claims work. The kit refuses to activate a
Sortyard project while the legacy driver still has build on for it, and refuses to re-enable the
legacy driver while Sortyard is active.

- AC1: An attempt to activate with the legacy side still on fails with the evidence.

Source: driver §6 ("Nothing else should build or merge for a project that has `build` on"); in-flight-steering.

### MIG-009 — Hypercare and rollback
**MS7** · WP7.1 · MUST · KEEP

Each cutover has a hypercare window (default 7 days; 14 for the pilot) with a written verdict:
claims correct, landings fenced, hand-backs owned. Until the verdict, rollback is possible: stop
Sortyard for the project, re-enable the legacy driver from the frozen snapshot. After the
verdict the legacy side for that project is switched off, not kept as a fallback.

- AC1: The rollback path is rehearsed once in the replica before the pilot.
- AC2: A verdict lists every operator intervention during the window.

Source: CORPUS M3.14, M4.5–M4.7; the estate's standing rule that legacy paths are shut down or cut over, never kept as a fallback.

### MIG-010 — Rule conformance ledger
**MS7** · WP7.2 · MUST · KEEP

Every enforceable rule of the legacy system is mapped to a requirement in this specification, a
policy key, a policy pack, or a recorded retirement with its reason.
[16-legacy-parity.md](16-legacy-parity.md) is the seed; it is completed against `AGENTS.md`, the
templates and the skills before the first product cutover.

- AC1: No row is left "unmapped" at the pilot's verdict.
- AC2: Before each cutover, every KEEP and FIX row the project relies on has a passing parity scenario (REC-025) or a dated waiver by the owner.

Source: CORPUS M5.1, M5.5 ("each prose rule either becomes a Policy or is consciously retired").

### MIG-011 — Legacy retirement
**MS7** · WP7.5 · MUST · KEEP

After the last cutover: the legacy conductor CronJobs, the dispatcher, the release controller,
the host crons and watches are removed; the Plane projects are archived read-only; final exports
are stored. A one-source-of-truth audit lists every remaining second copy of any fact; the
milestone is not done while the list is non-empty.

- AC1: Each retired watch or cron names the Sortyard mechanism that replaces it, or the reason it is no longer needed.

Source: CORPUS M4.8–M4.10; MECHANISMS.md registry (the list of what exists).

### MIG-012 — Estate mechanism observers
**MS7** · WP7.3 · MUST · KEEP

The estate mechanisms the legacy check watches beyond the pipeline (CronJobs and resources on
three clusters, scheduled CI workflows, host timers) keep being watched: through external
heartbeats (REC-018) and an optional observer integration for cluster objects and CI schedules.

- AC1: Before the legacy mechanism check is switched off, every entry of `mechanisms.yaml` is either registered in Sortyard or recorded as out of scope with an owner.

Source: `mechanisms.yaml` (68 entries across HARNESS, DEVOPS, ROVE, CPV2, LOOP boards).

### MIG-013 — The experiment rig gets an explicit fate
**MS7** · WP7.5 · MUST · KEEP

The experiment rig that shares the legacy control plane (corpus, treatments, compare and eval
views, the scorecard battery) is inventoried and, by a recorded decision, either archived or kept
as its own deployment. It is not carried into Sortyard.

- AC1: The decision record exists before the legacy control plane is removed.

Source: CORPUS M4.4; harness-console decided D11 (experiment views moved under "Lab").

### MIG-014 — Importing historical evidence
**LATER** · — · LATER · KEEP

Importing the frozen ledger history and battery baselines into Sortyard is deferred. The frozen
snapshot (MIG-001) stays the record.

- AC1: Dashboards mark the period before a project's cutover as "not in Sortyard".

Source: CORPUS M4.2; DESIGN §8 non-goals ("migrating historical ledger data beyond an import of open work").

### MIG-015 — Close out the Phase 1 prototypes
**MS0** · WP0.2 · MUST · FIX

Each Phase 1 deliverable that was merged into meta-harness instead of the product repository is
either ported into `sortyard/sortyard` with its tests or recorded as retired: the identity matrix
(`identity/`), the generated clients (`clients/`), the definitions loader and seed
(`definitions/`), the claim comparator (`claim-comparison/`), the evidence tool
(`legacy-evidence/`), the latency instrument (`one-loop-latency/`), `spec/PERMISSIONS.md`.

- AC1: [14-mapping.md](14-mapping.md)'s carry-over table has a final disposition for every row.
- AC2: `pytest spec` gates CI.

Source: meta-harness `projects/sortyard/` (about 5,000 lines across six folders); `ci.yml` (`spec` job fails on main); board: SORTYARD-9, 10, 11, 12, 14, 15 are Done while the product repo holds only PRs #1–#4.
