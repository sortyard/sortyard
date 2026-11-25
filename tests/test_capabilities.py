"""Acceptance (SY-V3-PREFLIGHT-PROBES): a lane capability file that breaks a rule cannot load.

The loader is the rule (HARNESS-V3 section 3.3): these tests feed it a valid file with one
thing changed and expect it to refuse, naming the rule. The example file the package ships is
held to the same loader, and a task's needs are checked against the file.
"""

from __future__ import annotations

import pathlib
from datetime import timedelta

import pytest

from sortyard.kernel.capabilities import (
    KINDS,
    CapabilityError,
    Lane,
    Need,
    Repository,
    example_text,
    load,
)

DIGEST = "sha256:" + "a1" * 32
OTHER_DIGEST = "sha256:" + "b2" * 32

VALID = f"""
version = 1
lane = "walwarden"
resolver = "platform"
gap-limit = "2h"
runner-pool = "walwarden-runners"
defaults = ["repository:walwarden/app"]

[images]
worker = "registry.test/walwarden/worker@{DIGEST}"
ci = "registry.test/walwarden/ci@{DIGEST}"

[[repositories]]
name = "walwarden/app"
workflow-files = true

[[repositories]]
name = "walwarden/charts"

[[secrets]]
name = "DEPLOY_TOKEN"

[[secrets]]
name = "REGISTRY_PASSWORD"

[[services]]
name = "cluster-api"
"""


def changed(old: str, new: str) -> str:
    assert VALID.count(old) == 1, old
    return VALID.replace(old, new)


def refused(text: str) -> CapabilityError:
    with pytest.raises(CapabilityError) as caught:
        load(text)
    return caught.value


def test_a_valid_file_loads_as_typed_values() -> None:
    lane = load(VALID)
    assert isinstance(lane, Lane)
    assert (lane.name, lane.resolver, lane.runner_pool) == (
        "walwarden",
        "platform",
        "walwarden-runners",
    )
    assert lane.worker_image.reference == f"registry.test/walwarden/worker@{DIGEST}"
    assert lane.ci_image is not None
    assert lane.worker_image.digest == lane.ci_image.digest == DIGEST
    assert lane.repositories == {
        "walwarden/app": Repository("walwarden/app", workflow_files=True),
        "walwarden/charts": Repository("walwarden/charts", workflow_files=False),
    }
    assert lane.secrets == ("DEPLOY_TOKEN", "REGISTRY_PASSWORD")
    assert lane.services == ("cluster-api",)
    assert (lane.gap_limit, lane.gap_limit_text) == (timedelta(hours=2), "2h")
    # Every task needs the worker image and the runner pool; the file adds the rest.
    assert [need.text for need in lane.defaults] == [
        "worker-image",
        "runner-pool",
        "repository:walwarden/app",
    ]


def test_loading_fails_when_the_worker_image_digest_differs_from_the_ci_image_digest() -> None:
    """Loading fails when the worker image digest differs from the CI image digest."""
    error = refused(changed(f"ci@{DIGEST}", f"ci@{OTHER_DIGEST}"))
    assert error.rule == "worker-image-is-ci-image"
    assert "walwarden" in str(error) and DIGEST in str(error) and OTHER_DIGEST in str(error)
    # The same name with another digest is refused too: the digest is what is compared.
    same_name = changed(f"walwarden/ci@{DIGEST}", f"walwarden/worker@{OTHER_DIGEST}")
    assert refused(same_name).rule == "worker-image-is-ci-image"
    # Equal digests under different names load: that is the valid file.
    ci_image = load(VALID).ci_image
    assert ci_image is not None and load(VALID).worker_image.reference != ci_image.reference


# The estate canary lane as SORTYARD-187 declared it (noncelogic/estate-gitops
# sortyard-kernel/values.yaml at 567313c): its CI is a check, and it repeats the worker image
# as ci. It must load as it is (SY-V3-LANE-CI-NOT-AN-IMAGE).
ESTATE_IMAGE = f"noncelogicci.azurecr.io/sortyard/walwarden-worker@{DIGEST}"
CANARY = f"""
version = 1
lane = "canary"
resolver = "platform"
runner-pool = "aks"
slots = 1
projects = ["canary"]
defaults = ["repository:noncelogic/sortyard-canary", "secret:CLAUDE_CODE_OAUTH_TOKEN"]

[images]
worker = "{ESTATE_IMAGE}"
ci = "{ESTATE_IMAGE}"

[[repositories]]
name = "noncelogic/sortyard-canary"
checks = ["check"]

[[secrets]]
name = "CLAUDE_CODE_OAUTH_TOKEN"
"""
REPLICA_LANE = pathlib.Path(__file__).resolve().parent.parent / "replica" / "lane.toml"


