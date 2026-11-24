"""Acceptance: the size of the hand-written kernel, by the rule of SY-DEC-010 (SY-V3-KERNEL-SIZE).

Win criterion 10 of HARNESS-V3 section 5 keeps the hand-written kernel under 5,000 lines,
against 37,797 in the conductor. DECISIONS.md, SY-DEC-010, says what is counted; this file is
the one place that holds the rule as values (`COUNTED`, `MAY_IMPORT`, `DATA_SUFFIXES`,
`BUDGET`) and the record names it.

The budgeted figure is raw lines: every line of the `.py` files of the counted packages, as
`wc -l` counts them, which is how the conductor's 37,797 was counted. The code-line figure
(lines that hold code: no blank line, comment line or docstring) is computed and printed
beside it and gates nothing.

A count of named packages can be escaped by putting kernel code somewhere else and importing
it. So a counted package may import only the standard library, the project's declared
dependencies and the counted packages; `src/` holds one package; and a counted package holds
only Python and its data files. What this cannot see is said in the record: a package that
imports the kernel (`sortyard.services` does) is not reached by any of it.

`python -m tests.test_kernel_size` prints both figures by package.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PACKAGE = SRC / "sortyard"
BUDGET = 5000
# The packages of src/sortyard whose Python is the hand-written kernel.
COUNTED = ("engine", "kernel", "lane")
# The packages of src/sortyard that are not kernel and that the kernel may import all the
# same. None today. A package added here is read by the kernel without being counted, so each
# entry needs its reason in SY-DEC-010.
MAY_IMPORT: tuple[str, ...] = ()
# What a counted package holds besides Python: the tables and policy it ships as data.
DATA_SUFFIXES = frozenset({".toml"})
RECORD = "SY-DEC-010"
# What the scan reports for an import whose target it cannot read.
DYNAMIC = "(an import by a name that is not a literal)"

_NOT_CODE = frozenset(
    {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENCODING,
        tokenize.ENDMARKER,
    }
)
_DOCUMENTED = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def code_lines(source: str) -> int:
    """How many physical lines of a Python source hold code. Reported, not budgeted.

    A line counts when a token of code is on it: so a line of code with a comment after it
    counts once, and every line of a statement or a string that runs over several lines
    counts. The lines of a docstring (the string that opens a module, a class or a function)
    do not count; any other string does.
    """
    docstrings: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, _DOCUMENTED) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    code: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in _NOT_CODE:
            code.update(range(token.start[0], token.end[0] + 1))
    return len(code - docstrings)


def raw_lines(source: str) -> int:
    """How many lines a source has, as `wc -l` counts a file that ends with a newline."""
    return len(source.splitlines())


def sources(package: str) -> list[pathlib.Path]:
    return sorted((PACKAGE / package).rglob("*.py"))


def sizes() -> dict[str, tuple[int, int]]:
    """(raw lines, code lines) of each counted package."""
    found: dict[str, tuple[int, int]] = {}
    for package in COUNTED:
        texts = [path.read_text() for path in sources(package)]
        found[package] = (sum(map(raw_lines, texts)), sum(map(code_lines, texts)))
    return found


def _is_import_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    called = node.func
    return (isinstance(called, ast.Attribute) and called.attr == "import_module") or (
        isinstance(called, ast.Name) and called.id in {"__import__", "import_module"}
    )


def imports(source: str, module: str) -> set[str]:
    """What the source of `module` (dotted, as `sortyard.kernel.item`; a package's
    `__init__` as `sortyard.kernel.__init__`) imports.

    A module outside `sortyard` is given by its top-level name. One inside is given as
    `sortyard.<package>`, and `sortyard` alone when the import names the top package and
    nothing under it. `DYNAMIC` stands for a call of `import_module` or `__import__` whose
    argument is not a literal string.
    """
    found: set[str] = set()
    home = module.split(".")[:-1]  # the package the module is in

    def add(target: str, names: list[str] | None = None) -> None:
        parts = target.split(".")
        if parts[0] != "sortyard":
            found.add(parts[0])
        elif len(parts) > 1:
            found.add(f"sortyard.{parts[1]}")
        else:  # `import sortyard` (names is None), or `from sortyard import a, b`
            found.update(f"sortyard.{name}" for name in names or ())
            if not names:
                found.add("sortyard")

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            # `from . import x` starts at the module's package, each further dot one up.
            base = home[: len(home) - (node.level - 1)] if node.level else []
            if node.level and not base:
                found.add(DYNAMIC)  # it reaches above the top package
            else:
                add(".".join([*base, *filter(None, [node.module])]), names)
        elif _is_import_call(node):
            assert isinstance(node, ast.Call)
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                add(first.value)
            else:
                found.add(DYNAMIC)
    return found


def allowed_imports() -> set[str]:
    """The standard library, the project's declared runtime dependencies, and the counted
    and allowed packages of `sortyard`."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = set()
    for requirement in project["dependencies"]:
        name = re.match(r"[A-Za-z0-9_.-]+", requirement)
        assert name is not None, requirement
        declared.add(name.group(0).lower().replace("-", "_"))
    return {
        *sys.stdlib_module_names,
        *declared,
        *(f"sortyard.{package}" for package in (*COUNTED, *MAY_IMPORT)),
    }


