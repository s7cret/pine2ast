from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.openpine_contract import build_openpine_contract_payload
from pine2ast.semantic.collection_signatures import collection_return_type, method_parameter_specs
from pine2ast.semantic.signature_coverage import build_signature_coverage_report


def _codes(source: str) -> list[str]:
    return [diag.code for diag in parse_code(source, ParseOptions(run_semantic=True)).diagnostics]


def test_extended_array_method_signatures_validate_index_and_value_types() -> None:
    source = """//@version=6
indicator("arrays")
array<float> xs = array.new<float>()
xs.insert("bad", close)
xs.fill("bad")
"""
    diag_codes = _codes(source)

    assert diag_codes.count(codes.COLLECTION_ELEMENT_TYPE) >= 2


def test_extended_matrix_and_map_method_signatures_validate_receiver_specialized_types() -> None:
    source = """//@version=6
indicator("collections")
matrix<float> mx = matrix.new<float>(2, 2, 0.0)
mx.reshape("2", 3)
map<string, float> a = map.new<string, float>()
map<int, float> b = map.new<int, float>()
a.put_all(b)
"""
    diag_codes = _codes(source)

    assert diag_codes.count(codes.COLLECTION_ELEMENT_TYPE) >= 2


def test_collection_return_types_cover_new_release4_methods() -> None:
    assert collection_return_type("array<float>", "slice") == "array<float>"
    assert collection_return_type("array<float>", "join") == "string"
    assert collection_return_type("array<float>", "sort_indices") == "array<int>"
    assert collection_return_type("matrix<float>", "row") == "array<float>"
    assert collection_return_type("matrix<float>", "transpose") == "matrix<float>"


def test_collection_parameter_specs_mark_optional_parameters() -> None:
    fill_specs = [spec.to_dict() for spec in method_parameter_specs("array<float>", "fill")]
    sort_specs = [spec.to_dict() for spec in method_parameter_specs("array<float>", "sort")]

    assert fill_specs == [
        {"name": "value", "type": "float", "role": "value", "required": True},
        {"name": "index_from", "type": "int", "role": "index", "required": False},
        {"name": "index_to", "type": "int", "role": "index", "required": False},
    ]
    assert sort_specs == [
        {"name": "order", "type": "string", "role": "order", "required": False},
        {"name": "sort_field", "type": "int|string", "role": "sort_field", "required": False},
    ]


def test_openpine_collection_contract_reports_extended_access_methods() -> None:
    source = """//@version=6
indicator("contract")
array<float> xs = array.new<float>()
array<float> ys = xs.slice(0, 1)
string joined = xs.join(",")
array<int> order = xs.sort_indices()
matrix<float> mx = matrix.new<float>(2, 2, 0.0)
array<float> row = mx.row(0)
"""
    result = parse_code(source, ParseOptions(source_name="collection_contract.pine"))
    assert result.ok

    payload = build_openpine_contract_payload(result, source_path="collection_contract.pine")
    accesses = payload["collections"]["accesses"]
    by_form = {item["function_form"]: item for item in accesses}

    assert by_form["array.slice"]["result_type"] == "array<float>"
    assert by_form["array.join"]["result_type"] == "string"
    assert by_form["array.sort_indices"]["result_type"] == "array<int>"
    assert by_form["matrix.row"]["result_type"] == "array<float>"
    assert by_form["matrix.row"]["arguments"][0]["expected_type"] == "int"


def test_signature_coverage_counts_collection_methods_as_signature_ready() -> None:
    report = build_signature_coverage_report(6).to_dict()
    methods = report["categories"]["methods"]

    assert methods["signature_pending_count"] == 0
    assert "array.insert" not in methods["signature_pending"]
    assert "matrix.reshape" not in methods["signature_pending"]
    assert "map.put_all" not in methods["signature_pending"]
    assert report["summary"]["signature_ready_ratio"] == 1.0


def test_signature_coverage_cli_can_gate_ready_ratio(capsys) -> None:
    from pine2ast.semantic.signature_coverage import main

    assert main(["--version", "6", "--fail-under-signature-ready-ratio", "1.0"]) == 0
    capsys.readouterr()
    assert main(["--version", "6", "--fail-under-signature-ready-ratio", "1.01"]) == 1
