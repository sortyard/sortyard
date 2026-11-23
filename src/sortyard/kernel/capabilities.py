"""The lane capability file: what a lane's work needs to run (HARNESS-V3 section 3.3).

A lane declares, as data, the worker image by digest, the CI image by digest, the repositories
it pushes to, the secrets it reads by name, the services it calls, its runner pool, and who
resolves a need that fails. This module turns that file into typed values and refuses a file
that breaks one of the section's two rules:

- **The worker image is the CI image.** Both are pinned by digest and the digests are equal.
- **No optional credentials.** A secret marked optional cannot be declared.

A task lists its needs against the file as references (`secret:NAME`, `repository:owner/name`,
`service:NAME`, `runner-pool`, `worker-image`). A need the lane does not declare is refused:
`Lane.needs_for` is the only way a task's list becomes needs to exercise, and it adds the
lane's defaults. `sortyard.kernel.preflight` exercises them.

Loading is a pure function of the text, as the state table's is. `lane_example.toml`, shipped
next to this module, shows the format.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from importlib import resources
from typing import Any

from sortyard.kernel.states import parse_duration

WORKER_IMAGE = "worker-image"
RUNNER_POOL = "runner-pool"
REPOSITORY = "repository"
SECRET = "secret"
SERVICE = "service"
# Every kind of need. The first two have one instance per lane and take no name.
KINDS = (WORKER_IMAGE, RUNNER_POOL, REPOSITORY, SECRET, SERVICE)
_UNNAMED = frozenset({WORKER_IMAGE, RUNNER_POOL})

_DIGEST = re.compile(r"^[^@\s]+@(sha256:[0-9a-f]{64})$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REPOSITORY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_TOP_KEYS = frozenset(
    {
        "version",
        "lane",
        "resolver",
        "gap-limit",
        "runner-pool",
        "defaults",
        "images",
        "repositories",
        "secrets",
        "services",
    }
)
_ENTRY_KEYS: Mapping[str, frozenset[str]] = {
    "repositories": frozenset({"name", "workflow-files"}),
    "secrets": frozenset({"name", "optional"}),
    "services": frozenset({"name"}),
}


class CapabilityError(ValueError):
    """The capability file, or a task's needs against it, breaks a rule.

    `rule` is the rule's short name (for example `worker-image-is-ci-image`,
    `no-optional-credentials`, `undeclared-need`); the message names the lane and the value.
    """

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(f"{rule}: {message}")
        self.rule = rule


@dataclass(frozen=True, order=True)
class Need:
    """One thing a task needs, as a reference into the lane's capability file."""

    kind: str
    name: str = ""

    @property
    def text(self) -> str:
        return f"{self.kind}:{self.name}" if self.name else self.kind

    def __str__(self) -> str:
        return self.text

    @classmethod
    def parse(cls, text: object) -> Need:
        """`"secret:NAME"`, `"repository:owner/name"`, `"service:NAME"`, `"runner-pool"` or
        `"worker-image"`."""
        if not isinstance(text, str):
            raise CapabilityError("malformed-need", f"a need is a string, not {text!r}")
        kind, separator, name = text.partition(":")
        if kind not in KINDS:
            raise CapabilityError(
                "malformed-need", f"{text!r} names no kind of need (one of {', '.join(KINDS)})"
            )
        if kind in _UNNAMED:
            if separator:
                raise CapabilityError("malformed-need", f"{text!r}: {kind} takes no name")
            return cls(kind)
        pattern = _REPOSITORY_NAME if kind == REPOSITORY else _NAME
        if not pattern.match(name):
            form = "owner/name" if kind == REPOSITORY else "a name"
            raise CapabilityError("malformed-need", f"{text!r}: {kind} needs {form} after ':'")
        return cls(kind, name)


@dataclass(frozen=True)
class Image:
    """An image pinned by digest: `reference` is `name@sha256:...`, `digest` the `sha256:...`."""

    reference: str
    digest: str


@dataclass(frozen=True)
class Repository:
    """A repository the lane pushes to; `workflow_files` when that includes workflow files."""

    name: str
    workflow_files: bool = False


@dataclass(frozen=True)
class Lane:
    """A loaded lane capability file."""

    name: str
    resolver: str
    worker_image: Image
    ci_image: Image
    runner_pool: str
    repositories: Mapping[str, Repository]
    secrets: tuple[str, ...]
    services: tuple[str, ...]
    defaults: tuple[Need, ...]
    gap_limit: timedelta | None = None
    gap_limit_text: str | None = None
    version: int = 1

    def declares(self, need: Need) -> bool:
        if need.kind in _UNNAMED:
            return not need.name
        if need.kind == REPOSITORY:
            return need.name in self.repositories
        if need.kind == SECRET:
            return need.name in self.secrets
        return need.kind == SERVICE and need.name in self.services

    def check(self, need: Need | str) -> Need:
        """The need, if this lane declares it; `CapabilityError` (`undeclared-need`) if not."""
        parsed = need if isinstance(need, Need) else Need.parse(need)
        if not self.declares(parsed):
            raise CapabilityError(
                "undeclared-need", f"lane {self.name!r} does not declare {parsed.text!r}"
            )
        return parsed

    def needs_for(self, task_needs: Iterable[Need | str] = ()) -> tuple[Need, ...]:
        """Every need to exercise for a task: the lane's defaults, then the task's own.

        Each appears once, in that order. A need the lane does not declare is refused.
        """
        ordered: dict[Need, None] = dict.fromkeys(self.defaults)
        for need in task_needs:
            ordered.setdefault(self.check(need))
        return tuple(ordered)


