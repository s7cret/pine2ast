from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import Argument, CallExpr, Identifier, Literal, MemberAccessExpr
from pine2ast.diagnostics import Severity
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic import version_coverage
from pine2ast.semantic.collection_signatures import (
    COLLECTION_ACCESS_OPERATIONS,
    COLLECTION_METHOD_PARAMETER_TEMPLATES,
    COLLECTION_MUTATION_OPERATIONS,
    CollectionCallResolution,
    CollectionParameterSpec,
    CollectionSignatureIssue,
    collection_function_names,
    collection_kind_from_function_name,
    collection_kind_from_type,
    collection_operation_from_function_name,
    collection_return_type,
    function_parameter_specs,
    generic_constructor_expected_arity,
    is_collection_method,
    method_parameter_specs,
    resolve_collection_call,
)
from pine2ast.semantic.extractors import (
    _const_value_expr,
    _literal_sequence,
    extract_alertconditions,
    extract_dependencies,
    extract_drawing_calls,
    extract_inputs,
    extract_plots,
    extract_request_calls,
    extract_strategy_calls,
)
from pine2ast.semantic.version_semantics import load_semantic_requirements

SPAN = SourceSpan(0, 1, 1, 1, 1, 2)


def _identifier(name: str) -> Identifier:
    return Identifier(SPAN, name)


def _literal(value: object, literal_type: str) -> Literal:
    return Literal(SPAN, value, literal_type)  # type: ignore[arg-type]


def _arg(value: Any, name: str | None = None) -> Argument:
    return Argument(SPAN, name, value)


class _Engine:
    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self.overrides = overrides or {}

    def infer_type(self, value: Any) -> str:
        if isinstance(value, Identifier):
            return self.overrides.get(value.name, "unknown")
        if isinstance(value, Literal):
            return value.literal_type
        return "unknown"


def _function_call(kind: str, operation: str, args: list[Argument]) -> CallExpr:
    return CallExpr(SPAN, MemberAccessExpr(SPAN, _identifier(kind), operation), args)


def _method_call(receiver: str, operation: str, args: list[Argument]) -> CallExpr:
    return CallExpr(SPAN, MemberAccessExpr(SPAN, _identifier(receiver), operation), args)


def test_collection_name_kind_operation_and_constructor_helpers() -> None:
    names = collection_function_names()
    assert "array.push" in names and "matrix.get" in names and "map.put" in names
    assert collection_kind_from_type("array<float>") == "array"
    assert collection_kind_from_type("matrix<int>") == "matrix"
    assert collection_kind_from_type("float") is None
    assert collection_kind_from_function_name("array.push") == "array"
    assert collection_kind_from_function_name("unknown.push") is None
    assert collection_kind_from_function_name("push") is None
    assert collection_operation_from_function_name("array.push") == "push"
    assert collection_operation_from_function_name("array.not_real") is None
    assert collection_operation_from_function_name("not_real") is None
    assert collection_operation_from_function_name("unknown.push") is None
    assert generic_constructor_expected_arity("array.new") == 1
    assert generic_constructor_expected_arity("map.new") == 2
    assert generic_constructor_expected_arity("unknown.new") is None


def test_collection_parameter_specialization_optional_and_unknown_paths() -> None:
    assert method_parameter_specs(None, "get") == ()
    assert method_parameter_specs("float", "get") == ()
    assert method_parameter_specs("array<float>", "not_real") == ()

    fill = method_parameter_specs("array<float>", "fill")
    assert [row.to_dict() for row in fill] == [
        {"name": "value", "type": "float", "role": "value", "required": True},
        {"name": "index_from", "type": "int", "role": "index", "required": False},
        {"name": "index_to", "type": "int", "role": "index", "required": False},
    ]
    put = method_parameter_specs("map<string,array<int>>", "put")
    assert [(row.name, row.type_name) for row in put] == [
        ("key", "string"),
        ("value", "array<int>"),
    ]
    unknown = method_parameter_specs("array", "push")
    assert unknown[0].type_name == "unknown"

    function = function_parameter_specs("map.put", "map<string,float>")
    assert [(row.name, row.type_name) for row in function] == [
        ("id", "map<string,float>"),
        ("key", "string"),
        ("value", "float"),
    ]
    assert function_parameter_specs("map.not_real", "map<string,float>") == ()
    assert function_parameter_specs("not_real", None) == ()


