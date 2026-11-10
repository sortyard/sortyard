# Sortyard

Sortyard is an open-source delivery harness — conductor, control plane and task manager —
deployed with one Helm chart, with a UI for everything for the operator and APIs for everything
for agents. The design record is [`DESIGN.md`](DESIGN.md) (architecture: §4); the stack is
decided in [`DECISIONS.md`](DECISIONS.md) (SY-DEC-001); the frozen domain model and API
contract are in [`spec/`](spec/).

This repository is at the **Phase 1 skeleton**: the six services exist as entry points, the
API service answers health/readiness/info, and the chart installs the API plus Postgres. No
domain behaviour yet — see [`MILESTONES.md`](MILESTONES.md) for what lands next.

## Quickstart — a running, empty Sortyard on a local cluster

You need [Docker](https://docs.docker.com/get-docker/),
[kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation),
[kubectl](https://kubernetes.io/docs/tasks/tools/) and
[Helm 3](https://helm.sh/docs/intro/install/). Run every command from the repository root.

```sh
# 1. A throwaway Kubernetes cluster.
kind create cluster --name sortyard

# 2. Build the image and hand it to the cluster (no registry needed). The tag must match
#    appVersion in charts/sortyard/Chart.yaml, which is what the chart deploys by default.
docker build -t ghcr.io/sortyard/sortyard:0.1.0 .
kind load docker-image ghcr.io/sortyard/sortyard:0.1.0 --name sortyard

# 3. Install: the API service + Postgres, configured by charts/sortyard/values.yaml.
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
sortyard-api                             # serves on :8080; SORTYARD_DATABASE_HOST/PORT locate Postgres
```

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the same checks on every pull
request and every push to `main`, plus `helm lint`/`helm template` and a container build.

## Layout

| Path | What |
|---|---|
| `src/sortyard/services/` | The six services (§4), one console script each: `sortyard-api`, `sortyard-conductor`, `sortyard-context-assembler`, `sortyard-eval-runner`, `sortyard-sensor-runner`, `sortyard-integrator`. All but the API are stubs that start, log and idle. |
| `charts/sortyard/` | The Helm chart: API Deployment + Service, Postgres StatefulSet + Service + Secret. |
| `Dockerfile` | One image for every service; the Deployment's `command` picks the entry point. |
| `spec/` | Phase 0: the §3 JSON Schemas and the OpenAPI spec, with their tests. |
| `tests/` | Tests for the package, chart, CI and this quickstart. |

## Project charter

Sortyard is the open-source harness reboot: the delivery harness (conductor, k3s control
plane, task manager) rethought from first principles as an open-source package anyone can
deploy (Helm chart), with a UI for everything for the operator and APIs for everything for
agents — without losing the control, tunability and flexibility of the current system.
Joe named it Sortyard on 2026-11-06 ("harness" rejected) and registered sortyard.ai the
same day; the GitHub org is github.com/sortyard.

The design record is the Sortyard design draft v5, held locally at
~/workspace/harness-reboot/HARNESS-REBOOT-DRAFT-v5.md (Juno's workspace) until the code
repo exists; the draft's domain model (§3), architecture (§4) and migration plan (§8) are
the Phase 0 source of truth.

### Phase 0 scope (freeze the model — no code moves yet)

1. Verify the conductor's fix-round/review semantics from the product-factory source and
   amend the design draft to match (the design's one unverified fact).
2. Freeze the domain model: JSON Schemas for every §3 domain object, authored into
   projects/sortyard/spec/ (definitions in git).
3. Write the OpenAPI spec for the Sortyard API, including the MCP permission matrix.
4. Create the code repo github.com/sortyard/sortyard (private) and seed it from
   projects/sortyard (README, AGENTS.md, LICENSE, spec/, branding/).
5. Nothing ships and no existing project migrates in Phase 0; later phases are filed
   separately when Phase 0 lands.

### Tracking

Sortyard has its own Plane project — **Sortyard** (identifier `SORTYARD`), at
https://plane.ts.noncelogic.com/noncelogic/projects/10d493fb-4cef-4ef1-ab70-a0aefca87d59/issues/
— migrated off the HARNESS board on 2026-11-09 (the 2026-11-08 MH→Plane migration moved
ROVE/LOOP/CPV2 but left Sortyard behind). Like HARNESS, the SORTYARD product has `tasks: off`
and no plan file: work enters only as board items created directly (conductor/add_item.py), and
the board item IS the filing. The project is registered with the conductor in the
`conductor-config` ConfigMap `products.json` (ns exp-phase0): one lane, `tasks: false`,
`repo: noncelogic/meta-harness`.

The former HARNESS board items were recreated on the SORTYARD board and the HARNESS originals
retired (Cancelled, each pointing at its replacement). Old → new: HARNESS-286→SORTYARD-1,
287→SORTYARD-2 (Done, delivered via PR #259), 288→SORTYARD-3, 289→SORTYARD-4, 310→SORTYARD-5,
311→SORTYARD-6, 312→SORTYARD-7, 313→SORTYARD-8, 314→SORTYARD-9, 315→SORTYARD-10, 316→SORTYARD-11,
317→SORTYARD-12, 318→SORTYARD-13, 319→SORTYARD-14, 320→SORTYARD-15, 321→SORTYARD-16. (HARNESS-290,
the PR #244 review tracker, is a HARNESS item and stays on the HARNESS board.) Do not add a
plan/tasks file for this project, and do not add a repos.yaml entry yet: the code repo
github.com/sortyard/sortyard is created by SORTYARD-4 ("Sortyard Phase 0: create
github.com/sortyard/sortyard (private) and seed it from projects/sortyard").

### Branding

The commissioned Sortyard brand kit (2026-11-06) will live at projects/sortyard/branding/
when the package lands; see projects/sortyard/branding/README.md.
