#!/usr/bin/env bash
# Sortyard local replica: the deployment's shape on a throwaway kind cluster, in one command.
#
#   ./replica/replica.sh up        check tools, create the cluster, build + load the image,
#                                  deploy the fake providers and the chart, then smoke-test
#   ./replica/replica.sh smoke     re-run the smoke test against a running replica
#   ./replica/replica.sh lane      admit two items and see each merged (the second with the
#                                  kernel pod deleted mid-item) against a running replica
#   ./replica/replica.sh forward   expose the API on localhost:8080 (foreground; Ctrl-C stops)
#   ./replica/replica.sh status    pods, jobs and the Helm release
#   ./replica/replica.sh logs [C]  follow a component's logs (default shadow-conductor; api)
#   ./replica/replica.sh down      delete the cluster and everything in it
#   ./replica/replica.sh check     only check the prerequisites
#
# What it deploys is charts/sortyard itself (with replica/values.yaml layered on): the API
# Deployment + Service, Postgres StatefulSet + Service + password Secret, the migration Job,
# the shadow conductor, the workflow engine server and the kernel service with its Role. Only
# outside third-party providers are faked: Plane's REST API and the production conductor's
# pass log (replica/fakes.yaml, behind the same read-only API key Secret shape production
# uses), and GitHub, its API and its git hosting (replica/fake-github.yaml, behind a GitHub App
# key Secret made for the cluster). The lane's worker Jobs are real Jobs in the cluster, running
# the worker image: the Sortyard image plus a scripted agent (replica/worker/). Re-running `up`
# rebuilds the images and rolls out the change.
#
# Every kubectl/helm call is pinned to the replica's own context (kind-$CLUSTER): the script
# never touches whatever cluster your current kube-context points at.
#
# Environment: SORTYARD_REPLICA_CLUSTER (default sortyard), SORTYARD_REPLICA_NAMESPACE (default
# sortyard), SORTYARD_REPLICA_TIMEOUT (seconds per wait, default 300).
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CLUSTER=${SORTYARD_REPLICA_CLUSTER:-sortyard}
NAMESPACE=${SORTYARD_REPLICA_NAMESPACE:-sortyard}
TIMEOUT=${SORTYARD_REPLICA_TIMEOUT:-300}
RELEASE=sortyard
IMAGE_REPO=ghcr.io/sortyard/sortyard
API_KEY_SECRET=sortyard-replica-plane-read
FAKES_CONFIGMAP=sortyard-replica-fakes
FAKES=sortyard-fake-providers
# The lane half: the worker image, the fake GitHub and what an item is admitted against.
WORKER_REPO=ghcr.io/sortyard/sortyard-replica-worker
GITHUB_APP_SECRET=sortyard-replica-github-app
GITHUB_CONFIGMAP=sortyard-replica-fake-github
GITHUB=sortyard-fake-github
LANE=replica
LANE_REPOSITORY=replica/app
# The workspace, project and role binding replica/bootstrap.toml declares.
LANE_WORKSPACE=ws-replica-lane
LANE_PROJECT=proj-replica
LANE_BINDING=rb-replica

# Tool: minimum supported version, the version CI and this script are tested with, install docs.
KIND_MIN=0.20.0 KIND_TESTED=v0.25.0 KIND_URL=https://kind.sigs.k8s.io/docs/user/quick-start/#installation
KUBECTL_MIN=1.27.0 KUBECTL_TESTED=v1.31.4 KUBECTL_URL=https://kubernetes.io/docs/tasks/tools/
HELM_MIN=3.12.0 HELM_TESTED=v3.16.3 HELM_URL=https://helm.sh/docs/intro/install/
DOCKER_URL=https://docs.docker.com/get-docker/
CURL_URL=https://curl.se/download.html

say() { printf '==> %s\n' "$*"; }
die() { printf 'replica: %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '3,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
    printf 'usage: %s {up|smoke|lane|forward|status|logs|down|check}\n' "$0" >&2
    exit 2
}

