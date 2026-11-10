"""API service — the only door (design §4): console, agents and conductor are all its clients.

Phase 1 skeleton: liveness, Postgres-backed readiness and installation info. The REST surface
of spec/openapi.json lands with the core state API task; this module gives it a home.

Endpoints:
  GET /healthz   200 while the process serves requests.
  GET /readyz    200 when Postgres answers, 503 otherwise (the Kubernetes readiness gate).
  GET /v1/info   name, version and the services of this package.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import struct
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import FrameType

from sortyard import __version__
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

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Config:
        return cls(
            host=env.get("SORTYARD_API_HOST", cls.host),
            port=int(env.get("SORTYARD_API_PORT", cls.port)),
            database_host=env.get("SORTYARD_DATABASE_HOST", cls.database_host),
            database_port=int(env.get("SORTYARD_DATABASE_PORT", cls.database_port)),
        )


def postgres_answers(host: str, port: int, timeout: float) -> bool:
    """True when the listener at host:port speaks the Postgres protocol."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall(SSL_REQUEST)
            return conn.recv(1) in (b"S", b"N")
    except OSError:
        return False


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, config: Config) -> None:
        self.config = config
        super().__init__((config.host, config.port), Handler)


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
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _json(self, status: HTTPStatus, body: Mapping[str, object]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        log.info("%s %s", self.address_string(), format % args)


def make_server(config: Config) -> Server:
    return Server(config)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sortyard-api",
        description="Sortyard API service. Configured by SORTYARD_API_* and "
        "SORTYARD_DATABASE_* environment variables.",
    )
    parser.parse_args(argv)
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
