#!/bin/sh
# Sortyard schema migrations: the command of the chart's migration Job
# (templates/migrate-job.yaml), and what tests/test_migrations.py runs against a fresh database.
#
# Usage: migrate.sh [DIR]      DIR holds NNNN_*.sql (default: this script's directory)
# Connection: the standard libpq variables PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD.
# Needs only sh, psql and sha256sum, so it runs in the stock Postgres image.
#
# Applies DIR/NNNN_*.sql in order. Each file runs in one transaction together with the row
# recording it in sortyard.schema_migration, so a migration lands entirely or not at all. A
# recorded migration is skipped, and refused if its file has changed since (sha256): released
# migrations are immutable; change the schema with a new file. On a fresh install the Job
# starts alongside Postgres, so it first waits up to SORTYARD_MIGRATE_WAIT_SECONDS (default
# 300) for the database to accept connections.
set -eu

dir=${1:-$(dirname "$0")}
wait_seconds=${SORTYARD_MIGRATE_WAIT_SECONDS:-300}
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-5}"
export PGOPTIONS="${PGOPTIONS:--c client_min_messages=warning}"

run_psql() { psql -X -q -v ON_ERROR_STOP=1 "$@"; }

waited=0
until run_psql -tAc 'SELECT 1' >/dev/null 2>&1; do
    if [ "$waited" -ge "$wait_seconds" ]; then
        echo "migrate: database not reachable after ${wait_seconds}s:" >&2
        run_psql -tAc 'SELECT 1' >/dev/null
        exit 1
    fi
    echo "migrate: waiting for the database"
    sleep 2
    waited=$((waited + 2))
done

run_psql <<'SQL'
CREATE SCHEMA IF NOT EXISTS sortyard;
CREATE TABLE IF NOT EXISTS sortyard.schema_migration (
    version text PRIMARY KEY,
    sha256 text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

applied=0
for file in "$dir"/[0-9][0-9][0-9][0-9]_*.sql; do
    if [ ! -e "$file" ]; then
        echo "migrate: no migrations in $dir" >&2
        exit 1
    fi
    version=$(basename "$file" .sql)
    sum=$(sha256sum "$file" | cut -d ' ' -f 1)
    recorded=$(echo "SELECT sha256 FROM sortyard.schema_migration WHERE version = :'version';" |
        run_psql -tA -v version="$version")
    if [ -n "$recorded" ]; then
        if [ "$recorded" != "$sum" ]; then
            echo "migrate: $version changed after it was applied (recorded sha256 $recorded," \
                "file $sum); add a new migration instead of editing a released one" >&2
            exit 1
        fi
        echo "migrate: $version already applied"
        continue
    fi
    echo "migrate: applying $version"
    echo "INSERT INTO sortyard.schema_migration (version, sha256) VALUES (:'version', :'sha256');" |
        run_psql --single-transaction -v version="$version" -v sha256="$sum" -f "$file" -f -
    applied=$((applied + 1))
done
echo "migrate: done ($applied applied)"
