"""Generate ``sortyard.models._generated`` from the §3 JSON Schemas in spec/ (SY-DEC-001).

The schema is the contract and the models are derived from it: never edit the generated module
by hand. After changing a schema, regenerate and commit both:

    python -m sortyard.models.codegen           # rewrite _generated.py and schemas.json
    python -m sortyard.models.codegen --check   # exit 1 if either committed file has drifted

``schemas.json`` bundles the schemas themselves (keyed by ``$id``) into the package, so the
installed services validate documents against the full JSON Schemas (``sortyard.models.schema``)
— the generated classes enforce the structural contract only.

What becomes a class: every top-level object schema (named by its ``title``), every object in
a ``$defs`` block (common definitions by their own name, a schema's own definitions prefixed
with its title) and every inline object with declared properties (parent name + property name;
array items add ``Item``). ``allOf`` members contribute their properties; the conditional
branches (``if``/``then``, ``not``) do not change the shape and are left to JSON Schema
validation. Enums and consts become ``Literal`` types.
"""

from __future__ import annotations

import argparse
import json
import keyword
import pathlib
import re
import sys
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC = ROOT / "spec"
GENERATED = pathlib.Path(__file__).with_name("_generated.py")
BUNDLE = pathlib.Path(__file__).with_name("schemas.json")
COMMON = "common.schema.json"
RESERVED = {"additional_properties", "from_dict", "to_dict", "json_fields"}
WIDTH = 100

Node = dict[str, Any]


