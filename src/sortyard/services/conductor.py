"""Conductor — single-writer claim loop and chain advancer (design §4).

Phase 1 runs the conductor in *shadow mode* only (``sortyard-conductor --shadow``, design §8):
on the production conductor's cadence it reads the real input path read-only, computes what it
would claim and refuse, and records that in the DecisionLog (see ``sortyard.shadow``). It
never claims, merges, comments or writes outside its own database. Without ``--shadow`` the
conductor is still the structure-only stub: real claims are Phase 3.

Shadow configuration (environment):
  SORTYARD_SHADOW_SOURCE        snapshot (default) | plane
  SORTYARD_SHADOW_SNAPSHOT      snapshot: a pass feed ({"passes": [board view, ...]}), a
                                directory of board views (one per pass) or a single board
                                view; file path or http(s) URL. Only a feed or directory
                                retains passes between reads, so only they record every pass
  SORTYARD_SHADOW_PLANE_URL     plane: base URL of the Plane instance
  SORTYARD_SHADOW_PLANE_WORKSPACE   plane: workspace slug
  SORTYARD_SHADOW_PLANE_PROJECTS    plane: comma-separated project ids
  SORTYARD_SHADOW_PLANE_API_KEY     plane: a READ-ONLY API key
  SORTYARD_SHADOW_LANES         plane: lane registry (products.json), file path or URL
  SORTYARD_SHADOW_PASSES        plane: the production conductor's pass log, file path or URL;
                                each new pass in it is recorded, replayed from the Plane
                                issues and gating output it retained (sources.PlaneSource)
  SORTYARD_SHADOW_GATING        optional: task_ready gating output, file path or URL
  SORTYARD_SHADOW_WORKSPACE     workspace the DecisionLog is scoped to (default ws-shadow)
  SORTYARD_DATABASE_HOST/PORT/NAME/USER/PASSWORD   the shadow's own database (libpq PG*
                                variables fill in whatever is unset)
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from collections.abc import Mapping, Sequence
from types import FrameType
from typing import Any

from sortyard.services import _stub

SUMMARY = "Conductor — single-writer claim loop and chain advancer (design §4)."

log = logging.getLogger("sortyard.conductor")

# drive.py's cadence: one production conductor pass about every five minutes.
DEFAULT_SHADOW_INTERVAL = 300.0


def source_from_env(env: Mapping[str, str]) -> Any:
    from sortyard.shadow import sources

    kind = env.get("SORTYARD_SHADOW_SOURCE", "snapshot")
    gating = env.get("SORTYARD_SHADOW_GATING") or None
    if kind == "snapshot":
        return sources.SnapshotSource(env["SORTYARD_SHADOW_SNAPSHOT"], gating=gating)
    if kind == "plane":
        return sources.PlaneSource(
            base_url=env["SORTYARD_SHADOW_PLANE_URL"],
            workspace_slug=env["SORTYARD_SHADOW_PLANE_WORKSPACE"],
            project_ids=[
                p.strip() for p in env["SORTYARD_SHADOW_PLANE_PROJECTS"].split(",") if p.strip()
            ],
            api_key=env["SORTYARD_SHADOW_PLANE_API_KEY"],
            lanes_path=env["SORTYARD_SHADOW_LANES"],
            gating=gating,
            passes=env["SORTYARD_SHADOW_PASSES"],
        )
    raise ValueError(f"SORTYARD_SHADOW_SOURCE must be 'snapshot' or 'plane', not {kind!r}")


def connect_kwargs(env: Mapping[str, str]) -> dict[str, str]:
    names = {"HOST": "host", "PORT": "port", "NAME": "dbname", "USER": "user"}
    names["PASSWORD"] = "password"
    return {
        key: env[f"SORTYARD_DATABASE_{suffix}"]
        for suffix, key in names.items()
        if env.get(f"SORTYARD_DATABASE_{suffix}")
    }


def provisional_installation(env: Mapping[str, str]) -> dict[str, Any]:
    """The installation record the DecisionLog's workspace hangs off, when none exists yet.

    Until the definitions loader seeds the real one (SORTYARD-12), the shadow writes this
    clearly-marked placeholder; ``.invalid`` hosts (RFC 2606) stand in for unknown endpoints.
    """
    namespace = env.get("SORTYARD_NAMESPACE", "sortyard")
    return {
        "id": env.get("SORTYARD_INSTALLATION_ID", "inst-sortyard"),
        "name": "provisional (created by the shadow conductor until the installation is seeded)",
        "cluster": {"name": env.get("SORTYARD_CLUSTER_NAME", "unknown")},
        "namespaces": {"control_plane": namespace, "workers": namespace},
        "storage": {"storage_class": ""},
        "ingress": {"host": "sortyard.invalid"},
        "auth_provider": {
            "kind": "oidc",
            "issuer": "https://sortyard.invalid/",
            "client_id": "sortyard-console",
        },
    }


_warned_single_view = False


def shadow_pass(env: Mapping[str, str]) -> bool:
    """One shadow poll: record every production pass not recorded yet. False when it could
    not complete."""
    import psycopg
    import psycopg.conninfo

    from sortyard.shadow import sources

    try:
        source = source_from_env(env)
    except (KeyError, ValueError) as exc:
        log.warning("shadow: input path unavailable, nothing recorded: %s", exc)
        return False
    workspace = env.get("SORTYARD_SHADOW_WORKSPACE", "ws-shadow")
    try:
        conninfo = psycopg.conninfo.make_conninfo(**connect_kwargs(env))
        with psycopg.connect(conninfo, autocommit=True) as conn:
            try:
                return _ingest(conn, source, workspace, env)
            except sources.SourceError as exc:
                log.warning("shadow: input path unavailable, nothing recorded: %s", exc)
                return False
    except psycopg.Error as exc:
        log.warning("shadow: could not record the pass: %s", exc)
        return False


def _ingest(conn: Any, source: Any, workspace: str, env: Mapping[str, str]) -> bool:
    from sortyard.shadow import evaluate, ledger, sources

    global _warned_single_view
    pending = source.pending(lambda pid: ledger.is_recorded(conn, pid))
    if getattr(source, "single_view", False) and not _warned_single_view:
        _warned_single_view = True
        log.warning(
            "shadow: %s is a single board view; production passes between reads are not"
            " observed — point SORTYARD_SHADOW_SNAPSHOT at a pass feed to record every pass",
            source.location,
        )
    ledger.ensure_workspace(conn, workspace, provisional_installation(env))
    policy = evaluate.ClaimPolicy()
    for snapshot in pending.snapshots:
        decisions = evaluate.evaluate(snapshot, policy)
        pass_id = ledger.record_pass(
            conn,
            workspace_id=workspace,
            snapshot=snapshot,
            policy=policy,
            decisions=decisions,
            ts=sources.now(),
        )
        if pass_id is None:
            log.info("shadow: pass for %s already recorded", snapshot.production_pass_id)
            continue
        claims = [d.item_id for d in decisions if d.claimed]
        log.info(
            "shadow: pass %s: would claim %s; refused %d (snapshot %s)",
            pass_id,
            claims or "nothing",
            len(decisions) - len(claims),
            snapshot.content_hash(),
        )
    return True


def run_shadow(once: bool, interval: float, env: Mapping[str, str]) -> int:
    stop = threading.Event()

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        log.info("received signal %d, stopping", signum)
        stop.set()

    if not once:
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)
    log.info("conductor: shadow mode (read-only; records would-claim decisions only)")
    while True:
        ok = shadow_pass(env)
        if once:
            return 0 if ok else 1
        if stop.wait(interval):
            log.info("conductor: shadow stopped")
            return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--shadow" not in args:
        return _stub.run("conductor", SUMMARY, args)
    parser = argparse.ArgumentParser(prog="sortyard-conductor", description=SUMMARY)
    parser.add_argument(
        "--shadow", action="store_true", help="observe-only: log would-claim decisions"
    )
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_SHADOW_INTERVAL,
        help="seconds between passes (default: drive.py's 300)",
    )
    parsed = parser.parse_args(args)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    return run_shadow(parsed.once, parsed.interval, os.environ)


if __name__ == "__main__":
    sys.exit(main())
