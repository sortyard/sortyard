# Sortyard

> **Governing scope: [SY-DEC-005](DECISIONS.md#sy-dec-005) (2026-11-23 amendment).** Sortyard is
> the workflow kernel plus the tracker view of company/HARNESS-V3.md, stored to Postgres only
> (SY-DEC-004 no longer applies to the core), with a durable workflow engine behind one module.
> Delivery-plan increments MS1, MS2 and MS6 are deferred until the kernel runs one lane.

Sortyard is a source-available delivery harness — conductor, control plane and task manager —
deployed with one Helm chart, with a UI for everything for the operator and APIs for everything
for agents. The design record is [`DESIGN.md`](DESIGN.md) (architecture: §4); the stack is
decided in [`DECISIONS.md`](DECISIONS.md) (SY-DEC-001); the frozen domain model and API
contract are in [`spec/`](spec/).

This repository is at **Phase 1**: the six services exist as entry points, the API service
serves the Phase 1 REST surface of the OpenAPI spec behind service-account tokens and the §7
permission matrix (below), the chart installs the API plus Postgres with the §3 domain schema
and the event ledger migrated in, and the conductor can run in shadow mode (below) — observing
the production conductor's input path and logging what it would claim.

Contributors and agents: start with [`AGENTS.md`](AGENTS.md), the repo brief (architecture
map, build loop, conventions, known gaps).

The [ecosystem requirements baseline](docs/requirements/README.md) is kept as reference: it
holds requirement IDs, acceptance and provenance, not the build order, which SY-DEC-005 sets.
Its contracts describe planned capabilities; the code and runbooks below describe the
existing Postgres implementation.

## Quickstart — a running, empty Sortyard on a local cluster

**One command:** `./replica/replica.sh up` checks the tools listed below (and their
versions), then does all of the following on a kind cluster. It also adds the shadow
conductor, reading fake outside providers (Plane, the production pass log), and smoke-tests
the result.
`./replica/replica.sh down` removes it. Details are in [`AGENTS.md`](AGENTS.md#local-replica).
The manual steps:

You need [Docker](https://docs.docker.com/get-docker/),
[kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation),
[kubectl](https://kubernetes.io/docs/tasks/tools/) and
[Helm 3](https://helm.sh/docs/intro/install/) (tested with kind v0.25.0, kubectl v1.31.4 and
Helm v3.16.3; the replica also needs curl). Run every command from the repository root.

```sh
# 1. A throwaway Kubernetes cluster.
kind create cluster --name sortyard

# 2. Build the image and hand it to the cluster (no registry needed). The tag must match
#    appVersion in charts/sortyard/Chart.yaml, which is what the chart deploys by default.
docker build -t ghcr.io/sortyard/sortyard:0.1.0 .
kind load docker-image ghcr.io/sortyard/sortyard:0.1.0 --name sortyard

# 3. Install: the API service + Postgres, configured by charts/sortyard/values.yaml. Helm
#    returns once the migration Job has created the schema in the empty database
#    (its log: kubectl logs job/sortyard-migrate).
helm install sortyard charts/sortyard
kubectl rollout status statefulset/sortyard-postgres --timeout=180s
kubectl rollout status deployment/sortyard-api --timeout=180s

# 4. Talk to it.
kubectl port-forward svc/sortyard-api 8080:8080 &
curl http://localhost:8080/readyz    # {"status": "ready", "database": "ok"}
curl http://localhost:8080/v1/info   # {"name": "sortyard", "version": "0.1.0", "services": [...]}
```

`/readyz` is ready only once the API reaches Postgres; `/healthz` is liveness. To remove
everything: `kind delete cluster --name sortyard`.

Every setting lives in the one values file, `charts/sortyard/values.yaml`. To use an existing
Postgres instead of the bundled one:
`helm install sortyard charts/sortyard --set postgres.enabled=false --set postgres.external.host=<host> --set postgres.auth.existingSecret=<secret with key "password">`.

### Develop locally (Python 3.11+)

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
ruff check . && ruff format --check .   # lint
mypy                                     # strict typecheck
pytest                                   # tests/ (chart tests need helm on PATH)
pytest spec                              # the Phase 0 schema + OpenAPI tests
python -m sortyard.models.codegen --check   # generated models match spec/ (CI fails on drift)
sortyard-api                             # serves on :8080; SORTYARD_DATABASE_HOST/PORT locate Postgres
```

The migration, ledger and API tests (`tests/test_migrations.py`, `tests/test_api_*.py`) run
against a real Postgres and are skipped without one. Point them at any server you may create
databases on, using the standard libpq variables (each run creates and drops its own database):

```sh
docker run -d --name sortyard-pg -e POSTGRES_PASSWORD=pw -p 5432:5432 postgres:16-alpine
PGHOST=localhost PGUSER=postgres PGPASSWORD=pw pytest tests/test_migrations.py   # needs psql
```

## API service (Phase 1)

`sortyard-api` is the only door (design §4). Under `/v1/workspaces/{workspace_id}/` it serves
the Phase 1 surface of [`spec/openapi.json`](spec/openapi.json): tasks (create, groom, ready,
claim, advance, hand back, block/unblock, cancel, requeue, per-task DecisionLog), lanes,
policy read paths (policies, prioritization and sequencing policies, with their versions) and
policy edits, the DecisionLog, decisions, a build worker's context-packet read and result
submit, findings, the Integrator instruction, role bindings and service-account tokens. The
routed operations and the roles allowed on each are `sortyard.api.permissions.OPERATIONS`,
held to the spec's `x-sortyard-roles` by `tests/test_api_contract.py`, which also runs every
operation against the spec's status codes and response schemas.

Every call carries `Authorization: Bearer <token>`. Tokens are stored only as SHA-256 hashes
(`sortyard.api_token`, migration 0002) and are confined to one workspace:

- **Service accounts** (§7): an admin issues a token for an `agent-service-account`
  RoleBinding with `POST .../role-bindings/{id}/tokens {"agent_role": ...}`. A `build-worker`
  token names its `stage_run_id` and reaches only that stage run's context packet and result
  (once); a `sensor` token names its `project_id` and files findings and `origin: sensor`
  tasks there only; a `grooming-agent` token creates and grooms (`origin: grooming`), never
  claims or merges; only the `conductor` claims, advances, hands back or instructs the
  Integrator; only operator accounts edit policies and lanes or answer decisions. A token is
  refused (422 `create_and_claim`) if it — together with the service account's other live
  tokens — would both create and claim tasks; the table refuses such a row too.
- **Operators**: until OIDC sessions land, an operator credential is printed by
  `sortyard-api --issue-operator-token <role-binding-id>` (admin/operator/viewer bindings;
  the binding's current role applies on every call), e.g.
  `kubectl exec deployment/sortyard-api -- sortyard-api --issue-operator-token rb-admin`.
  The binding comes from `sortyard-api --bootstrap` ([First operator](#first-operator)).

Every mutation writes an AuditLog entry and a ledger event.

### First operator

A new deployment has no workspace, no project and no operator, and the API takes no call
without an operator's token. `sortyard-api --bootstrap FILE` makes them from a declaration
file, and `--issue-operator-token` then prints a token for a binding the file declares. Both
are interim, until OIDC sessions exist.

The declaration is TOML: one workspace, with its projects, operators and role bindings. Each
entry is the object as its schema in [`spec/`](spec/) defines it (`workspace`, `project`,
`operator`, `role-binding`), without `workspace_id`. It holds no credential.

```toml
[workspace]
id = "ws-acme"
name = "Acme"
# installation_id: leave it out for the deployment's own installation: its id is the API
# service's SORTYARD_INSTALLATION_ID (default inst-sortyard), and it is created as a provisional
# record if there is none.

[[projects]]
id = "proj-app"
name = "App"
archetype = { id = "arch-saas-product", version = "1.0.0" }
repos = []
tracker = { kind = "internal" }
state = "active"

[[operators]]
id = "op-first"
subject = "oidc|first"        # the OIDC subject this operator will sign in as
display_name = "First operator"
state = "active"

[[role_bindings]]
id = "rb-first-admin"
principal = { kind = "operator", id = "op-first" }
role = "admin"                # admin, operator or viewer
scope = { kind = "workspace" } # or { kind = "project", ref = "proj-app" }
```

```sh
# 1. Create what the file declares (FILE, or - for standard input; a Job can mount the file).
kubectl exec -i deployment/sortyard-api -- sortyard-api --bootstrap - < bootstrap.toml
# 2. A token for a declared binding.
kubectl exec deployment/sortyard-api -- sortyard-api --issue-operator-token rb-first-admin
```

What the command does:

- It validates every entry as the API validates a request body (the generated model and the
  full JSON Schema), and checks that a binding's operator and a project scope's project are
  declared or already in the workspace.
- It creates what is missing, in one transaction, and prints one line for each object:
  `created <kind> <id>` or `unchanged <kind> <id>`. A created role binding's line also says
  what it grants: `created role_binding rb-first-admin (admin for operator op-first, scope
  workspace)`. It prints no credential and issues none.
- Running it again with the same file changes nothing. Add a project or an operator to the
  file and run it again: only the new objects are created.
- An object that exists with different content is **refused and named, never overwritten**
  (so is an invalid entry). A refused run writes nothing at all and exits 1. To change an
  existing object, use the API. A workspace the shadow conductor made first has its id as
  its name: declare that name. A file that leaves `installation_id` out is the same
  declaration only under the same `SORTYARD_INSTALLATION_ID`: run under another value, it
  differs from the stored workspace and is refused.
- The file declares operators and their bindings (`admin`, `operator`, `viewer`). An
  `agent-service-account` binding is refused here: an admin grants those through the API.
- `--bootstrap` and `--issue-operator-token` are separate runs; giving both, or an empty
  value, is a usage error (exit 2).
- Each object it creates is in the AuditLog (channel `system`) and the ledger, with the actor
  `system/bootstrap`.

[`replica/bootstrap.toml`](replica/bootstrap.toml) is the file the local replica uses.

## Shadow conductor (Phase 1)

`sortyard-conductor --shadow` is the conductor in observe-only mode (design §8): every pass
(default every 300 s, drive.py's cadence) it reads the production conductor's input path —
the board view, the lane registry (`products.json`) and the task_ready gating output —
**read-only** (GET only; it holds no write credential and no Kubernetes token), computes what
it would claim and refuse, and appends that to the DecisionLog (`sortyard.decision_log`, plus
`shadow_would_claim` / `shadow_would_skip` / `shadow_pass` events in the ledger). It never
claims, merges, comments or writes anywhere but its own database. Each production pass
(`production_pass_id`) is recorded once.

Two input sources (`charts/sortyard/values.yaml`, `shadow.*`; formats in
`src/sortyard/shadow/sources.py`): `snapshot` — a **pass feed** by URL or path
(`{"passes": [board view, ...]}`, or a directory with one board view per pass) that retains
passes until the shadow has read them, e.g. drive.py's board views exported by the
production control plane; every pass not yet recorded is recorded on the next read, however
many arrived in between (a single board view also works, but only sees the pass current at
read time). `plane` — the board straight from Plane's REST API with a read-only API key,
plus the lane registry mounted from a ConfigMap, driven by the production conductor's pass log
(`shadow.plane.passes`), which retains each pass's inputs (the Plane issues and task_ready
output it read); every new pass is replayed from its own inputs and recorded, however many
arrived between polls. A pass with no retained inputs can only be read live while it is the
newest; an older one stops the poll (nothing recorded, logged) instead of being decided
against a board it never saw. Redirects that would carry the API
key to another origin, or downgrade https to http, are refused.

Runbook:

```sh
# Start (pass feed by URL):
helm upgrade sortyard charts/sortyard --reuse-values --set shadow.enabled=true --set shadow.snapshot=<pass-feed URL>
# Start (Plane): secret with a READ-ONLY key, then point the shadow at the board + lane registry.
kubectl create secret generic plane-read --from-literal=api-key=<read-only Plane API key>
helm upgrade sortyard charts/sortyard --reuse-values --set shadow.enabled=true --set shadow.source=plane --set shadow.plane.url=<Plane URL> --set shadow.plane.workspace=<slug> --set 'shadow.plane.projects={<project id>}' --set shadow.plane.apiKeySecret=plane-read --set shadow.lanes.configMap=<ConfigMap holding products.json> --set shadow.plane.passes=<pass-log URL> --set shadow.interval=15
# Watch it:
kubectl logs -f deployment/sortyard-shadow-conductor
kubectl exec statefulset/sortyard-postgres -- psql -U sortyard sortyard -c "SELECT conductor_pass_id, decision, task_id, doc->'reason_codes' FROM sortyard.decision_log ORDER BY recorded_at DESC, (doc->'inputs'->>'preview_position')::int LIMIT 20"
# Pause (keeps config): kubectl scale deployment/sortyard-shadow-conductor --replicas=0
# Stop:
helm upgrade sortyard charts/sortyard --reuse-values --set shadow.enabled=false
```

Locally: `SORTYARD_SHADOW_SNAPSHOT=board.json sortyard-conductor --shadow --once` (environment
variables: `src/sortyard/services/conductor.py`).

## Kernel service

`sortyard-kernel` takes an item from admitted to merged: it is the workflow engine's worker,
with every owner of the item state table, and the observer loop that asks GitHub and the
cluster how each item's outside work is going. The chart installs it with `kernel.enabled=true`
(which needs `engine.enabled=true`, the workflow engine server on Postgres): one Deployment, a
service account, and a Role in the worker namespace that grants what the worker Jobs' port
calls and nothing else. The API then mounts the lane files too and admits items
(`POST /v1/workspaces/{id}/items`).

What it runs on is values, mounted as files (`charts/sortyard/values.yaml`, `kernel.*`): the
lane capability files (`kernel.lanes`, format `src/sortyard/kernel/lane_example.toml`), the
decision policy (`kernel.decisionPolicy`) and how workers run (`kernel.worker`: the agent
command for build, fix and review). Every credential is a Secret you create and name; the
render fails when one is missing, and none is optional:

```sh
# The GitHub App the lanes' tokens are minted from: its id in the values, its key in a Secret.
kubectl create secret generic github-app --from-file=private-key.pem=<the App's private key file>
helm upgrade sortyard charts/sortyard --reuse-values \
  --set engine.enabled=true --set kernel.enabled=true \
  --set kernel.github.appId=<App id> --set kernel.github.appKeySecret=github-app \
  --set-file kernel.lanes.<lane>=<lane capability file> \
  --set-json 'kernel.worker.agents={"build":["<agent>","..."],"fix":["<agent>","..."],"review":["<agent>","..."]}'
kubectl logs -f deployment/sortyard-kernel
```

Worker Jobs run in the release's cluster by default (`kernel.workers.namespace`, default the
release namespace). To run them in another cluster, set `kernel.workers.sameCluster=false` and
`kernel.workers.clusterSecret` to a Secret with the keys `server`, `token` and `ca.crt`: no
Role is rendered and the pod holds no token of its own cluster. One replica runs; a pod that
is deleted loses nothing, since the engine and Postgres hold every item's state.

### Worker image

A worker Job runs three containers of the lane's worker image (`sortyard-worker clone`,
`agent`, `push`), so that image needs `sortyard-worker`, `git` and the agent command. The
Sortyard image has the first two and no agent. A worker image is the Sortyard image plus your
agent, in one layer:

```dockerfile
FROM ghcr.io/sortyard/sortyard:<version>
USER root
RUN <install your agent CLI>
USER 10001
```

Push it, name it by digest in the lane capability file (`[images] worker` and `ci`: they are
the same image), and give the agent's command line in `kernel.worker.agents`. The agent is run
in the item's clone with the brief on standard input, and never holds the GitHub token.
`replica/worker/` is a complete example with a scripted agent.

## Data model

The §3 domain objects are frozen as JSON Schemas in [`spec/`](spec/), and everything else is
derived from them:

- **Python models** — `sortyard.models` holds one frozen dataclass per object (and per nested
  shape), generated into `src/sortyard/models/_generated.py` by `python -m
  sortyard.models.codegen`. Never edit that file: change the schema, regenerate, commit both.
  `Model.from_dict()` / `to_dict()` convert to and from the schema's JSON form;
  `sortyard.models.MODELS` maps each schema file to its model.
- **Postgres** — [`charts/sortyard/migrations/`](charts/sortyard/migrations/) holds numbered SQL
  migrations, applied in order by `migrate.sh`, which the chart runs as a Job after every
  install and upgrade. Each §3 object has a table in the `sortyard` schema whose `doc` JSONB
  column is the object exactly as its schema defines it; the other columns are generated from
  `doc`. Definitions are keyed by `(id, version)` and are immutable; everything else by `id`.
  A released migration is never edited: the runner refuses one whose file changed.
- **Event ledger** — `sortyard.event` is append-only (UPDATE, DELETE and TRUNCATE are refused;
  the same holds for the DecisionLog and AuditLog). `SELECT sortyard.append_event(doc)` assigns
  the event its `seq` and is idempotent: the same event appended twice records once, while
  reusing an id for different content is refused. `sortyard.object_history(kind, id)` returns
  one object's events in ledger order.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the same checks on every pull
request to `main` and every push to `main`, plus `helm lint`/`helm template` and a container
build, in one job, `test`: the one required status check on `main` (strict, up to date with
`main`). The replica boot runs nightly and on demand in
[`.github/workflows/slow.yml`](.github/workflows/slow.yml).

### Published image

[`.github/workflows/publish.yml`](.github/workflows/publish.yml) builds the `Dockerfile` for
every commit on `main` (and on demand, on `main`) and pushes it as
`<registry>/sortyard/sortyard:<full commit sha>`. The registry is not named in this repository:
it is the repository variable `ACR_REGISTRY`. The login is the secrets `ACR_PUSH_USERNAME` and
`ACR_PUSH_PASSWORD`, which exist only in the environment `publish`; its deployment branches are
limited to `main`, so a run on any other branch is not given them. The job never runs for a
pull request. After the push it pulls
the image by digest, smoke-tests it, and writes `image=<registry>/sortyard/sortyard@sha256:...`
and the commit to the job summary (and as job outputs).

A deployment names the image by that digest, never by a tag: set `image.repository` to
`<registry>/sortyard/sortyard` and `image.digest` to the `sha256:...` value, and every Sortyard
container (API, kernel and its init container, shadow conductor) is rendered as
`repository@sha256:...`. A value that is not `sha256:` plus 64 lower-case hex characters fails
the render. With `image.digest` empty the chart names the image by tag, as before.

## Layout

| Path | What |
|---|---|
| `src/sortyard/services/` | The six services (§4), one console script each: `sortyard-api`, `sortyard-conductor`, `sortyard-context-assembler`, `sortyard-eval-runner`, `sortyard-sensor-runner`, `sortyard-integrator`. Besides the API (REST surface in `src/sortyard/api/`), only the conductor's shadow mode (`--shadow`) does work yet; the rest are stubs that start, log and idle. |
| `src/sortyard/api/` | The API's REST surface: the §7 permission matrix (`permissions.py`), tokens (`auth.py`), routing, handlers and the Postgres store with its audit/ledger writes. |
| `src/sortyard/shadow/` | The shadow conductor: read-only input adapters, the claim decision (a pure function), and the DecisionLog writer. |
| `src/sortyard/models/` | The §3 data models, generated from `spec/` (`codegen.py` is the generator). |
| `charts/sortyard/` | The Helm chart: API Deployment + Service, Postgres StatefulSet + Service + Secret, the migration Job, and (opt-in) the shadow conductor Deployment, the workflow engine server on Postgres and the kernel service with its worker Role. |
| `charts/sortyard/migrations/` | The SQL migrations (§3 tables + event ledger; 0002: the API token store) and `migrate.sh`, the Job's runner. |
| `Dockerfile` | One image for every service; the Deployment's `command` picks the entry point. It is also the base of a lane's worker image (it has `sortyard-worker` and `git`, and no agent). |
| `spec/` | Phase 0: the §3 JSON Schemas and the OpenAPI spec, with their tests. |
| `replica/` | The one-command local replica: `replica.sh` (kind + this chart + fake outside providers), its kind config, values overrides, fakes, its lane file, its bootstrap declaration (`bootstrap.toml`) and its worker image (`replica/worker/`). |
| `tests/` | Tests for the package, chart, CI, replica, this quickstart and `AGENTS.md`. |
| `docs/findings/` | Friction found while building the repo's own foundations, filed as findings ([`contributor-foundation.md`](docs/findings/contributor-foundation.md)). |
| `docs/goldfish/` | Goldfish reports: a zero-context agent runs the documented install and files every point of friction (Phase 1: [`phase-1-install-smoke.md`](docs/goldfish/phase-1-install-smoke.md)). |

## Project charter

Sortyard is the workflow kernel plus the tracker view described in company/HARNESS-V3.md, as
[SY-DEC-005](DECISIONS.md#sy-dec-005) (2026-11-23 amendment) records; the ecosystem control
surface is deferred. The core stores to Postgres only. [The requirements baseline](docs/requirements/README.md)
is kept as reference for requirement IDs, service ownership and contracts; its
dependency-ordered delivery plan is not the current build order. [Decision records](DECISIONS.md)
explain the stack and its amendments.

### Tracking

Execution state, ordering, parent scopes and blocked-by relations live on the
[Sortyard Plane board](https://plane.ts.noncelogic.com/noncelogic/projects/10d493fb-4cef-4ef1-ab70-a0aefca87d59/issues/).
Product changes target `sortyard/sortyard`. Meta-harness stays commit-forward for unmigrated
governance and definitions; it is not a second task-status store. The historical design and
corpus remain provenance, with the active baseline taking precedence where they conflict.

## Licence

Sortyard is source-available. Sortyard is licensed under the Functional Source License,
Version 1.1, ALv2 Future License (FSL-1.1-ALv2); see LICENSE.md. You may use,
copy, modify and redistribute it for any purpose other than a Competing Use as that licence
defines it. Each version becomes available under the Apache License, Version 2.0 on the second
anniversary of the date that version was made available. The spec/ directory is licensed under
the Apache License, Version 2.0; see LICENSE-APACHE. Versions of this repository published
before the commit that added this notice were published under the Apache License, Version 2.0
and remain available under it.

The licence text is in [`LICENSE.md`](LICENSE.md) and the same statement is in
[`NOTICE`](NOTICE). The Apache License 2.0 text is in [`LICENSE-APACHE`](LICENSE-APACHE) and
[`spec/LICENSE`](spec/LICENSE).