def pascal(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", name) if part)


def literal(value: Any) -> str:
    """A Python literal for a JSON scalar, strings double-quoted."""
    return json.dumps(value) if isinstance(value, str) else repr(value)


def attribute(name: str) -> str:
    ident = re.sub(r"\W", "_", name)
    if ident[:1].isdigit():
        ident = f"_{ident}"
    if keyword.iskeyword(ident) or keyword.issoftkeyword(ident) or ident in RESERVED:
        ident += "_"
    return ident


@dataclass
class Prop:
    name: str
    alternatives: list[str]
    required: bool
    description: str | None


@dataclass
class Klass:
    name: str
    description: str | None
    props: list[Prop] = field(default_factory=list)
    open: bool = False
    schema_id: str | None = None
    store: str | None = None


class Generator:
    def __init__(self, spec: pathlib.Path) -> None:
        self.docs: dict[str, Node] = {}
        self.stems: dict[str, str] = {}
        for path in sorted(spec.glob("*.schema.json")):
            doc = json.loads(path.read_text())
            self.docs[doc["$id"]] = doc
            self.stems[doc["$id"]] = path.name.removesuffix(".schema.json")
        self.classes: dict[str, Klass] = {}
        self.order: list[str] = []
        self.by_node: dict[tuple[str, str], str] = {}
        self.models: dict[str, str] = {}

    # -- references --------------------------------------------------------------------

    def resolve(self, ref: str, base: str) -> tuple[str, str, Node]:
        url = urljoin(base, ref)
        doc_id, _, pointer = url.partition("#")
        node: Any = self.docs[doc_id]
        for part in [p for p in pointer.split("/") if p]:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return doc_id, pointer, node

    def def_name(self, doc_id: str, pointer: str) -> str:
        defname = pointer.rsplit("/", 1)[-1]
        if self.stems[doc_id] == COMMON.removesuffix(".schema.json"):
            return pascal(defname)
        return str(self.docs[doc_id]["title"]) + pascal(defname)

    # -- shapes ------------------------------------------------------------------------

    @staticmethod
    def is_object_class(node: Node) -> bool:
        return "properties" in node or any(
            "$ref" in m or "properties" in m for m in node.get("allOf", [])
        )

    def collect(self, node: Node, base: str) -> tuple[dict[str, tuple[Node, str]], list[str], bool]:
        """Properties (in schema order, allOf members first), required names, openness."""
        props: dict[str, tuple[Node, str]] = {}
        required: list[str] = []
        for member in node.get("allOf", []):
            if "$ref" in member:
                doc_id, _, target = self.resolve(member["$ref"], base)
                sub_props, sub_req, _ = self.collect(target, doc_id)
            elif "properties" in member:
                sub_props, sub_req, _ = self.collect(member, base)
            else:
                continue  # if/then/not: conditional, does not change the shape
            props.update(sub_props)
            required += [r for r in sub_req if r not in required]
        for name, sub in node.get("properties", {}).items():
            props[name] = (sub, base)
        required += [r for r in node.get("required", []) if r not in required]
        closed = node.get("additionalProperties") is False or (
            node.get("unevaluatedProperties") is False
        )
        return props, required, not closed

    def klass(self, name: str, node: Node, base: str, key: tuple[str, str] | None) -> str:
        if key is not None and key in self.by_node:
            return self.by_node[key]
        if name in self.classes:
            raise ValueError(f"two schema objects generate the class name {name}")
        if key is not None:
            self.by_node[key] = name
        k = Klass(name=name, description=node.get("description"))
        self.classes[name] = k
        self.order.append(name)
        props, required, k.open = self.collect(node, base)
        for prop_name, (sub, sub_base) in props.items():
            alternatives = self.type_of(sub, sub_base, name + pascal(prop_name))
            k.props.append(
                Prop(prop_name, alternatives, prop_name in required, sub.get("description"))
            )
        return name

    def type_of(self, node: Any, base: str, context: str) -> list[str]:
        """The node's Python type as a list of union alternatives."""
        if node is True or node == {} or not isinstance(node, dict):
            return ["Any"]
        if "$ref" in node:
            doc_id, pointer, target = self.resolve(node["$ref"], base)
            if self.is_object_class(target):
                return [
                    self.klass(self.def_name(doc_id, pointer), target, doc_id, (doc_id, pointer))
                ]
            return self.type_of(target, doc_id, context)
        if "const" in node:
            return [f"Literal[{literal(node['const'])}]"]
        if "enum" in node:
            values = node["enum"]
            lit = [f"Literal[{', '.join(literal(v) for v in values if v is not None)}]"]
            return (lit if any(v is not None for v in values) else []) + (
                ["None"] if None in values else []
            )
        for combinator in ("oneOf", "anyOf"):
            if combinator in node:
                out: list[str] = []
                for i, member in enumerate(node[combinator]):
                    for alt in self.type_of(member, base, f"{context}{i}"):
                        if alt not in out:
                            out.append(alt)
                return out
        if self.is_object_class(node):
            return [self.klass(context, node, base, None)]
        kind = node.get("type")
        if isinstance(kind, list):
            out = []
            for k in kind:
                for alt in self.type_of({**node, "type": k}, base, context):
                    if alt not in out:
                        out.append(alt)
            return out
        if kind == "object":
            extra = node.get("additionalProperties")
            value = (
                self.type_of(extra, base, context + "Value") if isinstance(extra, dict) else ["Any"]
            )
            return [f"dict[str, {' | '.join(value)}]"]
        if kind == "array":
            item = self.type_of(node.get("items", True), base, context + "Item")
            return [f"list[{' | '.join(item)}]"]
        simple = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "null": "None",
        }
        if kind in simple:
            return [simple[kind]]
        return ["Any"]

    # -- driving -----------------------------------------------------------------------

    def run(self) -> str:
        common_id = next(
            i for i, s in self.stems.items() if s == COMMON.removesuffix(".schema.json")
        )
        for doc_id, doc in self.docs.items():
            if doc_id == common_id:
                continue
            name = self.klass(doc["title"], doc, doc_id, (doc_id, ""))
            k = self.classes[name]
            k.schema_id = doc_id
            k.store = doc.get("x-sortyard-store")
            self.models[self.stems[doc_id]] = name
        for doc_id, doc in self.docs.items():
            for defname, sub in doc.get("$defs", {}).items():
                if self.is_object_class(sub):
                    pointer = f"/$defs/{defname}"
                    self.klass(self.def_name(doc_id, pointer), sub, doc_id, (doc_id, pointer))
        return self.render()

    # -- rendering ---------------------------------------------------------------------

    def render(self) -> str:
        names = sorted(self.classes)
        lines = [
            "# GENERATED by sortyard.models.codegen from spec/*.schema.json. DO NOT EDIT.",
            "# Regenerate: python -m sortyard.models.codegen   (CI fails on drift)",
            '"""Data models for the §3 domain objects, generated from the frozen JSON Schemas."""',
            "",
            "from __future__ import annotations",
            "",
            "from dataclasses import dataclass, field",
            "from typing import Any, ClassVar, Final, Literal",
            "",
            "from sortyard.models._runtime import UNSET, Model, Unset",
            "",
            "__all__ = [",
            *[f'    "{n}",' for n in [*names, "MODELS"]],
            "]",
        ]
        for name in self.order:
            lines += ["", "", *self.render_class(self.classes[name])]
        lines += [
            "",
            "",
            "#: Schema file stem (spec/<stem>.schema.json) -> its top-level model.",
            "MODELS: Final[dict[str, type[Model]]] = {",
            *[f'    "{stem}": {name},' for stem, name in sorted(self.models.items())],
            "}",
            "",
        ]
        return "\n".join(lines)

    def render_class(self, k: Klass) -> list[str]:
        out = ["@dataclass(frozen=True, kw_only=True)", f"class {k.name}(Model):"]
        if k.description:
            out += docstring(k.description, "    ")
        if k.schema_id:
            out.append(f"    SCHEMA_ID: ClassVar[str | None] = {literal(k.schema_id)}")
            out.append(f"    STORE: ClassVar[str | None] = {literal(k.store)}")
        if k.open:
            out.append("    OPEN: ClassVar[bool] = True")
        for p in k.props:
            if p.description:
                out += comment(p.description, "    ")
            out.append(self.render_field(p))
        if k.open:
            out.append("    additional_properties: dict[str, Any] = field(default_factory=dict)")
        if not k.props and not k.open:
            out.append("    pass")
        return out

    @staticmethod
    def render_field(p: Prop) -> str:
        name = attribute(p.name)
        nullable = "None" in p.alternatives
        alts = [a for a in p.alternatives if a != "None"]
        if p.required:
            tp, default = " | ".join(alts + (["None"] if nullable else [])), None
        elif nullable:
            tp, default = " | ".join([*alts, "None", "Unset"]), "UNSET"
        else:
            tp, default = " | ".join([*alts, "None"]), "None"
        if name != p.name:
            args = ([f"default={default}"] if default else []) + [
                f'metadata={{"json": "{p.name}"}}'
            ]
            return f"    {name}: {tp} = field({', '.join(args)})"
        return f"    {name}: {tp}" + (f" = {default}" if default else "")


