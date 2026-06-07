from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import codes

BOOL_VERSION_CODES = {
    codes.NON_BOOL_CONDITION,
    codes.NA_IN_BOOL_CONTEXT,
    codes.BOOL_CANNOT_BE_NA,
}


def _error_codes(source: str, *, run_semantic: bool = True) -> list[str]:
    result = parse_code(source, ParseOptions(run_semantic=run_semantic))
    return [diag.code for diag in result.diagnostics if diag.severity.value in {"ERROR", "FATAL"}]


def test_v6_numeric_conditions_are_semantic_diagnostics_only() -> None:
    source = """//@version=6
indicator("T")
if close
    x = 1
y = volume ? true : false
"""

    parser_only = parse_code(source, ParseOptions(run_semantic=False))
    assert parser_only.ast is not None
    assert codes.NON_BOOL_CONDITION not in {diag.code for diag in parser_only.diagnostics}

    assert codes.NON_BOOL_CONDITION in _error_codes(source)


def test_v6_na_in_bool_context_is_rejected() -> None:
    source = """//@version=6
indicator("T")
if na
    x = 1
"""

    assert codes.NA_IN_BOOL_CONTEXT in _error_codes(source)


def test_v6_bool_targets_cannot_receive_na() -> None:
    source = """//@version=6
indicator("T")
type Box
    bool enabled
f(bool flag = na) => flag
g(bool flag) => flag
bool b = na
bool c = close > open ? na : true
b := na
box = Box.new(na)
x = g(na)
"""

    got = _error_codes(source)
    assert got.count(codes.BOOL_CANNOT_BE_NA) >= 6


def test_v5_keeps_legacy_bool_compatibility_for_version_rules() -> None:
    source = """//@version=5
indicator("T")
type Box
    bool enabled
f(bool flag = na) => flag
g(bool flag) => flag
if close
    x = 1
if na
    y = 1
bool b = na
b := na
box = Box.new(na)
z = g(na)
"""

    result = parse_code(source, ParseOptions(strict_v6=False))
    assert result.ast is not None
    assert result.ast.version == 5
    assert {diag.code for diag in result.diagnostics}.isdisjoint(BOOL_VERSION_CODES)
