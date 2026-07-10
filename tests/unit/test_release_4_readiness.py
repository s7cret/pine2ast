from __future__ import annotations

import json
import tomllib
from pathlib import Path

from pine2ast import __version__
from pine2ast.release import (
    CANONICAL_DOCS,
    RELEASE_VERSION,
    build_release_manifest,
    release_manifest_json,
)

ROOT = Path(__file__).resolve().parents[2]


def test_release_version_metadata_is_3_2_0():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == RELEASE_VERSION == "4.0.0"
    assert pyproject["project"]["version"] == "4.0.0"


def test_docs_are_canonical_for_3_2():
    docs = sorted(path.name for path in (ROOT / "docs").glob("*.md"))
    assert docs == sorted(CANONICAL_DOCS)
    assert not [name for name in docs if name.startswith(("STAGE", "P1_", "P2_", "SPEC_", "TZ_"))]


def test_readme_top_level_description_is_release_focused():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "4.0.0" in readme
    assert "openpine.frontend.v1" in readme
    assert "not a TradingView runtime" in readme
    assert "docs/STAGE" not in readme
    assert "release_readiness" not in readme
    assert "release-report" not in readme


def test_release_manifest_gate_passes_for_repo():
    manifest = build_release_manifest(ROOT)
    assert manifest.ok, [check.to_dict() for check in manifest.checks if not check.ok]
    payload = manifest.to_dict()
    assert payload["contracts"]["ast"] == "pine.ast_contract.v1"
    assert payload["contracts"]["openpine"] == "openpine.frontend.v1"
    assert payload["contracts"]["runtime_contract_profile"] == "runtime_contract_v1_4"
    assert payload["contracts"]["semantic_snapshot"] == "pine2ast.semantic_snapshot.v1"
    assert payload["signature_coverage"]["v5"]["summary"]["missing_count"] == 0
    assert payload["signature_coverage"]["v6"]["summary"]["missing_count"] == 0
    checks = {check["name"]: check for check in payload["checks"]}
    assert checks["distribution_hygiene"]["ok"] is True
    registry_oracle = checks["runtime_registry_semantic_oracle"]
    assert registry_oracle["ok"] is True
    assert set(registry_oracle["details"]) == {"v5", "v6"}
    for version in ("v5", "v6"):
        assert registry_oracle["details"][version]["missing"] == []
        assert registry_oracle["details"][version]["mismatched"] == []


def test_release_manifest_json_is_valid_json():
    payload = json.loads(release_manifest_json(ROOT))
    assert payload["schema_version"] == "pine2ast.release_manifest.v1"
    assert payload["ok"] is True


def test_packaged_release_manifest_has_no_local_paths():
    manifest_path = ROOT / "pine2ast" / "compatibility" / "release_4_0_manifest.json"
    text = manifest_path.read_text(encoding="utf-8")
    assert "/mnt/" not in text
    assert "\\Users\\" not in text
    assert "C:\\" not in text
