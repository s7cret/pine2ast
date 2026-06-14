from __future__ import annotations

import json
from pathlib import Path

from pine2ast.api import ParseOptions, ast_to_json, parse_code
from pine2ast.cli import main as cli_main
from pine2ast.contracts import contract_check_file_payload, validate_contract_payload
from pine2ast.inspect_contract import build_inspect_payload
from pine2ast.openpine_contract import build_openpine_contract_payload
from pine2ast.release import build_release_manifest

SOURCE = """//@version=6
indicator("Contract Smoke", overlay=true)
var array<float> xs = array.new<float>()
array.push(xs, close)
plot(array.get(xs, 0))
"""


def _parse_ok():
    result = parse_code(SOURCE, ParseOptions(version=6, source_name="contract_smoke.pine"))
    assert result.ok, [diagnostic.to_dict() for diagnostic in result.diagnostics]
    return result


def test_public_contract_validator_accepts_ast_inspect_and_openpine_payloads() -> None:
    result = _parse_ok()
    ast_payload = json.loads(ast_to_json(result.ast))
    inspect_payload = build_inspect_payload(
        result,
        source_path="contract_smoke.pine",
        include_openpine_contract=True,
    )
    openpine_payload = build_openpine_contract_payload(result, source_path="contract_smoke.pine")

    assert validate_contract_payload(ast_payload, expected_contract="pine.ast_contract.v1").ok
    assert validate_contract_payload(inspect_payload).ok
    assert validate_contract_payload(openpine_payload).ok


def test_public_contract_validator_reports_missing_nested_sections() -> None:
    result = _parse_ok()
    payload = build_openpine_contract_payload(result, source_path="bad_contract.pine")
    payload.pop("collections")

    report = validate_contract_payload(payload)

    assert not report.ok
    assert any(
        issue.path == "$.collections" and issue.code == "missing_key" for issue in report.issues
    )


def test_contract_check_file_payload_uses_embedded_openpine_contract(tmp_path: Path) -> None:
    source_path = tmp_path / "contract_smoke.pine"
    source_path.write_text(SOURCE, encoding="utf-8")

    payload = contract_check_file_payload(source_path)

    assert payload["ok"] is True
    assert payload["parse_ok"] is True
    assert payload["contract_ok"] is True
    assert payload["contract_report"]["contract"] == "pine2ast.inspect.optimizer.v1"


def test_cli_contract_check_writes_json(tmp_path: Path) -> None:
    source_path = tmp_path / "contract_smoke.pine"
    output_path = tmp_path / "contract.json"
    source_path.write_text(SOURCE, encoding="utf-8")

    exit_code = cli_main(["contract-check", str(source_path), "--json", str(output_path)])

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["contract_report"]["ok"] is True


def test_release_manifest_includes_public_contract_smoke() -> None:
    payload = build_release_manifest(Path(__file__).resolve().parents[2]).to_dict()
    checks = {check["name"]: check for check in payload["checks"]}

    assert checks["public_contract_smoke"]["ok"] is True
    assert checks["public_contract_smoke"]["details"]["contract_report"]["ok"] is True
