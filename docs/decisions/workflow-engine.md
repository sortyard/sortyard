# SY-DEC-007 — The durable workflow engine: Temporal

Date: 2026-11-23. Item: SY-V3-ENGINE-SURVIVES-FAILURE (SORTYARD-158; company/HARNESS-V3.md
section 3.1, phase 0). Status: decided under the owner's accepted plan; reversible as below.

## What was decided

The kernel's durable workflow engine is **Temporal**, reached only through `src/sortyard/engine/`.
That package is the only code that imports the SDK (`tests/test_engine_boundary.py`). It gives
the kernel four things. The kernel handles no Temporal type and catches no Temporal exception:
failures cross the boundary as the package's own `StepFailed`, `LimitPassed`, `WorkflowFailed`,
`WorkflowNotFound` and `EngineUnavailable`.

| The kernel asks for | `sortyard.engine` | On Temporal |
| --- | --- | --- |
| start a workflow | `Engine.start`, a function registered with `Registry.workflow` | one generic dynamic workflow that runs the registered function its type name selects |
| a durable timer | `Context.timer` | a workflow timer |
| a signal from outside | `Engine.signal`, `Context.wait_signal` | a workflow signal, buffered by the server |
| a step that is retried and recorded | `Context.step`, a function registered with `Registry.step` | one generic dynamic activity with a retry policy |

`Engine.recorded` reads where a workflow stands (finished steps, pending timers, accepted
signals, whether it is idle, and the error of a workflow-code defect the engine is retrying)
from the engine's records, never from a worker.

The hand-written transition, schedule, lease and queue code planned in the native-execution
design (closed pull request 13) is not written.

## The owner's answer this carries out

HARNESS-V3 decision 2: "Engine: Temporal on our Postgres, behind one module; DBOS as fallback",
with "phase 0 still runs the failure tests". Section 3.1 says the statements about both engines
were from general knowledge and that phase 0 verifies them with four failure tests. This record
is that verification for Temporal. It opens no new question.

## Options considered

| Option | Result on 2026-11-23 |
| --- | --- |
| Temporal (Python SDK `temporalio` 1.36.1, MIT) | **Chosen.** All four failure tests pass (below). |
| DBOS Transact (Python) | Not needed as the fallback. The conductor's earlier build of this item (closed pull request 17) reported that `dbos` 3.6.0 passed the same four tests against Postgres 16; that result was not re-run here. That build chose DBOS only because its worker could not download Temporal's test server (HTTP 403 from its egress proxy), which the item says is a worker gap to report, not a reason to change the engine. |
| Hand-written engine | Replaced by the owner's section 3.1 decision; not reconsidered. |

## Failure test results

Command: `pytest tests/test_engine_failure.py tests/test_engine_boundary.py`. Run on a
workstation (Python 3.12.3, Linux x86-64) and by the `test` job of the pull request that added
this record (Python 3.11). Versions: **temporalio 1.36.1**; the development server is pinned to
Temporal CLI v1.10.1, which reports Server 1.32.2; the time-skipping test server is pinned to
v1.36.0 (`sortyard/engine/testing.py` holds both pins).

The kill tests run real worker processes (`tests/engine_worker.py`) on the sample workflows of
`tests/engine_sample.py` and stop them with SIGKILL. A worker is killed only after the engine
itself reports the position the test means to kill it at; no test waits a fixed time.

| Test (`tests/test_engine_failure.py`) | Result |
| --- | --- |
| A workflow finishes after its worker is killed mid-step and finished steps do not run again | **Pass.** Step one ran once. The step the worker died in ran twice (once interrupted, once to its end), although its own timeout is 30 minutes. The last step ran once. |
| A waiting workflow keeps its position across a worker restart on changed step code | **Pass.** The new worker ran a changed copy of the sample. Step one was not run again and its recorded result was reused; the step after the wait ran on the new code. |
| A seven-day timer fires under the test clock | **Pass.** After six days on the test clock the timer was still pending; after the seventh it fired and the workflow finished, having waited seven days by the engine's clock. |
| A signal sent with no worker running is delivered when a worker starts | **Pass.** With every worker dead the engine accepted and kept the signal; a new worker delivered it. A second test starts and signals a workflow before any worker has ever run. |