def test_collection_return_type_matrix_covers_all_shape_families() -> None:
    expected = {
        ("array<float>", "get"): "float",
        ("array<float>", "size"): "int",
        ("array<float>", "includes"): "bool",
        ("array<float>", "copy"): "array<float>",
        ("array<float>", "sort_indices"): "array<int>",
        ("array<float>", "join"): "string",
        ("array<float>", "push"): "void",
        ("matrix<float>", "get"): "float",
        ("matrix<float>", "rows"): "int",
        ("matrix<float>", "is_square"): "bool",
        ("matrix<float>", "row"): "array<float>",
        ("matrix<float>", "eigenvectors"): "matrix<float>",
        ("matrix<float>", "transpose"): "matrix<float>",
        ("matrix<float>", "mult"): "unknown",
        ("matrix<float>", "set"): "void",
        ("map<string,float>", "get"): "float",
        ("map<string,float>", "contains"): "bool",
        ("map<string,float>", "keys"): "array<string>",
        ("map<string,float>", "values"): "array<float>",
        ("map<string,float>", "size"): "int",
        ("map<string,float>", "copy"): "map<string,float>",
        ("map<string,float>", "put"): "float",
        ("float", "get"): None,
    }
    for (receiver, operation), return_type in expected.items():
        assert collection_return_type(receiver, operation) == return_type

    for kind, operations in COLLECTION_METHOD_PARAMETER_TEMPLATES.items():
        receiver = {"array": "array<float>", "matrix": "matrix<float>", "map": "map<string,float>"}[
            kind
        ]
        for operation in operations:
            assert is_collection_method(receiver, operation)
            assert collection_return_type(receiver, operation) is not None
            assert (operation in COLLECTION_MUTATION_OPERATIONS[kind]) != (
                operation in COLLECTION_ACCESS_OPERATIONS[kind]
            )
    assert not is_collection_method("float", "get")


def test_collection_resolution_function_and_method_forms() -> None:
    engine = _Engine({"a": "array<float>", "m": "map<string,float>", "x": "float"})

    function = resolve_collection_call(
        _function_call("array", "push", [_arg(_identifier("a")), _arg(_literal(1, "int"))]),
        engine=engine,
    )
    assert function is not None and function.ok
    assert function.form == "function"
    assert function.is_mutation and not function.is_access
    assert function.return_type == "void"
    assert [binding.expected_type for binding in function.bindings] == ["array<float>", "float"]

    method = resolve_collection_call(
        _method_call("a", "get", [_arg(_literal(0, "int"))]),
        engine=engine,
    )
    assert method is not None and method.ok
    assert method.form == "method"
    assert method.is_access and not method.is_mutation
    assert method.return_type == "float"

    assert resolve_collection_call(_method_call("x", "get", []), engine=engine) is None
    assert resolve_collection_call(_function_call("math", "max", []), engine=engine) is None

    incomplete = resolve_collection_call(_function_call("array", "push", []), engine=engine)
    assert incomplete is not None
    assert not incomplete.ok
    assert any(issue.code == "P2A1404" for issue in incomplete.issues)

    wrong_receiver = resolve_collection_call(
        _function_call("array", "push", [_arg(_identifier("x")), _arg(_literal(1, "int"))]),
        engine=engine,
    )
    assert wrong_receiver is not None
    assert wrong_receiver.receiver_type == "float"


def test_collection_argument_binding_reports_each_fail_closed_error() -> None:
    engine = _Engine({"a": "array<float>"})
    call = _function_call(
        "array",
        "fill",
        [
            _arg(_identifier("a")),
            _arg(_literal("bad", "string")),
            _arg(_literal(0, "int"), "index_from"),
            _arg(_literal(1, "int"), "index_from"),
            _arg(_literal(2, "int"), "unknown"),
            _arg(_literal(3, "int")),
            _arg(_literal(4, "int"), "value"),
        ],
    )
    resolution = resolve_collection_call(call, engine=engine)
    assert resolution is not None and not resolution.ok
    assert {binding.binding for binding in resolution.bindings} == {
        "positional",
        "named",
        "unknown",
        "extra_positional",
    }
    codes = {issue.code for issue in resolution.issues}
    assert {"P2A1401", "P2A1403", "P2A1805"} <= codes

    missing = resolve_collection_call(
        _function_call("map", "put", [_arg(_identifier("m"))]),
        engine=_Engine({"m": "map<string,float>"}),
    )
    assert missing is not None and not missing.ok
    assert any(issue.code == "P2A1404" for issue in missing.issues)

    warning = CollectionSignatureIssue(Severity.WARNING, "P2A9999", "warning", SPAN)
    manual = CollectionCallResolution(
        "get",
        "array.get",
        "function",
        "array",
        "array<float>",
        (CollectionParameterSpec("id", "array<float>", "id"),),
        (),
        "float",
        (warning,),
    )
    assert manual.ok


