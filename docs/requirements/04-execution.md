# 04 — Execution and credentials

Areas: **EXE** (how a stage runs: binding, Jobs, mirrors, harnesses) and **CRD** (credential
custody, the subscription pool, the broker). These replace `mh.py`'s worker launcher, `auth.py`,
`cred_sync.py` and the mirror handling split between `mh.py` and `drive.py`.

The principle kept from the owner (DESIGN §1.11): **no unbound agents**. An agent never "picks up"
a task. A stage runs only after a recorded set of checks has passed, inside a bounded envelope,
in a place the operator chose.

Line references to `mh.py` come from working notes of a partial code read (see
[17-evidence.md](17-evidence.md)); constants were spot-checked.

---

## EXE — execution

### EXE-001 — Execution binding is a recorded, named check set
**MS3** · WP3.2 · MUST · KEEP

Before a stage is launched the controller records a binding: workflow and stage (pinned
versions), packet template version and packet hash, harness profile (harness, model, effort,
fallback), worker image digest, resource envelope and deadline, repo and base commit with the
mirror's freshness fact, credential selection, materialised inputs. If any element cannot be
resolved the stage is not launched and the task shows `unbound: <element>`.

- AC1: Every stage run references exactly one binding; the Job is rendered from the binding and nothing else.
- AC2: The v1 `unbound` elements are: `mirror-base-missing`, `mirror-stale`, `input-unverified`, `no-eligible-credential`, `image-unresolved`, `packet-too-large`, `definition-invalid`.
- AC3: The binding does not include skill versions or context recipes; those objects are not part of 1.0 (see [11-coherence.md](11-coherence.md) CF-05).

Source: DESIGN §3.7b; `ensure_base`, `vendor_inputs`, `_pick_claude_account` (the checks that exist today, in three places).

### EXE-002 — One stage, one Job, one pod
**MS3** · WP3.2 · MUST · KEEP

Each stage attempt is one Kubernetes Job with `backoffLimit: 0`, `restartPolicy: Never`,
`activeDeadlineSeconds` equal to the stage deadline, and a TTL after finish. The pod runs as a
non-root user with privilege escalation disabled.

- AC1: A Job is labelled with project, task, chain, stage and attempt; the controller can find its Jobs after a restart from labels alone.
- AC2: Kubernetes never retries a stage; retries are new attempts decided by the controller (FLW-018).

Source: `mh.py` Job render (notes: ns `muse-workloads`, `backoffLimit 0`, `ttlSecondsAfterFinished 86400`, `runAsUser 1000`).

### EXE-003 — Resource envelopes and deadlines per stage class
**MS3** · WP3.2 · MUST · KEEP

Every stage has CPU and memory requests and limits and a wall-clock deadline, all policy data.
Shipped defaults: shape 45 min, build 60 min, verify 60 min, proof 120 min; a request may raise a
deadline within 300–10,800 s. Default envelopes (request/limit): shape 0.5 CPU, 1 Gi / 1 CPU,
2 Gi; build and verify 1 CPU, 2 Gi / 1.5 CPU, 8 Gi; proof 2 CPU, 4 Gi / 4 CPU, 6 Gi.

- AC1: A stage that reaches its deadline is killed and recorded as `deadline exceeded`, distinct from a task failure.
- AC2: The agent's own timeout is the deadline minus a collection margin (default 300 s) so results are still collected.
- AC3: The estate's overrides (builds and fix rounds at 3 h) are expressed as policy, not code.

Source: `mh.py` `STAGE_DEADLINE_S`, `STAGE_RESOURCES`; driver §4 (`BUILD_DEADLINE_S`, LOOP-486 timed out three times at 1 h).

### EXE-004 — Isolated work directories
**MS3** · WP3.2 · MUST · KEEP

Each stage attempt gets its own working directory with a fresh clone. No two attempts share a
mutable directory. A later stage starts from the previous stage's recorded head, checked out
clean.

- AC1: Concurrency test: two stages of different chains on the same repo cannot observe each other's files.
- AC2: A fix round's checkout equals the head commit of the branch under review exactly (tree hash compared).