More tests in the same file cover the rest of the boundary: a step that raises is retried and
recorded once; a step out of attempts fails the workflow unless the workflow catches
`StepFailed`; a signal wait can time out; a workflow id cannot be used twice; a step bounded by
a limit is abandoned when its durable timer fires first, and the workflow is reported idle at
its next wait; a defect in workflow code keeps the workflow running and is reported; calls on
an unknown or ended workflow raise `WorkflowNotFound`.

## What the tests showed about Temporal

These are properties the kernel has to design for. Each was observed in the runs above.

1. **A dead worker is noticed by silence; a hung step by its timeout.** The server does not
   know a worker died. The boundary makes every running step report in (a heartbeat) and tells
   the server to rerun a step that has been silent for 10 seconds, so the kill test's step was
   rerun in seconds although its timeout is 30 minutes. A step that hangs in a live worker keeps
   reporting in, so only its `timeout` ends it: `Registry.step` requires one. This fits the
   kernel rule that every state has a limit.
2. **A step may run more than once.** The interrupted step ran twice. Steps must be safe to
   repeat (at-least-once); only a step that finished is never run again.
3. **A restarted worker picks work up after a short delay.** The kill tests take 10 to 15
   seconds each, most of it the server waiting out the dead worker's task before handing it to
   the new one (about 10 seconds; this matches the SDK's default sticky-queue timeout, which is
   an inference, not something the tests isolate).
4. **Workflow code is replayed.** A restarted worker rebuilds a workflow's position by running
   the workflow function again against the recorded history. Step code may change freely.
   Workflow functions must stay deterministic, and a change to the order of steps, timers and
   waits before a workflow's current position breaks its replay. The kernel's generic workflow
   interprets a state table, so this is a rule for that one function.
5. **The SDK's import sandbox is off.** The SDK refuses workflow classes that are not at module
   level and re-imports workflow modules in a sandbox. The boundary uses one module-level
   dynamic workflow with the unsandboxed runner so the kernel can register plain functions.
   The cost: nothing checks determinism at import time; a broken rule shows as a replay error.
