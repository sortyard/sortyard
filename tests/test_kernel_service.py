"""Acceptance (SY-V3-LANE-RUNTIME): the kernel service starts only on a complete configuration
and with every owner of the shipped table; its observer and its decision policy do what the
service relies on.

The settings, the assembly, the observer, the policy and the item workflow are real. The
observer test runs on the engine's development server and a fresh Postgres, with scripted
owners standing where the adapters would (the adapters themselves run in
tests/test_lane_runtime.py). Nothing here reaches GitHub or a cluster: assembling contacts
nothing.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import replace
from typing import Any

import pytest

from sortyard.engine import Registry
from sortyard.engine.testing import local_engine, time_skipping_engine
from sortyard.kernel import policy
from sortyard.kernel.item import register, start_item
from sortyard.kernel.ledger import Ledger
from sortyard.kernel.observer import Observer
from sortyard.kernel.states import shipped
from sortyard.kernel.store import Items
from sortyard.services import kernel
from tests.api_harness import WS
from tests.fake_github import APP_ID, PEM
from tests.kernel_db import Connect, admitted, database
from tests.kernel_harness import SILENT, Owners, until
from tests.pg import requires_postgres
from tests.runtime_harness import LANE as LANE_TEXT
from tests.worker_harness import LANE

ROOT = pathlib.Path(__file__).resolve().parent.parent
PASSWORD = "the-database-password-no-one-prints"
WORKER = """
[agents]
build = ["agent", "--build"]
fix = ["agent", "--fix"]
review = ["agent", "--review"]
[secrets]
MODEL_API_KEY = { secret = "models", key = "api-key" }
[services]
cluster-api = "http://cluster-api.test/healthz"
"""
TABLE_OWNERS = sorted(
    {state.owner for state in shipped().states.values() if state.owner and not state.decision}
)


def environment(root: pathlib.Path) -> dict[str, str]:
    """A complete configuration, as a deployment mounts it."""
    (root / "lanes").mkdir()
    (root / "lanes" / "walwarden.toml").write_text(LANE_TEXT)
    (root / "worker.toml").write_text(WORKER)
    (root / "app.pem").write_bytes(PEM)
    (root / "kube-token").write_text("a-cluster-token\n")
    return {
        "SORTYARD_ENGINE_TARGET": "engine.test:7233",
        "SORTYARD_DATABASE_HOST": "db.test",
        "SORTYARD_DATABASE_NAME": "sortyard",
        "SORTYARD_DATABASE_USER": "sortyard",
        "SORTYARD_DATABASE_PASSWORD": PASSWORD,
        "SORTYARD_LANES_DIR": str(root / "lanes"),
        "SORTYARD_WORKER_CONFIG": str(root / "worker.toml"),
        "SORTYARD_GITHUB_APP_ID": APP_ID,
        "SORTYARD_GITHUB_APP_KEY_FILE": str(root / "app.pem"),
        "SORTYARD_JOBS_NAMESPACE": "lanes",
        "SORTYARD_KUBE_URL": "http://kube.test",
        "SORTYARD_KUBE_TOKEN_FILE": str(root / "kube-token"),
    }


def test_the_service_exits_non_zero_and_names_every_missing_required_setting(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing required setting stops the service before it starts, with what is missing
    named; there are no optional credentials, and no value is printed."""
    complete = environment(tmp_path)
    assert kernel.main([], env={}) == 2
    said = capsys.readouterr().err
    assert all(name in said for name in kernel.REQUIRED)
    for name in kernel.REQUIRED:
        without = {key: value for key, value in complete.items() if key != name}
        assert kernel.main([], env=without) == 2, name
        said = capsys.readouterr().err
        assert name in said and PASSWORD not in said
        assert not [other for other in kernel.REQUIRED if other != name and other in said]
    # Cluster access is required too: a token file for a named API server, or a pod's own.
    assert kernel.main([], env={**complete, "SORTYARD_KUBE_TOKEN_FILE": ""}) == 2
    assert "SORTYARD_KUBE_TOKEN_FILE" in capsys.readouterr().err
    outside = {k: v for k, v in complete.items() if not k.startswith("SORTYARD_KUBE")}
    assert kernel.main([], env=outside) == 2
    assert "SORTYARD_KUBE_URL" in capsys.readouterr().err
    # In a pod, the service account stands in for both.
    in_cluster = {**outside, "KUBERNETES_SERVICE_HOST": "10.0.0.1"}
    assert kernel.Settings.from_env(in_cluster).kube_url is None


