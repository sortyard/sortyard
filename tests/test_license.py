"""Acceptance (SY-LICENSE-FSL): distributions publish FSL terms and the Apache exceptions.

Build an sdist and then a wheel from that sdist, away from checkout build caches. Assertions
on their metadata and bundled licences exercise what a packager receives. The standalone
spec/ licence must agree with the shipped Apache text. Checkout configuration guards are
supplementary and do not establish distribution contents.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The FSL-1.1-ALv2 template (getsentry/fsl.software) with the Notice line filled in. If the
# licensor name changes, the Notice line in LICENSE.md and this checksum change together.
LICENSE_MD_SHA256 = "95ca1c4276b98a42ebd360b1dafc4ecd2beda3b4f8833238adebfa5c5bd745ec"
# The complete Apache text retained from LICENSE before the FSL change.
APACHE_SHA256 = "b07da1d97928b26514b1761e055d8603b6951e61ac73a6fa7b2ca36652122855"

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
LICENCE_FILES = {"LICENSE.md", "LICENSE-APACHE", "NOTICE"}


@dataclass(frozen=True)
class Distribution:
    metadata: Message
    licences: dict[str, bytes]


@pytest.fixture(scope="module")
def distributions(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Distribution]:
    work = tmp_path_factory.mktemp("licence-build")
    source = work / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "venv", "dist", "build", "*.egg-info", "__pycache__", ".*cache"
        ),
    )
    result = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(work / "dist"), str(source)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # The default build command builds the wheel from the sdist, so missing sdist files
    # cannot be supplied accidentally by the original checkout.
    (sdist,) = (work / "dist").glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        files: dict[str, bytes] = {}
        for member in archive.getmembers():
            if member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                files[member.name.split("/", 1)[1]] = stream.read()
    source_distribution = Distribution(
        BytesParser().parsebytes(files["PKG-INFO"]),
        {name: files[name] for name in LICENCE_FILES if name in files},
    )
    (wheel,) = (work / "dist").glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        (metadata_name,) = (
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        licence_prefix = metadata_name.removesuffix("METADATA") + "licenses/"
        wheel_distribution = Distribution(
            BytesParser().parsebytes(archive.read(metadata_name)),
            {
                name.removeprefix(licence_prefix): archive.read(name)
                for name in archive.namelist()
                if name.startswith(licence_prefix) and not name.endswith("/")
            },
        )
    return {"sdist": source_distribution, "wheel": wheel_distribution}


@pytest.fixture(params=["sdist", "wheel"])
def distribution(
    request: pytest.FixtureRequest, distributions: dict[str, Distribution]
) -> Distribution:
    return distributions[str(request.param)]


def _flat(text: str) -> str:
    """Collapse line wrapping so wrapped prose compares equal to the one-line statement."""
    return " ".join(text.split())


def test_distribution_publishes_fsl_metadata_and_all_licence_files(
    distribution: Distribution,
) -> None:
    assert distribution.metadata["License-Expression"] == "FSL-1.1-ALv2"
    assert set(distribution.metadata.get_all("License-File", [])) == LICENCE_FILES
    assert set(distribution.licences) == LICENCE_FILES
    assert distribution.metadata["License"] is None
    assert not OPEN_SOURCE.search(str(distribution.metadata["Summary"]))


def test_license_md_is_the_exact_fsl_text(distribution: Distribution) -> None:
    data = distribution.licences["LICENSE.md"]
    assert hashlib.sha256(data).hexdigest() == LICENSE_MD_SHA256
    text = data.decode()
    assert "FSL-1.1-ALv2" in text
    assert "Copyright 2026 NONCE LOGIC LLC" in text
    assert data.endswith(b".\n") and not data.endswith(b"\n\n")


def test_notice_states_licence_conversion_spec_exception_and_earlier_versions(
    distribution: Distribution,
) -> None:
    notice = _flat(distribution.licences["NOTICE"].decode())
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


def test_published_readme_carries_notice_and_says_source_available(
    distribution: Distribution,
) -> None:
    assert distribution.metadata["Description-Content-Type"] == "text/markdown"
    readme = distribution.metadata.get_payload()
    assert isinstance(readme, str)
    assert "## Licence" in readme
    section = readme.split("## Licence", 1)[1].split("\n## ", 1)[0]
    assert NOTICE_TEXT in _flat(section)
    assert "source-available" in readme
    assert not OPEN_SOURCE.search(readme)


def test_checkout_licence_configuration() -> None:
    """Supplementary configuration guard; distribution tests establish shipped contents."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["license"] == "FSL-1.1-ALv2"
    assert set(project["license-files"]) == LICENCE_FILES
    assert not OPEN_SOURCE.search(project["description"])
    assert not OPEN_SOURCE.search((ROOT / "AGENTS.md").read_text())
    assert not (ROOT / "LICENSE").exists()


def test_distribution_preserves_the_apache_licence_for_spec_and_future_use(
    distribution: Distribution,
) -> None:
    data = distribution.licences["LICENSE-APACHE"]
    assert hashlib.sha256(data).hexdigest() == APACHE_SHA256
    assert (ROOT / "spec" / "LICENSE").read_bytes() == data
    apache = data.decode()
    assert "Apache License" in apache and "Version 2.0, January 2004" in apache
    assert "END OF TERMS AND CONDITIONS" in apache
