#!/bin/sh
# The workflow engine's setup steps (docs/decisions/workflow-engine.md): the commands of the
# chart's engine schema Job and of the engine server's init container (templates/engine.yaml),
# and what replica/engine_server.py runs with docker against a real Postgres.
#
# Usage: setup.sh schema | wait-schema | namespace
#
#   schema       In the engine's admin-tools image. Creates the engine's two databases when
#                SORTYARD_ENGINE_CREATE_DATABASES is true, then sets up and upgrades their
#                schemas with the upstream schema tool (temporal-sql-tool) to the version that
#                image ships, then records in the engine database that the schema is ready for
#                SORTYARD_ENGINE_SERVER_VERSION (the SQL in SORTYARD_ENGINE_MARK_FILE). Every
#                step skips what is already there, so it is safe to run again.
#                Connection: SQL_HOST, SQL_PORT, SQL_USER, SQL_PASSWORD (the tool reads them).
#   wait-schema  In the Postgres image. Returns once `schema` has recorded the schema as ready
#                for SORTYARD_ENGINE_SERVER_VERSION: the server never starts on a database that
#                is missing or older than it needs. After SORTYARD_ENGINE_WAIT_SECONDS without
#                the record it fails, saying what it waited for; the pod restarts it, so it
#                keeps trying and nothing is left waiting unseen.
#                Connection: the libpq PG* variables.
#   namespace    In the admin-tools image. Waits for the server at TEMPORAL_ADDRESS, then
#                creates the namespace SORTYARD_ENGINE_NAMESPACE, or sets the retention of the
#                one that exists, and returns once the namespace answers a query.
#
# Needs only sh and the tools named, so it runs in the stock images.
set -eu

wait_seconds=${SORTYARD_ENGINE_WAIT_SECONDS:-300}

# retry WHAT COMMAND...: run COMMAND every 2 s until it succeeds; after wait_seconds, run it
# once more with its output shown and fail.
retry() {
    what=$1
    shift
    waited=0
    until "$@" >/dev/null 2>&1; do
        if [ "$waited" -ge "$wait_seconds" ]; then
            echo "engine: gave up waiting for $what after ${wait_seconds}s:" >&2
            "$@" >&2
            exit 1
        fi
        echo "engine: waiting for $what"
        sleep 2
        waited=$((waited + 2))
    done
}

sql_tool() { temporal-sql-tool --plugin postgres12 "$@"; }

# schema_of DATABASE NAME: bring one database to the schema version the image ships.
schema_of() {
    if [ "${SORTYARD_ENGINE_CREATE_DATABASES:-true}" = true ]; then
        sql_tool --database "$1" create-database
    fi
    sql_tool --database "$1" setup-schema --version 0.0
    sql_tool --database "$1" update-schema --schema-dir "$schema_root/$2/versioned"
}

case ${1:-} in
schema)
    schema_root=${SORTYARD_ENGINE_SCHEMA_ROOT:-/etc/temporal/schema/postgresql/v12}
    # On a fresh install the Job starts alongside Postgres.
    retry "Postgres at $SQL_HOST:$SQL_PORT" nc -z "$SQL_HOST" "$SQL_PORT"
    schema_of "$SORTYARD_ENGINE_DATABASE" temporal
    schema_of "$SORTYARD_ENGINE_VISIBILITY_DATABASE" visibility
    sql_tool --database "$SORTYARD_ENGINE_DATABASE" \
        setup-schema --disable-versioning --schema-file "$SORTYARD_ENGINE_MARK_FILE"
    echo "engine: schema ready for server $SORTYARD_ENGINE_SERVER_VERSION"
    ;;
wait-schema)
    export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-5}"
    ready() {
        psql -X -q -tA -v ON_ERROR_STOP=1 -v version="$SORTYARD_ENGINE_SERVER_VERSION" <<'SQL' | grep -qx 1
SELECT 1 FROM sortyard_engine_schema WHERE server_version = :'version';
SQL
    }
    waited=0
    until ready 2>/dev/null; do
        if [ "$waited" -ge "$wait_seconds" ]; then
            echo "engine: no schema for server $SORTYARD_ENGINE_SERVER_VERSION after" \
                "${wait_seconds}s: the engine schema Job has not finished (see its pods' logs)." \
                "This container is restarted and waits again; a failed Job is removed after" \
                "its ttl and made again by the next install or upgrade of the release." >&2
            exit 1
        fi
        echo "engine: waiting for the schema Job (schema for server $SORTYARD_ENGINE_SERVER_VERSION)"
        sleep 2
        waited=$((waited + 2))
    done
    echo "engine: schema ready for server $SORTYARD_ENGINE_SERVER_VERSION"
    ;;
namespace)
    cli() { temporal "$@" --address "$TEMPORAL_ADDRESS"; }
    namespace=$SORTYARD_ENGINE_NAMESPACE
    retention=$SORTYARD_ENGINE_RETENTION
    retry "the engine server at $TEMPORAL_ADDRESS" cli operator cluster health
    if cli operator namespace describe --namespace "$namespace" >/dev/null 2>&1; then
        cli operator namespace update --namespace "$namespace" --retention "$retention" >/dev/null
    else
        # Lost a race with another run of this Job: the namespace is there, which is the point.
        cli operator namespace create --namespace "$namespace" --retention "$retention" ||
            cli operator namespace describe --namespace "$namespace" >/dev/null
    fi
    # A new namespace takes a moment to reach the server's caches; this also reads visibility.
    retry "namespace $namespace to answer" cli workflow list --namespace "$namespace" --limit 1
    echo "engine: namespace $namespace ready (retention $retention)"
    ;;
*)
    echo "usage: $0 schema|wait-schema|namespace" >&2
    exit 2
    ;;
esac
