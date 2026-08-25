from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

from openpine_contracts import get_schema, list_schema_ids, validate_payload

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "pine2ast"
CONTRACTS_VERSION = "5.0.0rc5"
CONTRACTS_COMMIT = "6b5e67445e2772057cd877e158c7aa0c58bdfe37"
FRONTEND_V2 = "openpine.frontend.v2"
GENERATED_ARTIFACT_V2 = "openpine.generated_artifact.v2"
INTENT_V2 = "openpine.intent.v2"

_HANDMADE_ENUMS = frozenset({"Finality", "RevisionState", "SemanticProfile", "WarmupMode"})
_CATALOG_SCHEMA_COPIES = frozenset(
    {
        "openpine.frontend.v2.json",
        "openpine.generated_artifact.v2.json",
        "openpine.support_profile.v2.json",
        "openpine.intent.v2.json",
        "pine.ast.v1.json",
    }
)


def _iter_package_text_files() -> list[Path]:
    files: list[Path] = []
    for path in PACKAGE.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".json"}:
            continue
        files.append(path)
    return files


def test_contracts_pin_and_catalog() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'"openpine-contracts=={CONTRACTS_VERSION}"' in text
    assert "git+" not in text
    ids = list_schema_ids()
    assert FRONTEND_V2 in ids
    assert GENERATED_ARTIFACT_V2 in ids
    assert INTENT_V2 in ids


def test_ci_contracts_checkouts_use_exact_rc4_commit() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert workflow.count(f"ref: {CONTRACTS_COMMIT}") == 2
    assert "91c405e759206b542d22df242ef55ac49b1f0bb4" not in workflow


def test_ci_deduplicates_feature_branch_push_and_pull_request_runs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "push:\n    branches: [main]" in workflow
    assert "pull_request:\n    branches: [main]" in workflow
    assert "github.event.pull_request.number || github.ref" in workflow


def test_package_identity_is_5_0_0rc4() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    from pine2ast._version import __version__

    assert pyproject["project"]["version"] == "5.0.0rc5"
    assert __version__ == "5.0.0rc5"


def test_no_local_openpine_contracts_sot_copy() -> None:
    local = PACKAGE / "openpine_contracts"
    assert not local.exists(), (
        "local pine2ast/openpine_contracts/ SoT copy must be deleted; "
        "import the installed openpine_contracts package"
    )


def test_package_code_has_no_handmade_frontend_v1() -> None:
    hits = [
        str(path.relative_to(ROOT))
        for path in _iter_package_text_files()
        if "openpine.frontend.v1" in path.read_text(encoding="utf-8")
    ]
    assert hits == []


def test_package_code_has_no_handmade_canonical_enums() -> None:
    hits: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name in _HANDMADE_ENUMS:
                hits.append(f"{path.relative_to(ROOT)}:{node.name}")
    assert hits == []


def test_no_local_catalog_schema_json_copies() -> None:
    found = [
        str(path.relative_to(ROOT))
        for path in PACKAGE.rglob("*.json")
        if "__pycache__" not in path.parts and path.name in _CATALOG_SCHEMA_COPIES
    ]
    assert found == []


def test_release_and_validation_use_catalog_frontend_v2() -> None:
    from pine2ast.contracts.validation import OPENPINE_CONTRACT
    from pine2ast.release import OPENPINE_CONTRACT_VERSION

    ids = list_schema_ids()
    assert OPENPINE_CONTRACT_VERSION == FRONTEND_V2
    assert OPENPINE_CONTRACT == FRONTEND_V2
    assert OPENPINE_CONTRACT_VERSION in ids
    schema = get_schema(FRONTEND_V2)
    assert schema["$id"] == FRONTEND_V2


def test_release_manifest_pins_catalog_frontend_v2() -> None:
    manifest = json.loads(
        (PACKAGE / "compatibility" / "release_4_0_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["contracts"]["openpine"] == FRONTEND_V2
    assert manifest["package_version"] == "5.0.0rc5"


def test_frontend_v2_artifact_validates_against_catalog() -> None:
    from pine2ast.api import ParseOptions, parse_code
    from pine2ast.openpine_contract import build_frontend_v2_payload

    result = parse_code(
        '//@version=6\nindicator("T")\nplot(close)\n',
        ParseOptions(source_name="frontend_v2.pine"),
    )
    payload = build_frontend_v2_payload(result, source_path="frontend_v2.pine")
    validate_payload(FRONTEND_V2, payload)
    assert payload["semantic_profile"] == "strict_5x"
    assert payload["producer"] == "pine2ast"
