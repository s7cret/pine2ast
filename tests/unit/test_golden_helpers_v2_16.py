from __future__ import annotations

import json

from pine2ast.testing.golden import (
    compare_diagnostics,
    compare_golden,
    diagnostics_to_contract_payload,
    generate_golden,
    validate_invalid_diagnostic_contract,
)


def test_golden_helpers_cover_success_and_missing_paths(tmp_path):
    src = tmp_path / "ok.pine"
    src.write_text('//@version=6\nindicator("OK")\nplot(close)\n', encoding="utf-8")

    generated = generate_golden(src, ignore_spans=True, run_semantic=True)
    assert generated["ok"] is True

    ok, message = compare_golden(src, ignore_spans=True, run_semantic=True)
    assert (ok, message) == (True, "OK")

    ok, message = compare_golden(src, ast_path=tmp_path / "missing.ast.json")
    assert ok is False
    assert "does not exist" in message

    ok, message = compare_diagnostics(
        src,
        diagnostics_path=generated["diagnostics_path"],
        ignore_spans=True,
        run_semantic=True,
    )
    assert (ok, message) == (True, "OK")

    ok, message = compare_diagnostics(src, diagnostics_path=tmp_path / "missing.diag.json")
    assert ok is False
    assert "does not exist" in message

    assert diagnostics_to_contract_payload(
        [{"code": "X", "span": {"start_offset": 1}}], ignore_spans=True
    ) == [{"code": "X"}]


def test_invalid_diagnostic_contract_rejects_bad_contracts(tmp_path):
    src = tmp_path / "bad.pine"
    src.write_text('//@version=6\nindicator("Bad")\nif close\n    plot(close)\n', encoding="utf-8")

    ok, message = validate_invalid_diagnostic_contract(
        src, diagnostics_path=tmp_path / "missing.json"
    )
    assert ok is False
    assert "does not exist" in message

    empty_contract = tmp_path / "empty.diagnostics.json"
    empty_contract.write_text(json.dumps({"expected_codes": []}), encoding="utf-8")
    ok, message = validate_invalid_diagnostic_contract(src, diagnostics_path=empty_contract)
    assert ok is False
    assert "no expected_codes" in message

    missing_contract = tmp_path / "missing_code.diagnostics.json"
    missing_contract.write_text(json.dumps({"expected_codes": ["NO_SUCH_CODE"]}), encoding="utf-8")
    ok, message = validate_invalid_diagnostic_contract(src, diagnostics_path=missing_contract)
    assert ok is False
    assert "Missing expected" in message
