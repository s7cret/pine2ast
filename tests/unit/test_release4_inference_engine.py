from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.ast.nodes import Argument, Identifier, Literal, MemberAccessExpr
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.openpine_contract import build_openpine_contract_payload
from pine2ast.semantic.builtin_registry import load_builtin_registry
from pine2ast.semantic.inference import PineInferenceEngine, call_lookup_name
from pine2ast.semantic.signatures import SignatureResolver


def _z() -> SourceSpan:
    return SourceSpan.zero()


def test_inference_engine_preserves_user_enum_member_type_and_const_qualifier() -> None:
    result = parse_code(
        '//@version=6\nindicator("enum")\nenum Key\n    A\nvar map<Key, float> m = map.new<Key, float>()\n',
        ParseOptions(source_name="enum_member.pine"),
    )
    assert result.ok
    expr = MemberAccessExpr(_z(), Identifier(_z(), "Key"), "A")
    engine = PineInferenceEngine(symbols=result.semantic_model.symbols, pine_version=6)

    value = engine.infer_value(expr)

    assert value.type_name == "Key"
    assert value.qualifier == "const"
    assert not value.is_reference


def test_generic_map_constructor_uses_placeholder_registry_key_without_unknown_warning() -> None:
    registry = load_builtin_registry(pine_version=6)
    # Reuse a parsed AST expression so this verifies the parser's concrete generic shape.
    result = parse_code(
        '//@version=6\nindicator("map")\nenum Key\n    A\nvar map<Key, float> m = map.new<Key, float>()\n',
        ParseOptions(source_name="generic_map.pine"),
    )

    assert result.ok
    assert not [d for d in result.diagnostics if d.code == codes.UNKNOWN_BUILTIN_MEMBER]
    var_decl = next(item for item in result.ast.items if getattr(item, "name", None) == "m")
    lookup = call_lookup_name(var_decl.initializer.callee, registry)  # type: ignore[attr-defined]
    assert lookup == "map.new<type,type>"


def test_signature_resolver_specializes_map_key_and_value_from_generic_id_argument() -> None:
    result = parse_code(
        '//@version=6\nindicator("map")\nenum Key\n    A\nvar map<Key, float> m = map.new<Key, float>()\n',
        ParseOptions(source_name="map_signature.pine"),
    )
    assert result.ok
    registry = load_builtin_registry(pine_version=6)
    entry = registry["functions"]["map.put"]
    args = [
        Argument(_z(), None, Identifier(_z(), "m")),
        Argument(_z(), None, MemberAccessExpr(_z(), Identifier(_z(), "Key"), "A")),
        Argument(_z(), None, Literal(_z(), 1.0, "float")),
    ]

    resolution = SignatureResolver(pine_version=6).resolve_builtin(
        "map.put",
        entry,
        args,
        _z(),
        symbols=result.semantic_model.symbols,
        validate_types=True,
        validate_qualifiers=True,
    )

    assert resolution.ok
    assert [
        arg.parameter["type"] if arg.parameter else None for arg in resolution.resolved_arguments
    ] == [
        "map",
        "Key",
        "float",
    ]


def test_map_put_with_enum_key_parses_and_openpine_contract_reports_expected_types() -> None:
    code = """//@version=6
indicator("map")
enum Key
    A
var map<Key, float> m = map.new<Key, float>()
map.put(m, Key.A, 1.0)
"""
    result = parse_code(code, ParseOptions(source_name="map_put_enum.pine"))

    assert result.ok
    assert not [d for d in result.diagnostics if d.code == codes.ARGUMENT_TYPE]
    payload = build_openpine_contract_payload(result, source_path="map_put_enum.pine")
    mutation = payload["collections"]["mutations"][0]
    assert mutation["target"]["key_type"] == "Key"
    assert mutation["key"]["type"] == "Key"
    assert mutation["key"]["expected_type"] == "Key"
    assert mutation["key"]["type_ok"] is True
    assert mutation["value"]["expected_type"] == "float"
    assert mutation["value"]["type_ok"] is True
    assert [arg["parameter"] for arg in mutation["arguments"]] == ["id", "key", "value"]


def test_map_put_wrong_enum_key_still_fails_with_specialized_key_type() -> None:
    result = parse_code(
        '//@version=6\nindicator("map")\nenum Key\n    A\nvar map<Key, float> m = map.new<Key, float>()\nmap.put(m, "A", 1.0)\n',
        ParseOptions(source_name="map_put_bad_key.pine"),
    )

    assert not result.ok
    assert any(
        d.code == codes.ARGUMENT_TYPE and "expects Key" in d.message for d in result.diagnostics
    )
