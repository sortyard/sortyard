"""API service — the only door (design §4): console, agents and conductor are all its clients.

Endpoints:
  GET /healthz   200 while the process serves requests.
  GET /readyz    200 when Postgres answers, 503 otherwise (the Kubernetes readiness gate).
  GET /v1/info   name, version and the services of this package.
  /v1/workspaces/{workspace_id}/...   the Phase 1 REST surface of spec/openapi.json — tasks,
                 lanes, policy read paths, the DecisionLog, decisions, a build worker's stage-run
                 calls, findings, the Integrator instruction, role bindings and service-account
                 tokens — behind bearer tokens and the §7 permission matrix (sortyard.api).

Item change requests (`.../items/{item_id}/requests`) are sent to the item's workflow as a
signal, through the workflow engine at SORTYARD_ENGINE_TARGET (host:port). Without it the
service still serves everything else and answers those requests 503.

Admission (`POST .../items`) checks an item against the lane capability files in the directory
SORTYARD_LANES_DIR (`*.toml`, the files the kernel service reads) and starts its workflow on
that engine. Without both settings admission is answered 503.

Operator credential (interim, until OIDC sessions): ``sortyard-api --issue-operator-token
<role-binding-id>`` prints a bearer token for an admin/operator/viewer RoleBinding.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import signal
import socket
import struct
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import FrameType
from typing import Any

import psycopg
import psycopg.conninfo

from sortyard import __version__
from sortyard.api import auth, handlers, routing
from sortyard.engine.blocking import BlockingEngine
from sortyard.kernel import capabilities
from sortyard.kernel.item import start_item
from sortyard.services import SERVICES

log = logging.getLogger("sortyard.api")

# The Postgres SSLRequest message: length 8, code 80877103. Any Postgres server answers it with
# a single byte, 'S' or 'N', before authentication, so readiness proves "a Postgres is there"
# without credentials or a driver.
SSL_REQUEST = struct.pack("!ii", 8, 80877103)


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    database_host: str = "localhost"
    database_port: int = 5432
    database_timeout_seconds: float = 2.0
    database_name: str | None = None
    database_user: str | None = None
    database_password: str | None = None
    token_ttl_seconds: int = auth.DEFAULT_TTL_SECONDS
    #: host:port of the workflow engine. Unset: the service runs without one, and a change
    #: request for an item is answered 503.
    engine_target: str | None = None
    #: The directory of lane capability files (`*.toml`). Unset: admission is answered 503.
    lanes_dir: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        return cls(
            host=env.get("SORTYARD_API_HOST", cls.host),
            port=int(env.get("SORTYARD_API_PORT", cls.port)),
            database_host=env.get("SORTYARD_DATABASE_HOST", cls.database_host),
            database_port=int(env.get("SORTYARD_DATABASE_PORT", cls.database_port)),
            database_name=env.get("SORTYARD_DATABASE_NAME") or None,
            database_user=env.get("SORTYARD_DATABASE_USER") or None,
            database_password=env.get("SORTYARD_DATABASE_PASSWORD") or None,
            token_ttl_seconds=int(env.get("SORTYARD_API_TOKEN_TTL_SECONDS", cls.token_ttl_seconds)),
            engine_target=env.get("SORTYARD_ENGINE_TARGET") or None,
            lanes_dir=env.get("SORTYARD_LANES_DIR") or None,
        )

    def conninfo(self) -> str:
        """libpq connection string; fields left unset fall back to the PG* variables."""
        fields: dict[str, Any] = {
            "host": self.database_host,
            "port": self.database_port,
            "dbname": self.database_name,
            "user": self.database_user,
            "password": self.database_password,
            "connect_timeout": max(1, int(self.database_timeout_seconds)),
        }
        return psycopg.conninfo.make_conninfo(**{k: v for k, v in fields.items() if v is not None})


def postgres_answers(host: str, port: int, timeout: float) -> bool:
    """True when the listener at host:port speaks the Postgres protocol."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall(SSL_REQUEST)
            return conn.recv(1) in (b"S", b"N")
    except OSError:
        return False


Connect = Callable[[], "psycopg.Connection[Any]"]