def test_a_lane_whose_ci_is_checks_on_a_runner_pool_needs_no_ci_image() -> None:
    """A lane whose CI is checks on a runner pool needs no ci image (SY-V3-LANE-CI-NOT-AN-IMAGE).

    `ci = "checks"` says the lane's CI is the checks its repositories name, run on its runner
    pool; the file then names no CI image. A lane that names a CI image still names the worker
    image's digest, and a file cannot say both.
    """
    ci_line = f'ci = "registry.test/walwarden/ci@{DIGEST}"\n'
    checks = changed(ci_line, "").replace("\n[images]", '\nci = "checks"\n\n[images]')
    lane = load(checks)
    assert lane.ci_image is None and lane.runner_pool == "walwarden-runners"
    assert lane.worker_image == load(VALID).worker_image
    assert lane.repositories == load(VALID).repositories
    # must_catch: a ci image that differs from the worker image, without ci = "checks".
    assert refused(changed(f"ci@{DIGEST}", f"ci@{OTHER_DIGEST}")).rule == "worker-image-is-ci-image"
    # A file that says its CI is checks and names a CI image too, equal or not, is refused.
    for digest in (DIGEST, OTHER_DIGEST):
        both = checks.replace("[images]\n", f'[images]\nci = "registry.test/w/ci@{digest}"\n')
        assert refused(both).rule == "ci-is-checks-or-image"
    # ci takes only "checks"; the worker image is still required.
    for value in ('"image"', '""', "true", '["gate1"]'):
        other = checks.replace('ci = "checks"', f"ci = {value}")
        assert refused(other).rule == "ci-is-checks-or-image"
    worker_line = f'worker = "registry.test/walwarden/worker@{DIGEST}"\n'
    assert refused(checks.replace(worker_line, "")).rule == "missing-field"
    # Without ci = "checks" the CI image is still required.
    assert refused(changed(ci_line, "")).rule == "missing-field"
    # must_allow: the canary and replica lanes as they are.
    canary = load(CANARY)
    assert canary.ci_image is not None and canary.ci_image.digest == canary.worker_image.digest
    replica = load(REPLICA_LANE.read_text().replace("__WORKER_IMAGE__", ESTATE_IMAGE))
    assert replica.ci_image == replica.worker_image


def test_loading_fails_for_a_secret_declared_optional() -> None:
    """Loading fails for a secret declared optional."""
    text = changed('name = "REGISTRY_PASSWORD"', 'name = "REGISTRY_PASSWORD"\noptional = true')
    error = refused(text)
    assert error.rule == "no-optional-credentials"
    assert "REGISTRY_PASSWORD" in str(error) and "walwarden" in str(error)
    # Saying outright that a secret is not optional changes nothing.
    explicit = changed('name = "REGISTRY_PASSWORD"', 'name = "REGISTRY_PASSWORD"\noptional = false')
    assert load(explicit) == load(VALID)
    # No other spelling lets an optional credential in.
    for spelling in ("required = false", 'optional = "yes"'):
        other = changed('name = "REGISTRY_PASSWORD"', f'name = "REGISTRY_PASSWORD"\n{spelling}')
        assert refused(other).rule in {"unknown-key", "malformed-file"}


@pytest.mark.parametrize(
    ("old", "new", "rule"),
    [
        (f"worker@{DIGEST}", "worker:v1.2.3", "image-by-digest"),
        (f"ci@{DIGEST}", "ci@sha256:abc", "image-by-digest"),
        (f'ci = "registry.test/walwarden/ci@{DIGEST}"', "", "missing-field"),
        ('resolver = "platform"', "", "missing-field"),
        ('runner-pool = "walwarden-runners"', "", "missing-field"),
        ('lane = "walwarden"', "", "missing-field"),
        ("version = 1", "version = 2", "malformed-file"),
        ("version = 1", "version = true", "malformed-file"),
        ("version = 1", "version = 1.0", "malformed-file"),
        ('lane = "walwarden"', 'lane = "walwarden\\n"', "missing-field"),
        (f"ci@{DIGEST}", f"ci@{DIGEST}\\n", "image-by-digest"),
        ('name = "cluster-api"', 'name = "cluster-api\\n"', "malformed-file"),
        ('name = "walwarden/charts"', 'name = "walwarden/charts\\n"', "malformed-file"),
        ('gap-limit = "2h"', 'gap-limit = "soon"', "malformed-file"),
        ('gap-limit = "2h"', 'gap-limit = "2h"\nrunners = 4', "unknown-key"),
        ('name = "walwarden/charts"', 'name = "walwarden/app"', "duplicate"),
        ('name = "walwarden/charts"', 'name = "charts"', "malformed-file"),
        ('name = "cluster-api"', 'name = "cluster-api"\nurl = "https://x"', "unknown-key"),
        ('["repository:walwarden/app"]', '["repository:walwarden/other"]', "undeclared-need"),
        ('["repository:walwarden/app"]', '["database:main"]', "malformed-need"),
    ],
)
def test_a_file_that_breaks_a_rule_is_refused_by_the_rule_name(
    old: str, new: str, rule: str
) -> None:
    assert refused(changed(old, new)).rule == rule