def _rehashed(report: dict[str, Any]) -> dict[str, Any]:
    report = copy.deepcopy(report)
    report.pop("content_hash", None)
    report["content_hash"] = version_coverage._hash(report)
    return report


def test_version_coverage_report_full_verification_and_invariant_mutants() -> None:
    verified = {row.test_id for row in load_semantic_requirements() if row.owner == "pine2ast"}
    report = version_coverage.build_version_coverage_report(
        verified_test_ids=verified,
        full_test_suite_passed=True,
        catalog_gate_passed=True,
        differential_gate_passed=True,
    )
    assert version_coverage.validate_version_coverage_report(report) == ()
    assert set(report["versions"]) == {str(version) for version in range(1, 7)}
    assert all(
        row["normative_static_frontend"]["coverage_percent"] == 100.0
        for row in report["versions"].values()
    )

    mutant = copy.deepcopy(report)
    mutant["schema_id"] = "bad"
    assert "schema_id" in version_coverage.validate_version_coverage_report(mutant)

    mutant = copy.deepcopy(report)
    mutant.pop("content_hash")
    assert "content_hash_missing" in version_coverage.validate_version_coverage_report(mutant)

    mutant = copy.deepcopy(report)
    mutant["content_hash"] = "sha256:bad"
    assert "content_hash_mismatch" in version_coverage.validate_version_coverage_report(mutant)

    mutant = _rehashed(report)
    mutant["versions"].pop("6")
    mutant = _rehashed(mutant)
    assert "version_set" in version_coverage.validate_version_coverage_report(mutant)

    mutations = [
        ("row", lambda row: "bad", "v1.row"),
        ("static", lambda row: {**row, "normative_static_frontend": "bad"}, "v1.static"),
        (
            "counts",
            lambda row: {
                **row,
                "normative_static_frontend": {
                    **row["normative_static_frontend"],
                    "verified": row["normative_static_frontend"]["requirements_total"] + 1,
                },
            },
            "v1.static_counts",
        ),
        (
            "percent",
            lambda row: {
                **row,
                "normative_static_frontend": {
                    **row["normative_static_frontend"],
                    "coverage_percent": -1.0,
                },
            },
            "v1.static_percent",
        ),
        (
            "official",
            lambda row: {**row, "official_reference_symbol_coverage": {"coverage_percent": 100.0}},
            "v1.official_claim",
        ),
        (
            "oracle",
            lambda row: {**row, "tradingview_runtime_oracle": {"coverage_percent": 100.0}},
            "v1.oracle_claim",
        ),
        (
            "downstream",
            lambda row: {**row, "downstream_semantics": {"verified_by_pine2ast": 1}},
            "v1.downstream_claim",
        ),
    ]
    for _name, mutate, expected_issue in mutations:
        mutant = copy.deepcopy(report)
        mutant["versions"]["1"] = mutate(mutant["versions"]["1"])
        mutant = _rehashed(mutant)
        assert expected_issue in version_coverage.validate_version_coverage_report(mutant)


def test_version_pack_metrics_recursive_direct_and_duplicate_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "pine2ast"
    root.mkdir()
    monkeypatch.setattr(version_coverage, "_package_root", lambda: root)

    with pytest.raises(FileNotFoundError, match="exactly one"):
        version_coverage._find_pack(1)

    recursive = root / "packs" / "pine-v1.pack.json"
    recursive.parent.mkdir()
    recursive.write_text(
        json.dumps(
            {
                "pack_hash": "sha256:declared",
                "status": "PINNED",
                "tree": [
                    {"symbol_id": "f", "kind": "function"},
                    {"symbol_id": "m", "kind": "method"},
                    {"symbol_id": "o", "kind": "operator"},
                    {"symbol_id": "f", "kind": "function"},
                ],
            }
        ),
        encoding="utf-8",
    )
    metrics = version_coverage._pack_metrics(1)
    assert metrics["symbol_count"] == 3
    assert metrics["callable_count"] == 2
    assert metrics["operator_count"] == 1
    assert metrics["status"] == "PINNED"

    recursive.unlink()
    direct = root / "v1.pack.json"
    direct.write_text(
        json.dumps(
            {
                "content_hash": "sha256:direct",
                "completeness_status": "COMPLETE",
                "symbols": ["a", "b"],
                "operators": {"+": {}},
                "functions": {"f": {}},
                "methods": ["m"],
                "declarations": ["d"],
                "callables": ["c"],
            }
        ),
        encoding="utf-8",
    )
    metrics = version_coverage._pack_metrics(1)
    assert metrics["symbol_count"] == 2
    assert metrics["callable_count"] == 4
    assert metrics["operator_count"] == 1
    assert metrics["status"] == "COMPLETE"

    duplicate = root / "other" / "pine_v1.json"
    duplicate.parent.mkdir()
    duplicate.write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="exactly one"):
        version_coverage._find_pack(1)

    assert version_coverage._entry_count({"x": "not-a-container"}, "x") is None
    assert list(version_coverage._walk("text")) == []


