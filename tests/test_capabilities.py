"""Acceptance (SY-V3-PREFLIGHT-PROBES): a lane capability file that breaks a rule cannot load.

The loader is the rule (HARNESS-V3 section 3.3): these tests feed it a valid file with one
thing changed and expect it to refuse, naming the rule. The example file the package ships is
held to the same loader, and a task's needs are checked against the file.
"""

from __future__ import annotations

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
    assert load(VALID).worker_image.reference != load(VALID).ci_image.reference


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
    "text", ["", "secret", "secret:", "repository:app", "worker-image:x", "database:main", 7]
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
    assert lane.worker_image.digest == lane.ci_image.digest
    assert lane.repositories and lane.secrets and lane.services and lane.runner_pool
    assert any(repository.workflow_files for repository in lane.repositories.values())
    assert len(lane.defaults) > 2 and lane.gap_limit is not None