def test_a_setting_that_is_present_and_wrong_stops_the_service_too(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    complete = environment(tmp_path)
    (tmp_path / "empty").mkdir()
    (tmp_path / "not-a-key.pem").write_text("not a key")
    (tmp_path / "no-reviewer.toml").write_text(WORKER.replace("review =", "# review ="))
    (tmp_path / "unknown.toml").write_text(WORKER + "\n[surprise]\nkey = 1\n")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "lane.toml").write_text(LANE_TEXT.replace("slots = 2", "slots = 0"))
    (tmp_path / "policy.toml").write_text('version = 1\n[[rules]]\nanswer = "wait"\n')
    wrong = {
        "SORTYARD_GITHUB_APP_KEY_FILE": [
            str(tmp_path / "missing.pem"),
            str(tmp_path / "not-a-key.pem"),
        ],
        "SORTYARD_WORKER_CONFIG": [
            str(tmp_path / "no-reviewer.toml"),
            str(tmp_path / "unknown.toml"),
        ],
        "SORTYARD_LANES_DIR": [str(tmp_path / "empty"), str(tmp_path / "broken")],
        "SORTYARD_DECISION_POLICY": [str(tmp_path / "policy.toml")],
        "SORTYARD_OBSERVER_INTERVAL_SECONDS": ["0", "soon"],
    }
    for name, values in wrong.items():
        for value in values:
            assert kernel.main([], env={**complete, name: value}) == 2, (name, value)
            said = capsys.readouterr().err
            assert said.startswith("sortyard-kernel: ") and PASSWORD not in said, said


def test_the_service_registers_every_owner_of_the_shipped_table_and_refuses_one_missing(
    tmp_path: pathlib.Path,
) -> None:
    """Every owner the shipped table names has a function on the worker and, where its work
    ends outside the kernel, a look for the observer; an owner name with no owner registered
    is refused when the worker is put together."""
    settings = kernel.Settings.from_env(environment(tmp_path))
    assert settings.interval == 15 and settings.worker.secret_ref("MODEL_API_KEY") == (
        "models",
        "api-key",
    )
    assert settings.worker.agents["review"] == ["agent", "--review"]
    assert set(settings.lanes) == {"walwarden"} and settings.lanes["walwarden"].slots == 2
    runtime = kernel.assemble(settings)
    assert sorted(runtime.owners) == TABLE_OWNERS
    runtime.register(Registry())  # nothing missing
    # Only the capability-checker has no look: it answers in its own step, every time.
    assert sorted(set(TABLE_OWNERS) - set(runtime.looks)) == ["capability-checker"]
    for owner in TABLE_OWNERS:
        without = {name: fn for name, fn in runtime.owners.items() if name != owner}
        with pytest.raises(ValueError) as refused:
            replace(runtime, owners=without).register(Registry())
        assert owner in str(refused.value)


def test_sortyard_kernel_is_a_console_script_of_the_package() -> None:
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["sortyard-kernel"] == "sortyard.services.kernel:main"


def test_the_decision_policy_answers_what_a_rule_covers_and_nothing_else() -> None:
    """The decision step answers from the first matching rule; a question no rule covers gets
    no answer, so the item's default and then the table's apply. The shipped policy has no
    rules. A file that cannot be read in full is refused."""
    assert policy.shipped().rules == ()
    assert policy.shipped().decide({"state": "building", "cause": "limit"}) is None
    loaded = policy.load(
        """
version = 1
[[rules]]
state = "building"
outcome = "no-change"
answer = "wait"
reverse = "ask for a rebuild"
[[rules]]
state = "building"
answer = "rebuild"
reverse = "ask to resume"
[[rules]]
cause = "limit"
action = "narrow-or-split"
answer = "wait"
reverse = "ask to resume"
"""
    )

    def answer(**question: Any) -> str | None:
        reply = loaded.decide(
            {"state": None, "cause": None, "outcome": None, "action": None, **question}
        )
        assert reply is None or set(reply) == {"answer", "reverse"}
        return None if reply is None else reply["answer"]

    assert answer(state="building", cause="outcome", outcome="no-change") == "wait"
    assert answer(state="building", cause="limit") == "rebuild"  # the first rule did not match
    assert answer(state="fixing", cause="limit", action="narrow-or-split") == "wait"
    assert answer(state="fixing", cause="limit") is None
    assert answer(state="merging", cause="request") is None
    for broken in (
        "not toml [",
        "version = 2\nrules = []",
        "version = 1\nrules = 3",
        "version = 1\nsurprise = true",
        'version = 1\n[[rules]]\nanswer = "wait"',  # no way to reverse it
        'version = 1\n[[rules]]\nanswer = "wait"\nreverse = "x"\nwhen = "never"',
        'version = 1\n[[rules]]\nanswer = "wait"\nreverse = ""',
        'version = 1\n[[rules]]\nanswer = "wait"\nreverse = "x"\nstate = 3',
    ):
        with pytest.raises(ValueError):
            policy.load(broken)