EXTRACTOR_SOURCE = """//@version=6
indicator("extractors")
length = input.int(14, "Length", minval=1, maxval=100, step=1, options=[7, 14, 21], group="Core")
source = input.source(defval=close, title="Source")
mode = input.string("a", options=array.from("a", "b"))
flag = input.bool(true)
f(float x) => x
method twice(float self) => self * 2
x = f(close)
y = x.twice()
plot(x)
plotshape(flag)
plotchar(flag)
hline(0)
alertcondition(flag, "Alert")
label.new(bar_index, close)
line.new(bar_index, close, bar_index + 1, open)
box.new(bar_index, high, bar_index + 1, low)
table.new(position.top_right, 1, 1)
request.security(syminfo.tickerid, "D", close)
strategy.entry("L", strategy.long)
unknown_call(x)
"""


DEPENDENCY_SOURCE = """//@version=6
library("deps")
import alice/mathlib/1 as mathlib
type Point
    float x
f(float x) => x
method twice(float self) => self * 2
p = Point.new(1.0)
a = f(close)
b = a.twice()
c = mathlib.external(a)
d = ta.sma(close, 3)
var array<float> values = array.new<float>(0)
array.push(values, d)
e = unknown_call(d)
"""


def test_extractors_cover_inputs_calls_plots_drawings_and_dependencies() -> None:
    result = parse_code(EXTRACTOR_SOURCE, ParseOptions(max_diagnostics=500))
    assert result.ast is not None
    program = result.ast

    inputs = extract_inputs(program)
    assert [row.name for row in inputs] == ["length", "source", "mode", "flag"]
    length = inputs[0]
    assert (length.default_value, length.title, length.minval, length.maxval, length.step) == (
        14,
        "Length",
        1,
        100,
        1,
    )
    assert length.options == [7, 14, 21]
    assert length.group == "Core"
    assert inputs[2].options == ["a", "b"]

    assert [call.name for call in extract_strategy_calls(program)] == ["strategy.entry"]
    assert len(extract_request_calls(program)) == 1
    assert {call.callee.member for call in extract_request_calls(program)} == {"security"}
    assert len(extract_plots(program)) == 4
    assert len(extract_alertconditions(program)) == 1
    assert {call.name for call in extract_drawing_calls(program)} == {
        "label.new",
        "line.new",
        "box.new",
        "table.new",
    }

    dependencies = extract_dependencies(parse_code(DEPENDENCY_SOURCE).ast)
    assert dependencies.imports == ["alice/mathlib/1"]
    assert dependencies.import_aliases == ["mathlib"]
    assert "ta" in dependencies.namespaces and "array" in dependencies.namespaces
    assert "ta.sma" in dependencies.builtin_calls
    assert "array.new<float>" in dependencies.builtin_calls
    assert "array.push" in dependencies.builtin_calls
    assert dependencies.user_function_calls == ["f"]
    assert dependencies.method_calls == ["twice"]
    assert dependencies.udt_constructors == ["Point"]
    assert dependencies.external_calls == ["mathlib.external"]
    assert dependencies.unknown_calls == ["unknown_call"]


def test_extractor_literal_helpers_cover_member_identifier_fallback_and_sequences() -> None:
    assert _const_value_expr(_literal(3, "int")) == 3
    assert (
        _const_value_expr(MemberAccessExpr(SPAN, _identifier("strategy"), "long"))
        == "strategy.long"
    )
    assert _const_value_expr(_identifier("name")) == "name"
    assert _const_value_expr(SimpleNamespace(value=9)) == 9

    tuple_call = parse_code('//@version=6\nindicator("x")\nx = [1, close, strategy.long]\n').ast
    tuple_expr = next(
        node.initializer for node in tuple_call.items if getattr(node, "name", None) == "x"
    )
    assert _literal_sequence(_arg(tuple_expr)) == [1, "close", "strategy.long"]
    assert _literal_sequence(None) is None
    assert _literal_sequence(_arg(_identifier("not-a-sequence"))) is None
