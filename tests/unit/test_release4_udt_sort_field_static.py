from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.openpine_contract import build_openpine_contract_payload


def _error_codes(source: str) -> list[str]:
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [
        diagnostic.code
        for diagnostic in result.diagnostics
        if diagnostic.severity == Severity.ERROR
    ]


def test_udt_array_sort_field_string_and_int_are_valid() -> None:
    source = """//@version=6
indicator("sort")
type Data
    float price
    int timestamp
    string note
array<Data> xs = array.new<Data>(1, Data.new(close, time, "x"))
xs.sort(sort_field = "timestamp")
array<int> idx = array.sort_indices(xs, sort_field = 2)
plot(close)
"""

    assert _error_codes(source) == []


def test_udt_matrix_sort_field_is_valid() -> None:
    source = """//@version=6
indicator("sort")
type Data
    float price
    int timestamp
matrix<Data> mx = matrix.new<Data>(1, 1, Data.new(close, time))
mx.sort(column = 0, sort_field = "timestamp")
plot(close)
"""

    assert _error_codes(source) == []


def test_sort_field_on_non_udt_collection_is_rejected() -> None:
    source = """//@version=6
indicator("sort")
array<float> xs = array.new<float>(1, close)
xs.sort(sort_field = 0)
plot(close)
"""

    assert codes.ARGUMENT_TYPE in _error_codes(source)


def test_udt_sort_field_unknown_name_is_rejected() -> None:
    source = """//@version=6
indicator("sort")
type Data
    float price
array<Data> xs = array.new<Data>(1, Data.new(close))
xs.sort(sort_field = "missing")
plot(close)
"""

    assert codes.UNKNOWN_FIELD in _error_codes(source)


def test_udt_sort_field_out_of_range_index_is_rejected() -> None:
    source = """//@version=6
indicator("sort")
type Data
    float price
array<Data> xs = array.new<Data>(1, Data.new(close))
array.sort(xs, sort_field = 5)
plot(close)
"""

    assert codes.UNKNOWN_FIELD in _error_codes(source)


def test_udt_default_sort_field_must_be_sortable() -> None:
    source = """//@version=6
indicator("sort")
type Data
    bool flag
array<Data> xs = array.new<Data>(1, Data.new(true))
xs.sort()
plot(close)
"""

    assert codes.ARGUMENT_TYPE in _error_codes(source)


def test_udt_sort_field_requires_const_selector() -> None:
    source = """//@version=6
indicator("sort")
type Data
    float price
    int timestamp
array<Data> xs = array.new<Data>(1, Data.new(close, time))
string selector = close > open ? "price" : "timestamp"
xs.sort(sort_field = selector)
plot(close)
"""

    assert codes.ARGUMENT_QUALIFIER in _error_codes(source)


def test_openpine_static_validation_reports_udt_sort_field_issue() -> None:
    source = """//@version=6
indicator("sort")
type Data
    bool flag
array<Data> xs = array.new<Data>(1, Data.new(true))
xs.sort()
plot(close)
"""
    result = parse_code(source, ParseOptions(run_semantic=True))
    payload = build_openpine_contract_payload(result, source_path="sort.pine")

    assert any(
        issue["rule"] == "udt_sort_field_type_not_sortable"
        for issue in payload["static_validation"]["issues"]
    )


def test_udt_sort_field_const_selector_variable_is_not_false_positive() -> None:
    source = """//@version=6
indicator("sort")
type Data
    float price
    int timestamp
array<Data> xs = array.new<Data>(1, Data.new(close, time))
const int FIELD = 1
xs.sort(sort_field = FIELD)
plot(close)
"""

    assert _error_codes(source) == []
