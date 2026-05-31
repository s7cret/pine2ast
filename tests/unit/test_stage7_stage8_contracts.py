from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).absolute().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pine2ast.benchmark import perf_baseline  # noqa: E402
from pine2ast.cli import main  # noqa: E402
from tools.build_release_zip import ReleaseBuildError, build_manifest, build_zip  # noqa: E402

INSPECT_FIXTURE = ROOT / "tests" / "fixtures" / "inspect_contract" / "optimizer_strategy.pine"
INSPECT_CONTRACT = (
    ROOT / "tests" / "fixtures" / "inspect_contract" / "optimizer_strategy.inspect.json"
)


def test_inspect_optimizer_contract_matches_committed_fixture(tmp_path: Path):
    out = tmp_path / "inspect.json"
    assert main(["inspect", str(INSPECT_FIXTURE.relative_to(ROOT)), "--json", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    expected = json.loads(INSPECT_CONTRACT.read_text(encoding="utf-8"))
    assert payload == expected
    assert payload["schema_version"] == 1
    assert payload["contract"] == "pine2ast.inspect.optimizer.v1"
    assert payload["dependencies"]["external_calls"] == ["lib.score"]
    assert payload["inputs"][1]["options"] == [8, 12, 21]


def test_perf_baseline_report_has_stable_contract_and_budget_status():
    report = perf_baseline(ROOT / "tests" / "fixtures" / "inspect_contract", repeat=1)
    assert report["schema_version"] == 1
    assert report["report"] == "pine2ast.performance_baseline"
    assert report["ok"] is True
    assert report["bench"]["summary"]["file_count"] == 1
    assert report["bench"]["summary"]["ok_count"] == 1


def test_release_zip_is_reproducible_and_excludes_temp_venv_pycache_and_secrets(tmp_path: Path):
    root = tmp_path / "pkg"
    (root / "pine2ast").mkdir(parents=True)
    (root / "pine2ast" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "bad.pyc").write_bytes(b"bad")
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_text("bad\n", encoding="utf-8")
    (root / "temp").mkdir()
    (root / "temp" / "scratch.txt").write_text("bad\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=bad\n", encoding="utf-8")
    (root / "api_secret.txt").write_text("bad\n", encoding="utf-8")

    out1 = tmp_path / "one.zip"
    out2 = tmp_path / "two.zip"
    digest1 = build_zip(root, out1)
    digest2 = build_zip(root, out2)
    assert digest1 == digest2

    manifest = build_manifest(root, out1, digest1)
    assert manifest["checks"] == {
        "no_pycache": True,
        "no_temp_or_venv": True,
        "no_secret_names": True,
    }
    with zipfile.ZipFile(out1) as zf:
        names = zf.namelist()
    assert names == ["pkg/pine2ast/__init__.py"]


def test_release_zip_refuses_missing_file_and_empty_roots(tmp_path: Path):
    out = tmp_path / "out.zip"

    missing_root = tmp_path / "missing"
    try:
        build_zip(missing_root, out)
    except ReleaseBuildError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing release root should be refused")
    assert not out.exists()

    file_root = tmp_path / "file-root"
    file_root.write_text("not a directory\n", encoding="utf-8")
    try:
        build_zip(file_root, out)
    except ReleaseBuildError as exc:
        assert "must be a directory" in str(exc)
    else:
        raise AssertionError("file release root should be refused")
    assert not out.exists()

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    try:
        build_zip(empty_root, out)
    except ReleaseBuildError as exc:
        assert "no includable files" in str(exc)
    else:
        raise AssertionError("empty release root should be refused")
    assert not out.exists()


def test_release_manifest_refuses_empty_archive(tmp_path: Path):
    root = tmp_path / "pkg"
    root.mkdir()
    out = tmp_path / "empty.zip"
    with zipfile.ZipFile(out, "w"):
        pass

    try:
        build_manifest(root, out, "0" * 64)
    except ReleaseBuildError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty release archive should be refused")
