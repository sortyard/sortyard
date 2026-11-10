"""Acceptance: the API service serves liveness, Postgres-backed readiness and installation info."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from sortyard import __version__
from sortyard.services import SERVICES, api


@pytest.fixture
def refused_port() -> Iterator[int]:
    """A port this test owns that refuses connections: bound but never listening.

    Holding the socket open for the whole test stops any other process claiming the port,
    so a connection to it is reliably refused.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        yield port


def recv_exactly(conn: socket.socket, n: int, timeout: float) -> bytes | None:
    """Read exactly ``n`` bytes, tolerating TCP splitting them; None on EOF or deadline."""
    deadline = time.monotonic() + timeout
    buf = b""
    while len(buf) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        conn.settimeout(remaining)
        try:
            chunk = conn.recv(n - len(buf))
        except (TimeoutError, OSError):
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


class FakePostgres:
    """Answers the Postgres SSLRequest the way a real server without TLS does: one byte, 'N'."""

    REQUEST_TIMEOUT_SECONDS = 5.0

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port: int = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                request = recv_exactly(conn, len(api.SSL_REQUEST), self.REQUEST_TIMEOUT_SECONDS)
                if request == api.SSL_REQUEST:
                    conn.sendall(b"N")

    def close(self) -> None:
        self.sock.close()


def serve(db_port: int) -> tuple[str, api.Server]:
    config = api.Config(
        host="127.0.0.1",
        port=0,
        database_host="127.0.0.1",
        database_port=db_port,
        database_timeout_seconds=0.5,
    )
    server = api.make_server(config)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def get(url: str) -> tuple[int, dict[str, object]]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


@pytest.fixture
def postgres() -> Iterator[FakePostgres]:
    pg = FakePostgres()
    yield pg
    pg.close()


def test_fake_postgres_answers_an_ssl_request_split_across_segments(
    postgres: FakePostgres,
) -> None:
    with socket.create_connection(("127.0.0.1", postgres.port), timeout=5) as conn:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        for byte in api.SSL_REQUEST:
            conn.sendall(bytes([byte]))
            time.sleep(0.01)
        assert conn.recv(1) == b"N"


def test_recv_exactly_reports_early_eof() -> None:
    a, b = socket.socketpair()
    with a, b:
        b.sendall(api.SSL_REQUEST[:3])
        b.close()
        assert recv_exactly(a, len(api.SSL_REQUEST), 1.0) is None


def test_healthz_is_ok_without_a_database(refused_port: int) -> None:
    base, server = serve(refused_port)
    try:
        assert get(f"{base}/healthz") == (200, {"status": "ok"})
    finally:
        server.shutdown()


def test_readyz_refuses_when_postgres_is_unreachable(refused_port: int) -> None:
    base, server = serve(refused_port)
    try:
        status, body = get(f"{base}/readyz")
        assert status == 503
        assert body["status"] == "unavailable"
    finally:
        server.shutdown()


def test_readyz_is_ready_when_postgres_answers(postgres: FakePostgres) -> None:
    base, server = serve(postgres.port)
    try:
        assert get(f"{base}/readyz") == (200, {"status": "ready", "database": "ok"})
    finally:
        server.shutdown()


def test_readyz_refuses_a_listener_that_is_not_postgres() -> None:
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()
    base, server = serve(silent.getsockname()[1])
    try:
        status, _ = get(f"{base}/readyz")
        assert status == 503
    finally:
        server.shutdown()
        silent.close()


def test_info_names_the_version_and_services(refused_port: int) -> None:
    base, server = serve(refused_port)
    try:
        status, body = get(f"{base}/v1/info")
        assert status == 200
        assert body == {"name": "sortyard", "version": __version__, "services": sorted(SERVICES)}
    finally:
        server.shutdown()


def test_unknown_path_is_404(refused_port: int) -> None:
    base, server = serve(refused_port)
    try:
        status, body = get(f"{base}/nope")
        assert status == 404
        assert body == {"error": "not_found"}
    finally:
        server.shutdown()


def test_config_reads_the_environment() -> None:
    config = api.Config.from_env(
        {
            "SORTYARD_API_PORT": "9000",
            "SORTYARD_DATABASE_HOST": "db",
            "SORTYARD_DATABASE_PORT": "6543",
        }
    )
    assert (config.host, config.port, config.database_host, config.database_port) == (
        "0.0.0.0",
        9000,
        "db",
        6543,
    )
