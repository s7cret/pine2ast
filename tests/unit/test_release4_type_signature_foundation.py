from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.ast.nodes import Argument, Literal
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.signatures import SignatureResolver
from pine2ast.semantic.type_model import (
    PineType,
    is_reference_type_name,
    is_valid_map_key_type,
    split_top_level_csv,
)


def _lit(value: object, literal_type: str) -> Literal:
    return Literal(SourceSpan.zero(), value, literal_type)  # type: ignore[arg-type]


def _arg(name: str | None, value: object = 1, literal_type: str = "int") -> Argument:
    return Argument(SourceSpan.zero(), name, _lit(value, literal_type))


def test_type_model_parses_nested_generics_and_map_key_rules() -> None:
    typ = PineType.parse("map<string,array<float>>")

    assert typ.base == "map"
    assert [str(arg) for arg in typ.args] == ["string", "array<float>"]
    assert split_top_level_csv("string,array<float>,map<int,float>") == [
        "string",
        "array<float>",
        "map<int,float>",
    ]
    assert is_valid_map_key_type("string")
    assert is_valid_map_key_type("MyEnum", enum_types={"MyEnum"})
    assert not is_valid_map_key_type("line")
    assert is_reference_type_name("array<float>")


def test_signature_resolver_selects_point_overload_from_argument_types() -> None:
    entry = {
        "parameters": [
            {"name": "x1", "required": False, "type": "int"},
            {"name": "y1", "required": False, "type": "float"},
        ],
        "returns": "line",
        "overloads": [
            {
                "id": "point_pair",
                "parameters": [
                    {"name": "first_point", "required": True, "type": "chart.point"},
                    {"name": "second_point", "required": True, "type": "chart.point"},
                ],
                "returns": "line",
            }
        ],
    }
    args = [_arg(None, "p1", "chart.point"), _arg(None, "p2", "chart.point")]

    resolution = SignatureResolver(pine_version=6).resolve_builtin(
        "line.new",
        entry,
        args,
        SourceSpan.zero(),
        infer_arg_type=lambda arg: arg.value.literal_type,  # type: ignore[return-value]
    )

    assert resolution.ok
    assert resolution.uses_overload
    assert resolution.selected_overload_index == 0
    assert resolution.overload_id == "point_pair"
    assert resolution.return_type == "line"
    assert [binding.parameter["name"] for binding in resolution.resolved_arguments] == [
        "first_point",
        "second_point",
    ]


def test_plain_signature_resolution_is_not_marked_as_overload() -> None:
    entry = {"parameters": [{"name": "x", "required": True, "type": "int"}], "returns": "int"}
    resolution = SignatureResolver(pine_version=6).resolve_builtin(
        "demo.simple",
        entry,
        [_arg(None, 1, "int")],
        SourceSpan.zero(),
        infer_arg_type=lambda arg: arg.value.literal_type,  # type: ignore[return-value]
    )

    assert resolution.ok
    assert not resolution.uses_overload
    assert resolution.selected_overload_index is None


def test_line_and_box_point_overloads_bind_without_type_errors() -> None:
    code = """//@version=6
indicator("points", overlay=true)
p1 = chart.point.now(close)
p2 = chart.point.from_index(bar_index + 1, close)
ln = line.new(p1, p2)
bx = box.new(p1, p2, bgcolor=color.new(color.blue, 80))
"""
    result = parse_code(code, ParseOptions(source_name="point_overloads.pine"))

    assert result.ok
    assert not [d for d in result.diagnostics if d.code == codes.ARGUMENT_TYPE]


def test_map_new_rejects_reference_key_type_and_allows_enum_key_type() -> None:
    bad = parse_code(
        '//@version=6\nindicator("bad")\nvar bad = map.new<line, float>()\n',
        ParseOptions(source_name="bad_map_key.pine"),
    )
    good = parse_code(
        '//@version=6\nindicator("good")\nenum Key\n    A\nvar map<Key, float> labels = map.new<Key, float>()\n',
        ParseOptions(source_name="good_map_key.pine"),
    )

    assert any(
        d.code == codes.COLLECTION_ELEMENT_TYPE and "Map key type" in d.message
        for d in bad.diagnostics
    )
    assert good.ok


def test_user_method_on_builtin_series_does_not_emit_namespace_warning() -> None:
    code = """//@version=6
indicator("method")
method inc(float x, int n=1) => x + n
y = close.inc(2)
"""
    result = parse_code(code, ParseOptions(source_name="method_on_builtin_series.pine"))

    assert result.ok
    assert not [d for d in result.diagnostics if d.code == codes.UNKNOWN_BUILTIN_MEMBER]