def test_an_item_takes_the_policys_answer_and_falls_to_the_tables_default_without_one() -> None:
    """Through the real workflow: a build that changed nothing goes to the decision; with a
    rule the item waits, recorded as the policy's answer; with no rule it resumes, by the
    table's default."""
    rule = 'version = 1\n[[rules]]\nstate = "building"\noutcome = "no-change"\n'
    rule += 'answer = "wait"\nreverse = "send the item a rebuild request"\n'
    events: list[Mapping[str, Any]] = []
    owners = Owners(
        script={"building": [{"outcome": "no-change"}, {"outcome": "no-change"}, SILENT]}
    )

    async def scenario() -> None:
        for name, decide in (
            ("RULED", policy.load(rule).decide),
            ("UNRULED", policy.shipped().decide),
        ):
            registry = Registry()
            by_owner = {s.owner: owners.owner for s in shipped().states.values() if s.owner}
            register(registry, owners=by_owner, decide=decide, record=events.append)
            async with time_skipping_engine() as skipping:
                worker = asyncio.create_task(skipping.engine.run_worker(registry))
                try:
                    identifier = await start_item(skipping.engine, name, tenant="acme")
                    await until(
                        lambda: skipping.engine.recorded(identifier),  # noqa: B023
                        lambda recorded: recorded.idle,
                        f"{name} at rest",
                    )
                finally:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(scenario())

    def decided(item: str) -> list[tuple[str, str, str]]:
        return [
            (event["decision"]["answer"], event["decision"]["source"], event["state"])
            for event in events
            if event["item"] == item and event.get("decision")
        ]

    assert decided("RULED") == [("wait", "policy", "waiting")]
    assert decided("UNRULED")[0] == ("resume", "table", "building")


@pytest.fixture
def connect() -> Iterator[Connect]:
    yield from database()


@requires_postgres
def test_one_look_that_raises_does_not_stop_the_pass_for_other_items(
    connect: Connect, caplog: pytest.LogCaptureFixture
) -> None:
    """A pass asks each open stay's owner; one that raises, or answers something that is not
    an outcome, is passed over and the other items are still reported."""
    lanes = {LANE.name: replace(LANE, slots=3)}
    owners = Owners(script={"building": [SILENT, SILENT, SILENT]})
    looked: list[str] = []
    broken = {"X": True}

    def look(stay: Mapping[str, Any]) -> Any:
        looked.append(stay["item"])
        if stay["item"] == "X" and broken["X"]:
            raise RuntimeError("the cluster did not answer")
        if stay["item"] == "Z":
            return "built"  # not a reply
        return {"outcome": "built", "detail": {"head": "ab" * 20}}

    async def scenario() -> None:
        registry = Registry()
        by_owner = {s.owner: owners.owner for s in shipped().states.values() if s.owner}
        register(registry, owners=by_owner, decide=owners.decide, record=Ledger(connect).record)
        items = Items(connect)

        async def states() -> dict[str, str]:
            with connect() as conn:
                return dict(conn.execute("SELECT id, state FROM sortyard.item").fetchall())

        async with local_engine() as local:
            worker = asyncio.create_task(local.engine.run_worker(registry))
            try:
                for item in "XYZ":
                    admitted(connect, lanes, item, lane=LANE.name)
                    await start_item(local.engine, item, tenant=WS)
                await until(states, lambda s: set(s.values()) == {"building"}, "three builds")
                observer = Observer(local.engine, items.open_stays, {"executor": look})
                with caplog.at_level(logging.WARNING, logger="sortyard.kernel.observer"):
                    assert await observer.run_pass() == 1
                assert looked == ["X", "Y", "Z"]
                await until(states, lambda s: s["Y"] == "merged", "Y merged")
                assert (await states()) == {"X": "building", "Y": "merged", "Z": "building"}
                # Another pass, with the failure gone: X is reported; Z still says nothing.
                broken["X"] = False
                assert await observer.run_pass() == 1
                await until(states, lambda s: s["X"] == "merged", "X merged")
                assert (await states())["Z"] == "building"
                # An owner with no look is left to its limit; a pass over it sends nothing.
                assert await Observer(local.engine, items.open_stays, {}).run_pass() == 0
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(scenario())
    (warned,) = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert warned.args is not None and "X" in warned.args