Source: DESIGN §3.7b (shared-workdir collision, 2026-09-26); `mh.py` WORKER_TEMPLATE (`MH_START_SHA`, `clean -fd`).

### EXE-005 — What a worker can reach
**MS3** · WP3.2 · MUST · KEEP

A worker pod has: its stage token (IAM-007), its model credential, read access to the mirror, and
— only when the binding grants it — a read-only, single-repo Git host token for CI evidence. It
has no Git host write, no tracker credential beyond its stage token, no Kubernetes token, and no
route to the control-plane database. Network egress is limited by a NetworkPolicy to the mirror,
the API, the model provider and declared package registries.

- AC1: A pod-level test proves `kubectl auth can-i` is denied and the API refuses every operation except the two worker operations.
- AC2: After the agent finishes, the wrapper scans the work tree and the new commits for the evidence token; a hit fails the stage and nothing is committed.
- AC3: The evidence token is revoked or expires when the stage ends.

Source: driver §5 ("Jobs never push and never reach GitHub"); `drive.py` `GITHUB_READ`; `mh.py` GH token custody (notes: leak scan, `GH_LEAK`).

### EXE-006 — The stage contract
**MS3** · WP3.2 · MUST · KEEP

The contract between Sortyard and any worker image: input is a packet and a run descriptor;
output is a result document with `execution_ok` (the worker ran), `pass` (declared checks and
verdict), check results, declared outputs, the head commit, usage, and the tail of the agent's
report. Declared checks are run by the wrapper after the agent, never self-reported.

- AC1: `execution_ok` false is an infrastructure outcome (REC-002); `execution_ok` true with `pass` false is a task outcome (REC-003). The two are never conflated.
- AC2: A verify stage with no verdict line is `pass: false` with reason `no verdict`.
- AC3: The contract is published as a JSON Schema; the conformance test that any worker image can run follows with EXT-002.

Source: `mh.py` result builder (notes: `execution_ok`, `pass`, `VERDICT:` regex on the last 2,000 chars, checks run after the agent).

### EXE-007 — Results are validated, not trusted
**MS3** · WP3.2 · MUST · KEEP

The controller rejects a result whose identity (chain, stage, attempt, Job) does not match, whose
flags contradict its observations (`pass` without `execution_ok`; approve without a verdict), or
whose fields exceed their caps. `execution_ok` also requires that Kubernetes reports the Job
succeeded.

- AC1: A table-driven test covers each contradiction and each cap.
- AC2: A rejected result is recorded as a protocol error with the offending field; the stage is an infrastructure failure.

Source: `mh.py` `_result_protocol_error` (notes).

### EXE-008 — Mirrors are first-class and their freshness is a fact
**MS3** · WP3.3 · MUST · KEEP

Workers clone only from Sortyard's read-only mirror. For every dispatch the controller records
the mirror head and its age, ensures the base commit (or PR head) is present — seeding it if
needed — and refuses to dispatch when it is still missing. Mirrors are refreshed by Sortyard, not
by a host cron.

- AC1: A base missing from the mirror is a deterministic `unbound: mirror-base-missing`, retried once after a seed, then the task parks; it is never retried as infrastructure.
- AC2: A mirror older than the freshness threshold (default 300 s) is refreshed before dispatch; the recorded fact shows before and after.
- AC3: Every refresh attempt and its last success are recorded; from MS5 the mirror mechanism is registered with a freshness window (REC-017).

Source: `MIRROR_MISS`, `ensure_base`, `seed_mirror` incident notes (CPV2-408 burned ten builds on one missing head); `mh.py` `mirror_readiness_state` (stale if > 300 s).

### EXE-009 — Mirrors and run output do not need a shared volume
**MS3** · WP3.3 · MUST · NEW

By default workers reach the mirror over the cluster network (read-only Git over HTTP,
authenticated with the stage token) and return commits to a staging namespace on the mirror
service. A shared-volume mode is an optional optimisation. No `ReadWriteMany` storage class is
required to install.

- AC1: The default chart installs and runs the demo on a kind cluster and on a three-node cluster with only `ReadWriteOnce` storage.
- AC2: A worker can push only to `refs/sortyard/stage/<stage-run-id>/*` on the mirror service; any other ref is refused.

