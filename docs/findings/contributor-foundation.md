# Findings — contributor foundation (local replica + AGENTS.md)

**Task:** Sortyard Phase 1: contributor foundation. This covers the one-command local replica
of the deployment topology and the repo brief (`AGENTS.md`), the §11 piece of corpus M1.1.
**Date:** 2026-11-12.
**Method:** two proofs, run in a disposable Linux container (Docker 27.5.1, kind v0.25.0,
kubectl v1.31.4, helm v3.16.3, Python 3.11.2).

1. **Replica.** `./replica/replica.sh up` ran on a cold machine: kind cluster, image build,
   fake providers, chart install, smoke test. Then it ran again after a code change to
   `src/sortyard/services/api.py`, and finally `down`.
2. **Brief.** A zero-context agent got a copy of the repo and one instruction: make a small API
   change using only `AGENTS.md`. It was told nothing about the code, the design record or the
   replica, and reported every point of friction.

Friction found along the way is filed below, not silently worked around. Where the replica
*does* work around something, the workaround is named here, so the underlying issue stays
visible. Each finding is filed against **the repo**, **the docs**, **the chart** or **the
replica**.

## Results

| Step | Result |
|---|---|
| `./replica/replica.sh check` with no tools on PATH | Exit 1. Every missing tool is named with its tested version and an install link. "nothing was changed". |
| `./replica/replica.sh up`, cold | Exit 0 in 83 s. The API, Postgres, migration Job, shadow conductor and fake providers all came up with 0 restarts. Smoke: `/readyz` `{"status": "ready", "database": "ok"}`; 1 migration recorded; the shadow recorded both fixture passes (`shadow-replica-pass-1`: claim DEMO-4, skip DEMO-2/3; `shadow-replica-pass-2`: claim DEMO-2/DEMO-4, skip DEMO-3); fake audit `{"reads": 6, "writes": 0, "unauthorized": 0}`. |
| Edit `/v1/info` in `api.py`, then `./replica/replica.sh up` again | Exit 0 in 24 s. The new image (content tag) rolled out, and `GET /v1/info` returned the new field through the Service. |
| `./replica/replica.sh down` | The cluster was deleted. |
| Zero-context agent, brief only | **Finished unaided.** It made a JSON 405 + `Allow: GET` change to the API test-first (in its own copy; not part of this change), ran the build loop, `up` (94 s cold), checked the change with `forward` + curl, then `smoke` and `down`. It found the brief's architecture map and worked example led straight to `api.py`. Its friction is CF-07 onward, plus additions to CF-05 and CF-06. Two points it raised came from the snapshot it was given (the findings file did not exist yet, and a path test flagged bare file names) and are fixed in this change. |
| Re-run after fixing CF-07 | `up` passed in 81 s; no `kubectl port-forward` process was left; `down`. |

## Findings

### CF-01 — A rebuilt image does not roll out under the README's manual quickstart

**Against:** chart
**Severity:** major
**Evidence:** `charts/sortyard/values.yaml` sets `image.tag: ""`, which defaults to
`appVersion` (`0.1.0`), and `image.pullPolicy: IfNotPresent`. A contributor who follows the
README, changes code, rebuilds `ghcr.io/sortyard/sortyard:0.1.0`, runs `kind load` and then
`helm upgrade` gets an unchanged pod spec. Nothing restarts, and the old code keeps running
with no error. The replica works around this. `replica/replica.sh` (`build_image`) tags every
build by content (`replica-<image id>`) and passes `--set image.tag=…`; that is why the
second `up` above rolled out.
**What would fix it:** say so in the README's quickstart (rebuild with a new tag, or
`kubectl rollout restart`). Or give the chart an `image.digest` value, or a checksum
annotation, so a changed image changes the pod template.

### CF-02 — The shadow conductor's first pass races Postgres and the migrations, then waits a full interval

