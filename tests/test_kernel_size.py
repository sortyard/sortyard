"""Acceptance: the size of the hand-written kernel, by the rule of SY-DEC-010 (SY-V3-KERNEL-SIZE).

Win criterion 10 of HARNESS-V3 section 5 keeps the hand-written kernel under 5,000 lines.
DECISIONS.md, SY-DEC-010, says what is counted; this file is the one place that holds the rule
as values (`COUNTED`, `MAY_IMPORT`, `DATA_SUFFIXES`, `BUDGET`) and the record names it.

The budgeted figure is code lines: the physical lines of the `.py` files of the counted
packages that hold code. A blank line, a line holding only a comment and the lines of a
docstring are not counted, so explaining why costs nothing. The raw figure (`wc -l`) is
reported beside it and has no budget.

`python -m tests.test_kernel_size` prints both figures by package.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "sortyard"
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
    """How many physical lines of a Python source hold code.

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


def sources(package: str) -> list[pathlib.Path]:
    return sorted((PACKAGE / package).rglob("*.py"))


def sizes() -> dict[str, tuple[int, int]]:
    """(code lines, raw lines) of each counted package."""
    found: dict[str, tuple[int, int]] = {}
    for package in COUNTED:
        texts = [path.read_text() for path in sources(package)]
        found[package] = (sum(map(code_lines, texts)), sum(len(t.splitlines()) for t in texts))
    return found


def sortyard_imports(source: str, package: str) -> set[str]:
    """The packages of `sortyard` a source of `sortyard.<package>` imports, by `import`,
    `from ... import` (relative ones too) or an import by a literal name."""
    found: set[str] = set()

    def add(module: str, names: list[str]) -> None:
        parts = module.split(".")
        if parts[0] == "sortyard":
            # `from sortyard import x` names the package itself.
            found.update(parts[1:2] or names)

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name, [])
        elif isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            if node.level == 0:
                add(node.module or "", names)
            elif node.level == 1:  # from . import x, from .x import y: its own package
                found.add(package)
            else:  # from .. import x, from ..x import y: read from the top of sortyard
                add(".".join(["sortyard", *(node.module or "").split(".")]).rstrip("."), names)
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
            add(node.args[0].value, [])
    return found


def recorded_packages() -> set[str]:
    """The packages the decision record's table of figures gives a row to."""
    text = (ROOT / "DECISIONS.md").read_text()
    section = re.search(rf"^## {RECORD}\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert section is not None, f"DECISIONS.md has no {RECORD}"
    return set(re.findall(r"^\s*\|\s*`src/sortyard/(\w+)`", section.group(0), re.MULTILINE))


def test_the_kernel_size_by_the_recorded_rule_is_under_the_budget() -> None:
    """the kernel size by the recorded rule is under the budget"""
    found = sizes()
    total = sum(code for code, _ in found.values())
    assert total < BUDGET, (
        f"the kernel is {total} code lines, and the budget is under {BUDGET} (SY-DEC-010): "
        f"{found}. Remove what repeats, or amend the record; do not move code out of the count"
    )
    # Not vacuous: every counted package is there and holds code, and raw is never the smaller.
    for package, (code, raw) in found.items():
        assert 0 < code <= raw, package


def test_the_rule_counts_the_packages_the_decision_record_names() -> None:
    """the rule counts the packages the decision record names"""
    assert recorded_packages() == set(COUNTED)
    for package in COUNTED:
        assert (PACKAGE / package / "__init__.py").is_file(), package
    assert not set(MAY_IMPORT) & set(COUNTED)


def test_the_kernel_imports_no_sortyard_package_that_escapes_the_count() -> None:
    known = {*COUNTED, *MAY_IMPORT}
    escaping = {
        str(path.relative_to(ROOT)): sorted(outside)
        for package in COUNTED
        for path in sources(package)
        if (outside := sortyard_imports(path.read_text(), package) - known)
    }
    assert escaping == {}, (
        f"the kernel imports sortyard packages that are neither counted nor allowed: {escaping}. "
        "Count the package (COUNTED) or allow it (MAY_IMPORT), with the reason in SY-DEC-010"
    )
    # The scan sees the imports that are there: the lane adapters import the kernel.
    assert "kernel" in sortyard_imports((PACKAGE / "lane" / "runtime.py").read_text(), "lane")


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


def test_comments_docstrings_and_blank_lines_are_not_counted_and_code_is() -> None:
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
    # import, class, the four lines of QUERY, def, the two lines of text, return.
    assert code_lines(source) == 10
    assert code_lines("") == 0
    assert code_lines('"""Only a docstring."""\n') == 0
    # A string that does not open a body is code, wherever it stands.
    assert code_lines('x = 1\n"""not a docstring"""\n') == 2


def test_the_import_scan_catches_every_import_form() -> None:
    for source in (
        "import sortyard.models",
        "import sortyard.models.schema as schema",
        "from sortyard.models import Item",
        "from sortyard.models.schema import load",
        "from sortyard import models",
        "from .. import models",
        "from ..models import Item",
        "import importlib\nimportlib.import_module('sortyard.models')",
        "__import__('sortyard.models')",
        "def f() -> None:\n    from sortyard.models import Item",
    ):
        assert sortyard_imports(source, "kernel") == {"models"}, source
    assert sortyard_imports("from . import states\nfrom .states import load", "kernel") == {
        "kernel"
    }
    assert sortyard_imports("import sortyardish.models\nimport os", "kernel") == set()


if __name__ == "__main__":
    measured = sizes()
    for name, (code, raw) in measured.items():
        print(f"src/sortyard/{name}: {code} code lines, {raw} raw lines")
    print(
        f"total: {sum(code for code, _ in measured.values())} code lines (budget: under "
        f"{BUDGET}), {sum(raw for _, raw in measured.values())} raw lines"
    )