7. **An error in workflow code does not end the workflow.** Temporal treats an unexpected
   exception in a workflow function as a defect to fix and redeploy: the workflow stays running
   and the pass is retried. The boundary keeps that (work in flight survives a bad deploy) and
   reports the error as `Recorded.defect`. Only the boundary's own outcomes that a workflow lets
   through (`StepFailed`, `LimitPassed`, a signal wait's `TimeoutError`) fail the workflow.
6. **The test clock moves only when told, and not while a step runs.** On the time-skipping
   server a timer fires when the test advances the clock (`TestClock.advance`). With a step in
   progress the advance call did not return (it timed out), so a limit that beats a running
   step is tested on the development server in real time.

## Gaps against the item as written

- **Network beyond the package index.** The item allows "the tests running without an estate
  cluster or network beyond the package index". No cluster is needed. The package index is not
  enough: the SDK downloads the development server and the test server on first use from
  `temporal.download` (about 125 MB and 85 MB) and caches them in the system temporary
  directory. No Python package ships them. A build environment that blocks that host cannot run
  the engine tests; that is a declared need of the lane (HARNESS-V3 section 3.3), and the tests
  fail there, they do not skip.
- **"Temporal on our Postgres" was not verified by SORTYARD-158.** The development server keeps
  its state in memory and nothing was deployed. SORTYARD-183 closed this: see
  [The engine server on Postgres](#the-engine-server-on-postgres) below.

## The engine server on Postgres

Date: 2026-11-23. Item: SY-V3-CHART-ENGINE (SORTYARD-183; HARNESS-V3 sections 3.1 and 6). This
is where the engine first runs as a server on Postgres instead of the SDK's test servers.

### What the chart installs

With `engine.enabled=true`, `charts/sortyard/templates/engine.yaml` renders:

| Object | What it is |
| --- | --- |
| Deployment `<release>-engine` | The upstream server image `temporalio/server:1.32.2`, pinned by digest (`sha256:7bf69188a6232fea14869b9cef3d94aa82a1601d99517f7e86c71f22da4e0670`). One process runs all four services (frontend, history, matching, worker). An init container waits for the schema Job's record before the server starts. |
| Service `<release>-engine` | The one address, port 7233. The API's `SORTYARD_ENGINE_TARGET` is set to it. |
| Job `<release>-engine-schema-<hash>` | `temporalio/admin-tools:1.32.2` (digest `sha256:4a95866efba29d7e17ab012df5232795e8b0ad0f7d5f9d1ec4df321f7792a754`): the upstream schema tool `temporal-sql-tool`, then the `temporal` CLI. |
| ConfigMap `<release>-engine` | `charts/sortyard/engine/setup.sh` (the Job's and the init container's commands), the SQL of the schema record, and the server's dynamic configuration file. |

1.32.2 is the server version the development server of the SORTYARD-158 tests reports, so the
four failure tests now run against the same server version in memory and on Postgres.

**Store: Postgres only.** Two databases, `temporal` (workflow state) and `temporal_visibility`
(visibility), both through the server's `postgres12` plugin. No Cassandra and no Elasticsearch:
the templates set no setting of either, and `tests/test_chart.py` refuses one. The databases
are on the chart's Postgres, or on the external server the chart is pointed at
(`postgres.enabled=false`), or on an external server of the engine's own
(`engine.database.host`). The password is always a Secret reference; with an external database
rendering fails unless the Secret is named.

**Settings.** The server image has no configuration file. It builds its configuration from
environment variables through a template compiled into the server binary
(`common/config/config_template_embedded.yaml` in temporalio/temporal at v1.32.2), so the
Deployment sets `DB=postgres12`, `POSTGRES_SEEDS`, `DB_PORT`, `POSTGRES_USER`, `POSTGRES_PWD`
(from the Secret), `DBNAME`, `VISIBILITY_DBNAME`, `NUM_HISTORY_SHARDS` and `BIND_ON_IP`. Two
things found by running the image, not from its documentation:

- The server exits at start unless a dynamic configuration file exists at
  `DYNAMIC_CONFIG_FILE_PATH`; the image ships none. The ConfigMap provides one
  (`engine.dynamicConfig`, empty by default).
- Without an authorizer the server warns that a future version will refuse to start unless
  `--allow-no-auth` is given. The Deployment sets `TEMPORAL_ALLOW_NO_AUTH=true` (see the gaps).

**Schema.** The deprecated `auto-setup` image is not used. The Job's `schema` step runs, for
each database, `temporal-sql-tool create-database` (unless `engine.database.create=false`),
`setup-schema --version 0.0` and `update-schema --schema-dir` with the versioned schema the
admin-tools image ships, then records in the table `sortyard_engine_schema` of the engine
database that the schema is ready for server 1.32.2. The server's init container waits for that
row, so the server never starts on a missing or older schema, on install or on upgrade. The
Job's last step waits for the server and creates the `default` namespace (the one
`sortyard.engine` connects to) with the configured retention, or updates the retention of the
one that exists. Run a second time against the same Postgres, every step skipped what was
there (the tool reported "found zero updates from current version 1.19") and exited 0.

The Job is an ordinary Job, not a Helm hook, and its name ends in a hash of its whole rendered
spec and of the files it mounts. A post-install hook would deadlock `helm upgrade --wait`: Helm
would wait for the server, which waits for the Job, which a hook only starts after the wait. A
pre-install hook (what the upstream chart uses) cannot reach a Postgres that the same release
installs. A Job's pod template cannot be changed in place, so anything that changes the spec (a
value, the script, the server version, the chart version in its labels) has to make a new Job;
hashing the rendered spec itself is what guarantees that, and `tests/test_chart.py` holds it
over every value that reaches the Job and a chart version bump.