**Against:** chart
**Severity:** minor
**Evidence:** on the cold `up`, the first log lines of the shadow conductor were
`shadow: could not record the pass: connection failed: connection to server at
"10.96.244.40", port 5432 failed: Connection refused`. The next pass, 15 s later (the
replica's `shadow.interval`), succeeded. With the chart default (`interval: 300`), a fresh
install shows an empty DecisionLog for five minutes after an error that looks alarming. The
Deployment has no init container or readiness gate on the schema being migrated.
**What would fix it:** retry quickly at startup until the schema exists (e.g. wait for
`sortyard.schema_migration`), or add an init container that waits for it, as `migrate.sh`
already does for the database.

### CF-03 — The API has no authentication, so the replica's "auth shape" is the data-plane credentials only

**Against:** repo
**Severity:** major
**Evidence:** `src/sortyard/services/api.py` serves `/healthz`, `/readyz` and `/v1/info` to
anyone. `spec/openapi.json` declares security schemes, and the §7 permission matrix lives in
`spec/PERMISSIONS.md`, which is missing (goldfish GF1-09). The replica therefore reproduces
the auth that exists: the chart-generated Postgres password Secret (`secretKeyRef` in the
API and shadow pods) and the shadow's read-only Plane API key Secret, which the fake Plane
enforces (401 without it; the smoke test asserts `"unauthorized": 0`). It cannot prove API
auth, because there is none yet.
**What would fix it:** when the API gains authentication (SORTYARD-7), extend
`replica.sh smoke` to call the API with and without a credential, and fake the identity
provider under `replica/fakes/` if it is an outside one.

### CF-04 — The deployment topology is two of six services; the replica can only mirror that

**Against:** chart
**Severity:** minor
**Evidence:** `charts/sortyard/templates/` deploys the API and (opt-in) the shadow conductor.
`sortyard-context-assembler`, `sortyard-eval-runner`, `sortyard-sensor-runner` and
`sortyard-integrator` have no Deployment, although DESIGN.md §4 requires the eval and sensor
runners to be "separate deployments ... enforcing §1.4 by topology". The replica installs the
chart itself, so it will pick up each service as soon as the chart deploys it. Until then,
"faithful topology" means faithful to a partial chart.
**What would fix it:** chart templates for the remaining services as they gain work loops
(each later Phase task). No replica change is needed.

### CF-05 — A stock Debian/Ubuntu `python3` cannot run the documented `pip install -e '.[dev]'`

**Against:** docs
**Severity:** minor
**Evidence:** in this container, `python3 -m venv .venv` failed with "ensurepip is not
available" (the `python3-venv` package is not installed), and `python3 -m pip` gave "No
module named pip". The goldfish install run hit the same wall (GF1, Environment). The
workaround was `python3 -m venv --without-pip` plus `get-pip.py`. `AGENTS.md`'s build loop
now names it; the README's "Develop locally" block does not.
The zero-context agent hit it too. The brief's first fallback hint gave no URL for
`get-pip.py`; it now gives the full command.
**What would fix it:** name the OS package (`python3-venv`) or the workaround in the README
too, or ship a `uv`/container-based dev path that does not depend on the host Python's
packaging.

### CF-06 — Each `up` leaves another image tag behind on the host and the kind node

**Against:** replica
**Severity:** minor
**Evidence:** `build_image` in `replica/replica.sh` tags every build
`ghcr.io/sortyard/sortyard:replica-<id>` (that is the CF-01 workaround) and `kind load`s it.
Old tags are never removed. After many edit-and-`up` cycles, the host's Docker and the kind
node's containerd keep accumulating ~150 MB images. `down` deletes the node but leaves the
host's `replica*` images and the 1.04 GB `kindest/node` image. The zero-context agent found
four `replica*` images after its own `down`. `AGENTS.md` now says so.
**What would fix it:** after a successful rollout, remove the previous `replica-*` tags from
the host (`docker image rm`) and the node (`crictl rmi` via `docker exec`). A chart-level fix for CF-01
(a digest-pinned image) would remove the need for new tags altogether.

### CF-07 — `smoke` orphaned its `kubectl port-forward` processes (found by the zero-context agent; fixed here)

**Against:** replica
**Severity:** major
**Evidence:** after `./replica/replica.sh smoke` returned 0, `ps` showed two
`kubectl ... port-forward svc/sortyard-api :8080` / `svc/sortyard-fake-providers :8080`
processes reparented to PID 1. `start_forward` backgrounded the shell function `k`, so `$!`
was a subshell; `stop_forward` killed that subshell and left kubectl running. Repeated
`up`/`smoke` runs piled up forwards, and `down` did not remove them.
**What would fix it:** done in this change: `start_forward` runs
`(exec kubectl --context ... port-forward ...) &`, so `$!` is kubectl itself.
`tests/test_replica.py` asserts the pattern, and a re-run of `up` left no forward behind.

### CF-08 — Database tests need a host `psql`, and nothing said how to get one

**Against:** docs
**Severity:** minor
**Evidence:** `tests/pg.py` requires `shutil.which("psql")`. The brief showed how to start a
Postgres server in Docker but not that a client is needed. The zero-context agent had no
`psql` and no sudo. It wrote a shim that runs `psql` in a `postgres:16-alpine` container
(with `--network host` and the repo mounted, because `migrate.sh` passes `-f <file>`), which
made the database tests take 2 min 11 s. `AGENTS.md` now names the client package; the README
still does not.
**What would fix it:** name `postgresql-client` in the README too. Or let `tests/pg.py` fall
back to `docker run ... psql` when no host client exists, so `docker` alone is enough for
the full suite.

### CF-09 — The chart's install NOTES print kubectl commands with no context

**Against:** chart
**Severity:** minor
**Evidence:** `charts/sortyard/templates/NOTES.txt` prints `kubectl -n sortyard rollout status
...` and `kubectl -n sortyard port-forward ...`. `replica.sh up` shows these NOTES. Copied as
printed, they act on the user's *current* kube-context, which may be a different cluster.
This is at odds with the replica's guarantee that every call is pinned to `kind-sortyard`.
The zero-context agent flagged it. `AGENTS.md` now tells replica users to add `--context
kind-sortyard` or use the subcommands.
**What would fix it:** have the replica install pass `--hide-notes` (Helm ≥ 3.16) or print
its own next steps only. Optionally make the NOTES print the context Helm installed into.
