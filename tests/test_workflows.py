"""Acceptance: the image is published from main only, by commit, with read-only permissions.

`publish.yml` builds the repository Dockerfile and pushes it to the deployer's registry
(SY-V3-ESTATE-DEPLOYED: "the image is published to the estate registry by the repository CI by
digest"). It holds the push credentials, so these tests hold what keeps them safe: it never runs
for a pull request, its token can only read, its secrets come from an environment limited to
main and reach two steps only, the image is tagged with the commit and nothing else is pushed,
the password reaches `docker login` on standard input, and the registry is named by a
repository variable.

Where a step is a script, the test runs the script itself, as the runner would (`bash -eo
pipefail`, the environment the job and the step give it), with a stand-in `docker` on PATH
that records every call and answers as told. No real docker, registry or network is used.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
PUBLISH = WORKFLOWS / "publish.yml"
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")

COMMIT = "c0ffee" + "0123456789abcdef" * 2 + "00"
REGISTRY = "registry.test"
USERNAME = "a-push-user"
PASSWORD = "a-push-password"
REPOSITORY = f"{REGISTRY}/sortyard/sortyard"
TAGGED = f"{REPOSITORY}:{COMMIT}"
DIGEST = "sha256:" + "0123456789abcdef" * 4
BY_DIGEST = f"{REPOSITORY}@{DIGEST}"
SECRETS = {"ACR_PUSH_USERNAME": USERNAME, "ACR_PUSH_PASSWORD": PASSWORD}

# The stand-in docker: records its arguments (and, for a login, its standard input), prints the
# repo digests it is told to for `image inspect`, and fails the one subcommand it is told to.
FAKE_DOCKER = """#!{python}
import json, os, sys
argv = sys.argv[1:]
call = {{"argv": argv}}
if argv[:1] == ["login"]:
    call["stdin"] = sys.stdin.read()
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(call) + "\\n")
if argv[:2] == ["image", "inspect"]:
    sys.stdout.write(os.environ.get("FAKE_REPO_DIGESTS", ""))
sys.exit(1 if argv[:1] == [os.environ.get("FAKE_DOCKER_FAILS", "")] else 0)
"""


def workflow() -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(PUBLISH.read_text())
    return data


def job() -> dict[str, Any]:
    (only,) = workflow()["jobs"].values()
    made: dict[str, Any] = only
    return made


def steps() -> list[dict[str, Any]]:
    every: list[dict[str, Any]] = job()["steps"]
    return every


def scripts() -> list[dict[str, Any]]:
    return [step for step in steps() if "run" in step]


@dataclasses.dataclass
class Run:
    """One step's script, run."""

    code: int
    said: str
    calls: list[dict[str, Any]]

    def docker(self, *first: str) -> list[list[str]]:
        return [c["argv"] for c in self.calls if c["argv"][: len(first)] == list(first)]


class Runner:
    """Runs the job's scripts the way the runner does, against the stand-in docker."""

    def __init__(self, tmp: pathlib.Path) -> None:
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        fake = self.bin / "docker"
        fake.write_text(FAKE_DOCKER.format(python=sys.executable))
        fake.chmod(0o755)
        self.log = tmp / "docker.jsonl"
        self.output = tmp / "output"
        self.summary = tmp / "summary"
        for path in (self.log, self.output, self.summary):
            path.write_text("")
        self.context = {
            "vars.ACR_REGISTRY": REGISTRY,
            "github.sha": COMMIT,
            "github.ref": "refs/heads/main",
            **{f"secrets.{name}": value for name, value in SECRETS.items()},
        }
        self.ref = "refs/heads/main"

    def outputs(self) -> dict[str, str]:
        lines = [line.split("=", 1) for line in self.output.read_text().splitlines()]
        return {name: value for name, value in lines}

    def value(self, text: object) -> str:
        """A workflow value with its expressions resolved; an unknown expression is an error."""

        def resolved(match: re.Match[str]) -> str:
            name = match[1]
            output = re.fullmatch(r"steps\.(\w+)\.outputs\.(\w+)", name)
            if output:
                assert [s for s in steps() if s.get("id") == output[1]], name
                return self.outputs().get(output[2], "")
            return self.context[name]

        return EXPRESSION.sub(resolved, str(text))

    def run(self, step: dict[str, Any], **env: str) -> Run:
        given = {**job().get("env", {}), **step.get("env", {})}
        environ = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "GITHUB_REF": self.ref,
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "FAKE_DOCKER_LOG": str(self.log),
            **{name: self.value(text) for name, text in given.items()},
            **env,
        }
        before = len(self.log.read_text().splitlines())
        done = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            env=environ,
            cwd=self.tmp,
            capture_output=True,
            text=True,
            timeout=60,
        )
        calls = [json.loads(line) for line in self.log.read_text().splitlines()[before:]]
        return Run(done.returncode, done.stdout + done.stderr, calls)

    def run_all(self, **env: str) -> list[tuple[dict[str, Any], Run]]:
        """The whole job: each script in order, a later one skipped after a failure unless it
        runs always."""
        done: list[tuple[dict[str, Any], Run]] = []
        failed = False
        for step in scripts():
            if failed and step.get("if") != "always()":
                continue
            ran = self.run(step, **env)
            failed = failed or ran.code != 0
            done.append((step, ran))
        return done


