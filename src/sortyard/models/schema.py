"""Full JSON Schema validation against the packaged §3 schemas (``schemas.json``).

The generated models enforce the structural contract only; the value constraints — numeric
bounds, patterns, the schemas' if/then and ``not`` rules — are checked here, against the very
schemas the models were generated from (``python -m sortyard.models.codegen`` writes both).
"""

from __future__ import annotations

import functools
import json
from importlib import resources
from typing import Any

import jsonschema  # type: ignore[import-untyped]
from referencing import Registry, Resource

from sortyard.models._runtime import Model


@functools.cache
def _registry() -> Registry[Any]:
    text = resources.files("sortyard.models").joinpath("schemas.json").read_text()
    docs: dict[str, Any] = json.loads(text)
    return Registry().with_resources(
        (uri, Resource.from_contents(doc)) for uri, doc in docs.items()
    )


@functools.cache
def validator(schema_id: str) -> Any:
    """A Draft 2020-12 validator for the schema with this ``$id``."""
    schema = _registry().contents(schema_id)
    return jsonschema.Draft202012Validator(schema, registry=_registry())


def errors(model: type[Model], doc: Any) -> list[str]:
    """Every way ``doc`` violates the full schema of ``model`` (empty when it conforms)."""
    if model.SCHEMA_ID is None:
        raise ValueError(f"{model.__name__} is not a top-level schema object")
    found = sorted(validator(model.SCHEMA_ID).iter_errors(doc), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in found]