Source: inference — today mirrors and run directories live on one PVC (`mh-work`) mounted by the tools pod and every Job, which fixes the topology to one node or RWX storage.

### EXE-010 — Workers commit; only Sortyard moves commits
**MS3** · WP3.3 · MUST · KEEP

The wrapper commits the agent's changes locally with trailers naming chain, stage and task. The
controller takes exactly the new commits (base..head) from the stage's staging ref. A stage with
no new commits is recorded as `no change`.

- AC1: Workers never push to the Git host and never open PRs (enforced by EXE-005, verified by a test that the worker image has no host credential helper configured).
- AC2: A head already delivered for this stage is never re-judged as `no change` because a later step failed (idempotent landing, MRG-002).

Source: `fetch_run_commit` (only the new commits by bundle), commit trailers `MH-Stage/MH-Item/MH-Run` (notes); driver "Recovery" (push marker).

### EXE-011 — External inputs are fetched only when marked, and verified
**MS4** · WP4.8 · MUST · KEEP

A task names external changes it builds on in `builds_on[]` (PR, commit, branch). Before
dispatch each is fetched into the mirror under a vendor ref and verified; the packet names its
commit. One that cannot be fetched or verified means the stage is not dispatched and the task
parks naming the reference. References in prose are citations: logged, never fetched, never a
stop.

- AC1: A task citing `PR #41` only in prose is dispatched normally and the log says the citation was not vendored.
- AC2: A `builds_on` entry that cannot be fetched parks the task with `not dispatched: <reference>`.
- AC3: File inputs from other tasks are passed as `(repo, commit, path)` and materialised read-only in the work directory.

Source: conductor README "Incident notes" `vendor_inputs` / `external_refs` (HARNESS-239; the 2026-11-09 false stops on evidence citations); `mh.py` attachments (notes).

### EXE-012 — Harness adapters
**MS3** · WP3.5 · MUST · KEEP

A harness is a worker image that honours the stage contract. 1.0 ships four: `scripted` (a
deterministic fake for demos, CI and the replica — MS3), `none` (runs declared commands only, for
proof/check stages — MS3), `claude-code` and `codex` (MS4, WP4.2).

- AC1: The whole product test suite runs with `scripted` and no model credential.
- AC2: (WP4.2) The same task completes with `claude-code` and with `codex` in the estate cluster.
- AC3: Adding a harness requires an image and a profile definition, no change to the controller.

Source: `mh.py` `validate_request` (harness `claude|codex|none`); AGENTS.md "pipeline purity" (fake providers in the pipeline).

### EXE-013 — Harness routing and the fallback chain are policy
**MS4** · WP4.2 · MUST · KEEP

Which harness, model and effort run each stage is policy data. Shipped estate values: build-side
stages on `claude-code`/opus with fallback to `codex`; verify-side stages on `codex` at high
effort. When no account of the first family is eligible, or a usage limit hits mid-stage, the
stage re-dispatches down the chain and the move is stamped in the stage facts.

- AC1: The stage record shows requested and actual harness and model, and `fallback_from`, `fallback_reason` when a fallback happened.
- AC2: The next stage starts again at the top of the chain.

Source: conductor README "Harness routing" (Joe, 2026-11-07); `mh.py` `_fall_back_to_next_family` (notes).

### EXE-014 — Agent CLI versions are pinned or soaked
**MS4** · WP4.2 · SHOULD · KEEP

A harness profile either pins the agent CLI version or uses a soak rule: the highest stable
version that has been public for at least N hours (default 6), resolved once and then installed
exactly. The resolved version is a binding fact.

- AC1: A release published less than N hours ago is never installed under the soak rule (clock-injected test).
- AC2: The install step can be disabled, so that an image with the CLI baked in is used unchanged (the air-gapped path, DEP-015).

Source: driver "Worker CLIs" (`MH_CLI_SOAK_HOURS`; `@openai/codex` 0.165.0 killed every worker started in a six-minute window on 2026-10-27).

### EXE-015 — Packets come from versioned templates and are recorded
**MS3** · WP3.5 · MUST · KEEP

