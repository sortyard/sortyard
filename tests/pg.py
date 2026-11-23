"""A throwaway Postgres database for tests, driven through `psql` (no Python driver needed).

Database tests run when `psql` is on PATH and PGHOST is set (standard libpq variables:
PGHOST, PGPORT, PGUSER, PGPASSWORD). CI sets SORTYARD_REQUIRE_POSTGRES=1, which turns "not
available" into a failure instead of a skip.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "charts" / "sortyard" / "migrations"
MIGRATE = MIGRATIONS / "migrate.sh"
PSQL = shutil.which("psql")
AVAILABLE = PSQL is not None and bool(os.environ.get("PGHOST"))

if not AVAILABLE and os.environ.get("SORTYARD_REQUIRE_POSTGRES"):
    raise RuntimeError("SORTYARD_REQUIRE_POSTGRES is set but psql/PGHOST are not available")

requires_postgres = pytest.mark.skipif(
    not AVAILABLE, reason="no Postgres (set PGHOST and put psql on PATH; CI requires it)"
)


class Database:
    """One database, addressed by name; every call is a fresh psql session."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.env = {**os.environ, "PGDATABASE": name}

    def run(
        self, sql: str, variables: Mapping[str, str] | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        assert PSQL is not None
        args = [PSQL, "-X", "-q", "-tA", "-v", "ON_ERROR_STOP=1"]
        for key, value in (variables or {}).items():
            args += ["-v", f"{key}={value}"]
        return subprocess.run(
            args, input=sql, env=self.env, capture_output=True, text=True, check=check
        )

    def value(self, sql: str, variables: Mapping[str, str] | None = None) -> str:
        return self.run(sql, variables).stdout.strip()

    def json(self, sql: str, variables: Mapping[str, str] | None = None) -> Any:
        return json.loads(self.value(sql, variables))

    def error(self, sql: str, variables: Mapping[str, str] | None = None) -> str:
        """Run a statement that must fail; return the server's error text."""
        proc = self.run(sql, variables, check=False)
        assert proc.returncode != 0, f"expected failure, got: {proc.stdout}"
        return proc.stderr

    def migrate(self, directory: pathlib.Path = MIGRATIONS) -> subprocess.CompletedProcess[str]:
        """Run the migration Job's script (from `directory`) against this database."""
        return subprocess.run(
            ["sh", str(directory / MIGRATE.name), str(directory)],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )


def fresh_database() -> Iterator[Database]:
    """Create an empty database, yield it, drop it."""
    admin = Database(os.environ.get("PGDATABASE", "postgres"))
    name = f"sortyard_test_{uuid.uuid4().hex[:12]}"
    admin.run(f'CREATE DATABASE "{name}"')
    try:
        yield Database(name)
    finally:
        admin.run(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
