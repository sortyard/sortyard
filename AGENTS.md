# AGENTS.md — Sortyard repo brief

> **Governing scope: [SY-DEC-005](DECISIONS.md#sy-dec-005) (2026-11-23 amendment).** Sortyard is
> the workflow kernel plus the tracker view of company/HARNESS-V3.md. The core stores to
> Postgres only; SY-DEC-004 (Appwrite) no longer applies to it. A durable workflow engine is
> used behind one module, not hand-written. Delivery-plan increments MS1, MS2 and MS6 are
> deferred until the kernel runs one lane. Read that record before any kernel task.

Read this file first. It is meant to be enough, together with the code it points at, for an
agent or a new contributor to make a first change without anyone briefing them. If something
here is wrong or missing, that is a bug: fix it in the same change, or file it (see
[Known gaps](#known-gaps)).

## Requirements reference

The [ecosystem requirements baseline](docs/requirements/README.md), its catalog and its
delivery plan are reference: they keep requirement IDs, acceptance and provenance, but they do
not set the build order, and where they conflict with SY-DEC-005 the decision record wins.
Planned contracts under `docs/requirements/contracts/` are distinct from the implemented
`spec/` contract.

## What this is

Sortyard is a source-available delivery harness: a conductor, a control plane and a task manager,
deployed with one Helm chart. The operator gets a UI for everything and agents get APIs for
everything. The repo is at the **Phase 1 skeleton** stage:

- the six services exist as console scripts of one Python package;
- the API answers `/healthz`, `/readyz` and `/v1/info`, and serves the Phase 1 REST surface
  of `spec/openapi.json` behind bearer tokens and the §7 permission matrix;
- the chart installs the API, Postgres and a schema migration Job, and can add the conductor
  in **shadow mode** (it reads the production conductor's inputs read-only and records what it
  would claim), the workflow engine server on Postgres (`engine.enabled`) and the **kernel
  service** that takes an item from admitted to merged (`kernel.enabled`).

Stack (decided, `DECISIONS.md` SY-DEC-001): Python 3.11+ backend, one package. TypeScript +
React console (not started). Postgres only. Models generated from the JSON Schemas in
`spec/`. Helm.

## Architecture map

How it fits together. Arrows show who calls whom.

```
operator / agents ──HTTP──▶ sortyard-api ──▶ Postgres (schema "sortyard": §3 tables + event ledger)
                                                ▲
                     migration Job (migrate.sh) ┘   applies charts/sortyard/migrations/*.sql
                                                ▲
sortyard-conductor --shadow ──GET only──▶ Plane / pass feed / lane registry (outside providers)
           └──writes DecisionLog + ledger events─┘

With kernel.enabled (it needs engine.enabled):

operator ──admitItem──▶ sortyard-api ──starts the item's workflow──▶ engine server (Temporal)
                             │ (lane files mounted)                    ▲      └─▶ Postgres
                             ▼                                         │ worker + signals
                         Postgres ◀──items, runs, stays── sortyard-kernel ──▶ GitHub (App tokens,
                                                              │                pull requests, merge)
                                       Role in the worker     └─▶ Kubernetes API: one worker Job per
                                       namespace, or a Secret     dispatch (clone, agent, push)
                                       for another cluster
```

Services. Each one is a console script in `pyproject.toml` and a module in
`src/sortyard/services/`. All of them ship in one image (`Dockerfile`); the Deployment's
`command` picks which one runs.

| Console script | Module | State today | Deployed by the chart |
|---|---|---|---|
| `sortyard-api` | `src/sortyard/services/api.py` | health, readiness (Postgres reachable), info, and the Phase 1 REST surface (`src/sortyard/api/`) | always (`charts/sortyard/templates/api.yaml`) |
| `sortyard-conductor` | `src/sortyard/services/conductor.py` | `--shadow` works; without it, a stub | `shadow.enabled=true` (`charts/sortyard/templates/shadow-conductor.yaml`) |
| `sortyard-context-assembler` | `src/sortyard/services/context_assembler.py` | stub | no |
| `sortyard-eval-runner` | `src/sortyard/services/eval_runner.py` | stub | no |
| `sortyard-sensor-runner` | `src/sortyard/services/sensor_runner.py` | stub | no |
| `sortyard-integrator` | `src/sortyard/services/integrator.py` | stub | no |
| `sortyard-kernel` | `src/sortyard/services/kernel.py` | the kernel service (SY-V3-LANE-RUNTIME): the engine worker with every owner of the shipped state table registered, and the observer loop. Reads its settings from the environment and mounted files and exits 2 naming any required one that is missing | `kernel.enabled=true` (`charts/sortyard/templates/kernel.yaml`; needs `engine.enabled=true`) |
| `sortyard-worker` | `src/sortyard/services/worker.py` | not a service: what the three containers of a worker Job run. `clone` (holds the token) clones the item's repository; `agent` (no token, no secret volume) runs the configured agent command; `push` (holds the token) pushes `sortyard/<item id>` from a clone the agent never touched, or reads the review verdict, and reports one result as its termination message | no (the worker launcher creates its Jobs, in the lane's worker image: the Sortyard image, which has `sortyard-worker` and `git`, plus the lane's agent; README "Worker image") |

The stubs share `src/sortyard/services/_stub.py`. The registry of all six is
`src/sortyard/services/__init__.py` (`SERVICES`).

Packages and directories:

| Path | What lives there |
|---|---|
| `src/sortyard/` | The one Python package (`__version__` in `src/sortyard/__init__.py`). |
| `src/sortyard/services/` | The six services (table above). |
| `src/sortyard/api/` | The API service's REST surface (§4, §7). `permissions.py` is the §7 permission matrix in code (`OPERATIONS`, held to the spec's `x-sortyard-roles` by `tests/test_api_contract.py`). `auth.py` holds bearer tokens: service-account issuance (refusing any token set that could both create and claim tasks) and operator tokens. `routing.py` routes, authenticates and authorizes before any read. `handlers.py` has one function per operation. `store.py` is the Postgres access, with the AuditLog and ledger writes every mutation makes. |
| `src/sortyard/engine/` | The durable workflow engine boundary (HARNESS-V3 §3.1): start a workflow, a durable timer, a signal from outside, a retried and recorded step. The **only** package that imports the engine SDK (Temporal; `tests/test_engine_boundary.py` holds this). `testing.py` starts a real engine server for tests. Why Temporal, the versions and the failure-test results: `docs/decisions/workflow-engine.md`. |
| `src/sortyard/kernel/` | The workflow kernel (HARNESS-V3 §3.1). `item_states.toml` is the item state table: every state names its owner, limit, default and reason, and adding a state is a change to that file only. `states.py` loads it and refuses a state that could stall (a missing field, a blocked state, no exit). `item.py` is the one generic workflow that runs the table on `sortyard.engine`: it records each transition, calls the owner step, starts the limit as a durable timer and applies the declared default when the limit passes; a decision always answers in the same pass. Nothing an owner or a signal sends can stop an item: what is not understood counts as no reply, and the limit still applies. |
| `src/sortyard/kernel/ledger.py` | The kernel's projection in Postgres (HARNESS-V3 §3.2; migration `0003_kernel_items.sql`): items, runs and links, each row carrying the tenant (`workspace_id`), beside the event ledger. `Ledger.record` is the item workflow's record step: one database call writes the item row, its run rows and one ledger Event together. `queue` and `timeline` are the tracker view's two reads (`getProjectQueue`, `getItemTimeline`). Nothing writes item state any other way: the database refuses a direct update, and `requestItemChange` sends the workflow a signal instead. |
| `src/sortyard/kernel/preflight.py` | Capabilities and preflight. `capabilities.py` loads a lane capability file (HARNESS-V3 §3.3; format shown by `lane_example.toml`): worker and CI image by digest, repositories, secrets, services, runner pool and the resolver of a failed need. It refuses a worker image digest that differs from the CI image digest, a secret marked optional, and a task need the lane does not declare. `preflight.py` is the `capability-checker` and `need` owners (`Preflight`): one probe per need through the `Probe` interface, each result recorded; a failed probe dispatches no build, opens or joins the one open capability-gap item for that need (`GapRegistry`), and `close_gap` sends every linked item back to preflight. Real probes (GitHub, secret store, cluster) are adapters outside the kernel. |
| `src/sortyard/kernel/admission.py`, `scheduler.py`, `observer.py`, `store.py`, `policy.py` | The lane runtime's kernel side (SY-V3-LANE-RUNTIME; migration `0004_lane_runtime.sql`). `admission.py` checks an item (outcome, a named acceptance test, lane, declared needs, resolving links, risk tier) and writes the item, its links and its spec, or nothing; the API's `admitItem` calls it and starts the workflow in the same transaction. `scheduler.py` is the owner of `admitted`: an item is dispatched when its blockers are merged and its lane (`slots` in the capability file) has a free slot, the grant being a row written under a lane lock. `store.py` reads specs and the open stays (dispatch number, action, detail on `item_run`) and is the Postgres `GapRegistry` and probe-result sink. `observer.py` is the polling loop: each pass asks every open stay's owner for an outcome and sends it with the stay's dispatch number; it holds no state. `policy.py` loads the decision policy (`decision_policy.toml`, shipped with no rules) that the decision step consults. |
| `src/sortyard/lane/runtime.py` | Puts a lane together (`build`): every owner of the shipped table on one database, GitHub port and jobs port, the looks the observer uses, and opening an item's pull request once its build is observed. |
| `src/sortyard/lane/` | Lane adapters: the ports a lane's work runs on (HARNESS-V3 §3.1, §3.3). `github.py` is the GitHub port (`GitHub`, a Protocol; `HttpGitHub`, the real client as a GitHub App) and what runs on it: `CiAdapter` (owner `ci-adapter` of `checking`), `MergeAdapter` (owner `merge-adapter` of `merging`) and `RepositoryProbe` (the preflight probe of a `repository` need). There is no webhook receiver: an owner answers at once when GitHub already knows, else leaves the stay open, and `observe` is the same look for a poller. Merging never waits on what cannot clear by itself: a branch behind its base is updated at once, merges of the base on top of the reviewed commit need no new review, any other new commit answers `moved` (back to `checking`), and what only a change to the pull request can clear answers `conflict` with a stable finding. The pull request of an item is found by its branch, `sortyard/<item id>`. Tests run the real client against `tests/fake_github.py` over HTTP; the fake and the client are held to GitHub's published API description, vendored in `tests/contracts/github/` (`tests/test_github_contract.py`). |
| `src/sortyard/lane/jobs.py`, `src/sortyard/lane/worker.py` | The worker launcher. `jobs.py` is the jobs port (`Jobs`) and its Kubernetes client on the standard library (`KubeJobs`): launch a Job with its brief (a ConfigMap) and its per-job secret, read its phase and termination message, refresh the secret's token, delete a Job with what it created, and delete an item's earlier dispatches by label. `worker.py` is the `executor` and `reviewer` owners (`Launcher`): one Job per dispatch under a name derived from tenant, item and dispatch, so a repeated call launches none and nothing is kept in memory; a launch first deletes the item's earlier Jobs; the Job's deadline is the stay's limit (`limit_seconds` of the owner call). `Launcher.observe` turns a finished Job into the state's outcome, replaces an ageing token while the Job runs and deletes the per-job secret when it ends; `probes` gives the preflight its `secret`, `service` and `worker-image` probes. The fake Kubernetes API server for tests is `tests/fake_jobs.py`, held to the OpenAPI fragment in `tests/contracts/kubernetes/`. |
| `src/sortyard/shadow/` | The shadow conductor. `sources.py` holds the read-only input adapters (`SnapshotSource`, `PlaneSource`; every HTTP call goes through `ReadOnlyHttp`, which allows GET only). `board.py` holds the queue snapshot model. `evaluate.py` holds the claim decision, a pure function. `ledger.py` writes the DecisionLog. |
| `src/sortyard/models/` | The §3 domain models. `_generated.py` is generated by `codegen.py` from `spec/*.schema.json`; **never edit it by hand**. `_runtime.py` is the base `Model` (`from_dict`/`to_dict`). |
| `spec/` | The frozen contract: one JSON Schema per §3 object, plus `spec/openapi.json`. Their tests are `spec/test_schemas.py` and `spec/test_openapi.py`. Conventions are in `spec/NOTES.md`; the §7 permission matrix, summarised, is `spec/PERMISSIONS.md`. |
| `charts/sortyard/` | The Helm chart. It has **one** values file, `charts/sortyard/values.yaml`. Templates: API, Postgres (StatefulSet + Secret), the migration Job, the shadow conductor, and with `engine.enabled=true` the workflow engine server on Postgres (`charts/sortyard/templates/engine.yaml`: Deployment, Service and a schema Job running `charts/sortyard/engine/setup.sh`). `replica/engine_server.py` runs that rendered server with docker for `tests/test_engine_server.py` (the four failure tests against the server on Postgres; skipped unless `SORTYARD_ENGINE_SERVER_TARGET` is set, required in `slow.yml`). With `kernel.enabled=true` (which needs the engine) `charts/sortyard/templates/kernel.yaml` adds the kernel service: one Deployment (one replica; its init container runs `charts/sortyard/kernel/wait_engine.py` until the engine answers), its ServiceAccount, two ConfigMaps of files rendered from values (the lane capability files, which the API mounts too, and the worker configuration and decision policy), and a Role and RoleBinding in the worker namespace that grant exactly what the jobs port calls (`tests/test_chart.py` runs the port against the fake API server and compares). With `kernel.workers.sameCluster=false` the worker Jobs run in another cluster, reached through a Secret (`server`, `token`, `ca.crt`), and no Role is rendered. Every credential is a required Secret reference: the render fails without it. |
| `charts/sortyard/migrations/` | Numbered SQL migrations plus `migrate.sh`, their runner (the Job's command, and what the tests run). |
| `replica/` | The one-command local replica (see [Local replica](#local-replica)): `replica/replica.sh`, the kind config, replica values, and fake outside providers in `replica/fakes/` (Plane and the pass log: `replica/fakes.yaml`; GitHub's API and git hosting: `replica/fakes/fake_github_host.py`, `replica/fake-github.yaml`). For the kernel: the lane capability file `replica/lane.toml`, the worker image `replica/worker/` (the Sortyard image plus a scripted agent) and `replica/admit.py`, which admits an item through the API from inside the API pod. |
| `tests/` | Tests for the package, chart, CI, replica, docs and this brief. `tests/pg.py` gives tests a throwaway Postgres. |
| `docs/` | Reports and findings. `docs/goldfish/` holds zero-context install runs; `docs/findings/` holds friction found building the repo itself. |
| `.github/` | CI. `.github/workflows/ci.yml` runs one job, `test`, on every pull request to main and every push to main: lint, typecheck, tests (with a real Postgres and helm), spec tests, chart lint/render and the image build. `.github/workflows/slow.yml` boots the replica nightly and on demand, outside the merge gate. |
| `DESIGN.md`, `DECISIONS.md`, `MILESTONES.md`, `CORPUS.md` | The design record: architecture (§4), stack decision, the phase plan, and the milestone corpus (M1.x items). Read the relevant section before changing behaviour. |

Data flow worth knowing before you touch it:

- **Schema first.** To change a domain object, edit `spec/<object>.schema.json`, run
  `python -m sortyard.models.codegen`, and commit both files. CI fails on drift.
- **Database.** Every §3 object has a table in schema `sortyard`. Its `doc` JSONB column holds
  the object exactly as the schema defines it; the other columns are generated from `doc`.
  `sortyard.event`, `sortyard.decision_log` and the audit log are append-only: the database
  refuses UPDATE/DELETE/TRUNCATE. Append through `SELECT sortyard.append_event(doc)`.
- **Migrations are immutable once released.** Add `charts/sortyard/migrations/NNNN_name.sql`.
  Never edit an applied file: `migrate.sh` refuses one whose sha256 changed.
- **The shadow never writes outside its own database.** It holds no write credential and no
  Kubernetes token. Keep it that way: tests assert GET-only.

## Build loop

Python 3.11+. These are the commands CI runs, in its order:

```sh
python3 -m venv .venv && . .venv/bin/activate   # "ensurepip is not available"? see below
pip install -e '.[dev]'
python -m sortyard.models.codegen --check       # generated models match spec/
ruff check . && ruff format --check .           # lint + format (line length 100)
mypy                                            # strict: src/, tests/, replica/, the chart's kernel script
pytest tests                                    # chart/replica-render tests need helm; DB tests need Postgres
```

If the host Python has no `venv`/`pip` (Debian/Ubuntu without `python3-venv`):
`python3 -m venv --without-pip .venv && . .venv/bin/activate && curl -fsSL https://bootstrap.pypa.io/get-pip.py | python`.

Engine tests (`tests/test_engine_failure.py`) run a real engine server as a child process and
need no cluster. The server binaries are not Python packages: the SDK downloads them on first
use from `temporal.download` and caches them in the system temporary directory
(`docs/decisions/workflow-engine.md`). Without that reach the engine tests fail; they do not skip.

The worker tests (`tests/test_worker_entry.py`, `tests/test_lane_worker.py`) run `git` against
repositories they create on disk; they need `git` on PATH and no network.

Database tests (`tests/test_migrations.py`, parts of `tests/test_shadow.py`) are skipped unless
`psql` is on PATH and `PGHOST` points at a Postgres where you may create databases. Each run
creates and drops its own database. They need a host `psql` client (`postgresql-client` on
Debian/Ubuntu, `libpq` on Homebrew):

```sh
docker run -d --name sortyard-pg -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16-alpine
PGHOST=localhost PGUSER=postgres PGPASSWORD=pw pytest tests
```

CI sets `SORTYARD_REQUIRE_HELM=1` and `SORTYARD_REQUIRE_POSTGRES=1`. With those set, a
missing tool fails the run instead of skipping tests. Set them locally to get CI's behaviour.

`pytest spec` runs the Phase 0 seed tests; CI gates on it.

The one required status check on `main` is `test` (the one job in `ci.yml`), strict: a pull
request must be up to date with `main` before it merges (policies/placement-defaults.yaml#gates).
`main` runs no other job, so everything it runs is proven on the pull request first. Keep
`ci.yml` to that one job; put a slow suite in `slow.yml` (nightly and on demand) instead.
`tests/test_ci.py` holds this.

## Local replica

One command boots the deployment's shape on a throwaway kind cluster:

```sh
./replica/replica.sh up        # a few minutes cold (it pulls the engine images), less on re-run
```

It needs Docker, kind, kubectl, helm and curl. Tested with kind v0.25.0, kubectl v1.31.4 and
helm v3.16.3. `./replica/replica.sh check` lists anything missing or too old, with install
links, and changes nothing. Then `up`:

1. creates the kind cluster `sortyard` from `replica/kind.yaml` (the node image is pinned by
   digest);
2. builds the one image and tags it by content, so a re-run rolls out your change, and the
   replica's worker image on top of it (`replica/worker/`: the image plus a scripted agent),
   and loads both; the lane file names the worker image by the digest the node holds it under;
3. deploys the **fake outside providers** from `replica/fakes.yaml`:
   `replica/fakes/fake_plane.py` serves Plane's REST API and the production conductor's pass
   log from `replica/fakes/fixtures.json`. It also adds the lane registry ConfigMap and a
   random read-only Plane API key Secret, which the fake enforces;
   and **GitHub**, from `replica/fake-github.yaml`: `replica/fakes/fake_github_host.py` serves
   GitHub's REST API with the tests' strict fake (`tests/fake_github.py`) and git over HTTP
   on a bare repository, behind a GitHub App key Secret made for the cluster;
4. installs **`charts/sortyard` itself**, with `replica/values.yaml` layered on top. That file
   only enables the shadow (pointed at the fakes), the engine and the kernel (pointed at the
   fake GitHub, with the scripted agent's commands) and shrinks the volume. Topology, Services,
   Secrets and the kernel's Role are the chart's own;
5. smoke-tests the result: `/healthz`, `/readyz` and `/v1/info` through the API Service;
   migrations recorded; the engine answers; the shadow records both fixture passes in the
   DecisionLog; the fake saw zero writes and zero unauthenticated reads;
6. runs the **lane**: admits an item through the API and waits until it is merged, in Sortyard
   and as a pull request on the fake GitHub of the commit a real worker Job pushed; then admits
   a second item, deletes the kernel pod while its build Job runs, and waits until that one is
   merged too.

Other commands:

```sh
./replica/replica.sh smoke     # re-run the smoke test
./replica/replica.sh lane      # run the lane again: two more items, one kernel pod deleted
./replica/replica.sh forward   # API on http://localhost:8080 (foreground: use a second terminal)
./replica/replica.sh logs api  # follow a component (default: shadow-conductor)
./replica/replica.sh status    # pods, jobs, Helm release
./replica/replica.sh down      # delete the cluster
```

The Helm NOTES printed during `up` show bare `kubectl` commands; with the replica, add
`--context kind-sortyard` (or use the subcommands above). `down` keeps the built images
(`docker image prune` / `docker rmi` to reclaim them). Every kubectl and helm call is pinned to the `kind-sortyard` context, so the script never acts
on your current kube-context. `SORTYARD_REPLICA_CLUSTER`, `SORTYARD_REPLICA_NAMESPACE` and
`SORTYARD_REPLICA_TIMEOUT` override the defaults. Database shell:
`kubectl --context kind-sortyard -n sortyard exec -it statefulset/sortyard-postgres -- psql -U sortyard sortyard`.

The replica follows the chart. When the chart gains a component, the replica gets it for
free. When a component gains a new **outside** dependency (a git host, model provider or
object store), add a fake for it under `replica/fakes/` and wire it in
`replica/fakes.yaml`. Never stub out Sortyard's own components.

## Making a change

1. Find the owning module in the [Architecture map](#architecture-map), and the design section
   it implements (the module docstrings cite `§n`).
2. **Write the failing test first** in `tests/test_<area>.py`. Tests are acceptance-style:
   each file's docstring states the acceptance it holds. Look at the neighbours before adding
   one.
3. Make it pass. Run the [Build loop](#build-loop). If you touched the chart, a service, the
   Dockerfile or the migrations, also run `./replica/replica.sh up`.
4. Update the docs the change makes wrong: `README.md`, this file, and the chart's
   `values.yaml` comments. `tests/test_readme.py` and `tests/test_agents_md.py` check parts of
   them.

Worked example (a first change): make `/v1/info` report something new.

- Test: add an assertion in `tests/test_api.py`, which starts the server on a free port.
- Code: `Handler.do_GET` in `src/sortyard/services/api.py`.
- Check: `pytest tests/test_api.py`, then `./replica/replica.sh up`. Run
  `./replica/replica.sh forward` in a second terminal and `curl localhost:8080/v1/info`.

## Conventions

- **Typing.** Strict mypy. `from __future__ import annotations` at the top of every module with code.
  No `Any` where a real type is known.
- **Style.** ruff (rules E, F, W, I, B, UP, SIM, RUF), line length 100, formatted by
  `ruff format`. Module docstrings explain *why*, and cite the design section.
- **Dependencies.** Runtime: `psycopg[binary]`, `jsonschema`, and `temporalio` (imported only
  by `src/sortyard/engine/`). `cryptography` signs the GitHub App token and is imported only by
  `src/sortyard/lane/github.py` (SY-DEC-008). Dev extras: `pyproject.toml`. Don't add
  one without a reason the change needs.
- **Configuration.** Services read `SORTYARD_*` environment variables (documented in each
  service's docstring). The chart is the only place they are set in a deployment, from the one
  `charts/sortyard/values.yaml`. A second values file in the chart is refused by a test.
- **Generated code.** `src/sortyard/models/_generated.py` comes only from `codegen.py`.
- **Security posture.** Read-only adapters, least privilege (`runAsNonRoot`, read-only root
  filesystem, dropped capabilities, no service-account token unless needed). Secrets come in by
  `secretKeyRef`, never as values in a template.
- **Commits/PRs.** One task per change. Leave unrelated cleanups for their own change.

## Known gaps

Read these before you trust a green run.

- `/readyz` checks that a Postgres answers, not that the API can log in (goldfish GF1-07).
- Operator tokens are an interim credential (`sortyard-api --issue-operator-token`) until
  OIDC sessions land.
- The chart deploys the API, the shadow conductor, the engine server and the kernel service.
  The four other services are stubs with no Deployment.
- The kernel's Role cannot limit a Secret read to metadata, which is all the jobs port asks
  for: Kubernetes RBAC grants `get` on a Secret whole. It is limited to the worker namespace.
- A worker cluster other than the release's is reached with a `server`/`token`/`ca.crt` Secret,
  not a kubeconfig file: the kernel service reads those three settings and no kubeconfig.
- The replica's fake GitHub records a merge without moving the git repository's base branch,
  so every replica item builds on the seed commit; and the replica's lane runs no checks
  (`checks = []`), so `checking` passes at once there. Fix and red-check paths are covered by
  `tests/test_lane_runtime.py`, not by the replica.
- Friction found building the replica and this brief:
  `docs/findings/contributor-foundation.md`. The goldfish install run:
  `docs/goldfish/phase-1-install-smoke.md`.
