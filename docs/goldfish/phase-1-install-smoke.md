# Goldfish report — Phase 1 install + smoke (corpus M1.14)

**Repo state under test:** `main` at `4e412c8` ("Sortyard Phase 1: repo + chart skeleton", #1).
**Date:** 2026-11-10.
**Scope:** install + smoke, per MILESTONES.md item SORTYARD-16. Install the chart on a clean
cluster, load the seed definitions, run the demo workflow. The shadow-decision smoke in M1.14
comes later, with the Phase 1B items, and is not tested here.
**Method:** a zero-context agent starts from the repository alone, with no other briefing,
and follows the docs literally. Every point of friction is filed below against **the repo**,
**the docs** or **the chart**. The report is the deliverable. Fixing the findings is separate
work.

## Environment

- A disposable Linux container: Python 3.11.2 and a working Docker client and daemon (27.5.1).
- The quickstart needs `kind`, `kubectl` and `helm`. None of them was on `PATH`. `pip` was
  missing too (`python3 -m pip`: no module named pip), and the only network access allowed was
  read access to GitHub. So the binaries, the base image (`python:3.11-slim`), the
  `postgres:16-alpine` image and the `.[dev]` extras could not be fetched.
- As a result, **the cluster part of the quickstart (steps 1–4) was not run.** Each of those
  commands was checked against the repo by reading the source instead. The parts that need no
  cluster were run for real: the API service from source, its endpoints, and a stub service.
  A run on a real cluster is still owed (see Verdict).

## Run log

Each command from the README quickstart, in order, with what happened.

| # | Command | Result |
|---|---|---|
| 1 | `kind create cluster --name sortyard` | **Not run**: `kind` is not installed. The repo has no prerequisite check and no replica script that would bring the tool in (GF1-05). |
| 2 | `docker build -t ghcr.io/sortyard/sortyard:0.1.0 .` | **Not run**: the build pulls `python:3.11-slim`, which is outside the allowed network. Static check: the tag matches `appVersion: "0.1.0"` in `charts/sortyard/Chart.yaml`, and the Dockerfile installs a package with no runtime dependencies. |
| 2 | `kind load docker-image ghcr.io/sortyard/sortyard:0.1.0 --name sortyard` | **Not run**: no `kind`. Static check: `image.pullPolicy: IfNotPresent` means kind uses the loaded image. |
| 3 | `helm install sortyard charts/sortyard` | **Not run**: no `helm`. Static check: names render as `sortyard-api` and `sortyard-postgres` (the release name contains the chart name, so `_helpers.tpl` does not double it), which matches the rollout commands. |
| 3 | `kubectl rollout status statefulset/sortyard-postgres --timeout=180s` | **Not run**: no `kubectl`. |
| 3 | `kubectl rollout status deployment/sortyard-api --timeout=180s` | **Not run**: no `kubectl`. |
| 4 | `kubectl port-forward svc/sortyard-api 8080:8080` | **Not run**. Stand-in: started the API from source with `PYTHONPATH=src SORTYARD_API_PORT=18080 python3 -m sortyard.services.api`. It came up and logged its listen address. |
| 4 | `curl http://localhost:8080/readyz` | Stand-in on :18080 with no Postgres: `503 {"status": "unavailable", "database": "unreachable"}`, as documented. GF1-07 covers what a 200 here does *not* prove. |
| 4 | `curl http://localhost:8080/v1/info` | Stand-in: `200 {"name": "sortyard", "version": "0.1.0", "services": ["api", "conductor", "context-assembler", "eval-runner", "integrator", "sensor-runner"]}`, which matches the README. |

The task's next steps have no command in the docs:

| Step | Result |
|---|---|
| Load the seed definitions | **Blocked**: nothing in the repo loads definitions and there are no seed definitions to load (GF1-01). |
| Run the demo workflow | **Blocked**: there is no demo workflow and no REST surface to run one through. Probes of `spec/openapi.json` paths all returned 404: `GET /v1/installation`, `GET /v1/workspaces`, `GET /v1/workflows`, `GET /v1/tasks`, `GET /openapi.json`. `POST /v1/workspaces` returned an HTML 501 page (GF1-02, GF1-06). |
| Stub services | `PYTHONPATH=src python3 -m sortyard.services.conductor --once` logged "stub service started (no work loop yet)" and "stopped", exit 0, as the README says. |
| Develop locally (`pip install -e '.[dev]'`, lint, typecheck, `pytest`) | **Not run**: no `pip` and no package index in this environment. |

## Findings

### GF1-01 — No seed definitions and no definitions loader, so "load the seed definitions" has nothing to run

**Against:** repo
**Severity:** blocker
**Evidence:** `git ls-files` contains no definitions or seed directory, no loader module and no
CLI or API endpoint that accepts definitions. `src/sortyard/services/` has only the API (three
endpoints) and five stubs. That work is SORTYARD-12 (corpus M1.2, "definitions loader + seed
corpus"), which has not landed.
**What would fix it:** land SORTYARD-12, and make the README quickstart end with the
command that loads the seed definitions.

### GF1-02 — No demo workflow and no REST surface: the API serves 3 of the spec's 134 paths

**Against:** repo
**Severity:** blocker
**Evidence:** `spec/openapi.json` declares 134 paths. `src/sortyard/services/api.py` serves
`/healthz`, `/readyz` and `/v1/info`, and returns 404 for everything else. Every spec path
probed returned `404 {"error": "not_found"}` (Run log). This task's declared input, "API service
— REST surface per the OpenAPI spec" (HARNESS-312 / SORTYARD-7), is not on `main`. No file in
the repo names or describes a demo workflow.
**What would fix it:** land SORTYARD-7. Ship a named demo workflow, plus the commands to run
it, in the quickstart.

### GF1-03 — No `AGENTS.md`: the repo brief a zero-context agent is meant to start from is missing

**Against:** repo
**Severity:** major
**Evidence:** there is no `AGENTS.md` or `CLAUDE.md` anywhere in the tree. DESIGN.md §11 ("an
`AGENTS.md` that actually suffices") and CORPUS.md M1.1 both require one. The README's charter
says the repo is seeded "from projects/sortyard (README, AGENTS.md, LICENSE, spec/, branding/)",
but neither `AGENTS.md` nor `branding/` arrived. Tracked as SORTYARD-13.
**What would fix it:** land SORTYARD-13's `AGENTS.md`.

### GF1-04 — The README's "Project charter" section is operator context a stranger cannot resolve, and it contradicts the top of the README

**Against:** docs
**Severity:** major
**Evidence:** `README.md` from "## Project charter" onward has several problems:
- It points at a design draft "held locally at ~/workspace/harness-reboot/... (Juno's
  workspace) until the code repo exists", although `DESIGN.md` is in this repo.
- It lists "Phase 0 scope (... no code moves yet)" and "Nothing ships", while the top of the
  README describes the Phase 1 skeleton.
- It links an internal Plane host, `conductor/add_item.py`, and a ConfigMap in namespace
  `exp-phase0`.
- It promises `projects/sortyard/branding/`, a path that does not exist in this repo.

An agent reading the README top to bottom cannot tell which half is current.
**What would fix it:** move the charter and tracking notes to a design-record file (or delete
them), and keep the README about this repo as it is now.

### GF1-05 — No one-command local replica or prerequisite check; a bare environment fails at step 1 with no guidance

**Against:** repo
**Severity:** major
**Evidence:** this run. The quickstart assumes `kind`, `kubectl`, `helm` and Docker, and lists
them with no versions. Nothing in the repo (no script, Makefile or Compose file) checks for the
tools, pins versions, or boots the topology in one command. CORPUS.md M1.1 calls for "a
one-command local replica (Compose or kind)". CI pins Helm `v3.16.3`, but the README does not
say so. Tracked as SORTYARD-13.
**What would fix it:** a single replica entry point that checks prerequisites and their
versions before doing anything, with the pinned versions listed in the README.

### GF1-06 — Unsupported methods get Python's default HTML error page, not JSON

**Against:** repo
**Severity:** minor
**Evidence:** `POST /v1/workspaces` (a spec operation) returned `501` with a `text/html` body,
`<title>Error response</title> ... Unsupported method ('POST')`. Every other response from the
API is JSON. `Handler` in `src/sortyard/services/api.py` defines only `do_GET`. An agent client
that parses JSON trips on this page while exploring the API.
**What would fix it:** a JSON error body (and `405` with `Allow`) for every method. This is
probably absorbed by SORTYARD-7.

### GF1-07 — `/readyz` proves a Postgres is listening, not that the API can log in; a wrong password installs green

**Against:** repo
**Severity:** minor
**Evidence:** `postgres_answers()` in `src/sortyard/services/api.py` sends only the SSLRequest
pre-auth probe. `SORTYARD_DATABASE_USER`/`PASSWORD`/`NAME` are passed in by
`charts/sortyard/templates/api.yaml` but never read. With
`--set postgres.auth.existingSecret=<secret holding the wrong password>`, both rollouts in step
3 succeed and `/readyz` returns 200. The README's line "`/readyz` is ready only once the API
reaches Postgres" is literally true but overstates what is checked.
**What would fix it:** authenticate in the readiness check once a driver lands (SORTYARD-7 or
the Postgres schema task). Until then, the README should say readiness is credential-blind.

### GF1-08 — `helm uninstall` leaves the Postgres Secret and data volume behind, and the docs do not say so

**Against:** docs
**Severity:** minor
**Evidence:** `charts/sortyard/templates/postgres-secret.yaml` carries
`helm.sh/resource-policy: keep`, and the StatefulSet's `volumeClaimTemplates` PVC is never
deleted by Helm. The behaviour is deliberate (it keeps the password and data consistent across
reinstalls), but the README only documents `kind delete cluster`. An operator on a cluster
they keep will find leftovers after `helm uninstall sortyard`.
**What would fix it:** one README line naming what survives uninstall and how to remove it.

### GF1-09 — `pytest spec` is listed as a routine check but fails on `main`, and the §7 permission matrix it reads is missing

**Against:** repo
**Severity:** major
**Evidence:** `spec/test_openapi.py:19` reads `spec/PERMISSIONS.md`, and that file is not in
the repo. `.github/workflows/ci.yml` (job `spec`) records that these tests "currently fail on
main", lists two missing `issueServiceAccountToken` schema fields, and runs the job with
`continue-on-error: true`. The README's "Develop locally" block lists `pytest spec` next to the
gating checks without that caveat, so a newcomer's first red result is a known one. (This run
could not execute `pytest spec` because the `.[dev]` extras could not be installed. The
evidence comes from the files.)
**What would fix it:** repair the seed (add `spec/PERMISSIONS.md` and the schema fields), or
until then note the known failure in the README.

## Verdict

**Verdict:** blocked

The install path the repo documents is coherent as far as it goes. Every name, tag and port in
the quickstart matches the chart and Dockerfile, and the API and stubs behave as documented
when run from source. But a zero-context agent cannot finish this task unaided on `main`.
There are no seed definitions (GF1-01) and no demo workflow or REST surface (GF1-02). Two of the
three inputs this task names have not landed: the API service (HARNESS-312 / SORTYARD-7) and the
replica and repo brief (HARNESS-318 / SORTYARD-13). The cluster steps were checked statically
only, because this environment had no `kind`/`helm`/`kubectl` and no network for images.

**Re-run owed:** once SORTYARD-7, SORTYARD-12 and SORTYARD-13 land, re-run this report on a
cluster that has the quickstart's tools, starting again from the repo alone. Per CORPUS.md R7,
the legibility thread assumes these findings are fixed, not just filed.

**Not verified in this run:** whether `ghcr.io/sortyard/sortyard:0.1.0` is published. If it
is not and the agent skips `kind load`, step 3 ends in `ErrImagePull`. There is also no check
that `postgres:16-alpine` starts under the chart's `fsGroup: 70` on kind's default
StorageClass.
