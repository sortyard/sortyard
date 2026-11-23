"""Acceptance: only src/sortyard/engine imports the workflow engine SDK (HARNESS-V3 §3.1).

The kernel reaches the engine through `sortyard.engine` alone, so the engine can be replaced by
changing only that package. Any other Python file in the repository that imports an engine SDK
(DBOS or Temporal), by `import`, `from ... import` or `importlib.import_module`, fails this test.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINE_PACKAGE = ROOT / "src" / "sortyard" / "engine"
ENGINE_SDKS = frozenset({"dbos", "temporalio"})
# Skipped at the top of the repository only: a package named build or dist deeper down is code.
SKIP_TOP = frozenset({".git", ".venv", "venv", "build", "dist", "node_modules"})


def imported_modules(source: str) -> set[str]:
    """Top-level module names a Python source imports, statically or by a literal name."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
                or (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"__import__", "import_module"}
                )
            )
        ):
            found.add(node.args[0].value.split(".")[0])
    return found


def python_files() -> list[pathlib.Path]:
    return [
        path
        for path in sorted(ROOT.rglob("*.py"))
        if path.relative_to(ROOT).parts[0] not in SKIP_TOP
        and not any(part.endswith(".egg-info") for part in path.relative_to(ROOT).parts)
    ]


def engine_importers() -> dict[str, set[str]]:
    importers: dict[str, set[str]] = {}
    for path in python_files():
        sdks = imported_modules(path.read_text()) & ENGINE_SDKS
        if sdks:
            importers[str(path.relative_to(ROOT))] = sdks
    return importers


def test_only_src_sortyard_engine_imports_the_engine_sdk() -> None:
    importers = engine_importers()
    outside = {
        path: sdks
        for path, sdks in importers.items()
        if not (ROOT / path).is_relative_to(ENGINE_PACKAGE)
    }
    assert outside == {}, f"engine SDK imported outside src/sortyard/engine: {outside}"
    # The scan is not vacuous: it sees the engine package's own import of the SDK.
    assert any((ROOT / path).is_relative_to(ENGINE_PACKAGE) for path in importers)


def test_the_scan_catches_every_import_form() -> None:
    for source in (
        "import dbos",
        "import temporalio.client as tc",
        "from dbos import DBOS",
        "from temporalio.worker import Worker",
        "import importlib\nimportlib.import_module('dbos')",
        "__import__('temporalio')",
        "def f() -> None:\n    from dbos._client import DBOSClient",
    ):
        assert imported_modules(source) & ENGINE_SDKS, source
    assert not imported_modules("from sortyard.engine import step\nimport dbosish") & ENGINE_SDKS
