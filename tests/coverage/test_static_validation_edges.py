from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pine2ast import parse_code
from pine2ast.ast.nodes import (
    Argument,
    CallExpr,
    FunctionDeclaration,
    GenericInstantiationExpr,
    Identifier,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    Parameter,
    UnaryExpr,
    VarDeclaration,
)
from pine2ast.ast.types import TypeRef
from pine2ast.diagnostics import Severity
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic import static_validation as validation

SPAN = SourceSpan(0, 1, 1, 1, 1, 2)


def _identifier(name: str) -> Identifier:
    return Identifier(SPAN, name)


def _literal(value: object, literal_type: str) -> Literal:
    return Literal(SPAN, value, literal_type)  # type: ignore[arg-type]


def _arg(value: Any, name: str | None = None) -> Argument:
    return Argument(SPAN, name, value)


def _member(owner: Any, name: str) -> MemberAccessExpr:
    return MemberAccessExpr(SPAN, owner, name)


def _call(name: str, *args: Argument) -> CallExpr:
    if "." in name:
        owner, member = name.split(".", 1)
        callee = _member(_identifier(owner), member)
    else:
        callee = _identifier(name)
    return CallExpr(SPAN, callee, list(args))


def _profile(version: int):
    return parse_code(f'//@version={version}\nindicator("v{version}")\n').ast.version_context


def test_static_validation_issue_and_report_serialization() -> None:
    issue = validation.StaticValidationIssue(
        Severity.ERROR,
        "P2A9999",
        "problem",
        SPAN,
        "test_rule",
        None,
    )
    payload = issue.to_dict()
    assert payload["severity"] == "ERROR"
    assert payload["details"] == {}

    failed = validation.StaticValidationReport("v1", (issue,), 1, 2, 3, 4, 5, 6)
    assert failed.ok is False
    assert failed.to_dict()["summary"] == {
        "issue_count": 1,
        "generic_type_ref_count": 1,
        "generic_constructor_count": 2,
        "dynamic_request_count": 3,
        "exported_declaration_count": 4,
        "strategy_exit_count": 5,
        "udt_sort_field_count": 6,
    }
    assert validation.StaticValidationReport("v1", (), 0, 0, 0, 0, 0).ok is True


def test_generic_type_and_constructor_arity_helpers() -> None:
    assert validation._validate_type_ref_arity(TypeRef("Point", [], SPAN)) is None
    assert validation._validate_type_ref_arity(TypeRef("array", [], SPAN)) is None
    assert (
        validation._validate_type_ref_arity(TypeRef("array", [TypeRef("float", [], SPAN)], SPAN))
        is None
    )
    issue = validation._validate_type_ref_arity(TypeRef("map", [TypeRef("string", [], SPAN)], SPAN))
    assert issue is not None and issue.rule == "generic_type_arity"

    unknown = GenericInstantiationExpr(SPAN, _identifier("unknown"), [])
    assert validation._validate_generic_constructor_arity(unknown) is None
    correct = GenericInstantiationExpr(
        SPAN,
        _member(_identifier("array"), "new"),
        [TypeRef("float", [], SPAN)],
    )
    assert validation._validate_generic_constructor_arity(correct) is None
    wrong = GenericInstantiationExpr(
        SPAN,
        _member(_identifier("map"), "new"),
        [TypeRef("string", [], SPAN)],
    )
    issue = validation._validate_generic_constructor_arity(wrong)
    assert issue is not None and issue.details == {
        "constructor": "map.new",
        "expected": 2,
        "actual": 1,
    }


def test_dynamic_request_declaration_catalog_binding_and_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disabled = parse_code('//@version=5\nindicator("disabled", dynamic_requests=false)\n').ast
    enabled = parse_code('//@version=6\nindicator("enabled", dynamic_requests=true)\n').ast
    assert (
        validation._declaration_dynamic_requests(disabled, disabled.version_context)["enabled"]
        is False
    )
    assert (
        validation._declaration_dynamic_requests(enabled, enabled.version_context)["enabled"]
        is True
    )

    monkeypatch.setattr(
        validation,
        "load_catalog_readonly_view",
        lambda pine_version: {
            "functions": {
                "request.fake": {
                    "parameters": [
                        "skip",
                        {"name": "removed", "removed_in": 5},
                        {"name": "future", "added_in": 6},
                        {"name": "symbol"},
                        {},
                    ]
                }
            }
        },
    )
    assert validation._active_parameter_names("request.fake", _profile(5)) == ["symbol"]
    assert validation._active_parameter_names("request.fake", _profile(6)) == ["future", "symbol"]
    bound = validation._bind_argument_names(
        "request.fake",
        [
            _arg(_identifier("ticker")),
            _arg(_literal("D", "string"), "timeframe"),
            _arg(_identifier("extra")),
        ],
        _profile(5),
    )
    assert [name for _arg_row, name in bound] == ["symbol", "timeframe", None]

    class Engine:
        def infer_qualifier(self, value: Any) -> str:
            return "series" if isinstance(value, Identifier) else "const"

    monkeypatch.setattr(validation, "PineInferenceEngine", lambda **kwargs: Engine())
    monkeypatch.setattr(
        validation,
        "_active_parameter_names",
        lambda function_name, profile: ["symbol", "timeframe", "expression"],
    )
    request = _call(
        "request.security",
        _arg(_identifier("ticker")),
        _arg(_literal("D", "string")),
        _arg(_identifier("close")),
    )
    issues = list(
        validation._dynamic_request_issues(
            [(request, ("if",))],
            program=disabled,
            profile=disabled.version_context,
            semantic_model=None,
        )
    )
    assert len(issues) == 1
    assert issues[0].details["local_scope"] is True
    assert issues[0].details["series_context_parameters"] == ["symbol"]
    assert "local scope" in issues[0].message

    assert (
        list(
            validation._dynamic_request_issues(
                [(request, ("if",))],
                program=enabled,
                profile=enabled.version_context,
                semantic_model=None,
            )
        )
        == []
    )
    assert (
        list(
            validation._dynamic_request_issues(
                [(_call("math.max", _arg(_literal(1, "int"))), ())],
                program=disabled,
                profile=disabled.version_context,
                semantic_model=None,
            )
        )
        == []
    )


