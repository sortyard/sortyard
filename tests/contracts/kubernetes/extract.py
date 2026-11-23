"""Cut the fragment of the Kubernetes OpenAPI document the jobs port is held to.

Usage: python tests/contracts/kubernetes/extract.py path/to/swagger.json

Writes openapi.json next to this file: the operations in OPERATIONS with their parameters
resolved, and every definition they reach. Descriptions are dropped; nothing else is changed.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

VERSION = "v1.31.4"
SOURCE = f"https://raw.githubusercontent.com/kubernetes/kubernetes/{VERSION}/api/openapi-spec/swagger.json"
OPERATIONS = {
    "/apis/batch/v1/namespaces/{namespace}/jobs": ("get", "post"),
    "/apis/batch/v1/namespaces/{namespace}/jobs/{name}": ("get", "delete"),
    "/api/v1/namespaces/{namespace}/configmaps": ("post",),
    "/api/v1/namespaces/{namespace}/configmaps/{name}": ("delete",),
    "/api/v1/namespaces/{namespace}/secrets": ("post",),
    "/api/v1/namespaces/{namespace}/secrets/{name}": ("get", "patch", "delete"),
    "/api/v1/namespaces/{namespace}/pods": ("get",),
}
PREFIX = "#/definitions/"


def strip(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: strip(value)
            for key, value in node.items()
            if not (key == "description" and isinstance(value, str))
        }
    if isinstance(node, list):
        return [strip(value) for value in node]
    return node


def references(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(PREFIX):
                found.add(value.removeprefix(PREFIX))
            else:
                found |= references(value)
    elif isinstance(node, list):
        for value in node:
            found |= references(value)
    return found


def main(source: str) -> None:
    document = json.loads(pathlib.Path(source).read_text())

    def parameter(raw: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in raw:
            raw = document["parameters"][raw["$ref"].removeprefix("#/parameters/")]
        return {key: raw[key] for key in ("name", "in", "required", "schema") if key in raw}

    paths: dict[str, Any] = {}
    for path, methods in OPERATIONS.items():
        item = document["paths"][path]
        shared = [parameter(raw) for raw in item.get("parameters", [])]
        paths[path] = {
            method: {
                "operationId": item[method]["operationId"],
                "consumes": item[method].get("consumes", []),
                "parameters": shared
                + [parameter(raw) for raw in item[method].get("parameters", [])],
                "responses": {
                    code: {"schema": response["schema"]}
                    for code, response in item[method]["responses"].items()
                    if "schema" in response
                },
            }
            for method in methods
        }
    definitions: dict[str, Any] = {}
    pending = references(paths)
    while pending:
        name = pending.pop()
        if name not in definitions:
            definitions[name] = strip(document["definitions"][name])
            pending |= references(definitions[name])
    out = {
        "source": SOURCE,
        "version": VERSION,
        "paths": paths,
        "definitions": dict(sorted(definitions.items())),
    }
    target = pathlib.Path(__file__).with_name("openapi.json")
    target.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
