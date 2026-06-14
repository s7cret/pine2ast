from __future__ import annotations

from pine2ast.api import parse_code
from pine2ast.diagnostics import codes
from pine2ast.openpine_contract import build_openpine_contract_payload
from pine2ast.semantic.collection_signatures import (
    collection_function_names,
    collection_return_type,
    generic_constructor_expected_arity,
    method_parameter_specs,
)


def _error_codes(source: str) -> list[str]:
    result = parse_code(source)
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_collection_method_form_validates_array_index_types() -> None:
    code = """//@version=6
indicator("array index")
array<float> xs = array.new<float>()
float x = xs.get("bad")
"""
    assert codes.COLLECTION_ELEMENT_TYPE in _error_codes(code)


def test_collection_method_form_validates_matrix_row_and_column_types() -> None:
    code = """//@version=6
indicator("matrix index")
matrix<float> mx = matrix.new<float>(2, 2, 1.0)
float x = mx.get("row", 0)
"""
    assert codes.COLLECTION_ELEMENT_TYPE in _error_codes(code)


def test_collection_method_form_validates_map_contains_enum_key_type() -> None:
    code = """//@version=6
indicator("map key")
enum Key
    A
map<Key, float> weights = map.new<Key, float>()
bool ok = weights.contains("A")
"""
    assert codes.COLLECTION_ELEMENT_TYPE in _error_codes(code)


def test_collection_copy_methods_are_known_and_typed() -> None:
    code = """//@version=6
indicator("copy")
array<float> xs = array.new<float>()
array<float> ys = xs.copy()
map<string, float> src = map.new<string, float>()
map<string, float> dst = src.copy()
matrix<float> a = matrix.new<float>(2, 2, 1.0)
matrix<float> b = a.copy()
"""
    assert _error_codes(code) == []
    assert collection_return_type("array<float>", "copy") == "array<float>"
    assert collection_return_type("map<string,float>", "copy") == "map<string,float>"


def test_generic_collection_constructor_type_argument_arity_is_validated() -> None:
    code = """//@version=6
indicator("bad map")
map<string> m = map.new<string>()
"""
    assert codes.ARGUMENT_COUNT in _error_codes(code)
    assert generic_constructor_expected_arity("map.new") == 2


def test_collection_signature_catalog_covers_core_function_forms() -> None:
    names = collection_function_names()
    assert {
        "array.get",
        "array.set",
        "array.copy",
        "matrix.get",
        "matrix.copy",
        "map.put",
        "map.contains",
        "map.copy",
    } <= names
    assert method_parameter_specs("map<Key,float>", "contains")[0].type_name == "Key"


def test_openpine_collection_access_contract_includes_copy_size_and_includes() -> None:
    code = """//@version=6
indicator("access contract")
array<float> xs = array.new<float>()
array<float> ys = xs.copy()
bool has = xs.includes(close)
int n = xs.size()
map<string, float> source = map.new<string, float>()
map<string, float> clone = source.copy()
int count = source.size()
"""
    result = parse_code(code)
    assert result.ok
    payload = build_openpine_contract_payload(result, source_path="access_contract.pine")
    access_by_operation = [
        (item["operation"], item["result_type"]) for item in payload["collections"]["accesses"]
    ]
    assert ("copy", "array<float>") in access_by_operation
    assert ("includes", "bool") in access_by_operation
    assert ("size", "int") in access_by_operation
    assert ("copy", "map<string,float>") in access_by_operation