def test_strategy_exit_requires_effective_action() -> None:
    calls = [
        (_call("strategy.exit", _arg(_literal("X", "string"))), ()),
        (_call("strategy.exit", _arg(_literal(1.0, "float"), "stop")), ()),
        (
            _call(
                "strategy.exit",
                _arg(_literal(1.0, "float"), "trail_points"),
                _arg(_literal(1.0, "float"), "trail_offset"),
            ),
            (),
        ),
        (_call("strategy.exit", _arg(_literal(1.0, "float"), "trail_offset")), ()),
        (_call("strategy.entry"), ()),
    ]
    issues = list(validation._strategy_exit_issues(calls, profile=_profile(6)))
    assert len(issues) == 2
    assert all(issue.rule == "strategy_exit_must_do_something" for issue in issues)


def _library_program():
    program = parse_code('//@version=6\nlibrary("edge")\n').ast
    function = FunctionDeclaration(
        SPAN,
        "f",
        [Parameter(SPAN, "x", None)],
        _literal(1, "int"),
        True,
    )
    method = MethodDeclaration(
        SPAN,
        "m",
        None,
        None,
        [Parameter(SPAN, "x", None)],
        _literal(1, "int"),
        True,
    )
    variable = VarDeclaration(
        SPAN,
        "value",
        None,
        None,
        TypeRef("int", [], SPAN),
        _literal(1, "int"),
        True,
    )
    const_variable = VarDeclaration(
        SPAN,
        "constant",
        None,
        "const",
        TypeRef("int", [], SPAN),
        _literal(1, "int"),
        True,
    )
    program.items.extend([function, method, variable, const_variable])
    return program


def test_library_export_rules_cover_function_method_and_const_versions() -> None:
    program = _library_program()
    issues_v6 = list(validation._library_export_issues(program, profile=_profile(6)))
    rules_v6 = {issue.rule for issue in issues_v6}
    assert {
        "exported_function_parameter_type_required",
        "exported_method_receiver_required",
        "exported_method_parameter_type_required",
        "exported_variable_requires_const",
    } <= rules_v6
    assert "exported_const_requires_v6" not in rules_v6

    issues_v5 = list(validation._library_export_issues(program, profile=_profile(5)))
    assert "exported_const_requires_v6" in {issue.rule for issue in issues_v5}

    indicator = parse_code('//@version=6\nindicator("x")\n').ast
    assert validation._script_type(indicator) == "indicator"
    indicator.declaration = None
    assert validation._script_type(indicator) is None
    assert list(validation._library_export_issues(indicator, profile=_profile(6))) == []


def test_sort_field_literal_and_target_helpers() -> None:
    fields = (("price", "float", SPAN), ("name", "string", SPAN), ("flag", "bool", SPAN))
    assert validation._literal_int_value(_literal(2, "int")) == 2
    assert validation._literal_int_value(UnaryExpr(SPAN, "+", _literal(2, "int"))) == 2
    assert validation._literal_int_value(UnaryExpr(SPAN, "-", _literal(2, "int"))) == -2
    assert validation._literal_int_value(UnaryExpr(SPAN, "-", _literal("x", "string"))) is None
    assert validation._literal_int_value(_literal(2.0, "float")) is None
    assert validation._literal_string_value(_literal("name", "string")) == "name"
    assert validation._literal_string_value(_literal(1, "int")) is None

    parameter = SimpleNamespace(role="sort_field", name="selector")
    binding = SimpleNamespace(parameter=parameter, argument=_arg(_literal("name", "string")))
    resolution = SimpleNamespace(bindings=(SimpleNamespace(parameter=None), binding))
    assert validation._sort_field_binding(_call("array.sort"), resolution) is binding
    assert (
        validation._sort_field_binding(
            _call("array.sort"), SimpleNamespace(bindings=(SimpleNamespace(parameter=None),))
        )
        is None
    )

    assert validation._collection_element_type("array<Point>", "array") == "Point"
    assert validation._collection_element_type("matrix<Point>", "matrix") == "Point"
    assert validation._collection_element_type("map<string,Point>", "map") is None
    assert validation._collection_element_type("array<Point>", "matrix") is None

    assert validation._sort_field_target_field(None, fields) == ("price", "float", 0)
    assert validation._sort_field_target_field(None, ()) is None
    assert validation._sort_field_target_field(binding, fields) == ("name", "string", 1)
    missing = SimpleNamespace(parameter=parameter, argument=_arg(_literal("missing", "string")))
    assert validation._sort_field_target_field(missing, fields) is None
    indexed = SimpleNamespace(parameter=parameter, argument=_arg(_literal(2, "int")))
    assert validation._sort_field_target_field(indexed, fields) == ("flag", "bool", 2)
    negative = SimpleNamespace(parameter=parameter, argument=_arg(_literal(-1, "int")))
    assert validation._sort_field_target_field(negative, fields) is None