@pytest.fixture
def runner(tmp_path: pathlib.Path) -> Runner:
    return Runner(tmp_path)


def the_step(done: list[tuple[dict[str, Any], Run]], *first: str) -> tuple[dict[str, Any], Run]:
    """The one step whose script called `docker <first...>`."""
    (found,) = [(step, ran) for step, ran in done if ran.docker(*first)]
    return found


GOOD = {"FAKE_REPO_DIGESTS": f"other.test/sortyard/sortyard@sha256:{'f' * 64}\n{BY_DIGEST}\n"}


def test_publish_never_runs_for_a_pull_request() -> None:
    # PyYAML reads the bare key `on` as boolean True.
    on = workflow()[True]
    assert isinstance(on, dict) and set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"branches": ["main"]}
    assert not on["workflow_dispatch"], "no inputs: nothing a caller chooses reaches the job"


def test_publish_can_only_read_the_repository_and_runs_one_job_on_the_estate_runners() -> None:
    assert workflow()["permissions"] == {"contents": "read"}
    assert len(workflow()["jobs"]) == 1
    made = job()
    assert "permissions" not in made
    assert made["runs-on"] == "sortyard-ci"
    assert not {"container", "services", "strategy", "if", "continue-on-error", "uses"} & set(made)


def test_the_secrets_come_from_the_environment_limited_to_main() -> None:
    """The two secrets exist only in the environment `publish` (a repository setting limits its
    deployment branches to main): a job without it gets empty secrets on every branch."""
    assert job()["environment"] == "publish"


def test_one_publish_per_ref_at_a_time_and_a_running_one_is_never_cancelled() -> None:
    concurrency = workflow()["concurrency"]
    assert EXPRESSION.findall(concurrency["group"]) == ["github.ref"]
    assert concurrency["cancel-in-progress"] is False
    assert "concurrency" not in job()


def test_the_one_action_is_checkout_pinned_to_a_commit_without_its_credentials() -> None:
    (checkout,) = [step for step in steps() if "uses" in step]
    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", checkout["uses"])
    assert checkout["with"] == {"persist-credentials": False}, "the pushed commit, no token kept"
    assert set(checkout) == {"uses", "with"}
    # It is the second step: only the settings check runs before the repository is there.
    assert steps().index(checkout) == 1


def test_values_reach_a_script_through_its_environment_only() -> None:
    for step in scripts():
        assert "${{" not in step["run"], step.get("name")
        assert set(step) <= {"name", "id", "env", "run", "if"}, step.get("name")
        assert "shell" not in step and "working-directory" not in step
    # The registry is the repository variable and nothing else; no other variable is read.
    text = PUBLISH.read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    used = set(EXPRESSION.findall(code))
    assert {e for e in used if e.startswith("vars.")} == {"vars.ACR_REGISTRY"}
    assert {e for e in used if e.startswith("secrets.")} == {f"secrets.{name}" for name in SECRETS}
    assert not [e for e in used if e.startswith(("inputs.", "github.event", "github.head_ref"))]
    assert job()["env"]["REGISTRY"] == "${{ vars.ACR_REGISTRY }}"
    assert not re.search(r"[\w.-]+\.(io|com|net|azure\w*)/sortyard", code), "a registry by name"