def _fail(rule: str, lane: str, message: str) -> CapabilityError:
    return CapabilityError(rule, f"lane {lane!r}: {message}")


def _text(raw: Mapping[str, Any], key: str, lane: str, where: str = "") -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _fail("missing-field", lane, f"{where}{key} must be a non-empty string")
    return value


def _image(raw: Mapping[str, Any], key: str, lane: str) -> Image:
    reference = _text(raw, key, lane, "images.")
    match = _DIGEST.match(reference)
    if not match:
        raise _fail(
            "image-by-digest",
            lane,
            f"images.{key} is {reference!r}; an image is pinned as name@sha256:<64 hex digits>",
        )
    return Image(reference, match.group(1))


def _entries(raw: Mapping[str, Any], section: str, lane: str) -> list[Mapping[str, Any]]:
    """The entries of `[[section]]`, each a table with a well-formed, unique name."""
    entries = raw.get(section, [])
    if not isinstance(entries, list) or not all(isinstance(e, Mapping) for e in entries):
        raise _fail("malformed-file", lane, f"{section} must be an array of tables")
    pattern = _REPOSITORY_NAME if section == "repositories" else _NAME
    seen: set[str] = set()
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not pattern.match(name):
            raise _fail("malformed-file", lane, f"{section}: {name!r} is not a valid name")
        unknown = sorted(set(entry) - _ENTRY_KEYS[section])
        if unknown:
            raise _fail("unknown-key", lane, f"{section} {name!r} has unknown keys {unknown}")
        if name in seen:
            raise _fail("duplicate", lane, f"{section} declares {name!r} twice")
        seen.add(name)
    return entries


def load(text: str) -> Lane:
    """Load a lane capability file from its TOML text, or raise `CapabilityError`."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CapabilityError("malformed-file", f"not TOML: {error}") from error
    lane = raw.get("lane")
    if not isinstance(lane, str) or not _NAME.match(lane):
        raise CapabilityError("missing-field", f"lane must be a name, not {lane!r}")
    if raw.get("version") != 1:
        raise _fail("malformed-file", lane, f"version must be 1, not {raw.get('version')!r}")
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise _fail("unknown-key", lane, f"unknown keys {unknown}")

    images = raw.get("images")
    if not isinstance(images, Mapping):
        raise _fail("missing-field", lane, "[images] must give worker and ci")
    unknown = sorted(set(images) - {"worker", "ci"})
    if unknown:
        raise _fail("unknown-key", lane, f"images has unknown keys {unknown}")
    worker, ci = _image(images, "worker", lane), _image(images, "ci", lane)
    if worker.digest != ci.digest:
        raise _fail(
            "worker-image-is-ci-image",
            lane,
            f"the worker image digest {worker.digest} differs from the CI image digest "
            f"{ci.digest}; the worker image is the CI image",
        )

    for secret in _entries(raw, "secrets", lane):
        optional = secret.get("optional", False)
        if not isinstance(optional, bool):
            raise _fail("malformed-file", lane, f"secret {secret['name']!r}: optional is a boolean")
        if optional:
            raise _fail(
                "no-optional-credentials",
                lane,
                f"secret {secret['name']!r} is declared optional; a lane either reads a "
                "secret or does not declare it",
            )
    repositories: dict[str, Repository] = {}
    for entry in _entries(raw, "repositories", lane):
        workflow_files = entry.get("workflow-files", False)
        if not isinstance(workflow_files, bool):
            raise _fail(
                "malformed-file", lane, f"repository {entry['name']!r}: workflow-files is a boolean"
            )
        repositories[entry["name"]] = Repository(entry["name"], workflow_files)

    gap_limit_text = raw.get("gap-limit")
    gap_limit: timedelta | None = None
    if gap_limit_text is not None:
        try:
            gap_limit = parse_duration(str(gap_limit_text))
        except ValueError as error:
            raise _fail("malformed-file", lane, f"gap-limit: {error}") from error

    declared = Lane(
        name=lane,
        resolver=_text(raw, "resolver", lane),
        worker_image=worker,
        ci_image=ci,
        runner_pool=_text(raw, "runner-pool", lane),
        repositories=repositories,
        secrets=tuple(entry["name"] for entry in _entries(raw, "secrets", lane)),
        services=tuple(entry["name"] for entry in _entries(raw, "services", lane)),
        defaults=(),
        gap_limit=gap_limit,
        gap_limit_text=None if gap_limit_text is None else str(gap_limit_text),
        version=1,
    )
    defaults = raw.get("defaults", [])
    if not isinstance(defaults, list):
        raise _fail("malformed-file", lane, "defaults must be a list of needs")
    # Every task needs the lane's worker image and its runner pool; the file adds the rest.
    every = declared.needs_for([WORKER_IMAGE, RUNNER_POOL, *defaults])
    return replace(declared, defaults=every)


def example_text() -> str:
    """The text of the example lane capability file this package ships."""
    return resources.files("sortyard.kernel").joinpath("lane_example.toml").read_text()