def module_name(path: pathlib.Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts)


def escaping_imports() -> dict[str, list[str]]:
    """By file of a counted package: what it imports that the rule does not allow."""
    allowed = allowed_imports()
    return {
        str(path.relative_to(ROOT)): sorted(outside)
        for package in COUNTED
        for path in sources(package)
        if (outside := imports(path.read_text(), module_name(path)) - allowed)
    }


def packages_in(directory: pathlib.Path) -> set[str]:
    """The importable things a source directory holds: packages and modules."""
    return {
        path.stem
        for path in directory.iterdir()
        if path.name != "__pycache__"
        and not path.name.endswith((".egg-info", ".dist-info"))
        and (path.is_dir() or path.suffix in {".py", ".pth", ".so"})
    }


def recorded_packages() -> set[str]:
    """The packages the decision record's tables of figures give a row to."""
    text = (ROOT / "DECISIONS.md").read_text()
    section = re.search(rf"^## {RECORD}\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert section is not None, f"DECISIONS.md has no {RECORD}"
    rows = re.findall(r"^\s*\|\s*`src/sortyard/(\w+)`\s*\|\s*counted\b", section.group(0), re.M)
    return set(rows)


def test_the_kernel_size_by_the_recorded_rule_is_under_the_budget() -> None:
    """the kernel size by the recorded rule is under the budget"""
    found = sizes()
    total = sum(raw for raw, _ in found.values())
    assert total < BUDGET, (
        f"the kernel is {total} lines, and the budget is under {BUDGET} (SY-DEC-010): {found}. "
        "Remove what repeats. Do not cut an explanation, and do not move code out of the count"
    )
    # Not vacuous: every counted package is there and holds code, and code is never the larger.
    for package, (raw, code) in found.items():
        assert 0 < code <= raw, package


def test_the_rule_counts_the_packages_the_decision_record_names() -> None:
    """the rule counts the packages the decision record names"""
    assert recorded_packages() == set(COUNTED)
    for package in COUNTED:
        assert (PACKAGE / package / "__init__.py").is_file(), package
    assert not set(MAY_IMPORT) & set(COUNTED)
    # No second package beside `sortyard` for kernel code to live in.
    assert packages_in(SRC) == {"sortyard"}


def test_the_kernel_imports_nothing_that_escapes_the_count() -> None:
    assert escaping_imports() == {}, (
        "the kernel imports what is neither the standard library, a declared dependency, nor a "
        "counted package. Count the package (COUNTED) or allow it (MAY_IMPORT), with the "
        "reason in SY-DEC-010"
    )
    # The scan sees the imports that are there, and names them as the rule does.
    seen = imports((PACKAGE / "lane" / "runtime.py").read_text(), "sortyard.lane.runtime")
    assert {"sortyard.kernel", "sortyard.engine", "sortyard.lane", "time"} <= seen
    assert seen <= allowed_imports()
    assert {"temporalio", "psycopg", "cryptography"} <= allowed_imports()


def test_a_counted_package_holds_only_python_and_its_data_files() -> None:
    """Code kept in another kind of file (a stub, SQL, a script) would not be counted."""
    other = [
        str(path.relative_to(ROOT))
        for package in COUNTED
        for path in sorted((PACKAGE / package).rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".py"
        and path.suffix not in DATA_SUFFIXES
    ]
    assert other == []


def test_a_second_package_beside_sortyard_is_seen(tmp_path: pathlib.Path) -> None:
    for name in ("sortyard", "sortyard_release", "sortyard.egg-info", "__pycache__"):
        (tmp_path / name).mkdir()
    (tmp_path / "helpers.py").write_text("")
    assert packages_in(tmp_path) == {"sortyard", "sortyard_release", "helpers"}


def test_raw_lines_are_what_wc_counts_and_code_lines_leave_out_explanation() -> None:
    source = '''"""A module docstring
    of two lines."""

    # a comment alone

    import os  # a comment after code


    class Thing:
        """A class docstring."""

        QUERY = (
            "SELECT 1"
            " FROM somewhere"
        )

        def method(self) -> str:
            """A docstring
            over

            four lines."""
            # why this is so
            text = """a string that is not a docstring
            counts on every line"""
            return os.sep + text
    '''
    source = "\n".join(line.removeprefix("    ") for line in source.splitlines()) + "\n"
    assert raw_lines(source) == source.count("\n") == 26
    # import, class, the four lines of QUERY, def, the two lines of text, return.
    assert code_lines(source) == 10
    assert (raw_lines(""), code_lines("")) == (0, 0)
    assert code_lines('"""Only a docstring."""\n') == 0
    # A string that does not open a body is code, wherever it stands.
    assert code_lines('x = 1\n"""not a docstring"""\n') == 2


def test_the_import_scan_catches_every_import_form() -> None:
    allowed = allowed_imports()
    inside = "sortyard.kernel.item"
    for source in (
        "import sortyard.models",
        "import sortyard.models.schema as schema",
        "from sortyard.models import Item",
        "from sortyard.models.schema import load",
        "from sortyard import models",
        "from .. import models",
        "from ..models import Item",
        "from ..models.schema import load",
        "import importlib\nimportlib.import_module('sortyard.models')",
        "__import__('sortyard.models')",
        "def f() -> None:\n    from sortyard.models import Item",
    ):
        assert imports(source, inside) - allowed == {"sortyard.models"}, source
    # Its own package, however it is written, and from a module one level further down.
    for source in ("from . import states", "from .states import load", "from ..kernel import x"):
        assert imports(source, inside) == {"sortyard.kernel"}, source
    assert imports("from .. import states", "sortyard.kernel.sub.deep") == {"sortyard.kernel"}
    assert imports("from . import states", "sortyard.kernel.__init__") == {"sortyard.kernel"}
    # Ways round a scan that only looked for `sortyard.<package>`.
    for source, found in (
        ("import sortyard_release", "sortyard_release"),
        ("from sortyard_release.workflow import run", "sortyard_release"),
        ("import sortyard", "sortyard"),
        ("import sortyard as s", "sortyard"),
        ("import importlib\nimportlib.import_module('sortyard.' + 'release')", DYNAMIC),
        ("name = 'sortyard.release'\n__import__(name)", DYNAMIC),
        ("from importlib import import_module\nimport_module(f'sortyard.{1}')", DYNAMIC),
        ("from ... import release", DYNAMIC),  # above the top package
        ("import requests", "requests"),
    ):
        assert found in imports(source, inside) - allowed, source
    # What the kernel does import is allowed, by the same scan.
    for source in (
        "import os.path\nfrom collections.abc import Mapping",
        "from temporalio import workflow\nimport psycopg\nfrom psycopg.rows import dict_row",
        "from cryptography.hazmat.primitives import hashes",
        "from sortyard.engine import Engine\nfrom sortyard.kernel import policy",
        "import sortyard.lane.github\nfrom . import states",
    ):
        assert imports(source, inside) <= allowed, source


if __name__ == "__main__":
    measured = sizes()
    for name, (raw, code) in measured.items():
        print(f"src/sortyard/{name}: {raw} lines ({code} code lines)")
    print(
        f"total: {sum(raw for raw, _ in measured.values())} lines (budget: under {BUDGET}); "
        f"{sum(code for _, code in measured.values())} code lines, not budgeted"
    )
