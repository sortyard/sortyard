"""Acceptance: CI runs the repo's own checks on every pull request (design draft §9), and main
gates on exactly one required status check (policies/placement-defaults.yaml#gates).

The conductor's merge gate observes required checks. `ci.yml` therefore runs one job, `test`,
on every pull request to main and on push to main, and that job is the one required, strict
(up to date with main) check on main. main runs no other check, so no check main runs goes
unproven on the pull request. The slow suite (the kind replica boot) runs outside the gate, in
`slow.yml`, nightly and on demand. The one other job on main is `publish.yml`, which pushes the
image and can never run for a pull request (`tests/test_workflows.py` holds what it may do).
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ci.yml"
SLOW = WORKFLOWS / "slow.yml"
PUBLISH = WORKFLOWS / "publish.yml"
REQUIRED_CHECK = "test"


def load(path: pathlib.Path = WORKFLOW) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(path.read_text())
    return data


def as_triggers(on: object) -> dict[str, Any]:
    """A workflow's `on`, which may be one event name, a list of names or a map, as a map."""
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {str(name): None for name in on}
    assert isinstance(on, dict), on
    return {str(name): value for name, value in on.items()}


def triggers(path: pathlib.Path) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as boolean True.
    return as_triggers(load(path)[True])


def refused_events(path: pathlib.Path, on: dict[str, Any]) -> set[str]:
    """The events of a workflow other than ci.yml that the gate does not allow: any that run
    for a pull request, and a push, except the image publish's push."""
    gated = {"pull_request", "pull_request_target", "merge_group"}
    return (gated if path == PUBLISH else gated | {"push"}) & set(on)


def gate() -> dict[str, Any]:
    job: dict[str, Any] = load()["jobs"][REQUIRED_CHECK]
    return job


