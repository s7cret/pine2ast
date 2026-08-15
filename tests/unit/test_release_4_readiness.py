from __future__ import annotations

import json
import tomllib
from pathlib import Path

from pine2ast import __version__
from pine2ast.release import (
    CANONICAL_DOCS,
    RELEASE_VERSION,
    _compatibility_matrix_status,
    build_release_manifest,
    release_manifest_json,
)

ROOT = Path(__file__).resolve().parents[2]


def test_release_version_metadata_is_4_0_1():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == RELEASE_VERSION == "4.0.2"
    assert pyproject["project"]["version"] == "4.0.2"


def test_docs_are_canonical_for_3_2():
    docs = sorted(path.name for path in (ROOT / "docs").glob("*.md"))
    assert docs == sorted(CANONICAL_DOCS)
    assert not [name for name in docs if name.startswith(("STAGE", "P1_", "P2_", "SPEC_", "TZ_"))]


def test_readme_top_level_description_is_release_focused():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "4.0.2" in readme
    assert "openpine.frontend.v2" in readme
    assert "not a TradingView runtime" in readme
    assert "docs/STAGE" not in readme
    assert "release_readiness" not in readme
    assert "release-report" not in readme


def test_release_manifest_gate_passes_for_repo():
    manifest = build_release_manifest(ROOT)
    assert manifest.ok, [check.to_dict() for check in manifest.checks if not check.ok]
    payload = manifest.to_dict()
    assert payload["contracts"]["ast"] == "pine.ast_contract.v1"
    assert payload["contracts"]["openpine"] == "openpine.frontend.v2"
    assert payload["contracts"]["runtime_contract_profile"] == "runtime_contract_v1_4"
    assert payload["contracts"]["semantic_snapshot"] == "pine2ast.semantic_snapshot.v1"
    assert payload["signature_coverage"]["v5"]["summary"]["missing_count"] == 0
    assert payload["signature_coverage"]["v6"]["summary"]["missing_count"] == 0
    checks = {check["name"]: check for check in payload["checks"]}
    assert checks["distribution_hygiene"]["ok"] is True
    assert '"release": "4.0.0"' not in Path("tools/run_quality_gate.py").read_text()
    assert "pine2ast-4.0.0.zip" not in Path("docs/DEVELOPMENT.md").read_text()
    registry_oracle = checks["runtime_registry_semantic_oracle"]
    assert registry_oracle["ok"] is True
    assert set(registry_oracle["details"]) == {"v5", "v6"}
    for version in ("v5", "v6"):
        assert registry_oracle["details"][version]["missing"] == []
        assert registry_oracle["details"][version]["mismatched"] == []

    compatibility = payload["compatibility"]
    assert compatibility["scope"] == "frontend_only"
    assert compatibility["full_pipeline_parity_claimed"] is False
    assert compatibility["item_count"] == 743
    assert compatibility["frontend_ready"] is True
    assert compatibility["summary"]["codegen"]["NOT_STARTED"] > 0
    assert compatibility["summary"]["runtime"]["NOT_STARTED"] > 0
    assert compatibility["summary"]["golden"]["NOT_STARTED"] > 0
    assert checks["compatibility_scope_truthfulness"]["ok"] is True


def test_compatibility_release_gate_rejects_tampered_summary(tmp_path: Path):
    root = tmp_path / "repo"
    matrix_path = root / "pine2ast" / "compatibility" / "compatibility_matrix.json"
    matrix_path.parent.mkdir(parents=True)
    payload = json.loads(
        (ROOT / "pine2ast" / "compatibility" / "compatibility_matrix.json").read_text(
            encoding="utf-8"
        )
    )
    matrix_path.write_text(json.dumps(payload), encoding="utf-8")

    ok, details = _compatibility_matrix_status(root)

    assert ok is True
    assert details["full_pipeline_parity_claimed"] is False
    payload["summary"]["codegen"]["DONE_VERIFIED"] += 1
    matrix_path.write_text(json.dumps(payload), encoding="utf-8")
    assert _compatibility_matrix_status(root)[0] is False


def test_release_manifest_json_is_valid_json():
    payload = json.loads(release_manifest_json(ROOT))
    assert payload["schema_version"] == "pine2ast.release_manifest.v1"
    assert payload["ok"] is True


def test_packaged_release_manifest_has_no_local_paths():
    manifest_path = ROOT / "pine2ast" / "compatibility" / "release_4_0_manifest.json"
    text = manifest_path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["package_version"] == "4.0.2"
    version_check = next(
        check for check in payload["checks"] if check["name"] == "version_metadata"
    )
    assert version_check["details"] == {
        "package": "4.0.2",
        "pyproject": "4.0.2",
        "uv_lock": "4.0.2",
        "expected": "4.0.2",
    }
    assert payload["compatibility"]["scope"] == "frontend_only"
    assert payload["compatibility"]["full_pipeline_parity_claimed"] is False
    assert payload["compatibility"]["summary"]["golden"] == {
        "NOT_STARTED": 703,
        "IMPLEMENTED_UNVERIFIED": 40,
    }
    assert "/mnt/" not in text
    assert "\\Users\\" not in text
    assert "C:\\" not in text