**When the schema Job fails.** Nothing waits on a person to delete it. The Job retries within
its `backoffLimit` and `activeDeadlineSeconds`. Finished, failed or not, it is removed after
`engine.schema.ttlSecondsAfterFinished` (10 minutes), so the next install or upgrade of the
release finds no Job and makes it again; running it again is safe. Meanwhile the server's init
container waits `engine.schema.waitSeconds` for the record, then fails with a message naming
what it waited for; the Deployment restarts it, so the pod shows as failing rather than
waiting, and starts by itself once a Job has succeeded. What this does not do: Helm has no
loop of its own, so with plain `helm upgrade` the Job is made again only at the next upgrade;
whatever applies the release on a schedule is what closes that. The cost of the ttl is that a
Job that succeeded is also made again, and runs again, on the first upgrade after it expires.
That the ttl removal and the re-creation happen on a cluster was not run; the wait's limit is
tested against a real Postgres in the merge gate.

**The two images move together.** Rendering fails when `engine.toolsImage.tag` is not
`engine.image.tag` (the schema tool carries the schema of its own server version), when a tag
is not a full version (`latest`, `main`, `1.32`), and when a tag is changed while its digest is
still the one this chart ships for 1.32.2.

### Rendered from our own templates, not the upstream chart

| Option | Weighed on 2026-11-23 |
| --- | --- |
| Our own templates (one Deployment, one Service, one Job, one ConfigMap; about 300 template lines and a 100-line script) | **Chosen.** One values file and one release stay true (a test refuses a second values file). Every credential is a Secret reference by construction. Postgres is the only store the templates can express. The schema Job can use the chart's own Postgres. Cost: we follow upstream's image changes ourselves; the two found above (embedded configuration, required dynamic configuration file) are the kind of change to expect at a version bump, and the slow workflow is what catches them. |
| The upstream chart as a dependency (`temporal` 1.8.0, appVersion 1.32.2, from go.temporal.io/helm-charts) | Not chosen. Rendered with its PostgreSQL example values it produces 6 Deployments, 6 Services, 2 ConfigMaps, 2 Secrets, a test Pod and a schema Job that is a pre-install/pre-upgrade hook, from about 700 lines of values that also cover Cassandra, MySQL, Elasticsearch, a web UI and an admin-tools Deployment. Its schema hook runs before the release's own objects exist, so it cannot use the chart's Postgres. Its datastore `password` is a plain value unless `existingSecret` is set, so the "Secret reference only" and "Postgres only" rules would be ours to enforce from outside, on a values surface we do not own. It is the better choice once the engine needs its services scaled apart; moving to it changes only these templates. |

One process for the four services is the size this kernel needs today (item counts, not
request volume). `engine.replicas` can be raised: each replica runs all four services and they
find each other through the membership table in Postgres. That was not tested with more than
one replica.

`engine.historyShards` is 16, and is fixed at the first start: the server refuses a database
made with another count. 16 is a judgement for a small single-server estate (the server's own
default is 4, the upstream chart's example 512), not a measured number.

### The four failure tests against the server on Postgres

`tests/test_engine_server.py` runs the four failure tests through `sortyard.engine` against a
server on a real Postgres. `replica/engine_server.py up` starts it with docker **from the
rendered chart**: it runs the Postgres StatefulSet's container, the schema Job's containers and
the server Deployment's containers with the image, command, environment, user and read-only
root filesystem of their manifests, so the server tested is the chart's (same server image,
same schema tool and script, same settings), short of the cluster. The tests are skipped unless
`SORTYARD_ENGINE_SERVER_TARGET` names a server; the slow workflow (`.github/workflows/slow.yml`,
job `engine-server`) sets it, runs them, runs the schema Job a second time, runs them again and
then counts the workflows in both Postgres databases. The merge gate does not start the server.