def docstring(text: str, indent: str) -> list[str]:
    safe = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    wrapped = textwrap.wrap(safe, WIDTH - len(indent) - 3)
    if len(wrapped) == 1 and len(wrapped[0]) <= WIDTH - len(indent) - 6:
        return [f'{indent}"""{wrapped[0]}"""', ""]
    return [f'{indent}"""{wrapped[0]}', *[f"{indent}{w}" for w in wrapped[1:]], f'{indent}"""', ""]


def comment(text: str, indent: str) -> list[str]:
    return [f"{indent}#: {w}" for w in textwrap.wrap(text, WIDTH - len(indent) - 3)]


def generate(spec: pathlib.Path = SPEC) -> str:
    """The generated module's source for the schemas in ``spec``."""
    return Generator(spec).run()


def bundle(spec: pathlib.Path = SPEC) -> str:
    """Every schema in ``spec``, keyed by its ``$id``, as the packaged ``schemas.json``."""
    docs = {}
    for path in sorted(spec.glob("*.schema.json")):
        doc = json.loads(path.read_text())
        docs[doc["$id"]] = doc
    return json.dumps(docs, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sortyard.models.codegen", description=__doc__)
    parser.add_argument("--spec", type=pathlib.Path, default=SPEC, help="schema directory")
    parser.add_argument("--check", action="store_true", help="fail if the outputs have drifted")
    args = parser.parse_args(argv)
    outputs = {GENERATED: generate(args.spec), BUNDLE: bundle(args.spec)}
    if args.check:
        drifted = [p for p, text in outputs.items() if not p.exists() or p.read_text() != text]
        for path in drifted:
            print(f"{path} is out of date with {args.spec}; run {parser.prog}")
        if drifted:
            return 1
        print(f"{GENERATED.name} and {BUNDLE.name} match {args.spec}")
        return 0
    for path, text in outputs.items():
        path.write_text(text)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
