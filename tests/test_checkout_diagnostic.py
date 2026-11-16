"""Temporary DEVOPS-184 diagnostics retain failures without exposing job credentials."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github/workflows/ci.yml"


def diagnostic() -> dict[str, Any]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return dict(workflow["jobs"]["python"]["steps"][0])


def test_all_jobs_diagnose_before_unchanged_checkout_without_widening_permissions() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert job["steps"][0] == diagnostic()
        assert job["steps"][1] == {"uses": "actions/checkout@v4"}
    assert diagnostic()["continue-on-error"] is True
    assert diagnostic()["timeout-minutes"] == 1
    assert diagnostic()["env"] == {"DIAGNOSTIC_TOKEN": "${{ github.token }}"}


@pytest.mark.parametrize("git_status", [200, 404, "timeout"])
def test_job_token_probe_reports_status_without_logging_credentials_or_response_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], git_status: int | str
) -> None:
    secret = "synthetic-test-token-never-log"
    for key, value in {
        "DIAGNOSTIC_TOKEN": secret,
        "GITHUB_REPOSITORY": "sortyard/sortyard",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_JOB": "python",
        "GITHUB_EVENT_NAME": "push",
    }.items():
        monkeypatch.setenv(key, value)
    requests: list[urllib.request.Request] = []

    class Response:
        status = 200
        headers: ClassVar[dict[str, str]] = {"X-GitHub-Request-Id": "request-a"}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            pass

    class Opener:
        def open(self, request: urllib.request.Request, timeout: int) -> Response:
            assert timeout == 10
            requests.append(request)
            if request.full_url.startswith("https://github.com/") and git_status == "timeout":
                raise TimeoutError(secret)
            if request.full_url.startswith("https://github.com/") and git_status == 404:
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: Opener())
    lines = diagnostic()["run"].splitlines()
    program = "\n".join(lines[1:-1])
    exec(compile(program, "<checkout-diagnostic>", "exec"), {})
    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines()]
    assert [record["status"] for record in records] == [
        200,
        200,
        "network_error" if git_status == "timeout" else git_status,
        "network_error" if git_status == "timeout" else git_status,
    ]
    assert requests[0].headers["Authorization"] == "Bearer " + secret
    encoded = base64.b64encode(("x-access-token:" + secret).encode()).decode()
    assert requests[2].headers["Authorization"] == "Basic " + encoded
    assert requests[3].headers["Authorization"] == "Basic " + encoded
    assert secret not in output and encoded not in output
    assert "response_body" not in output
