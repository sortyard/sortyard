"""Acceptance (SY-LICENSE-FSL): Sortyard is FSL-1.1-ALv2; spec/ and earlier versions stay Apache."""

from __future__ import annotations

import hashlib
import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The FSL-1.1-ALv2 template (getsentry/fsl.software) with the Notice line filled in. If the
# licensor name changes, the Notice line in LICENSE.md and this checksum change together.
LICENSE_MD_SHA256 = "95ca1c4276b98a42ebd360b1dafc4ecd2beda3b4f8833238adebfa5c5bd745ec"

NOTICE_TEXT = (
    "Sortyard is licensed under the Functional Source License, Version 1.1, ALv2 Future License "
    "(FSL-1.1-ALv2); see LICENSE.md. You may use, copy, modify and redistribute it for any "
    "purpose other than a Competing Use as that licence defines it. Each version becomes "
    "available under the Apache License, Version 2.0 on the second anniversary of the date that "
    "version was made available. The spec/ directory is licensed under the Apache License, "
    "Version 2.0; see LICENSE-APACHE. Versions of this repository published before the commit "
    "that added this notice were published under the Apache License, Version 2.0 and remain "
    "available under it."
)

OPEN_SOURCE = re.compile(r"open[\s-]+source", re.IGNORECASE)


def _flat(text: str) -> str:
    """Collapse line wrapping so wrapped prose compares equal to the one-line statement."""
    return " ".join(text.split())


def test_license_md_is_the_exact_fsl_text() -> None:
    data = (ROOT / "LICENSE.md").read_bytes()
    assert hashlib.sha256(data).hexdigest() == LICENSE_MD_SHA256
    text = data.decode()
    assert "FSL-1.1-ALv2" in text
    assert "Copyright 2026 NONCE LOGIC LLC" in text
    assert data.endswith(b".\n") and not data.endswith(b"\n\n")


def test_notice_states_licence_conversion_spec_exception_and_earlier_versions() -> None:
    notice = _flat((ROOT / "NOTICE").read_text())
    assert NOTICE_TEXT in notice
    for phrase in (
        "FSL-1.1-ALv2",
        "Competing Use",
        "Each version becomes available under the Apache License, Version 2.0 on the second "
        "anniversary",
        "The spec/ directory is licensed under the Apache License, Version 2.0",
        "published before the commit that added this notice",
        "remain available under it",
    ):
        assert phrase in notice, phrase


def test_readme_carries_notice_and_no_file_says_open_source() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "## Licence" in readme
    section = readme.split("## Licence", 1)[1].split("\n## ", 1)[0]
    assert NOTICE_TEXT in _flat(section)
    assert "source-available" in readme
    for name in ("README.md", "AGENTS.md", "pyproject.toml"):
        found = OPEN_SOURCE.search((ROOT / name).read_text())
        assert found is None, f"{name} still says {found.group(0)!r}"


def test_pyproject_declares_fsl_and_lists_licence_files() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["license"] == "FSL-1.1-ALv2"
    assert set(project["license-files"]) == {"LICENSE.md", "LICENSE-APACHE", "NOTICE"}
    assert not OPEN_SOURCE.search(project["description"])
    for name in project["license-files"]:
        assert (ROOT / name).is_file(), name


def test_apache_text_stays_for_spec_and_as_future_licence() -> None:
    assert not (ROOT / "LICENSE").exists()
    apache = (ROOT / "LICENSE-APACHE").read_text()
    assert "Apache License" in apache and "Version 2.0, January 2004" in apache
    assert "END OF TERMS AND CONDITIONS" in apache
    assert (ROOT / "spec" / "LICENSE").read_text() == apache
