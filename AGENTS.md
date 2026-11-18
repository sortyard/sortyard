# AGENTS.md — Sortyard repo brief

Read this file first. It is meant to be enough, together with the code it points at, for an
agent or a new contributor to make a first change without anyone briefing them. If something
here is wrong or missing, that is a bug: fix it in the same change, or file it (see
[Known gaps](#known-gaps)).

## Current requirements authority

Read the [ecosystem baseline](docs/requirements/README.md) before new feature planning.
It supersedes the historical draft and corpus where they conflict. Planned contracts under
`docs/requirements/contracts/` are distinct from the implemented `spec/` contract.
The baseline preserves single service ownership and equal operator/agent public actions.

## Substrate planning amendment

[SY-DEC-004](docs/decisions/appwrite-substrate.md) selects Appwrite as the preferred future
persistence/auth substrate. This brief's Postgres commands and architecture describe the
current code and replica; they remain valid until a reviewed migration implements the new
backend. Preserve transaction, history and authorization guarantees during that work.

## What this is

Sortyard is an open-source delivery harness: a conductor, a control plane and a task manager,
deployed with one Helm chart. The operator gets a UI for everything and agents get APIs for
everything. The repo is at the **Phase 1 skeleton** stage:

- the six services exist as console scripts of one Python package;
- the API answers `/healthz`, `/readyz` and `/v1/info`, and serves the Phase 1 REST surface
  of `spec/openapi.json` behind bearer tokens and the §7 permission matrix;
- the chart installs the API, Postgres and a schema migration Job, and can add the conductor
  in **shadow mode** (it reads the production conductor's inputs read-only and records what it
  would claim).

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

The stubs share `src/sortyard/services/_stub.py`. The registry of all six is
`src/sortyard/services/__init__.py` (`SERVICES`).

Packages and directories:

| Path | What lives there |
|---|---|
| `src/sortyard/` | The one Python package (`__version__` in `src/sortyard/__init__.py`). |
| `src/sortyard/services/` | The six services (table above). |
| `src/sortyard/api/` | The API service's REST surface (§4, §7). `permissions.py` is the §7 permission matrix in code (`OPERATIONS`, held to the spec's `x-sortyard-roles` by `tests/test_api_contract.py`). `auth.py` holds bearer tokens: service-account issuance (refusing any token set that could both create and claim tasks) and operator tokens. `routing.py` routes, authenticates and authorizes before any read. `handlers.py` has one function per operation. `store.py` is the Postgres access, with the AuditLog and ledger writes every mutation makes. |
| `src/sortyard/shadow/` | The shadow conductor. `sources.py` holds the read-only input adapters (`SnapshotSource`, `PlaneSource`; every HTTP call goes through `ReadOnlyHttp`, which allows GET only). `board.py` holds the queue snapshot model. `evaluate.py` holds the claim decision, a pure function. `ledger.py` writes the DecisionLog. |
| `src/sortyard/checkout/` | The native checkout replay. The coordinator binds a versioned retry policy, recorded GitHub observations and an independent verifier. Run it locally with `python -m sortyard.checkout` as described in [the native execution design](docs/design/native-execution.md#the-first-runnable-slice). |
| `src/sortyard/lifecycle/` | Versioned lifecycle facts, incumbent trace intake and the shared pre-cutover scorecard. See [native execution §5](docs/design/native-execution.md#5-cutover-evidence). |
| `src/sortyard/models/` | The §3 domain models. `_generated.py` is generated by `codegen.py` from `spec/*.schema.json`; **never edit it by hand**. `_runtime.py` is the base `Model` (`from_dict`/`to_dict`). |
| `spec/` | The frozen contract: one JSON Schema per §3 object, plus `spec/openapi.json`. Their tests are `spec/test_schemas.py` and `spec/test_openapi.py`. Conventions are in `spec/NOTES.md`; the §7 permission matrix, summarised, is `spec/PERMISSIONS.md`. |
| `charts/sortyard/` | The Helm chart. It has **one** values file, `charts/sortyard/values.yaml`. Templates: API, Postgres (StatefulSet + Secret), the migration Job, and the shadow conductor. |
| `charts/sortyard/migrations/` | Numbered SQL migrations plus `migrate.sh`, their runner (the Job's command, and what the tests run). |
| `replica/` | The one-command local replica (see [Local replica](#local-replica)): `replica/replica.sh`, the kind config, replica values, and fake outside providers in `replica/fakes/`. |
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
mypy                                            # strict, over src/, tests/ and replica/
pytest tests                                    # chart/replica-render tests need helm; DB tests need Postgres
```

If the host Python has no `venv`/`pip` (Debian/Ubuntu without `python3-venv`):
`python3 -m venv --without-pip .venv && . .venv/bin/activate && curl -fsSL https://bootstrap.pypa.io/get-pip.py | python`.

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
./replica/replica.sh up        # ~1.5 min cold, ~25 s on re-run
```

It needs Docker, kind, kubectl, helm and curl. Tested with kind v0.25.0, kubectl v1.31.4 and
helm v3.16.3. `./replica/replica.sh check` lists anything missing or too old, with install
links, and changes nothing. Then `up`:

1. creates the kind cluster `sortyard` from `replica/kind.yaml` (the node image is pinned by
   digest);
2. builds the one image and tags it by content, so a re-run rolls out your change;
3. deploys the **fake outside providers** from `replica/fakes.yaml`:
   `replica/fakes/fake_plane.py` serves Plane's REST API and the production conductor's pass
   log from `replica/fakes/fixtures.json`. It also adds the lane registry ConfigMap and a
   random read-only Plane API key Secret, which the fake enforces;
4. installs **`charts/sortyard` itself**, with `replica/values.yaml` layered on top. That file
   only enables the shadow (pointed at the fakes) and shrinks the volume. Topology, Services
   and Secrets are the chart's own;
5. smoke-tests the result: `/healthz`, `/readyz` and `/v1/info` through the API Service;
   migrations recorded; the shadow records both fixture passes in the DecisionLog; the fake
   saw zero writes and zero unauthenticated reads.

Other commands:

```sh
./replica/replica.sh smoke     # re-run the smoke test
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
- **Dependencies.** Runtime: `psycopg[binary]` only. Dev extras: `pyproject.toml`. Don't add
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
- Only the API and the shadow conductor are deployed by the chart. The four other services
  are stubs with no Deployment.
- Friction found building the replica and this brief:
  `docs/findings/contributor-foundation.md`. The goldfish install run:
  `docs/goldfish/phase-1-install-smoke.md`.
