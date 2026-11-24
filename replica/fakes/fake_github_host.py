"""GitHub, faked for the local replica: its REST API and its git hosting, in one server.

The kernel service and the worker Jobs of the replica are the deployment's own; GitHub is the
outside provider they reach, and this stands where it would:

- every path but the ones below is GitHub's REST API, answered by the strict fake the tests
  use (`tests/fake_github.py`, held to GitHub's published API description): the kernel mints
  installation tokens as a GitHub App, opens pull requests, reads checks and merges here;
- `/git/<owner>/<name>.git/...` is git over HTTP (git's own `http-backend`) on a bare
  repository on disk: the worker's `clone` and `push` containers talk to it with the token
  the kernel minted. A token is accepted as GitHub would accept it: one the fake minted, not
  expired, for that repository, with `contents: read` to fetch and `contents: write` to push;
- what a worker pushed is what the API then shows: before every API call, and after every
  push, each branch head of the bare repository becomes the head the fake serves;
- `GET /_fake/state` gives the fake's contract violations and counts, and
  `GET /_fake/pull?repository=<owner>/<name>&branch=<branch>` the pull request of a branch, so
  the replica's smoke test can check what happened without a credential;
- `GET /healthz` is the fake's own liveness.

A merge is the fake's record only: the bare repository's base branch does not move, so every
item builds on the seed commit.

Run: `python fake_github_host.py --app-id ID --app-key-file KEY.pem --repository owner/name
[--root DIR] [--port 8080] [--url http://this-service:8080]`. It imports `tests.fake_github`,
so the directory above `tests/` must be on the import path: in the replica this file, the fake
and the vendored API description are mounted from one ConfigMap. It needs git, which the
Sortyard image has.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import logging
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import FrameType
from typing import Any
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from tests.fake_github import LEVELS, FakeGitHub, FakeRepo

log = logging.getLogger("fake-github")

GIT_PREFIX = "/git/"
BASE = "main"
RECEIVE = "git-receive-pack"
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "seed",
    "GIT_AUTHOR_EMAIL": "seed@example.invalid",
    "GIT_COMMITTER_NAME": "seed",
    "GIT_COMMITTER_EMAIL": "seed@example.invalid",
}

Reply = tuple[int, list[tuple[str, str]], bytes]


def _git(*args: str, cwd: pathlib.Path, stdin: str = "") -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={"PATH": os.environ.get("PATH", os.defpath), **_GIT_ENV},
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


class Host:
    """The fake's API and the bare repositories behind it, kept in step."""

    def __init__(self, fake: FakeGitHub, root: pathlib.Path) -> None:
        self.fake, self.root = fake, root
        self.repos: dict[str, FakeRepo] = {}
        self.counts = {"fetches": 0, "pushes": 0, "refused": 0}
        # One API call or one sync at a time: the fake's records are plain dictionaries.
        self._lock = threading.Lock()

    def bare(self, repository: str) -> pathlib.Path:
        return self.root / f"{repository}.git"

    def create(self, repository: str) -> FakeRepo:
        """A repository with one commit on its base branch, on disk and in the API."""
        bare = self.bare(repository)
        if not (bare / "HEAD").exists():
            bare.mkdir(parents=True, exist_ok=True)
            _git("init", "--quiet", "--bare", f"--initial-branch={BASE}", ".", cwd=bare)
            _git("config", "http.receivepack", "true", cwd=bare)
            blob = _git("hash-object", "-w", "--stdin", cwd=bare, stdin="seed\n")
            tree = _git("mktree", cwd=bare, stdin=f"100644 blob {blob}\tREADME.md\n")
            seed = _git("commit-tree", tree, "-m", "seed", cwd=bare)
            _git("update-ref", f"refs/heads/{BASE}", seed, cwd=bare)
        repo = self.repos[repository] = self.fake.repo(repository)
        head = _git("rev-parse", f"refs/heads/{BASE}", cwd=bare)
        repo.refs[f"refs/heads/{BASE}"] = self.fake.commit(repo, [], sha=head)
        self._sync()
        return repo

    def _heads(self, repository: str) -> dict[str, str]:
        listed = _git(
            "for-each-ref",
            "--format=%(refname:lstrip=2) %(objectname)",
            "refs/heads",
            cwd=self.bare(repository),
        )
        heads: dict[str, str] = {}
        for line in listed.splitlines():
            branch, _, sha = line.partition(" ")
            heads[branch] = sha
        return heads

    def _sync(self) -> None:
        """What was pushed to a bare repository is what the API shows."""
        for repository, repo in self.repos.items():
            for branch, sha in self._heads(repository).items():
                if branch != BASE and repo.refs.get(f"refs/heads/{branch}") != sha:
                    self.fake.push(repo, branch, sha=sha)

    def api(self, method: str, target: str, headers: Mapping[str, str], raw: bytes) -> Reply:
        with self._lock:
            self._sync()
            status, payload = self.fake.handle(method, target, headers, raw)
        return _json(status, payload)

    def state(self) -> Reply:
        with self._lock:
            found = {
                "violations": list(self.fake.violations),
                "requests": len(self.fake.requests),
                "tokens": len(self.fake.tokens),
                "git": dict(self.counts),
            }
        return _json(200, found)

    def pull(self, repository: str, branch: str) -> Reply:
        with self._lock:
            self._sync()
            repo = self.repos.get(repository)
            pulls = [pull for pull in repo.pulls if pull.branch == branch] if repo else []
            if not pulls:
                return _json(404, {"repository": repository, "branch": branch, "found": False})
            pull = pulls[-1]
            found = {
                "repository": repository,
                "branch": branch,
                "found": True,
                "number": pull.number,
                "open": pull.open,
                "merged": pull.merged,
                "head": pull.head,
                # The pull request's head is the commit a worker pushed over git.
                "pushed": self._heads(repository).get(branch) == pull.head,
            }
        return _json(200, found)

    def _may(self, repository: str, write: bool, authorization: str) -> bool:
        """Whether the request carries a token GitHub would take for this repository."""
        scheme, _, credential = authorization.partition(" ")
        try:
            _user, _, token = base64.b64decode(credential, validate=True).decode().partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return False
        with self._lock:
            repos, permissions, expires = self.fake.tokens.get(token, (set(), {}, 0.0))
        level = LEVELS.get(permissions.get("contents", ""), 0)
        return (
            scheme == "Basic"
            and repository in repos
            and expires > time.time()
            and level >= LEVELS["write" if write else "read"]
        )

    def git(self, method: str, target: str, headers: Mapping[str, str], raw: bytes) -> Reply:
        """One request of git's HTTP protocol, served by `git http-backend`."""
        split = urlsplit(target)
        path = split.path[len(GIT_PREFIX) - 1 :]
        repository = next((r for r in self.repos if path.startswith(f"/{r}.git/")), None)
        service = parse_qs(split.query).get("service", [path.rsplit("/", 1)[-1]])[0]
        write = service == RECEIVE
        if repository is None:
            return _json(404, {"message": "Not Found"})
        if not self._may(repository, write, headers.get("authorization", "")):
            self.counts["refused"] += 1
            return 401, [("WWW-Authenticate", 'Basic realm="fake GitHub"')], b""
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_PROJECT_ROOT": str(self.root),
            "GIT_HTTP_EXPORT_ALL": "1",
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": split.query,
            "CONTENT_TYPE": headers.get("content-type", ""),
            "CONTENT_LENGTH": str(len(raw)),
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_CONTENT_ENCODING": headers.get("content-encoding", ""),
            "GIT_PROTOCOL": headers.get("git-protocol", ""),
        }
        done = subprocess.run(
            ["git", "http-backend"], env=env, input=raw, capture_output=True, check=False
        )
        head, _, body = done.stdout.partition(b"\r\n\r\n")
        status, sent = 200, []
        for line in head.decode("latin-1").split("\r\n"):
            name, _, value = line.partition(":")
            if name.lower() == "status":
                status = int(value.split()[0])
            elif value and name.lower() != "content-length":
                sent.append((name, value.strip()))
        if done.returncode != 0 and not head:
            return _json(500, {"message": "git http-backend failed"})
        if method == "POST" and status == 200:
            self.counts["pushes" if write else "fetches"] += 1
            if write:
                with self._lock:
                    self._sync()
        return status, sent, body