Each stage's instructions are rendered from a versioned packet template with typed inputs (task
text as it stands now, findings, CI excerpts, checklists, input references). The rendered packet
is stored by content hash and capped at 200,000 characters. Links a worker cannot reach are
labelled as such.

- AC1: A stage run records the template id and version and the packet hash; the packet can be retrieved by an operator.
- AC2: A packet over the cap is refused as `unbound: packet-too-large` before any Job starts; grooming-class stages defer inputs instead of failing (from MS5, GRM-004).
- AC3: Packets are excluded from overview and list responses (API-011).

Source: `drive.py` `BUILD_PACKET`, `FIX_PACKET`, `REVIEW_PACKET`, `CONFLICT`; `mh.py` `MAX_PACKET_CHARS` (notes); `pr_body` incident note.

### EXE-016 — Containers inside a stage are opt-in
**MS4** · WP4.2 · SHOULD · KEEP

A project may enable a Docker sidecar for its build/verify/proof stages. It is off by default
because it needs a privileged container; enabling it is an audited project setting and is shown
on the binding.

- AC1: With the setting off, no privileged container exists in any worker pod (admission test).
- AC2: With it on, the sidecar has its own resource limits counted in the envelope.

Source: `mh.py` dind sidecar (notes: privileged, `docker:27-dind`, own limits).

### EXE-017 — Deterministic check stages with receipts
**MS3** · WP3.4 · MUST · KEEP

A `none`-harness stage runs declared commands against an exact `(base, candidate)` pair and
produces a receipt bound to both commits. A receipt whose commits differ from the request is
rejected. This is the merge proof for Git hosts without CI (MRG-011).

- AC1: A receipt for another candidate cannot be used to land this one (negative test).
- AC2: `unavailable` (the check could not run) is not a verdict: the stage is an infrastructure failure, never a pass or a fail.