def test_the_secrets_reach_the_settings_check_and_the_login_and_no_other_step(
    runner: Runner,
) -> None:
    done = runner.run_all(**GOOD)
    login, _ = the_step(done, "login")
    holders = [step for step in steps() if "secrets." in json.dumps(step)]
    assert holders == [steps()[0], login]
    for step in holders:
        assert step["env"] == {name: f"${{{{ secrets.{name} }}}}" for name in SECRETS}
    assert "secrets." not in json.dumps({k: v for k, v in job().items() if k != "steps"})
    assert "secrets." not in json.dumps({k: v for k, v in workflow().items() if k != "jobs"})


def test_no_step_is_conditional_or_may_fail_except_the_logout(runner: Runner) -> None:
    done = runner.run_all(**GOOD)
    logout, _ = the_step(done, "logout")
    assert logout == steps()[-1] and logout["if"] == "always()"
    for step in steps():
        assert "continue-on-error" not in step and "timeout-minutes" not in step, step.get("name")
    for step in steps()[:-1]:
        assert "if" not in step, step.get("name")
        assert not re.search(r"\|\|\s*(true|:)", step.get("run", "")), step.get("name")


def test_the_settings_check_stops_the_job_before_anything_else_when_one_is_missing(
    runner: Runner,
) -> None:
    check = steps()[0]
    assert "run" in check
    full = runner.run(check)
    assert full.code == 0 and not full.calls, full.said
    for name in ("REGISTRY", *SECRETS):
        missing = runner.run(check, **{name: ""})
        assert missing.code != 0, name
        assert "::error::" in missing.said and name.removeprefix("REGISTRY") in missing.said
        assert not missing.calls
    nothing = runner.run(check, REGISTRY="", ACR_PUSH_USERNAME="", ACR_PUSH_PASSWORD="")
    assert nothing.code != 0 and nothing.said.count("::error::") == 3
    # No value of a secret is ever printed, set or not.
    assert USERNAME not in full.said + nothing.said and PASSWORD not in full.said + nothing.said
    # A run asked for by hand on another branch stops here too.
    runner.ref = "refs/heads/some-branch"
    other = runner.run(check)
    assert other.code != 0 and "::error::" in other.said and not other.calls


def test_the_whole_job_builds_the_root_dockerfile_and_pushes_one_image_tagged_with_the_commit(
    runner: Runner,
) -> None:
    done = runner.run_all(**GOOD)
    assert [ran.code for _, ran in done] == [0] * len(scripts()), [r.said for _, r in done]
    calls = [call for _, ran in done for call in ran.calls]
    order = [call["argv"][0] for call in calls]
    # Built from the repository root's Dockerfile, under one name: the commit's.
    (build,) = [call["argv"] for call in calls if call["argv"][0] == "build"]
    assert build[-1] == "." and not {"-f", "--file", "--push", "--build-arg"} & set(build)
    assert not [word for word in build if word.startswith(("--file=", "-f=", "--tag=", "-t="))]
    assert [build[i + 1] for i, word in enumerate(build) if word in ("-t", "--tag")] == [TAGGED]
    # One push, of that name, and no other way of putting an image in a registry.
    assert [call["argv"] for call in calls if "push" in call["argv"]] == [["push", TAGGED]]
    assert not {"tag", "buildx", "manifest", "import", "load", "commit"} & set(order)
    assert not [call for call in calls if "--push" in call["argv"] or "imagetools" in call["argv"]]
    assert set(order) == {"build", "login", "push", "image", "pull", "run", "logout"}
    assert order.index("build") < order.index("login") < order.index("push")
    # Logged in to the variable's registry, and out of it at the end.
    assert order[-1] == "logout" and calls[-1]["argv"] == ["logout", REGISTRY]