def load_lanes(directory: str) -> dict[str, capabilities.Lane]:
    """Every lane capability file (`*.toml`) of a directory, by lane name. A file that breaks
    a rule, or a lane declared twice, is an error: the service does not start on it."""
    lanes: dict[str, capabilities.Lane] = {}
    for path in sorted(pathlib.Path(directory).glob("*.toml")):
        lane = capabilities.load(path.read_text())
        if lane.name in lanes:
            raise capabilities.CapabilityError("duplicate", f"lane {lane.name!r} in {path.name}")
        lanes[lane.name] = lane
    return lanes


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        config: Config,
        connect: Connect | None = None,
        signal_item: handlers.SignalItem | None = None,
        kernel: handlers.Kernel | None = None,
    ) -> None:
        self.config = config
        self.connect: Connect = connect or (lambda: psycopg.connect(config.conninfo()))
        self.signal_item = signal_item
        self.kernel = kernel
        self._engine: BlockingEngine | None = None
        if signal_item is None and config.engine_target:
            engine = self._engine = BlockingEngine(config.engine_target)
            self.signal_item = engine.signal
            if kernel is None and config.lanes_dir:

                def start(tenant: str, item: str, risk_tier: str) -> None:
                    engine.call(lambda e: start_item(e, item, tenant=tenant, risk_tier=risk_tier))

                self.kernel = handlers.Kernel(load_lanes(config.lanes_dir), start)
        super().__init__((config.host, config.port), Handler)

    def server_close(self) -> None:
        super().server_close()
        if self._engine is not None:
            self._engine.close()


class Handler(BaseHTTPRequestHandler):
    server: Server
    server_version = f"sortyard-api/{__version__}"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok"})
        elif path == "/readyz":
            cfg = self.server.config
            if postgres_answers(cfg.database_host, cfg.database_port, cfg.database_timeout_seconds):
                self._json(HTTPStatus.OK, {"status": "ready", "database": "ok"})
            else:
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"status": "unavailable", "database": "unreachable"},
                )
        elif path == "/v1/info":
            self._json(
                HTTPStatus.OK,
                {"name": "sortyard", "version": __version__, "services": sorted(SERVICES)},
            )
        else:
            self._operation("GET")

    def do_POST(self) -> None:
        self._operation("POST")

    def do_PATCH(self) -> None:
        self._operation("PATCH")

    def do_DELETE(self) -> None:
        self._operation("DELETE")

    def _operation(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        answer = routing.dispatch(
            method,
            self.path,
            {k: v for k, v in self.headers.items()},
            raw,
            self.server.connect,
            self.server.config.token_ttl_seconds,
            self.server.signal_item,
            self.server.kernel,
        )
        if answer is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        else:
            self._json(HTTPStatus(answer.status), answer.body, answer.content_type)

    def _json(
        self, status: HTTPStatus, body: object, content_type: str = "application/json"
    ) -> None:
        payload = b"" if status == HTTPStatus.NO_CONTENT else json.dumps(body).encode()
        self.send_response(status)
        if payload:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        log.info("%s %s", self.address_string(), format % args)


def make_server(
    config: Config,
    connect: Connect | None = None,
    signal_item: handlers.SignalItem | None = None,
    kernel: handlers.Kernel | None = None,
) -> Server:
    return Server(config, connect, signal_item, kernel)


def issue_operator_token(config: Config, role_binding_id: str, ttl_seconds: int) -> int:
    """Print a bearer token for an operator RoleBinding (the interim operator credential)."""
    try:
        with psycopg.connect(config.conninfo()) as conn:
            issued = auth.issue_operator_token(conn, role_binding_id, ttl_seconds)
    except (ValueError, psycopg.Error) as exc:
        print(f"sortyard-api: {exc}", file=sys.stderr)
        return 1
    print(issued.token)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sortyard-api",
        description="Sortyard API service. Configured by SORTYARD_API_* and "
        "SORTYARD_DATABASE_* environment variables.",
    )
    parser.add_argument(
        "--issue-operator-token",
        metavar="ROLE_BINDING_ID",
        help="print a bearer token for an admin/operator/viewer RoleBinding and exit "
        "(the interim operator credential until OIDC sessions)",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=12 * 3600,
        metavar="SECONDS",
        help="lifetime of a token from --issue-operator-token (default 43200)",
    )
    args = parser.parse_args(argv)
    if args.issue_operator_token:
        return issue_operator_token(Config.from_env(), args.issue_operator_token, args.ttl)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    server = make_server(Config.from_env())

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d, stopping", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    host, port = server.server_address[:2]
    log.info("sortyard-api %s listening on %s:%s", __version__, host, port)
    with server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
