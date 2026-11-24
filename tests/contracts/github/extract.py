"""Cut the fragment of GitHub's published REST description that the GitHub port uses.

Usage: python tests/contracts/github/extract.py <api.github.com.json> <commit of the source>

Writes `fragment.json` beside this file: for each operation in `OPERATIONS`, its documented
parameters, request body schema (and whether a body is required) and response schemas, plus
every component schema they refer to. Schemas are kept as published except that descriptions
and examples are dropped (they carry no shape). Nothing here runs in a test; it is how the
fragment is refreshed.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

# (method, path) of every GitHub endpoint src/sortyard/lane/github.py calls, and the reads of
# src/sortyard/services/red_main.py (the last four).
OPERATIONS = (
    ("get", "/repos/{owner}/{repo}/installation"),
    ("post", "/app/installations/{installation_id}/access_tokens"),
    ("get", "/repos/{owner}/{repo}/pulls"),
    ("post", "/repos/{owner}/{repo}/pulls"),
    ("get", "/repos/{owner}/{repo}/pulls/{pull_number}"),
    ("get", "/repos/{owner}/{repo}/branches/{branch}"),
    ("get", "/repos/{owner}/{repo}/commits/{ref}/check-runs"),
    ("put", "/repos/{owner}/{repo}/pulls/{pull_number}/update-branch"),
    ("put", "/repos/{owner}/{repo}/pulls/{pull_number}/merge"),
    ("get", "/repos/{owner}/{repo}/git/matching-refs/{ref}"),
    ("post", "/repos/{owner}/{repo}/git/refs"),
    ("delete", "/repos/{owner}/{repo}/git/refs/{ref}"),
    ("get", "/repos/{owner}/{repo}/git/commits/{commit_sha}"),
    ("get", "/repos/{owner}/{repo}/compare/{basehead}"),
    ("get", "/repos/{owner}/{repo}"),
    ("get", "/repos/{owner}/{repo}/contents/{path}"),
    ("get", "/repos/{owner}/{repo}/actions/workflows"),
    ("get", "/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"),
)
PROSE = ("description", "example", "examples", "summary", "externalDocs")
SCHEMAS = "#/components/schemas/"


def main(source: str, commit: str) -> None:
    api = json.loads(pathlib.Path(source).read_text())
    components: dict[str, Any] = {}

    def resolve(node: Any) -> Any:
        while isinstance(node, dict) and "$ref" in node:
            found = api
            for key in node["$ref"][2:].split("/"):
                found = found[key]
            node = found
        return node

    def schema(node: Any) -> Any:
        """A schema without its prose, with every schema it refers to collected."""
        if isinstance(node, list):
            return [schema(each) for each in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(SCHEMAS):
            name = ref.removeprefix(SCHEMAS)
            if name not in components:
                components[name] = None  # placeholder: a schema may refer to itself
                components[name] = schema(api["components"]["schemas"][name])
        kept = {}
        for key, value in node.items():
            if key == "properties":  # property names are data, not schema keywords
                kept[key] = {name: schema(each) for name, each in value.items()}
            elif key not in PROSE:
                kept[key] = schema(value)
        return kept

    def body(node: Any) -> Any:
        content = resolve(node).get("content", {}).get("application/json")
        # A response may document its media type with no schema (a redirect, not modified).
        return schema(content["schema"]) if content and "schema" in content else None

    paths: dict[str, Any] = {}
    for method, path in OPERATIONS:
        operation = api["paths"][path][method]
        parameters = [resolve(each) for each in operation.get("parameters", [])]
        paths.setdefault(path, {})[method] = {
            "operationId": operation["operationId"],
            "parameters": [
                {"name": each["name"], "in": each["in"], "schema": schema(each["schema"])}
                for each in parameters
            ],
            "requestBody": body(operation["requestBody"]) if "requestBody" in operation else None,
            "requestBodyRequired": bool(resolve(operation.get("requestBody", {})).get("required")),
            "responses": {code: body(each) for code, each in operation["responses"].items()},
        }
    fragment = {
        "source": "https://github.com/github/rest-api-description",
        "file": "descriptions/api.github.com/api.github.com.json",
        "commit": commit,
        "openapi": api["openapi"],
        "version": api["info"]["version"],
        "paths": paths,
        "components": {"schemas": dict(sorted(components.items()))},
    }
    target = pathlib.Path(__file__).with_name("fragment.json")
    target.write_text(json.dumps(fragment, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