def test_a_lane_may_name_the_projects_whose_items_it_takes() -> None:
    """Left out, a lane names no project and takes items of any (`projects` is empty)."""
    assert load(VALID).projects == ()
    named = load(changed('resolver = "platform"', 'resolver = "platform"\nprojects = ["a", "b"]'))
    assert named.projects == ("a", "b")
    assert load(changed('resolver = "platform"', 'resolver = "platform"\nprojects = ["p:1/x"]'))
    # An empty list would name nothing and take every project: it is refused, as are a
    # duplicate and an id the API would not accept.
    for bad in ('"a"', '["a", 1]', '[""]', "true", "[]", '["a", "a"]', '["-a"]', '["a b"]', "[[]]"):
        text = changed('resolver = "platform"', f'resolver = "platform"\nprojects = {bad}')
        assert refused(text).rule == "malformed-file", bad


def test_text_that_is_not_toml_is_refused() -> None:
    assert refused("lane = ").rule == "malformed-file"


def test_a_task_lists_its_needs_against_the_file() -> None:
    lane = load(VALID)
    needs = lane.needs_for(["secret:DEPLOY_TOKEN", "service:cluster-api", "worker-image"])
    assert [need.text for need in needs] == [
        "worker-image",
        "runner-pool",
        "repository:walwarden/app",
        "secret:DEPLOY_TOKEN",
        "service:cluster-api",
    ]
    assert needs[3] == Need("secret", "DEPLOY_TOKEN")
    # A task with no needs of its own has the lane's defaults.
    assert lane.needs_for() == lane.defaults


@pytest.mark.parametrize(
    "need", ["secret:NOT_DECLARED", "repository:walwarden/other", "service:billing"]
)
def test_a_need_the_lane_does_not_declare_is_refused(need: str) -> None:
    lane = load(VALID)
    with pytest.raises(CapabilityError) as caught:
        lane.needs_for([need])
    assert caught.value.rule == "undeclared-need"
    assert need in str(caught.value) and "walwarden" in str(caught.value)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "secret",
        "secret:",
        "secret:NAME\n",
        "repository:app",
        "repository:o/n\n",
        "worker-image:x",
        "database:main",
        7,
    ],
)
def test_a_need_that_is_not_a_reference_is_refused(text: object) -> None:
    with pytest.raises(CapabilityError) as caught:
        Need.parse(text)
    assert caught.value.rule == "malformed-need"


def test_need_references_round_trip() -> None:
    for text in ("worker-image", "runner-pool", "repository:o/n", "secret:S", "service:s"):
        need = Need.parse(text)
        assert need.text == str(need) == text and need.kind in KINDS


def test_the_shipped_example_file_loads_and_shows_every_part_of_the_format() -> None:
    lane = load(example_text())
    assert lane.resolver == "platform"
    assert lane.ci_image is not None and lane.worker_image.digest == lane.ci_image.digest
    assert lane.repositories and lane.secrets and lane.services and lane.runner_pool
    assert any(repository.workflow_files for repository in lane.repositories.values())
    assert len(lane.defaults) > 2 and lane.gap_limit is not None and lane.projects == ()
    # The projects line it shows, commented out, loads as written.
    named = example_text().replace('# projects = ["example"]', 'projects = ["example"]')
    assert load(named).projects == ("example",)
    # So does the ci line, once [images] stops naming a CI image.
    checks = example_text().replace('# ci = "checks"', 'ci = "checks"')
    assert refused(checks).rule == "ci-is-checks-or-image"
    ci_line = next(line for line in checks.splitlines() if line.startswith('ci = "registry'))
    assert load(checks.replace(ci_line, "")).ci_image is None
