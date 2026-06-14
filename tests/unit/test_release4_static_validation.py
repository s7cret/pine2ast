from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.openpine_contract import build_openpine_contract_payload
from pine2ast.semantic.static_validation import build_static_validation_report


def _codes(src: str, *, version: int = 6) -> list[str]:
    result = parse_code(src, ParseOptions(version=version, run_semantic=True))
    return [diag.code for diag in result.diagnostics]


def test_dynamic_request_disabled_rejects_local_request_in_v6() -> None:
    src = """//@version=6
indicator("x", dynamic_requests=false)
if close > open
    request.security(syminfo.tickerid, "D", close)
"""
    assert codes.REQUEST_SIGNATURE in _codes(src)


def test_dynamic_request_disabled_rejects_series_context_args_in_v6() -> None:
    src = """//@version=6
indicator("x", dynamic_requests=false)
tf = close > open ? "D" : "W"
request.security(syminfo.tickerid, tf, close)
"""
    assert codes.REQUEST_SIGNATURE in _codes(src)


def test_v5_local_request_requires_dynamic_requests_true() -> None:
    src = """//@version=5
indicator("x")
if close > open
    request.security(syminfo.tickerid, "D", close)
"""
    assert codes.REQUEST_SIGNATURE in _codes(src, version=5)


def test_v5_dynamic_requests_true_allows_local_request() -> None:
    src = """//@version=5
indicator("x", dynamic_requests=true)
if close > open
    request.security(syminfo.tickerid, "D", close)
"""
    assert codes.REQUEST_SIGNATURE not in _codes(src, version=5)


def test_exported_library_function_parameters_must_be_typed() -> None:
    src = """//@version=6
library("L")
export f(x) => x
"""
    assert codes.UNKNOWN_TYPE in _codes(src)


def test_exported_library_method_parameters_must_be_typed() -> None:
    src = """//@version=6
library("L")
export method pushTwice(array<float> a, value) =>
    a.push(value)
    a.push(value)
"""
    assert codes.UNKNOWN_TYPE in _codes(src)


def test_exported_const_variable_requires_v6_profile() -> None:
    src = """//@version=5
library("L")
export const float X = 1.0
"""
    assert codes.UNSUPPORTED_FEATURE in _codes(src, version=5)


def test_strategy_exit_must_have_effective_exit_action() -> None:
    src = """//@version=6
strategy("x")
strategy.exit("LX", "L")
"""
    assert codes.ARGUMENT_COUNT in _codes(src)


def test_strategy_exit_with_stop_is_valid_static_action() -> None:
    src = """//@version=6
strategy("x")
strategy.exit("LX", "L", stop=low)
"""
    assert codes.ARGUMENT_COUNT not in _codes(src)


def test_openpine_static_validation_contract_lists_release4_issues() -> None:
    src = """//@version=6
indicator("x", dynamic_requests=false)
if close > open
    request.security(syminfo.tickerid, "D", close)
"""
    result = parse_code(src, ParseOptions(run_semantic=True))
    payload = build_openpine_contract_payload(result, source_path="inline.pine")
    assert payload["static_validation"]["contract"] == "openpine.static_validation.v1"
    assert payload["static_validation"]["issue_count"] >= 1
    assert any(
        issue["code"] == codes.REQUEST_SIGNATURE for issue in payload["static_validation"]["issues"]
    )


def test_release4_static_report_keeps_generic_arity_summary() -> None:
    src = """//@version=6
indicator("x")
array<float> xs = array.new<float>()
"""
    result = parse_code(src, ParseOptions(run_semantic=False))
    assert result.ast is not None
    report = build_static_validation_report(result.ast)
    assert report.schema_version == "pine2ast.static_validation.v1"
    assert report.generic_type_ref_count >= 1
    assert report.generic_constructor_count >= 1
