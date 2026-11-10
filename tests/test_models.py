"""Acceptance: the Python data models are GENERATED from the §3 JSON Schemas (SY-DEC-001, §4a).

The schema is the contract: the generated module must be exactly what the generator produces
from spec/ today (a drift fails the build), every §3 object schema has a model, and every
schema example round-trips through its model unchanged.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import pytest
from referencing import Registry, Resource

from sortyard import models
from sortyard.models import codegen

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "spec"
OBJECT_SCHEMAS = sorted(p for p in SPEC.glob("*.schema.json") if p.name != "common.schema.json")


def stem(path: pathlib.Path) -> str:
    return path.name.removesuffix(".schema.json")


def load(path: pathlib.Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def registry() -> Registry[Any]:
    resources = [
        (load(p)["$id"], Resource.from_contents(load(p))) for p in SPEC.glob("*.schema.json")
    ]
    return Registry().with_resources(resources)


def examples() -> list[tuple[str, int, dict[str, Any]]]:
    return [
        (stem(p), i, example)
        for p in OBJECT_SCHEMAS
        for i, example in enumerate(load(p).get("examples", []))
    ]


def test_generated_module_matches_the_schemas() -> None:
    """The drift check: regenerating from spec/ must reproduce the committed module byte for
    byte. Fix with `python -m sortyard.models.codegen`."""
    assert codegen.GENERATED.read_text() == codegen.generate(SPEC)


def test_every_object_schema_has_a_generated_model() -> None:
    assert sorted(models.MODELS) == sorted(stem(p) for p in OBJECT_SCHEMAS)
    for p in OBJECT_SCHEMAS:
        schema = load(p)
        model = models.MODELS[stem(p)]
        assert model.__name__ == schema["title"]
        assert schema["$id"] == model.SCHEMA_ID
        assert schema.get("x-sortyard-store") == model.STORE


@pytest.mark.parametrize(
    ("kind", "index", "example"),
    examples(),
    ids=[f"{kind}-{index}" for kind, index, _ in examples()],
)
def test_every_example_round_trips_through_its_model(
    kind: str, index: int, example: dict[str, Any]
) -> None:
    schema = load(SPEC / f"{kind}.schema.json")
    validator = jsonschema.Draft202012Validator(schema, registry=registry())
    validator.validate(example)

    model = models.MODELS[kind]
    obj = model.from_dict(copy.deepcopy(example))
    assert isinstance(obj, model)
    out = obj.to_dict()
    assert out == example
    validator.validate(out)
    # And through JSON text, the form the API and the database carry.
    assert model.from_dict(json.loads(json.dumps(out))).to_dict() == example


def test_every_object_schema_has_an_example_to_round_trip() -> None:
    covered = {kind for kind, _, _ in examples()}
    assert covered == {stem(p) for p in OBJECT_SCHEMAS}


def test_nested_objects_are_typed_models() -> None:
    task = models.Task.from_dict(load(SPEC / "task.schema.json")["examples"][0])
    assert isinstance(task.priority, models.TaskPriority)
    assert task.priority.tier == "high"
    wf = models.Workflow.from_dict(load(SPEC / "workflow.schema.json")["examples"][0])
    assert isinstance(wf.stages[0], models.WorkflowStage)
    assert isinstance(wf.stages[0].role, models.VersionedRef)


def test_absent_and_null_are_distinct() -> None:
    """event.transition.from may be null; an explicit null must survive, and so must absence."""
    event = load(SPEC / "event.schema.json")["examples"][0]
    with_null = copy.deepcopy(event)
    with_null["transition"] = {"name": "create", "from": None, "to": "todo"}
    assert models.Event.from_dict(with_null).to_dict() == with_null
    absent = copy.deepcopy(event)
    absent["transition"] = {"name": "create", "to": "todo"}
    assert models.Event.from_dict(absent).to_dict() == absent


def test_python_keywords_keep_their_json_names() -> None:
    change = load(SPEC / "sequence-change.schema.json")["examples"][0]
    obj = models.SequenceChange.from_dict(change)
    assert obj.from_ == change["from"]
    assert obj.to_dict()["from"] == change["from"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(acceptance_test="x"), "acceptance_test"),
        (lambda d: d.pop("title"), "title"),
        (lambda d: d.update(state="finished"), "state"),
        (lambda d: d.update(sequence="2"), "sequence"),
        (lambda d: d.update(sequence=True), "sequence"),
        (lambda d: d["priority"].update(tier="meh"), "priority.tier"),
        (lambda d: d["priority"].update(extra=1), "priority.extra"),
        (lambda d: d.update(labels="sortyard"), "labels"),
    ],
)
def test_the_contract_is_enforced_on_decode(mutate: Any, message: str) -> None:
    task = copy.deepcopy(load(SPEC / "task.schema.json")["examples"][0])
    mutate(task)
    with pytest.raises(models.ModelError, match=message):
        models.Task.from_dict(task)


def test_open_objects_keep_their_extra_properties() -> None:
    """Policy kinds the draft leaves open (NOTES.md item 10) accept and keep unknown keys."""
    params = {"revision_cap": 4, "a_future_knob": {"x": 1}}
    obj = models.PolicyEscalation.from_dict(params)
    assert obj.to_dict() == params


def test_models_are_built_by_keyword_and_serialise_like_the_schema() -> None:
    ws = models.Workspace(
        id="ws-a", installation_id="inst-a", name="A", slug="a", created_at=None, updated_at=None
    )
    assert ws.to_dict() == {"id": "ws-a", "installation_id": "inst-a", "name": "A", "slug": "a"}