def run_lines(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_runs_on_every_pull_request_to_main_and_on_push_to_main() -> None:
    on = triggers(WORKFLOW)
    assert set(on) == {"pull_request", "push"}
    pr = on["pull_request"] or {}
    assert "paths" not in pr and "paths-ignore" not in pr, "every PR, not a filtered subset"
    assert pr.get("branches", ["main"]) == ["main"]
    assert on["push"]["branches"] == ["main"]
    assert "paths" not in on["push"] and "paths-ignore" not in on["push"]


def test_ci_has_exactly_one_job_and_it_is_the_required_check() -> None:
    jobs = load()["jobs"]
    assert list(jobs) == [REQUIRED_CHECK], "one job: the one required status check on main"
    job = gate()
    # The status-check context is the job's name; it must stay exactly the required one.
    assert job.get("name", REQUIRED_CHECK) == REQUIRED_CHECK
    # A gating job never passes on a failure it swallowed, and never fans out into contexts.
    assert "continue-on-error" not in job and "strategy" not in job and "if" not in job
    assert not any(step.get("continue-on-error") for step in job["steps"])


def test_no_other_workflow_runs_on_pull_requests_or_main() -> None:
    # main-stays-green: every check main runs is the required one; no non-gating checks. The
    # one exception is by name: the image publish, on push to main and never for a pull request.
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        if path == WORKFLOW:
            continue
        assert not refused_events(path, triggers(path)), path.name
    assert triggers(PUBLISH)["push"] == {"branches": ["main"]}


# The one label of the Sortyard org's runner scale set on the estate (SORTYARD-200; deployed from
# noncelogic/estate-gitops sortyard-ci/). No job runs on a GitHub-hosted runner.
RUNNER = "sortyard-ci"


def runs_on_hosted(runs_on: object) -> bool:
    """Whether a job's `runs-on` could pick a runner other than the estate set: anything but the
    set's one label, in any form `runs-on` takes (a label, a list of labels, a group map)."""
    return runs_on not in (RUNNER, [RUNNER])


def test_every_job_of_every_workflow_runs_on_the_estate_runners() -> None:
    jobs = {
        (path.name, name): job
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        for name, job in load(path)["jobs"].items()
    }
    assert {"ci.yml", "slow.yml", "publish.yml"} <= {name for name, _ in jobs}
    for where, job in jobs.items():
        assert not runs_on_hosted(job.get("runs-on")), where


def test_the_runner_rule_catches_a_hosted_runner_in_any_form() -> None:
    for runs_on in (
        "ubuntu-latest",
        ["ubuntu-latest"],
        ["self-hosted", "linux"],
        [RUNNER, "ubuntu-latest"],
        {"group": "Default"},
        "${{ matrix.os }}",
        None,
    ):
        assert runs_on_hosted(runs_on), runs_on
    assert not runs_on_hosted(RUNNER)
    assert not runs_on_hosted([RUNNER])


def test_the_other_workflow_rule_reads_every_form_of_on() -> None:
    """`on: push`, `on: [push]` and `on: {push: ...}` are the same trigger."""
    for name in ("push", "pull_request", "pull_request_target", "merge_group"):
        for text in (f"on: {name}", f"on: [{name}, workflow_dispatch]", f"on:\n  {name}:\n"):
            on = as_triggers(yaml.safe_load(text)[True])
            assert refused_events(SLOW, on) == {name}, text
            assert refused_events(PUBLISH, on) == ({name} - {"push"}), text
    for text in ("on: workflow_dispatch", "on: [schedule]", "on:\n  workflow_dispatch:\n"):
        assert not refused_events(SLOW, as_triggers(yaml.safe_load(text)[True])), text


def test_the_required_check_runs_lint_typecheck_tests_spec_chart_and_image() -> None:
    runs = run_lines(gate())
    for check in (
        "python -m sortyard.models.codegen --check",
        "ruff check",
        "ruff format --check",
        "mypy",
        "pytest tests",
        "pytest spec",
        "helm lint",
        "helm template",
        "docker build",
    ):
        assert check in runs, check


def test_chart_and_database_tests_are_required_in_ci_not_skipped() -> None:
    job = gate()
    assert job["services"]["postgres"]["image"].startswith("postgres:")
    assert job["env"]["SORTYARD_REQUIRE_HELM"] == "1"
    assert job["env"]["SORTYARD_REQUIRE_POSTGRES"] == "1"
    assert job["env"]["PGHOST"]


def test_brief_names_the_one_required_check() -> None:
    brief = (ROOT / "AGENTS.md").read_text()
    assert f"one required status check on `main` is `{REQUIRED_CHECK}`" in brief
    assert "strict" in brief


def test_slow_suite_boots_the_one_command_replica_outside_the_gate() -> None:
    on = triggers(SLOW)
    assert "schedule" in on and "workflow_dispatch" in on
    replica = load(SLOW)["jobs"]["replica"]
    runs = [step.get("run", "") for step in replica["steps"]]
    assert "./replica/replica.sh up" in runs
    assert any("./replica/replica.sh down" in run for run in runs)
    # Pinned to the versions AGENTS.md documents as tested.
    brief = (ROOT / "AGENTS.md").read_text()
    versions = [step.get("with", {}).get("version") for step in replica["steps"]]
    for version in ("v3.16.3", "v1.31.4"):
        assert version in versions and version in brief, version
    assert any("kind/releases/download/v0.25.0/" in run for run in runs)
    assert "v0.25.0" in brief


def test_the_slow_suite_runs_the_kernel_acceptance_against_the_booted_replica() -> None:
    """The one test that needs the cluster runs after the boot, told which cluster, and is
    named so that a renamed test fails the step (pytest exits 5 when nothing is selected)."""
    replica = load(SLOW)["jobs"]["replica"]
    steps = replica["steps"]
    runs = [step.get("run", "") for step in steps]
    boot = runs.index("./replica/replica.sh up")
    (step,) = [s for s in steps if "pytest tests/test_replica.py" in s.get("run", "")]
    assert steps.index(step) > boot
    assert step["env"]["SORTYARD_REPLICA_CLUSTER"] == "sortyard"
    selected = step["run"].split("-k", 1)[1].strip()
    names = [
        line.split("(")[0].removeprefix("def ")
        for line in (ROOT / "tests" / "test_replica.py").read_text().splitlines()
        if line.startswith("def test_")
    ]
    assert len([name for name in names if selected in name]) == 1
    assert "continue-on-error" not in step and "if" not in step


def test_the_image_smoke_runs_the_kernel_and_worker_entry_points_and_git() -> None:
    runs = run_lines(gate())
    for command in ("sortyard-conductor --once", "sortyard-api --help", "git --version"):
        assert f"sortyard:ci {command}" in runs, command
    assert "sortyard-kernel; test $? -eq 2" in runs
    assert "sortyard-worker | grep -q usage" in runs