def test_the_login_password_is_read_from_standard_input_and_is_on_no_command_line(
    runner: Runner,
) -> None:
    done = runner.run_all(**GOOD)
    calls = [call for _, ran in done for call in ran.calls]
    (login,) = [call for call in calls if call["argv"][0] == "login"]
    assert login["stdin"] == PASSWORD
    assert login["argv"] == ["login", REGISTRY, "--username", USERNAME, "--password-stdin"]
    for call in calls:
        assert not [word for word in call["argv"] if PASSWORD in word], call["argv"]
    assert not [ran.said for _, ran in done if PASSWORD in ran.said or USERNAME in ran.said]
    assert PASSWORD not in runner.output.read_text() + runner.summary.read_text()
    # A refused login stops the job before the push.
    (runner.tmp / "refused").mkdir()
    refused = Runner(runner.tmp / "refused")
    after = [call for _, ran in refused.run_all(FAKE_DOCKER_FAILS="login") for call in ran.calls]
    assert "push" not in [call["argv"][0] for call in after]


def test_the_digest_is_the_pushed_images_and_the_job_fails_when_there_is_none(
    runner: Runner,
) -> None:
    done = runner.run_all(**GOOD)
    push, _ = the_step(done, "push")
    step, ran = the_step(done, "image", "inspect")
    assert scripts().index(step) == scripts().index(push) + 1, "right after the push"
    # It asks for the digests of the name that was pushed, and takes this registry's.
    (inspect,) = ran.docker("image", "inspect")
    assert inspect[-1] == TAGGED
    assert runner.outputs() == {"image": BY_DIGEST, "digest": DIGEST, "commit": COMMIT}
    declared = {name: runner.value(text) for name, text in job()["outputs"].items()}
    assert declared == {"image": BY_DIGEST, "digest": DIGEST, "commit": COMMIT}
    assert runner.summary.read_text().splitlines() == [f"image={BY_DIGEST}", f"commit={COMMIT}"]

    for none in (
        "",
        f"other.test/sortyard/sortyard@{DIGEST}\n",  # only another registry's
        f"{REPOSITORY}@sha256:{'0' * 63}\n",  # short
        f"{REPOSITORY}@sha512:{'0' * 128}\n",
        f"{REPOSITORY}:{COMMIT}\n",  # a tag
    ):
        runner.output.write_text("")
        failed = runner.run(step, FAKE_REPO_DIGESTS=none)
        assert failed.code != 0 and "::error::" in failed.said, none
        assert runner.output.read_text() == "", none
    runner.output.write_text("")
    assert runner.run(step, FAKE_DOCKER_FAILS="image").code != 0
    assert runner.output.read_text() == ""


def test_the_pushed_image_is_pulled_by_its_digest_with_no_local_copy_and_smoke_tested(
    runner: Runner,
) -> None:
    done = runner.run_all(**GOOD)
    step, ran = the_step(done, "pull")
    digest_step, _ = the_step(done, "image", "inspect")
    assert scripts().index(step) > scripts().index(digest_step)
    calls = [call["argv"] for call in ran.calls]
    # The local name is removed first, so the pull is of what the registry holds.
    assert calls[:2] == [["image", "rm", TAGGED], ["pull", BY_DIGEST]]
    smokes = calls[2:]
    assert ["run", "--rm", BY_DIGEST, "sortyard-api", "--help"] in smokes
    assert ["run", "--rm", BY_DIGEST, "sh", "-c", "sortyard-kernel; test $? -eq 2"] in smokes
    assert all(call[:3] == ["run", "--rm", BY_DIGEST] for call in smokes), smokes
    # A pull, a removal or a smoke command that fails fails the step: nothing is swallowed.
    for failing in ("pull", "run", "image"):
        assert runner.run(step, FAKE_DOCKER_FAILS=failing).code != 0, failing
    # ... and a job whose pull fails reports no image in its summary.
    runner.summary.write_text("")
    again = runner.run_all(**GOOD, FAKE_DOCKER_FAILS="pull")
    assert [r.code for _, r in again if r.docker("pull")] == [1]
    assert runner.summary.read_text() == ""
    assert again[-1][1].docker("logout") == [["logout", REGISTRY]], "logged out all the same"


def test_the_logout_never_names_an_empty_registry(runner: Runner) -> None:
    """`docker logout ""` logs out of the default registry: with no registry there is none."""
    done = runner.run_all(REGISTRY="", REPOSITORY="/sortyard/sortyard", TAGGED="")
    assert [ran.code for _, ran in done] == [1, 0], "the settings check, then the logout only"
    assert not [call for _, ran in done for call in ran.calls]