def test_sort_field_issues_cover_non_udt_qualifier_type_unknown_and_unsortable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = parse_code('//@version=6\nindicator("sort")\n').ast
    profile = program.version_context
    point_fields = (
        ("price", "float", SPAN),
        ("flag", "bool", SPAN),
    )
    monkeypatch.setattr(
        validation, "_type_fields", lambda program: {"Point": point_fields, "Empty": ()}
    )

    class Engine:
        def infer_qualifier(self, value: Any) -> str:
            if isinstance(value, Identifier) and value.name == "series_selector":
                return "series"
            return "const"

        def infer_type(self, value: Any) -> str:
            if isinstance(value, Literal):
                return value.literal_type
            if isinstance(value, Identifier) and value.name == "series_selector":
                return "float"
            return "int"

    monkeypatch.setattr(validation, "PineInferenceEngine", lambda **kwargs: Engine())

    def resolution(receiver: str, binding: Any | None, operation: str = "sort") -> Any:
        return SimpleNamespace(
            collection_kind="array",
            operation=operation,
            receiver_type=receiver,
            function_form="array.sort",
            bindings=() if binding is None else (binding,),
        )

    parameter = SimpleNamespace(role="sort_field", name="sort_field")
    bindings = {
        "primitive": SimpleNamespace(parameter=parameter, argument=_arg(_literal(0, "int"))),
        "series": SimpleNamespace(
            parameter=parameter, argument=_arg(_identifier("series_selector"))
        ),
        "unknown": SimpleNamespace(
            parameter=parameter, argument=_arg(_literal("missing", "string"))
        ),
        "unsortable": SimpleNamespace(
            parameter=parameter, argument=_arg(_literal("flag", "string"))
        ),
        "valid": SimpleNamespace(parameter=parameter, argument=_arg(_literal("price", "string"))),
    }
    calls = {name: _call("array.sort", binding.argument) for name, binding in bindings.items()}
    none_call = _call("math.max")
    other_call = _call("array.push")
    empty_call = _call("array.sort")

    mapping = {
        id(calls["primitive"]): resolution("array<float>", bindings["primitive"]),
        id(calls["series"]): resolution("array<Point>", bindings["series"]),
        id(calls["unknown"]): resolution("array<Point>", bindings["unknown"]),
        id(calls["unsortable"]): resolution("array<Point>", bindings["unsortable"]),
        id(calls["valid"]): resolution("array<Point>", bindings["valid"]),
        id(none_call): None,
        id(other_call): resolution("array<Point>", None, "push"),
        id(empty_call): resolution("array<Empty>", None),
    }
    monkeypatch.setattr(
        validation, "resolve_collection_call", lambda call, engine: mapping[id(call)]
    )

    call_rows = [(call, ()) for call in [*calls.values(), none_call, other_call, empty_call]]
    issues = list(
        validation._sort_field_issues(
            call_rows,
            program=program,
            profile=profile,
            semantic_model=None,
        )
    )
    rules = [issue.rule for issue in issues]
    assert "udt_sort_field_requires_udt_collection" in rules
    assert "udt_sort_field_requires_const" in rules
    assert "udt_sort_field_argument_type" in rules
    assert "udt_sort_field_unknown_field" in rules
    assert "udt_sort_field_type_not_sortable" in rules


def test_type_field_map_and_top_level_static_report_are_consistent() -> None:
    program = parse_code("""//@version=6
indicator("report")
type Point
    float price
var array<Point> points = array.new<Point>()
array.sort(points, sort_field="price")
strategy.exit("X")
""").ast
    fields = validation._type_fields(program)
    assert fields["Point"][0][:2] == ("price", "float")
    report = validation.build_static_validation_report(program)
    assert report.schema_version == "pine2ast.static_validation.v1"
    assert report.generic_type_ref_count >= 1
    assert report.generic_constructor_count >= 1
    assert report.strategy_exit_count == 1
    assert validation.validate_static_semantics(program) == report.issues