# The replica's own cluster, never the ambient kube-context.
k() { kubectl --context "kind-$CLUSTER" --namespace "$NAMESPACE" "$@"; }
h() { helm --kube-context "kind-$CLUSTER" --namespace "$NAMESPACE" "$@"; }

# version_ge A B: true when dotted version A >= B (leading "v" ignored).
version_ge() {
    local IFS=.
    local -a a b
    read -r -a a <<<"${1#v}"
    read -r -a b <<<"${2#v}"
    local i
    for i in 0 1 2; do
        local x=${a[i]:-0} y=${b[i]:-0}
        if ((10#$x > 10#$y)); then return 0; fi
        if ((10#$x < 10#$y)); then return 1; fi
    done
    return 0
}

semver() { grep -oE 'v?[0-9]+\.[0-9]+\.[0-9]+' | head -n 1; }

# check_prereqs: every problem is reported, then the script stops before changing anything.
check_prereqs() {
    local problems=0 v
    if ! command -v docker >/dev/null 2>&1; then
        echo "docker: not found — install Docker ($DOCKER_URL)"
        problems=$((problems + 1))
    elif ! docker info >/dev/null 2>&1; then
        echo "docker: the daemon is not reachable (is Docker running, and may this user use it?)"
        problems=$((problems + 1))
    fi
    check_tool kind "$KIND_MIN" "$KIND_TESTED" "$KIND_URL" version || problems=$((problems + 1))
    check_tool kubectl "$KUBECTL_MIN" "$KUBECTL_TESTED" "$KUBECTL_URL" version --client ||
        problems=$((problems + 1))
    check_tool helm "$HELM_MIN" "$HELM_TESTED" "$HELM_URL" version --short ||
        problems=$((problems + 1))
    if ! command -v curl >/dev/null 2>&1; then
        echo "curl: not found — install curl ($CURL_URL)"
        problems=$((problems + 1))
    fi
    if ((problems > 0)); then
        echo
        echo "replica: $problems prerequisite problem(s); nothing was changed."
        echo "Tested with kind $KIND_TESTED, kubectl $KUBECTL_TESTED, helm $HELM_TESTED."
        return 1
    fi
    v=$(helm version --short 2>/dev/null | semver)
    say "prerequisites ok (helm $v; tested with kind $KIND_TESTED, kubectl $KUBECTL_TESTED, helm $HELM_TESTED)"
}

check_tool() {
    local tool=$1 min=$2 tested=$3 url=$4
    shift 4
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "$tool: not found — install $tool $tested (minimum v$min): $url"
        return 1
    fi
    local v
    v=$("$tool" "$@" 2>/dev/null | semver || true)
    if [[ -z $v ]]; then
        echo "$tool: could not read its version from '$tool $*'"
        return 1
    fi
    if ! version_ge "$v" "$min"; then
        echo "$tool: $tool v${v#v} is older than the minimum v$min — install $tested: $url"
        return 1
    fi
}

ensure_cluster() {
    if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
        say "kind cluster '$CLUSTER' exists"
    else
        say "creating kind cluster '$CLUSTER'"
        kind create cluster --name "$CLUSTER" --config "$ROOT/replica/kind.yaml" --wait "${TIMEOUT}s"
    fi
    k create namespace "$NAMESPACE" --dry-run=client -o yaml | k apply -f - >/dev/null
}

# build_image: builds the one Sortyard image and tags it by content, so a rebuilt image rolls
# out (a fixed tag with pullPolicy IfNotPresent would keep the old one running).
build_image() {
    say "building $IMAGE_REPO"
    docker build -q -t "$IMAGE_REPO:replica" "$ROOT" >/dev/null
    local id
    id=$(docker image inspect -f '{{.Id}}' "$IMAGE_REPO:replica")
    TAG=replica-${id#sha256:}
    TAG=${TAG:0:20}
    docker tag "$IMAGE_REPO:replica" "$IMAGE_REPO:$TAG"
    # The worker image: the Sortyard image plus the lane's agent (here a scripted one).
    docker build -q --build-arg BASE="$IMAGE_REPO:$TAG" -t "$WORKER_REPO:replica" \
        "$ROOT/replica/worker" >/dev/null
    id=$(docker image inspect -f '{{.Id}}' "$WORKER_REPO:replica")
    WORKER_TAG=replica-${id#sha256:}
    WORKER_TAG=${WORKER_TAG:0:20}
    docker tag "$WORKER_REPO:replica" "$WORKER_REPO:$WORKER_TAG"
    say "loading $IMAGE_REPO:$TAG and $WORKER_REPO:$WORKER_TAG into the cluster"
    kind load docker-image "$IMAGE_REPO:$TAG" "$WORKER_REPO:$WORKER_TAG" --name "$CLUSTER" \
        >/dev/null
    worker_image_by_digest
}

# worker_image_by_digest: sets WORKER_IMAGE to the worker image as a lane must name it, by
# digest. There is no registry: the digest is the one the node's containerd holds the loaded
# image under, and the image is given that name there so a Job that asks for it finds it.
worker_image_by_digest() {
    local node digest
    node=$(kind get nodes --name "$CLUSTER" | head -n 1)
    digest=$(docker exec "$node" ctr --namespace=k8s.io images ls "name==$WORKER_REPO:$WORKER_TAG" |
        grep -oE 'sha256:[0-9a-f]{64}' | head -n 1 || true)
    [[ -n $digest ]] || die "the node does not hold $WORKER_REPO:$WORKER_TAG"
    WORKER_IMAGE="$WORKER_REPO@$digest"
    docker exec "$node" ctr --namespace=k8s.io images tag --force \
        "$WORKER_REPO:$WORKER_TAG" "$WORKER_IMAGE" >/dev/null
    # The runtime learns the new name from containerd a moment later.
    local _
    for _ in $(seq 1 30); do
        docker exec "$node" crictl inspecti "$WORKER_IMAGE" >/dev/null 2>&1 && break
        sleep 1
    done
    docker exec "$node" crictl inspecti "$WORKER_IMAGE" >/dev/null ||
        die "the node's runtime does not know $WORKER_IMAGE"
    say "worker image: $WORKER_IMAGE"
}

# deploy_fake_github: GitHub's API and git hosting, behind a GitHub App key made for this
# cluster. The key is made in a container and piped into the Secret: it is never printed.
deploy_fake_github() {
    say "deploying the fake GitHub (API + git hosting)"
    if ! k get secret "$GITHUB_APP_SECRET" >/dev/null 2>&1; then
        docker run --rm "$IMAGE_REPO:$TAG" python -c '
import sys
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import rsa
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
sys.stdout.write(key.private_bytes(
    s.Encoding.PEM, s.PrivateFormat.TraditionalOpenSSL, s.NoEncryption()).decode())
' | k create secret generic "$GITHUB_APP_SECRET" --from-file=private-key.pem=/dev/stdin \
            >/dev/null
    fi
    local files=("$ROOT/replica/fakes/fake_github_host.py" "$ROOT/tests/fake_github.py"
        "$ROOT/tests/contracts/github/fragment.json")
    # Server-side: the files are too large for the annotation a client-side apply keeps.
    k create configmap "$GITHUB_CONFIGMAP" "${files[@]/#/--from-file=}" \
        --dry-run=client -o yaml | k apply --server-side --force-conflicts -f - >/dev/null
    local sha
    sha=$(cat "${files[@]}" | cksum | cut -d ' ' -f 1)
    sed -e "s|__IMAGE__|$IMAGE_REPO:$TAG|" -e "s|__FAKES_SHA__|$sha|" \
        "$ROOT/replica/fake-github.yaml" | k apply -f - >/dev/null
    k rollout status "deployment/$GITHUB" --timeout="${TIMEOUT}s"
}

deploy_fakes() {
    say "deploying the fake providers (Plane, production pass log)"
    if ! k get secret "$API_KEY_SECRET" >/dev/null 2>&1; then
        local key
        key=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
        k create secret generic "$API_KEY_SECRET" --from-literal=api-key="$key" >/dev/null
    fi
    k create configmap "$FAKES_CONFIGMAP" \
        --from-file="$ROOT/replica/fakes/fake_plane.py" \
        --from-file="$ROOT/replica/fakes/fixtures.json" \
        --dry-run=client -o yaml | k apply -f - >/dev/null
    local sha
    sha=$(cat "$ROOT/replica/fakes/fake_plane.py" "$ROOT/replica/fakes/fixtures.json" |
        od -An -tx1 | cksum | cut -d ' ' -f 1)
    sed -e "s|__IMAGE__|$IMAGE_REPO:$TAG|" -e "s|__FAKES_SHA__|$sha|" "$ROOT/replica/fakes.yaml" |
        k apply -f - >/dev/null
    k rollout status "deployment/$FAKES" --timeout="${TIMEOUT}s"
}

deploy_chart() {
    say "installing charts/sortyard as release '$RELEASE' (namespace $NAMESPACE)"
    # Helm returns once the post-install/upgrade migration Job has finished.
    # The lane capability file names the worker image by the digest the cluster holds.
    local lane_file
    lane_file=$(mktemp)
    sed "s|__WORKER_IMAGE__|$WORKER_IMAGE|g" "$ROOT/replica/lane.toml" >"$lane_file"
    h upgrade --install "$RELEASE" "$ROOT/charts/sortyard" \
        -f "$ROOT/replica/values.yaml" \
        --set image.tag="$TAG" \
        --set-file "kernel.lanes.$LANE=$lane_file" \
        --timeout "${TIMEOUT}s"
    rm -f "$lane_file"
    k rollout status "statefulset/$RELEASE-postgres" --timeout="${TIMEOUT}s"
    k rollout status "deployment/$RELEASE-api" --timeout="${TIMEOUT}s"
    k rollout status "deployment/$RELEASE-shadow-conductor" --timeout="${TIMEOUT}s"
    # The engine server starts once its schema Job has made the databases ready; the Job ends
    # once the server answers and the namespace exists.
    k rollout status "deployment/$RELEASE-engine" --timeout="${TIMEOUT}s"
    k wait --for=condition=complete job \
        --selector app.kubernetes.io/component=engine-schema --timeout="${TIMEOUT}s"
    # The kernel's pod waits for the engine, then serves.
    k rollout status "deployment/$RELEASE-kernel" --timeout="${TIMEOUT}s"
}

psql_value() {
    k exec "statefulset/$RELEASE-postgres" -- psql -X -q -tA -U sortyard sortyard -c "$1"
}

# start_forward SVC PORT: port-forward to a free local port; sets FORWARD_PORT, FORWARD_PID.
start_forward() {
    local log
    log=$(mktemp)
    # exec: $! must be kubectl itself, not a subshell that would orphan it when killed.
    (exec kubectl --context "kind-$CLUSTER" --namespace "$NAMESPACE" port-forward "svc/$1" ":$2") \
        >"$log" 2>&1 &
    FORWARD_PID=$!
    local _
    for _ in $(seq 1 50); do
        FORWARD_PORT=$(grep -oE '127\.0\.0\.1:[0-9]+' "$log" | head -n 1 | cut -d: -f2 || true)
        [[ -n $FORWARD_PORT ]] && break
        if ! kill -0 "$FORWARD_PID" 2>/dev/null; then
            cat "$log" >&2
            die "port-forward to svc/$1 failed"
        fi
        sleep 0.2
    done
    rm -f "$log"
    [[ -n $FORWARD_PORT ]] || die "port-forward to svc/$1 did not start"
}

stop_forward() { kill "$FORWARD_PID" 2>/dev/null || true; wait "$FORWARD_PID" 2>/dev/null || true; }

smoke() {
    say "smoke: API through its Service (port-forward, as the README's quickstart does)"
    start_forward "$RELEASE-api" 8080
    local api="http://127.0.0.1:$FORWARD_PORT" ready info
    trap stop_forward EXIT
    curl -fsS "$api/healthz" >/dev/null || die "GET /healthz failed"
    ready=$(curl -fsS "$api/readyz") || die "GET /readyz is not ready"
    [[ $ready == *'"database": "ok"'* ]] || die "GET /readyz: $ready"
    info=$(curl -fsS "$api/v1/info") || die "GET /v1/info failed"
    for service in api conductor context-assembler eval-runner integrator sensor-runner; do
        [[ $info == *"\"$service\""* ]] || die "GET /v1/info does not list $service: $info"
    done
    stop_forward
    trap - EXIT
    echo "    /healthz ok, /readyz $ready"
    echo "    /v1/info $info"

    say "smoke: migrations applied by the chart's Job"
    local migrations
    migrations=$(psql_value "SELECT count(*) FROM sortyard.schema_migration")
    ((migrations > 0)) || die "no migrations recorded in sortyard.schema_migration"
    echo "    $migrations migration(s) recorded"

    say "smoke: the workflow engine server answers the API pod, on the schema its Job made"
    local schema_for engine
    schema_for=$(k exec "statefulset/$RELEASE-postgres" -- \
        psql -X -q -tA -U sortyard temporal -c "SELECT server_version FROM sortyard_engine_schema")
    [[ -n $schema_for ]] || die "the engine schema Job recorded no schema version"
    # From the API's own pod, through sortyard.engine, at the address the chart gave it: an
    # unknown workflow is refused by name only by a server that has its namespace and its store.
    engine=$(k exec -i "deployment/$RELEASE-api" -- python - <<'PY'
import asyncio, os
from sortyard.engine import Engine, WorkflowNotFound

async def main() -> None:
    target = os.environ["SORTYARD_ENGINE_TARGET"]
    engine = await Engine.connect(target)
    try:
        await engine.recorded("replica-smoke-no-such-workflow")
    except WorkflowNotFound:
        print(f"engine at {target} answered")

asyncio.run(main())
PY
    ) || die "the API pod could not reach the engine server"
    [[ $engine == *answered ]] || die "the engine server did not answer as expected: $engine"
    echo "    $engine; schema ready for server $schema_for"

    say "smoke: the shadow conductor records every pass of the (fake) production pass log"
    # replica/fakes/fixtures.json's pass log holds two passes: one replayed from its retained
    # inputs, one (the newest) read live.
    local want=2 passes=0 _
    for _ in $(seq 1 $((TIMEOUT / 5))); do
        passes=$(psql_value "SELECT count(DISTINCT doc->'facts'->>'production_pass_id')
            FROM sortyard.event WHERE transition = 'shadow_pass'")
        ((passes >= want)) && break
        sleep 5
    done
    if ((passes < want)); then
        k logs "deployment/$RELEASE-shadow-conductor" --tail=40 >&2 || true
        die "the shadow recorded $passes of $want passes within ${TIMEOUT}s"
    fi
    psql_value "SELECT conductor_pass_id, task_id, decision FROM sortyard.decision_log
        ORDER BY recorded_at, (doc->'inputs'->>'preview_position')::int" | sed 's/^/    /'

    say "smoke: the shadow stayed read-only and authenticated against the fakes"
    start_forward "$FAKES" 8080
    trap stop_forward EXIT
    local audit
    audit=$(curl -fsS "http://127.0.0.1:$FORWARD_PORT/_fake/audit") || die "fake audit failed"
    stop_forward
    trap - EXIT
    [[ $audit == *'"writes": 0'* ]] || die "the shadow attempted writes: $audit"
    [[ $audit == *'"unauthorized": 0'* ]] || die "unauthenticated reads reached Plane: $audit"
    echo "    $audit"
    say "replica is up and smoke-tested"
}

item_state() {
    psql_value "SELECT coalesce(state, '') FROM sortyard.item
        WHERE workspace_id = '$LANE_WORKSPACE' AND id = '$1'"
}

# lane_diagnostics ITEM: what a failed wait leaves to read.
lane_diagnostics() {
    {
        echo "--- item $1: the states it entered"
        psql_value "SELECT sequence, state, cause, coalesce(detail::text, '') FROM sortyard.item_run
            WHERE workspace_id = '$LANE_WORKSPACE' AND item_id = '$1' ORDER BY sequence" || true
        echo "--- probe results"
        psql_value "SELECT need, passed, output FROM sortyard.probe_result
            WHERE workspace_id = '$LANE_WORKSPACE' AND item_id = '$1'" || true
        echo "--- jobs and pods"
        k get jobs,pods -o wide || true
        echo "--- kernel"
        k logs "deployment/$RELEASE-kernel" --all-containers --tail=80 || true
        echo "--- worker pods"
        k logs --selector app.kubernetes.io/managed-by=sortyard --all-containers --prefix \
            --tail=30 || true
        echo "--- fake GitHub"
        k logs "deployment/$GITHUB" --tail=40 || true
    } >&2
}

# wait_item ITEM STATE: until the item is in STATE.
wait_item() {
    local state="" _
    for _ in $(seq 1 $((TIMEOUT / 2))); do
        state=$(item_state "$1")
        [[ $state == "$2" ]] && return 0
        sleep 2
    done
    lane_diagnostics "$1"
    die "item $1 is in state '${state:-none}', not '$2', after ${TIMEOUT}s"
}

# bootstrap: the workspace, project, operator and role binding of replica/bootstrap.toml, made
# by the API service's own command (safe to run again: it creates only what is missing).
bootstrap() {
    local out
    out=$(k exec -i "deployment/$RELEASE-api" -- sortyard-api --bootstrap - \
        <"$ROOT/replica/bootstrap.toml" 2>&1) || die "sortyard-api --bootstrap failed: $out"
    printf '%s\n' "$out" | sed 's/^/    /'
}

admit() {
    local out
    out=$(k exec -i "deployment/$RELEASE-api" -- python - "$1" "$LANE_REPOSITORY" "$LANE" \
        "$LANE_WORKSPACE" "$LANE_PROJECT" "$LANE_BINDING" \
        <"$ROOT/replica/admit.py" 2>&1) || die "the API did not admit item $1: $out"
}

# github_get PATH: a GET of the fake GitHub's own report (no credential), through its Service.
github_get() {
    local out
    start_forward "$GITHUB" 8080
    trap stop_forward EXIT
    out=$(curl -fsS "http://127.0.0.1:$FORWARD_PORT$1") || die "fake GitHub: GET $1 failed"
    stop_forward
    trap - EXIT
    printf '%s' "$out"
}

# merged_on_github ITEM: the item's pull request is merged, and its head is the commit the
# worker Job pushed over git.
merged_on_github() {
    local pull
    pull=$(github_get "/_fake/pull?repository=$LANE_REPOSITORY&branch=sortyard/$1")
    [[ $pull == *'"merged": true'* && $pull == *'"pushed": true'* ]] ||
        die "item $1 is merged in Sortyard but not on the fake GitHub: $pull"
    echo "    $1 merged: $pull"
}

# active_worker_jobs: how many worker Jobs have a pod that has not ended.
active_worker_jobs() {
    k get jobs --selector app.kubernetes.io/managed-by=sortyard \
        -o jsonpath='{range .items[*]}{.status.active}{"\n"}{end}' | grep -c '^[1-9]' || true
}

# lane: the kernel takes an item from admitted to merged on the engine on Postgres, through
# real worker Jobs and the fake GitHub; and again with the kernel pod deleted mid-item.
lane() {
    local run first second state active pod
    run=$(date +%s)
    first="replica-$run-a" second="replica-$run-b"

    say "lane: sortyard-api --bootstrap makes the workspace, project and first operator"
    bootstrap

    say "lane: admit $first through the API and see it merged"
    admit "$first"
    wait_item "$first" merged
    merged_on_github "$first"

    say "lane: admit $second, delete the kernel pod while its build Job runs, see it merged"
    admit "$second"
    wait_item "$second" building
    # Mid-item means: the item is in `building` and its build Job is running in the cluster at
    # the moment the kernel pod is deleted. Both are read first, and the run fails otherwise.
    local _
    for _ in $(seq 1 30); do
        active=$(active_worker_jobs)
        ((active > 0)) && break
        sleep 1
    done
    pod=$(k get pods --selector app.kubernetes.io/component=kernel -o name)
    state=$(item_state "$second")
    active=$(active_worker_jobs)
    [[ $state == building ]] && ((active > 0)) ||
        die "item $second is in '$state' with $active worker Job(s) running: not mid-build"
    k delete "$pod" --wait=false >/dev/null
    echo "    deleted $pod with $second in '$state' (worker Jobs running: $active)"
    for _ in $(seq 1 "$TIMEOUT"); do
        k get "$pod" >/dev/null 2>&1 || break
        sleep 1
    done
    k rollout status "deployment/$RELEASE-kernel" --timeout="${TIMEOUT}s"
    [[ $(k get pods --selector app.kubernetes.io/component=kernel -o name) != "$pod" ]] ||
        die "the kernel pod was not replaced"
    wait_item "$second" merged
    merged_on_github "$second"

    say "lane: both items ran as workflows the engine stored in Postgres"
    local prefix="item:${#LANE_WORKSPACE}:$LANE_WORKSPACE" stored=0 _
    for _ in $(seq 1 15); do
        stored=$(k exec "statefulset/$RELEASE-postgres" -- \
            psql -X -q -tA -U sortyard temporal_visibility -c "SELECT count(*)
            FROM executions_visibility WHERE workflow_id IN ('$prefix:$first', '$prefix:$second')")
        [[ $stored == 2 ]] && break
        sleep 2
    done
    [[ $stored == 2 ]] || die "the engine's Postgres holds $stored of the 2 item workflows"
    echo "    engine: $stored item workflows in Postgres (temporal_visibility)"

    say "lane: the kernel and the workers stayed inside GitHub's published API"
    local report
    report=$(github_get /_fake/state)
    [[ $report == *'"violations": []'* ]] || die "the fake GitHub recorded violations: $report"
    [[ $report != *'"pushes": 0'* ]] || die "no worker pushed over git: $report"
    echo "    $report"
    say "lane: two items merged, the second across a kernel pod deletion"
}

forward() {
    say "API on http://localhost:8080 (Ctrl-C stops)"
    k port-forward "svc/$RELEASE-api" 8080:8080
}

logs() { k logs -f "deployment/$RELEASE-${1:-shadow-conductor}"; }

status() {
    h status "$RELEASE" || true
    k get pods,jobs,services
}

up() {
    check_prereqs || exit 1
    ensure_cluster
    build_image
    deploy_fakes
    deploy_fake_github
    deploy_chart
    smoke
    lane
    cat <<EOF

Next:
  ./replica/replica.sh forward                       # API on http://localhost:8080
  ./replica/replica.sh logs                          # follow the shadow conductor
  ./replica/replica.sh up                            # after a change: rebuild + roll out
  ./replica/replica.sh down                          # delete the cluster
EOF
}

down() {
    command -v kind >/dev/null 2>&1 || die "kind: not found ($KIND_URL)"
    say "deleting kind cluster '$CLUSTER'"
    kind delete cluster --name "$CLUSTER"
}

case "${1:-}" in
    up) up ;;
    smoke) smoke ;;
    lane) lane ;;
    forward) forward ;;
    status) status ;;
    logs) logs "${2:-}" ;;
    down) down ;;
    check) check_prereqs ;;
    *) usage ;;
esac
