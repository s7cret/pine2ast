from __future__ import annotations

import json
from pathlib import Path

from pine2ast import ParseOptions, parse_file
from pine2ast.diagnostics import Severity

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "fixtures" / "real_world_hardening"
INVALID = {"forbidden_visuals_nested_local_blocks.pine"}


def _fixtures() -> list[Path]:
    return sorted(FIXTURE_ROOT.glob("*.pine"))


def test_v31_real_world_hardening_fixture_set_is_complete():
    names = {path.name for path in _fixtures()}
    assert names == {
        "array_map_method_chains.pine",
        "forbidden_visuals_nested_local_blocks.pine",
        "if_expression_initializer.pine",
        "long_strategy_declaration_wrapped.pine",
        "request_security_tuple_nested.pine",
        "strategy_namespace_context_matrix.pine",
        "switch_multiline_cases.pine",
        "udt_constructor_history_fields.pine",
    }


def test_v31_real_world_hardening_valid_fixtures_parse_without_errors():
    for source in _fixtures():
        if source.name in INVALID:
            continue
        result = parse_file(str(source), ParseOptions(source_name=str(source)))
        errors = [d for d in result.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]
        assert not errors, f"{source.name}: {[d.to_dict() for d in errors]}"
        assert result.ast is not None


def test_v31_real_world_hardening_diagnostic_contracts():
    for source in _fixtures():
        contract_path = source.with_suffix(".diagnostics.json")
        if source.name not in INVALID:
            assert not contract_path.exists()
            continue
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        result = parse_file(str(source), ParseOptions(source_name=str(source)))
        actual_codes = {
            d.code for d in result.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}
        }
        assert set(contract["expected_codes"]).issubset(actual_codes)