Source: `mh.py` proof receipts (notes: `candidateCommit`/`baseCommit` must equal the request's; `unavailable` ⇒ not `execution_ok`); `ship.py` fence (DESIGN §3.7a).

### EXE-018 — Usage is captured per stage
**MS3** · WP3.5 · MUST · KEEP

Each stage records wall time, input/output/cache tokens, turns, the model actually used and the
credential identity (an id, never a secret).

- AC1: Usage fields are present for every finished stage or explicitly `unknown` with a reason.
- AC2: Usage is recorded for failed and cancelled attempts as well as passed ones, so that the delivery-cost metrics (OBS-006) need no other source.

Source: `mh.py` result builder and ledger row (notes: usage, `model_actual`, `account_id`); k3s `docs/usage-accounting.md`.

### EXE-019 — Agent traces are stored and viewable
**MS6** · WP6.3 · SHOULD · KEEP

The agent's event stream is captured per stage, redacted, stored as a blob with a retention
policy, and served to the trace viewer (UI-011). Capture failure is recorded as `missing`, never
silently absent.

- AC1: A multi-megabyte trace can be paged and searched without loading it whole.
- AC2: Secrets matching the redaction rules never appear in a stored trace (seeded-secret test).

Source: `mh_trajectories` (status `captured|missing|error`, notes); harness-console J3; TRAJECTORY-CAPTURE-DESIGN.md.

### EXE-020 — The control plane is protected from its workers
**MS3** · WP3.2 · MUST · NEW

Workers run in their own namespace with a ResourceQuota and LimitRange sized from the caps. The
control-plane pods have resource requests and, where the installer allows cluster-scoped objects,
a higher PriorityClass. A runaway worker can fail its own stage; it cannot evict the control
plane.

- AC1: Load test: workers pinned at their limits do not push control-plane API p95 latency past 1 s.
- AC2: The chart works without the PriorityClass (namespace-admin install, DEP-002) and says which protection is then missing.

Source: DESIGN §3.7b honesty note ("today it runs with only small requests and no PriorityClass/ResourceQuota protection").

### EXE-021 — Interrupted stages are reconciled, not lost
**MS3** · WP3.2 · MUST · KEEP

After a controller restart every non-terminal stage is reconciled against the cluster: a Job
that finished is collected; a Job still running is watched; a stage recorded as launching with no
Job is launched once.

- AC1: Kill the controller at each step of launch and collect: no stage is launched twice, none is left non-terminal without a Job (fault-injection matrix).
- AC2: A lost pod is an infrastructure failure with reason `pod lost`.

Source: `mh.py` `recover_interrupted`, `_drive_task_guarded` reconcile branch.

### EXE-022 — A running stage can be cancelled
**MS3** · WP3.2 · MUST · FIX

An operator can cancel a queued or running stage, or a whole chain. Cancel deletes the Job,
records `operator-cancelled`, frees the slot, and leaves the PR (if any) as chosen in the action:
left open or closed.

- AC1: Cancelling a running stage ends its pod within 60 s and no result from it is accepted afterwards (fenced by epoch).
- AC2: The confirm dialog and the CLI state the effect before acting.

Source: driver §5 ("A running task can't be cancelled"); driver §7 ("Stop an item mid-flight: Not supported yet").

---

## CRD — credentials

### CRD-001 — Custody classes
**MS4** · WP4.3 · MUST · KEEP

Every credential has a custody class with its own rules: `secret-ref` (a reference to a
Kubernetes Secret, optionally fed by an external secrets operator), `cli-owned` (subscription
credentials the agent CLI refreshes and writes back, kept as files on a dedicated volume), and
`minted` (short-lived tokens Sortyard mints per use, such as Git host installation tokens).
Domain objects hold references and state, never values.

- AC1: No API response, log line, event or trace contains a credential value (seeded-secret scan in CI).
- AC2: Each credential shows its class, health, last use and which stage runs consumed it.

Source: DESIGN §3.7a (CredentialCustody; subscription credentials deliberately not in the secrets store); driver §5 ("Never print, copy or move credential contents").

### CRD-002 — API-key model credentials are the default path
**MS4** · WP4.3 · MUST · NEW

A fresh install can run real agents with one model API key supplied as a Secret reference. The
subscription pool and the broker are optional.

- AC1: The quickstart for real agents needs exactly one Secret and one harness profile.
- AC2: When both an API key and pool accounts exist, policy says which a stage uses; the worker never sees both.

Source: DESIGN §8 Phase 6 ("the system installs and runs on API-key credentials alone"); `mh.py` WORKER_TEMPLATE unsets API keys today (subscription only), so this path is new.

### CRD-003 — Subscription account pool
**MS4** · WP4.3 · MUST · KEEP

Pool accounts are selected per stage: eligible accounts exclude, in order, operator-disabled,
excluded after a usage-limit failure for this task, cooling, quarantined, and those without a
valid token. Among eligible accounts: operator priority first, the previous stage's account if
still eligible, otherwise the unleased account with the least usage in the last five hours. A
usage limit cools the account until the reset time the CLI states (default five hours) and
re-queues the stage at most three times.

- AC1: The stage record names the account id, the selection reason and the alternatives rejected with their blocker.
- AC2: The pool selects and isolates failures; it is not a concurrency limiter. Concurrency is bounded only by the caps (SCH-007).
- AC3: Window, cooling time and requeue limit are policy data.

Source: `mh.py` pool (notes: `POOL_USAGE_WINDOW_S` 5 h, `POOL_COOLING_S` 5 h, `POOL_MAX_LIMIT_REQUEUES` 3, blocker order, sticky account, least-burned sort).

### CRD-004 — Pool health: quarantine and probes
**MS4** · WP4.3 · SHOULD · KEEP

An authentication failure quarantines the account. A small probe Job checks a quarantined account
at most every 15 minutes; recovery is recorded only when the probe succeeded against the same
credential generation and quarantine generation it started with. Viewing status never triggers a
paid probe.

- AC1: Replacing the credential files changes the generation and makes the next probe eligible immediately.
- AC2: A probe that started before a re-authentication cannot clear the new quarantine state.

Source: `mh.py` pool probes (notes: `POOL_PROBE_INTERVAL_S` 15 min, `POOL_PROBE_DEADLINE_S` 900, generation checks); harness-console J4 ("never triggers paid probes just by viewing status").

### CRD-005 — Broker flows for subscription sign-in
**MS4** · WP4.3 · SHOULD · KEEP

The operator adds or re-authenticates a pool account from the console: browser OAuth,
setup-token, paste-token, device code. The flow is a server-side state machine that survives
page refresh and navigation, shows progress, retries transient poll errors, and can be
cancelled.

- AC1: Reloading the page mid-flow resumes the same flow instead of failing with a conflict.
- AC2: Every flow ends in one of `connected`, `cancelled`, `failed (reason)`; none is left dangling after its timeout.

Source: harness-console J4 and VISION ("sign-in flows wipe themselves"); driver §5 (`/api/auth/claude/{start,submit,paste-token,probe,qualify}`).

### CRD-006 — One refresher per rotating credential
**MS4** · WP4.3 · SHOULD · KEEP

Credentials whose refresh token rotates are refreshed by exactly one keeper, ahead of the point
where a worker's CLI would refresh, under a lock. Worker copies are synchronised from the broker
copy and a newer worker-refreshed credential is never overwritten by an older broker copy.

- AC1: With N concurrent stages on one rotating credential, zero refreshes happen inside workers (asserted from keeper logs in a fixture).
- AC2: Keeper failure sets the credential state to `refresh-failed` with the provider's error code only; the state clears on the next successful sign-in.

Source: driver §5 Codex keeper (k3s-harness #201; the 2026-11-01 sign-out attributed, as inference, to concurrent Jobs spending one rotating refresh token); `cred_sync` compare rule (notes).

### CRD-007 — Git host credential: least privilege, minted, integrator-only
**MS4** · WP4.1 · MUST · FIX

The Git host write credential is used only by the integrator component. The preferred form is a
GitHub App whose installation tokens are minted per operation with the narrowest permissions; a
personal token is supported and flagged as weaker. Where the credential lives is an owner
decision (OD-6).

- AC1: Only the integrator pod mounts the App key or token; API and controller pods do not (manifest test).
- AC2: The App's required permissions are listed in the docs and verified at onboarding; a missing permission degrades by name (for example "cannot cancel superseded runs: Actions write missing").
- AC3: Token expiry is surfaced ahead of time on the credentials screen (UI-012) and, from MS5, as an attention item (OBS-014).

Source: driver §5 (the Git write credential in the cluster is the owner's personal token, with an expiry date; an App credential takes precedence if one is added); 2026-11-04 release note (`actions: write` needed for `cancel_pr_runs`).

### CRD-008 — Quota awareness
**MS5** · WP5.6 · SHOULD · KEEP

For each credential with a rate limit Sortyard keeps recent readings, computes the burn rate
inside the reset window, and raises one urgent `QUOTA <credential>` condition when remaining
drops below 20% or the projection reaches zero before the reset. The condition lists every
mechanism sharing the bucket.

- AC1: A fixture where the bucket burns to zero before reset raises the condition while remaining is still above zero.
- AC2: A credential with no reading inside its window is reported `stale`, not healthy.

Source: MECHANISMS.md (QUOTA items, `quota-reading-<holder>`, fixtures 6 and 9).

### CRD-009 — Operator account order and task-level selection
**MS4** · WP4.3 · SHOULD · KEEP

Account priority is data the operator sets per account. A task may carry a selection override:
prefer an account or family, optionally "wait for it", and a selection priority that wins a
contended account.

- AC1: No account identity appears in code; a new account slots in by its priority.
- AC2: The override is a typed task field (TRK-002 `select`) and its effect is recorded in stage facts.

Source: conductor README "Harness routing" (`Select:` line, `select_priority`, account `priority` in `mh_account_state`).

### CRD-010 — Redaction everywhere
**MS3** · WP3.5 · MUST · KEEP

Known secret values and secret-shaped strings are redacted from stage results, traces, logs,
packets, notes written by the system, and audit entries before they are stored.

- AC1: CI runs a seeded-secret test through a full chain and greps every store and log for the seed.
- AC2: The worker's evidence token is redacted from its own output before collection.

Source: `runtime.redact`; FACTORY-DASHBOARD-DESIGN "Source model and invariants" (no packet, prompt, tokens or secrets in read APIs); harness-console decided D10.
