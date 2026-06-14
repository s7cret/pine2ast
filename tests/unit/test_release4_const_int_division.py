from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.semantic.inference import PineInferenceEngine


def test_v6_const_int_division_initializer_is_float_for_explicit_int_target() -> None:
    src = """//@version=6
indicator("div")
const int ratio = 1 / 2
"""
    result = parse_code(src, ParseOptions(version=6))
    assert codes.TYPE_MISMATCH in [diag.code for diag in result.diagnostics]


def test_v6_const_int_division_is_accepted_for_float_target() -> None:
    src = """//@version=6
indicator("div")
const float ratio = 1 / 2
"""
    result = parse_code(src, ParseOptions(version=6))
    assert result.ok


def test_v5_const_int_division_legacy_int_profile_is_preserved() -> None:
    src = """//@version=5
indicator("div")
const int ratio = 1 / 2
"""
    result = parse_code(src, ParseOptions(version=5))
    assert codes.TYPE_MISMATCH not in [diag.code for diag in result.diagnostics]


def test_inference_engine_reports_v6_const_int_division_as_float() -> None:
    src = """//@version=6
indicator("div")
value = 1 / 2
"""
    result = parse_code(src, ParseOptions(run_semantic=True, version=6))
    assert result.ast is not None
    assignment = result.ast.items[0]
    expression = assignment.initializer
    assert (
        PineInferenceEngine(symbols=result.semantic_model.symbols, pine_version=6).infer_type(
            expression
        )
        == "float"
    )
