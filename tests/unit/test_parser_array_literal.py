from __future__ import annotations

from pine2ast import ParseOptions, parse_code


def test_flat_int_array():
    """Flat integer array literal."""
    src = """//@version=6
indicator("test")
x = [1, 2, 3]"""
    result = parse_code(src, ParseOptions(source_name="test"))
    errors = [(d.code, d.message) for d in result.diagnostics]
    assert errors == [], f"Unexpected errors: {errors}"
    assert result.ok


def test_flat_string_array():
    """Flat string array literal in variable assignment."""
    src = """//@version=6
indicator("test")
opts = ["None", "SuperTrend"]"""
    result = parse_code(src, ParseOptions(source_name="test"))
    errors = [(d.code, d.message) for d in result.diagnostics]
    assert errors == [], f"Unexpected errors: {errors}"
    assert result.ok


def test_empty_array():
    """Empty array literal."""
    src = """//@version=6
indicator("test")
arr = []"""
    result = parse_code(src, ParseOptions(source_name="test"))
    errors = [(d.code, d.message) for d in result.diagnostics]
    assert errors == [], f"Unexpected errors: {errors}"
    assert result.ok


def test_input_string_options_array():
    """input.string with options=[...] and group= named arg.

    This is the core regression: options=["None", "SuperTrend"] must parse
    as an array literal, and the trailing comma+named arg must not be
    consumed as array elements.
    """
    src = """//@version=6
strategy("")
engine = input.string("SuperTrend", "Trade engine",
     options=["None", "SuperTrend", "RSI50", "MACD"],
     group="Common")"""
    result = parse_code(src, ParseOptions(source_name="test"))
    errors = [(d.code, d.message) for d in result.diagnostics]
    assert errors == [], f"Unexpected errors: {errors}"
    assert result.ok


def test_input_string_options_single_element():
    """input.string with single-element options array."""
    src = """//@version=6
indicator("")
x = input.string("Foo", options=["Bar"], group="G")"""
    result = parse_code(src, ParseOptions(source_name="test"))
    errors = [(d.code, d.message) for d in result.diagnostics]
    assert errors == [], f"Unexpected errors: {errors}"
    assert result.ok


def test_nested_array():
    """Nested array literal [[1, 2], [3, 4]]."""
    src = """//@version=6
indicator("test")
nested = [[1, 2], [3, 4]]"""
    result = parse_code(src, ParseOptions(source_name="test"))
    errors = [(d.code, d.message) for d in result.diagnostics]
    assert errors == [], f"Unexpected errors: {errors}"
    assert result.ok


def test_array_in_expression():
    """Array used as function argument."""
    src = """//@version=6
indicator("test")
arr = [1, 2, 3]
x = math.sum(arr[0], arr[1])"""
    result = parse_code(src, ParseOptions(source_name="test"))
    errors = [(d.code, d.message) for d in result.diagnostics]
    assert errors == [], f"Unexpected errors: {errors}"
    assert result.ok
