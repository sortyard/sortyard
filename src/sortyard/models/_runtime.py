"""Runtime for the generated models: decoding from and encoding to the schema's JSON form.

Generated classes (``_generated.py``) are plain frozen dataclasses whose annotations carry the
contract; this module reads those annotations to decode and encode, so the generator emits
declarations only. Decoding enforces the structural contract (required properties, closed
objects, primitive types, enums/consts, nested shapes). The value constraints a type cannot
express — patterns, formats, numeric bounds, the schemas' if/then rules — are the JSON
Schema's job; validate against spec/ where those matter.

Absence is kept distinct from null. An optional property the schema does not allow to be null
is ``None`` when absent. An optional property that may be null defaults to ``UNSET`` when
absent, so an explicit null round-trips as null.
"""

from __future__ import annotations

import copy
import dataclasses
import types
import typing
from collections.abc import Mapping
from typing import Any, ClassVar, Literal, Self, TypeVar, Union


class ModelError(ValueError):
    """A document does not fit the model generated from its schema."""


@typing.final
class Unset:
    """Marker for an absent optional property whose schema also allows null."""

    _instance: ClassVar[Unset | None] = None

    def __new__(cls) -> Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = Unset()
EXTRA = "additional_properties"
M = TypeVar("M", bound="Model")


@dataclasses.dataclass(frozen=True, kw_only=True)
class Model:
    """Base of every generated model."""

    #: ``$id`` of the schema the model was generated from (top-level objects only).
    SCHEMA_ID: ClassVar[str | None] = None
    #: The schema's ``x-sortyard-store`` annotation (design §5.1).
    STORE: ClassVar[str | None] = None
    #: True when the schema admits properties beyond the declared ones; they are kept in
    #: ``additional_properties``.
    OPEN: ClassVar[bool] = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        """Decode a document in the schema's JSON form."""
        return _decode_model(cls, data, "")

    def to_dict(self) -> dict[str, Any]:
        """Encode to the schema's JSON form; absent properties are omitted."""
        out: dict[str, Any] = {}
        for f in _fields(type(self)):
            value = getattr(self, f.name)
            if f.default is None and value is None:
                continue
            if value is UNSET:
                continue
            out[f.metadata.get("json", f.name)] = _encode(value)
        if self.OPEN:
            extra: dict[str, Any] = getattr(self, EXTRA)
            out.update(copy.deepcopy(extra))
        return out

    @classmethod
    def json_fields(cls) -> dict[str, str]:
        """Declared JSON property name -> Python attribute name."""
        return {f.metadata.get("json", f.name): f.name for f in _fields(cls)}


_FIELDS: dict[type[Model], tuple[dataclasses.Field[Any], ...]] = {}
_HINTS: dict[type[Model], dict[str, Any]] = {}


def _fields(cls: type[Model]) -> tuple[dataclasses.Field[Any], ...]:
    if cls not in _FIELDS:
        _FIELDS[cls] = tuple(f for f in dataclasses.fields(cls) if f.name != EXTRA)
    return _FIELDS[cls]


def _hints(cls: type[Model]) -> dict[str, Any]:
    if cls not in _HINTS:
        _HINTS[cls] = typing.get_type_hints(cls)
    return _HINTS[cls]


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _decode_model(cls: type[M], data: object, path: str) -> M:
    if not isinstance(data, Mapping):
        raise ModelError(f"{path or cls.__name__}: expected an object, got {type(data).__name__}")
    fields = {f.metadata.get("json", f.name): f for f in _fields(cls)}
    if not cls.OPEN:
        for key in data:
            if key not in fields:
                raise ModelError(f"{_join(path, key)}: not a property of {cls.__name__}")
    hints = _hints(cls)
    kwargs: dict[str, Any] = {}
    for key, f in fields.items():
        where = _join(path, key)
        if key in data:
            value = data[key]
            if value is None and f.default is None:
                raise ModelError(f"{where}: may be absent but not null")
            kwargs[f.name] = _decode(hints[f.name], value, where)
        elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            raise ModelError(f"{where}: required property missing")
    if cls.OPEN:
        kwargs[EXTRA] = {k: copy.deepcopy(v) for k, v in data.items() if k not in fields}
    return cls(**kwargs)


def _decode(tp: Any, value: Any, path: str) -> Any:
    if tp is Any:
        return copy.deepcopy(value)
    origin = typing.get_origin(tp)
    if origin is Union or origin is types.UnionType:
        options = [a for a in typing.get_args(tp) if a is not Unset]
        if value is None and type(None) in options:
            return None
        for option in options:
            if option is type(None):
                continue
            try:
                return _decode(option, value, path)
            except ModelError:
                continue
        raise ModelError(f"{path}: {value!r} does not match {_show(tp)}")
    if origin is Literal:
        for allowed in typing.get_args(tp):
            if type(allowed) is type(value) and allowed == value:
                return value
        raise ModelError(f"{path}: {value!r} is not one of {list(typing.get_args(tp))}")
    if origin is list:
        if not isinstance(value, list):
            raise ModelError(f"{path}: expected an array, got {type(value).__name__}")
        (item,) = typing.get_args(tp)
        return [_decode(item, v, f"{path}[{i}]") for i, v in enumerate(value)]
    if origin is dict:
        if not isinstance(value, dict):
            raise ModelError(f"{path}: expected an object, got {type(value).__name__}")
        _, item = typing.get_args(tp)
        return {k: _decode(item, v, _join(path, k)) for k, v in value.items()}
    if isinstance(tp, type) and issubclass(tp, Model):
        return _decode_model(tp, value, path)
    if tp is type(None):
        if value is None:
            return None
    elif tp is bool or tp is str:
        if type(value) is tp:
            return value
    elif tp is int:
        if type(value) is int:
            return value
    elif tp is float:
        if type(value) in (int, float):
            return value
    else:
        raise TypeError(f"unsupported annotation {tp!r} at {path}")
    raise ModelError(f"{path}: expected {_show(tp)}, got {type(value).__name__}")


def _encode(value: Any) -> Any:
    if isinstance(value, Model):
        return value.to_dict()
    if isinstance(value, list):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    return copy.deepcopy(value)


def _show(tp: Any) -> str:
    names = {str: "string", int: "integer", float: "number", bool: "boolean", type(None): "null"}
    return names.get(tp, getattr(tp, "__name__", str(tp)))