Run on a workstation on 2026-11-23 (Python 3.12.3, Linux x86-64, Postgres 16, server 1.32.2),
five times in a row against one server, then once more after a second run of the schema Job:

| Test | Result on the server on Postgres |
| --- | --- |
| A workflow finishes after its worker is killed mid-step and finished steps do not run again | **Pass.** The same test function as on the development server. |
| A waiting workflow keeps its position across a worker restart on changed step code | **Pass.** The same test function. |
| A long timer | **Pass, as a different test.** See below. |
| A signal sent with no worker running is delivered when a worker starts | **Pass.** The same test function. |

The slow workflow gave the same result on a GitHub-hosted runner (Python 3.11; run 45282104013
on the branch of this item, 2026-11-23): the four tests passed before and after the second run
of the schema Job, with 8 workflows of the `default` namespace in each database afterwards. In
the same run the kind replica rolled the server out behind its schema Job, and the API pod
reached it through `sortyard.engine` at `sortyard-engine:7233`.

Afterwards, on the workstation, the `default` namespace had its workflows in `temporal.executions` and in
`temporal_visibility.executions_visibility` (4 and 4 after one run of the four tests). The
server used about 130 MiB of memory after the tests; the four tests take about 54 seconds.

Differences from the SORTYARD-158 run, all in the tests and none in `src/sortyard/engine`:

- **The timer test is not the seven-day test.** A real server has no test clock to move, so the
  seven-day timer cannot be skipped through. The server test starts a real 8-second timer, kills
  the worker, waits until the engine records the timer as fired **with no worker running**, and
  then starts a new worker, which finishes the workflow. That shows what the test clock cannot:
  the timer is the server's, kept in Postgres, and does not need a worker to fire. A timer of
  days on this server is covered by the seven-day test only through the test server's clock.
- **Each test has its own task queue and workflow-id prefix.** The server outlives a test run,
  and a workflow id can be used once. The worker process reads its task queue from
  `SORTYARD_ENGINE_TASK_QUEUE`.

### Gaps and what is not yet shown

- **Nothing authenticates callers of the engine.** The server runs without an authorizer and
  without TLS; the Service is cluster-internal (ClusterIP). Anything in the cluster that can
  reach the Service can start and signal workflows. Closing that (network policy, or mTLS with
  an authorizer) is its own item.
- **TLS to an external Postgres is not wired.** The server image and the schema tool both take
  TLS settings, but the chart sets none, so an external server must accept password
  authentication without TLS from the cluster.
- **A server restart is checked by hand, not by a standing test.** The tests kill workers, not
  the server. Once, on the workstation run above: a workflow waiting for a signal was read
  back unchanged after the server container was restarted (finished step kept, still waiting),
  then took its signal and finished on a new worker. The server keeps nothing outside Postgres
  in this deployment (read-only root filesystem, no volume).
- **`engine.database.create=false` is tested at render only.** The script then skips
  `create-database`; that path was not run against a Postgres whose user cannot create databases
  (run by hand, `create-database` as such a user exits 1 with "permission denied").
- **The cluster path stops at kind.** The kind replica (`replica/replica.sh`, slow workflow job
  `replica`) enables the engine and checks that the server rolls out behind its schema Job and
  answers the API pod through `sortyard.engine`. The failure tests themselves run against the
  docker form above, not inside kind. Nothing has been deployed to the estate, and an upgrade
  from one server version to the next has not been run.

## How to reverse

Replace `src/sortyard/engine/_temporal.py` and `testing.py` with another engine's
implementation of the same names, and run the same tests. The server side is
`charts/sortyard/templates/engine.yaml`, `charts/sortyard/engine/setup.sh` and the `engine`
values: replace those with the other engine's deployment. Nothing outside the package imports
the SDK or handles a Temporal type, and the boundary test fails if that changes. Workflows in
flight do not move between engines: finish or restart them.
