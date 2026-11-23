"""Fake outside providers for the local replica: Plane's REST API and the production
conductor's pass log.

The replica runs the deployment's own chart; only the third-party systems it reads are faked,
and they are faked in the shape the real adapter (``sortyard.shadow.sources.PlaneSource``)
reads, so the shadow conductor is configured exactly as it is in production:

- ``GET /api/v1/workspaces/<slug>/...`` — Plane. Requires ``X-API-Key`` to equal
  ``FAKE_PLANE_API_KEY`` (the same Secret the shadow mounts), else 401, like Plane.
  ``?cursor=<c>`` selects a page, as Plane's cursor pagination does.
- ``GET /conductor/passes.json`` — the production conductor's pass log (unauthenticated:
  the adapter reads it without a credential).
- ``GET /healthz`` — the fake's own liveness.
- ``GET /_fake/audit`` — counts of reads, writes and unauthorized requests, so the replica's
  smoke test can prove the shadow stayed read-only and authenticated.

Every method but GET is refused with ``405 Allow: GET`` and counted as a write attempt.

Responses come from a fixtures file (``fixtures.json``): ``{"plane": {path: body}, "passes":
pass log}``. Standard library only: it runs in the Sortyard image, mounted from a ConfigMap.

Run: ``FAKE_PLANE_API_KEY=k python fake_plane.py [--port 8080] [--fixtures fixtures.json]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import signal
import sys
import threading
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import FrameType
from typing import Any
from urllib.parse import parse_qs, urlsplit

log = logging.getLogger("fake-plane")

PASS_LOG = "/conductor/passes.json"


def load_fixtures(path: str | os.PathLike[str]) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(pathlib.Path(path).read_text())
    if not isinstance(data.get("plane"), Mapping) or "passes" not in data:
        raise ValueError(f"{path}: fixtures need 'plane' (path -> body) and 'passes'")
    return data


class FakeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], fixtures: Mapping[str, Any], api_key: str):
        if not api_key:
            raise ValueError("the fake Plane needs an API key to enforce")
        self.fixtures = fixtures
        self.api_key = api_key
        self.audit = {"reads": 0, "writes": 0, "unauthorized": 0, "not_found": 0}
        self.lock = threading.Lock()
        super().__init__(address, Handler)

    def count(self, what: str) -> None:
        with self.lock:
            self.audit[what] += 1


class Handler(BaseHTTPRequestHandler):
    server: FakeServer

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        if path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if path == "/_fake/audit":
            with self.server.lock:
                self._json(HTTPStatus.OK, dict(self.server.audit))
            return
        if path == PASS_LOG:
            self.server.count("reads")
            self._json(HTTPStatus.OK, self.server.fixtures["passes"])
            return
        if path.startswith("/api/"):
            if self.headers.get("X-API-Key") != self.server.api_key:
                self.server.count("unauthorized")
                self._json(HTTPStatus.UNAUTHORIZED, {"detail": "Invalid API key"})
                return
            cursor = parse_qs(parts.query).get("cursor")
            key = f"{path}?cursor={cursor[0]}" if cursor else path
            body = self.server.fixtures["plane"].get(key)
            if body is not None:
                self.server.count("reads")
                self._json(HTTPStatus.OK, body)
                return
        self.server.count("not_found")
        self._json(HTTPStatus.NOT_FOUND, {"detail": "Not found."})

    def _refuse(self) -> None:
        self.server.count("writes")
        log.warning("refused write: %s %s", self.command, self.path)
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"detail": "read-only fake"}, allow="GET")

    do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

    def _json(self, status: HTTPStatus, body: Any, allow: str | None = None) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        log.info("%s %s", self.address_string(), format % args)


def make_server(host: str, port: int, fixtures: Mapping[str, Any], api_key: str) -> FakeServer:
    return FakeServer((host, port), fixtures, api_key)


def main(argv: Sequence[str] | None = None) -> int:
    here = pathlib.Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(prog="fake_plane", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--fixtures", default=str(here / "fixtures.json"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    server = make_server(
        args.host, args.port, load_fixtures(args.fixtures), os.environ.get("FAKE_PLANE_API_KEY", "")
    )

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    log.info("fake Plane + pass log listening on %s:%s", args.host, args.port)
    with server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