def _json(status: int, payload: Any) -> Reply:
    data = b"" if payload is None else json.dumps(payload).encode()
    return status, [("Content-Type", "application/json")], data


class _Handler(BaseHTTPRequestHandler):
    host: Host
    protocol_version = "HTTP/1.1"

    def _body(self) -> bytes:
        if "chunked" not in self.headers.get("Transfer-Encoding", "").lower():
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))
        # git sends a large pack in chunks.
        body = b""
        while size := int(self.rfile.readline().split(b";")[0].strip() or b"0", 16):
            body += self.rfile.read(size)
            self.rfile.readline()
        self.rfile.readline()
        return body

    def _serve(self) -> None:
        raw = self._body()
        split = urlsplit(self.path)
        query = {name: values[0] for name, values in parse_qs(split.query).items()}
        lowered = {name.lower(): value for name, value in self.headers.items()}
        if split.path == "/healthz":
            reply = _json(200, {"status": "ok"})
        elif split.path == "/_fake/state":
            reply = self.host.state()
        elif split.path == "/_fake/pull":
            reply = self.host.pull(query.get("repository", ""), query.get("branch", ""))
        elif split.path.startswith(GIT_PREFIX):
            reply = self.host.git(self.command, self.path, lowered, raw)
        else:
            reply = self.host.api(self.command, self.path, dict(self.headers), raw)
        status, headers, data = reply
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

    def log_message(self, format: str, *args: Any) -> None:
        log.info("%s %s", self.address_string(), format % args)


class HostServer(ThreadingHTTPServer):
    daemon_threads = True


def make_server(
    host: str,
    port: int,
    *,
    app_id: str,
    public_key: rsa.RSAPublicKey,
    root: pathlib.Path,
    repositories: Sequence[str],
    url: str = "",
) -> tuple[HostServer, Host]:
    """The server (not yet serving) and the host behind it, with its repositories created."""
    fake = FakeGitHub(app_id, public_key)
    made = Host(fake, root)
    server = HostServer((host, port), type("Handler", (_Handler,), {"host": made}))
    fake.url = url or f"http://127.0.0.1:{server.server_address[1]}"
    for repository in repositories:
        made.create(repository)
    return server, made


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fake_github_host", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--url", default="", help="the URL clients reach this server at")
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--app-key-file", required=True, help="the App's private key (PEM)")
    parser.add_argument("--repository", action="append", required=True, help="owner/name")
    parser.add_argument("--root", default="/data", help="where the bare repositories live")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    key = serialization.load_pem_private_key(
        pathlib.Path(args.app_key_file).read_bytes(), password=None
    )
    if not isinstance(key, rsa.RSAPrivateKey):
        raise SystemExit("the App key is not an RSA private key")
    server, _ = make_server(
        args.host,
        args.port,
        app_id=args.app_id,
        public_key=key.public_key(),
        root=pathlib.Path(args.root),
        repositories=args.repository,
        url=args.url,
    )

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    log.info("fake GitHub (API + git) listening on %s:%s", args.host, args.port)
    with server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
