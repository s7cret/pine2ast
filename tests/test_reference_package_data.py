"""PEP 517 artifacts must work independently of checkout resource files."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
RESOURCE_NAMES = (
    "official_pine_v5_gap_baseline.json",
    "official_pine_v5_reference_index.json",
    "official_pine_v6_gap_baseline.json",
    "official_pine_v6_reference_index.json",
    "parity_matrix.json",
    "pine_v6_reference_catalog.json",
)
RESOURCE_ROOT = "pine2ast/reference_catalog/"


@pytest.fixture(scope="module")
def reference_artifacts(tmp_path_factory):
    output = tmp_path_factory.mktemp("reference-artifacts")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist", "--no-isolation", "--outdir", str(output)],
        cwd=PROJECT,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels, sdists = list(output.glob("*.whl")), list(output.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    return wheels[0], sdists[0]


def extracted_wheel(wheel, target):
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(target)
    return target


def isolated_probe(root, code):
    # -S excludes editable installs and site packages; -I ignores PYTHONPATH and
    # the working directory. Only this extracted wheel supplies pine2ast.
    bootstrap = (
        "import pathlib, sys; "
        "sys.path.insert(0, sys.argv[1]); "
        "import pine2ast; "
        "assert pathlib.Path(pine2ast.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve()); "
    )
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", bootstrap + code, str(root)],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_wheel_and_sdist_include_every_reference_resource(reference_artifacts):
    wheel, sdist = reference_artifacts
    with zipfile.ZipFile(wheel) as archive:
        for name in RESOURCE_NAMES:
            member = RESOURCE_ROOT + name
            assert archive.read(member) == (PROJECT / member).read_bytes()
    with tarfile.open(sdist, "r:gz") as archive:
        members = {member.name.split("/", 1)[1]: member for member in archive.getmembers() if "/" in member.name}
        for name in RESOURCE_NAMES:
            member = RESOURCE_ROOT + name
            stream = archive.extractfile(members[member])
            assert stream is not None and stream.read() == (PROJECT / member).read_bytes()


def test_extracted_wheel_validates_default_catalog_and_matrix(reference_artifacts, tmp_path):
    root = extracted_wheel(reference_artifacts[0], tmp_path)
    result = isolated_probe(root, "from pine2ast.reference_catalog import validate_catalog, validate_matrix; validate_catalog(); validate_matrix(); print('validated')")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "validated"


def test_extracted_wheel_missing_resources_cannot_fall_back_to_checkout(reference_artifacts, tmp_path):
    root = extracted_wheel(reference_artifacts[0], tmp_path)
    for name in ("pine_v6_reference_catalog.json", "parity_matrix.json"):
        resource = root / RESOURCE_ROOT / name
        original = resource.read_bytes()
        resource.unlink()
        try:
            result = isolated_probe(root, "from pine2ast.reference_catalog import validate_matrix; validate_matrix()")
        finally:
            resource.write_bytes(original)
        assert result.returncode != 0
        assert "FileNotFoundError" in result.stderr and name in result.stderr
