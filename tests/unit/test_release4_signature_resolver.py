from __future__ import annotations

from pine2ast.ast.nodes import Argument, Literal
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.signatures import SignatureResolver


def _lit(value: object, literal_type: str) -> Literal:
    return Literal(SourceSpan.zero(), value, literal_type)  # type: ignore[arg-type]


def _arg(name: str | None, value: object = 1, literal_type: str = "int") -> Argument:
    return Argument(SourceSpan.zero(), name, _lit(value, literal_type))


def test_signature_resolver_binds_named_and_positional_arguments() -> None:
    entry = {
        "parameters": [
            {"name": "x", "required": True, "type": "int"},
            {"name": "y", "required": False, "type": "int"},
        ]
    }
    resolution = SignatureResolver(pine_version=6).resolve_builtin(
        "demo.fn", entry, [_arg(None), _arg("y", 2)], SourceSpan.zero()
    )

    assert resolution.ok
    assert [
        b.parameter["name"] if b.parameter else None for b in resolution.resolved_arguments
    ] == [
        "x",
        "y",
    ]
    assert [b.binding for b in resolution.resolved_arguments] == ["positional", "named"]


def test_signature_resolver_reports_missing_unknown_and_duplicate_bindings() -> None:
    entry = {
        "parameters": [
            {"name": "x", "required": True, "type": "int"},
            {"name": "y", "required": True, "type": "int"},
        ]
    }
    resolution = SignatureResolver(pine_version=6).resolve_builtin(
        "demo.fn",
        entry,
        [_arg(None), _arg("x"), _arg("z")],
        SourceSpan.zero(),
    )

    issues = {(issue.code, issue.severity) for issue in resolution.issues}
    assert (codes.UNKNOWN_PARAMETER, Severity.ERROR) in issues
    assert (codes.DUPLICATE_NAMED_ARGUMENT, Severity.ERROR) in issues
    assert (codes.ARGUMENT_COUNT, Severity.ERROR) in issues


def test_signature_resolver_filters_removed_parameters_by_pine_version() -> None:
    entry = {
        "parameters": [
            {"name": "id", "required": True, "type": "string"},
            {
                "name": "when",
                "required": False,
                "type": "bool",
                "removed_in": "6",
                "diagnostic_code": codes.STRATEGY_WHEN_REMOVED,
            },
        ]
    }

    v5 = SignatureResolver(pine_version=5).resolve_builtin(
        "strategy.entry",
        entry,
        [_arg(None, "L", "string"), _arg("when", True, "bool")],
        SourceSpan.zero(),
    )
    v6 = SignatureResolver(pine_version=6).resolve_builtin(
        "strategy.entry",
        entry,
        [_arg(None, "L", "string"), _arg("when", True, "bool")],
        SourceSpan.zero(),
    )

    assert not any(issue.code == codes.STRATEGY_WHEN_REMOVED for issue in v5.issues)
    assert any(issue.code == codes.STRATEGY_WHEN_REMOVED for issue in v6.issues)
    assert "when" not in v6.known_parameter_names


def test_signature_resolver_selects_best_overload_using_type_resolver() -> None:
    entry = {
        "name": "demo.overloaded",
        "overloads": [
            {
                "id": "string_case",
                "parameters": [{"name": "x", "required": True, "type": "string"}],
                "returns": "string",
            },
            {
                "id": "float_case",
                "parameters": [{"name": "x", "required": True, "type": "float"}],
                "returns": "float",
            },
        ],
    }
    arg = _arg(None, 1.5, "float")

    resolution = SignatureResolver(pine_version=6).resolve_builtin(
        "demo.overloaded",
        entry,
        [arg],
        SourceSpan.zero(),
        argument_type_resolver=lambda argument: argument.value.literal_type,
    )

    assert resolution.ok
    assert resolution.overload_id == "float_case"
    assert resolution.result_type == "float"
    assert resolution.selected_overload_index == 1


def test_signature_resolver_can_emit_type_and_qualifier_issues() -> None:
    entry = {
        "parameters": [
            {"name": "title", "required": True, "type": "string", "qualifier_max": "const"},
            {"name": "flag", "required": True, "type": "bool"},
        ]
    }
    resolution = SignatureResolver(pine_version=6).resolve_builtin(
        "demo.strict",
        entry,
        [_arg(None, 42, "int"), _arg(None, None, "na")],
        SourceSpan.zero(),
        validate_types=True,
        validate_qualifiers=True,
        argument_type_resolver=lambda argument: argument.value.literal_type,
        argument_qualifier_resolver=lambda _argument: "series",
    )

    issue_codes = {issue.code for issue in resolution.issues}
    assert codes.ARGUMENT_TYPE in issue_codes
    assert codes.ARGUMENT_QUALIFIER in issue_codes
    assert codes.BOOL_CANNOT_BE_NA in issue_codes
