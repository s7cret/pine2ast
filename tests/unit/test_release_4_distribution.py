from __future__ import annotations

import json
from zipfile import ZipFile

from pine2ast.distribution import (
    build_distribution_manifest,
    create_source_zip,
    iter_release_files,
)


def test_distribution_manifest_selects_required_files_and_excludes_caches(tmp_path):
    root = tmp_path / "repo"
    (root / "pine2ast" / "__pycache__").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "README.md").write_text("readme", encoding="utf-8")
    (root / "CHANGELOG.md").write_text("changelog", encoding="utf-8")
    (root / "LICENSE").write_text("license", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='pine2ast'\n", encoding="utf-8")
    (root / "pine2ast" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pine2ast" / "_version.py").write_text('__version__ = "4.0.0"\n', encoding="utf-8")
    (root / "pine2ast" / "__pycache__" / "x.pyc").write_bytes(b"cache")
    (root / "pine2ast.egg-info").mkdir()
    (root / "pine2ast.egg-info" / "PKG-INFO").write_text("generated", encoding="utf-8")
    (root / ".release_gate_reports").mkdir()
    (root / ".release_gate_reports" / "QUALITY_GATE_FINAL.json").write_text("{}", encoding="utf-8")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_bytes(b"binary")
    (root / "venv" / "lib").mkdir(parents=True)
    (root / "venv" / "lib" / "native.so").write_bytes(b"binary")
    (root / "pine2ast-4.0.0.zip").write_bytes(b"archive")
    (root / "docs" / "README.md").write_text("docs", encoding="utf-8")

    manifest = build_distribution_manifest(root)
    selected = {path.relative_to(root).as_posix() for path in iter_release_files(root)}

    assert manifest.ok, manifest.to_dict()
    assert "pine2ast/__pycache__/x.pyc" not in selected
    assert "pine2ast.egg-info/PKG-INFO" not in selected
    assert ".release_gate_reports/QUALITY_GATE_FINAL.json" not in selected
    assert ".venv/bin/python" not in selected
    assert "venv/lib/native.so" not in selected
    assert "pine2ast-4.0.0.zip" not in selected
    assert manifest.excluded_file_count == 6


def test_distribution_zip_is_deterministic_and_extractable(tmp_path):
    root = tmp_path / "repo"
    (root / "pine2ast").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    for name in ["README.md", "CHANGELOG.md", "LICENSE", "pyproject.toml"]:
        (root / name).write_text(name, encoding="utf-8")
    (root / "pine2ast" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pine2ast" / "_version.py").write_text('__version__ = "4.0.0"\n', encoding="utf-8")
    (root / "docs" / "README.md").write_text("docs", encoding="utf-8")

    output = tmp_path / "out.zip"
    payload = create_source_zip(root, output, root_name="pine2ast-test")
    assert payload["ok"] is True
    with ZipFile(output) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "pine2ast-test/README.md" in names
        assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]
        archive.testzip() is None
    json.dumps(payload)
