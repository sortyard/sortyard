"""Acceptance: the image is published from main only, by commit, with read-only permissions.

`publish.yml` builds the repository Dockerfile and pushes it to the deployer's registry
(SY-V3-ESTATE-DEPLOYED: "the image is published to the estate registry by the repository CI by
digest"). It holds the push credentials, so what these tests hold is what keeps them safe: it
never runs for a pull request, its token can only read, the image is tagged with the commit and
never with a tag that moves, the password reaches `docker login` on standard input, and the
registry is named by a repository variable, not in this repository.
"""

from __future__ import annotations

import pathlib
import re
import shlex
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
PUBLISH = WORKFLOWS / "publish.yml"
SHA = "${{ github.sha }}"
REGISTRY = "${{ vars.ACR_REGISTRY }}"
SECRETS = {"ACR_PUSH_USERNAME", "ACR_PUSH_PASSWORD"}
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


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


def words_of(line: str) -> list[list[str]]:
    """The commands of one shell line, each as its words: split where the shell splits them
    (a pipe, `;`, `&&`, `$(`), never inside a quoted word."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    found: list[list[str]] = [[]]
    for token in lexer:
        if set(token) <= set("();<>|&"):
            found.append([])
        else:
            found[-1].append(token)
    return [words for words in found if words]


def commands(name: str) -> list[list[str]]:
    """Every `docker <name> ...` command of the job, as its words, with the environment the
    job and the step give put in place of `$NAME` (so a tag is read as what it resolves to)."""
    found: list[list[str]] = []
    for step in steps():
        env: dict[str, str] = {**job().get("env", {}), **step.get("env", {})}

        def resolved(word: str, env: dict[str, str] = env) -> str:
            return re.sub(r"\$\{?(\w+)\}?", lambda m: env.get(m[1], m[0]), word)

        for line in step.get("run", "").splitlines():
            for words in words_of(line):
                if words[:2] == ["docker", name]:
                    found.append([resolved(word) for word in words])
    return found


def test_publish_never_runs_for_a_pull_request() -> None:
    # PyYAML reads the bare key `on` as boolean True.
    on = workflow()[True]
    assert set(on) == {"push", "workflow_dispatch"}
    assert on["push"] == {"branches": ["main"]}
    # ... and a run asked for by hand on another branch stops before it builds.
    first = steps()[0]["run"]
    assert "refs/heads/main" in first and "uses" not in steps()[0]


def test_publish_can_only_read_the_repository() -> None:
    assert workflow()["permissions"] == {"contents": "read"}
    assert "permissions" not in job()


def test_the_image_is_tagged_with_the_commit_and_no_moving_tag() -> None:
    wanted = f"{REGISTRY}/sortyard/sortyard:{SHA}"
    (build,) = commands("build")
    tags = [build[i + 1] for i, word in enumerate(build) if word in ("-t", "--tag")]
    assert tags == [wanted]
    assert not [word for word in build if word.startswith(("-t=", "--tag="))]
    pushes = commands("push")
    assert pushes == [["docker", "push", wanted]]
    assert not commands("tag"), "no second name for the image"
    # The build is of the checked-out commit, which is the one the tag names.
    checkout = [step for step in steps() if step.get("uses", "").startswith("actions/checkout@")]
    assert len(checkout) == 1 and "ref" not in checkout[0].get("with", {})
    assert steps().index(checkout[0]) < [i for i, s in enumerate(steps()) if "run" in s][1]


def test_the_login_password_is_read_from_standard_input() -> None:
    (login,) = commands("login")
    assert "--password-stdin" in login
    assert not [word for word in login if word in ("-p", "--password") or "--password=" in word]
    assert not [word for word in login if word.startswith("-p") and word != "--password-stdin"]
    # No secret is written into a script: each reaches a step as an environment variable.
    for step in steps():
        assert "secrets." not in step.get("run", ""), step.get("name")
        assert not [v for v in step.get("with", {}).values() if "secrets." in str(v)]
    named = set(re.findall(r"secrets\.(\w+)", PUBLISH.read_text().split("\njobs:")[1]))
    assert named == SECRETS
    assert "secrets." not in str(job().get("env", {})), "a secret only where it is used"


def test_the_registry_is_a_repository_variable_and_the_job_stops_early_without_it() -> None:
    expressions = set(EXPRESSION.findall(PUBLISH.read_text().split("\njobs:")[1]))
    assert "vars.ACR_REGISTRY" in expressions
    assert not [e for e in expressions if e.startswith("vars.") and e != "vars.ACR_REGISTRY"]
    # The check of the variable and both secrets is the first step, before any build.
    first = steps()[0]
    assert set(first["env"]) == SECRETS and "REGISTRY" in job()["env"]
    for name in ("REGISTRY", *SECRETS):
        assert re.search(rf'-z "\${name}"', first["run"]), name
    assert "exit" in first["run"]
    # No workflow, chart or script names a registry of the deployer's.
    for path in (
        *WORKFLOWS.iterdir(),
        *(ROOT / "charts").rglob("*"),
        *(ROOT / "replica").rglob("*"),
    ):
        if path.is_file():
            assert "azurecr" not in path.read_text(errors="replace"), path


def test_the_published_image_is_pulled_by_digest_and_smoke_tested_and_reported() -> None:
    outputs = job()["outputs"]
    assert {"image", "commit"} <= set(outputs)
    (step_id,) = set(re.findall(r"steps\.(\w+)\.outputs", " ".join(outputs.values())))
    (published,) = [step for step in steps() if step.get("id") == step_id]
    assert "sha256:[0-9a-f]{64}" in published["run"], "a digest of another shape stops the job"
    assert "image=$REPOSITORY@$digest" in published["run"]
    after = steps()[steps().index(published) + 1 :]
    pulls = commands("pull")
    assert pulls == [["docker", "pull", f"${{{{ steps.{step_id}.outputs.image }}}}"]]
    runs = [words[words.index("--rm") + 1 :] for words in commands("run")]
    image = pulls[0][2]
    assert [image, "sortyard-api", "--help"] in runs
    assert [image, "sh", "-c", "sortyard-kernel; test $? -eq 2"] in runs
    assert all(words[0] == image for words in runs), "the smoke runs the pulled image only"
    summary = "\n".join(step.get("run", "") for step in after)
    assert "GITHUB_STEP_SUMMARY" in summary


def test_publish_uses_only_actions_ci_uses_at_the_same_version() -> None:
    ci = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    known = {step["uses"] for step in ci["jobs"]["test"]["steps"] if "uses" in step}
    assert {step["uses"] for step in steps() if "uses" in step} <= known
    assert not [s for s in steps() if s.get("continue-on-error")]
