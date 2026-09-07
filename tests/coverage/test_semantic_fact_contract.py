from __future__ import annotations

from types import SimpleNamespace

from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import (
    Argument,
    CallExpr,
    ConditionalExpr,
    GenericInstantiationExpr,
    Identifier,
    Literal,
    MemberAccessExpr,
    TupleExpr,
)
from pine2ast.ast.walk import iter_nodes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic import facts

SPAN = SourceSpan(0, 1, 1, 1, 1, 2)


FACT_SOURCE = """//@version=6
indicator("facts")
type Point
    float x = 0.0
    int y
enum Side
    left "Left"
    right
method move(Point self, float dx = 1.0, int count = 1) => self.x + dx * count
p = Point.new(1.0, 2)
p2 = Point.new(x=2.0, y=3)
x = p.x
unknown = p.missing
side = Side.left
badside = Side.missing
m1 = p.move(2.0)
m2 = p.move(dx=3.0, count=2)
var array<float> a = array.new<float>(0)
a.push(1.0)
a.set(0, 2.0)
av = a.get(0)
f(float q) =>
    if q > 0
        ta.sma(close, 2)
    else
        q
for i = 0 to 1
    a.push(i)
for v in a
    a.push(v)
while false
    a.clear()
switch x
    1 => a.push(1.0)
    => a.push(2.0)
"""


def _result():
    result = parse_code(FACT_SOURCE, ParseOptions(max_diagnostics=500))
    assert result.ast is not None
    assert result.semantic_model is not None
    return result


def _id(name: str) -> Identifier:
    return Identifier(SPAN, name)


def _lit(value: object, kind: str) -> Literal:
    return Literal(SPAN, value, kind)  # type: ignore[arg-type]


def _arg(value, name: str | None = None) -> Argument:
    return Argument(SPAN, name, value)


def test_semantic_fact_envelope_describes_types_enums_methods_and_contexts() -> None:
    result = _result()
    payload = facts.extract_semantic_facts(result.ast, semantic_model=result.semantic_model)

    assert payload["schema_version"] == 1
    assert payload["profile"] == "pine_v6"

    types = payload["types"]
    assert types["contract"] == "pine.types.v2"
    point = types["udts"][0]
    assert point["name"] == "Point"
    assert point["field_count"] == 2
    assert point["fields"][0]["default_type_ok"] is True
    assert point["fields"][1]["has_default"] is False
    assert {row["known"] for row in types["field_accesses"]} == {True, False}
    assert {row["known"] for row in types["enum_member_uses"]} == {True, False}
    assert types["enums"][0]["members"][0]["title"] == "Left"
    assert len(types["constructors"]) == 2
    assert all(not row["missing_required_fields"] for row in types["constructors"])

    methods = payload["methods"]
    declaration = methods["declarations"][0]
    assert declaration["name"] == "move"
    assert declaration["receiver"]["type"] == "Point"
    assert declaration["return_type"] == "float"
    assert [row["required"] for row in declaration["parameters"]] == [False, False]
    assert {row["kind"] for row in methods["calls"]} == {
        "user_defined",
        "builtin_collection",
    }
    assert any(row["function_form"] == "array.get" for row in methods["calls"])
    assert any(row["context"] == ["for_range"] for row in methods["calls"])
    assert any(row["context"] == ["for_in"] for row in methods["calls"])
    assert any(row["context"] == ["while"] for row in methods["calls"])
    assert any(row["context"] == ["switch"] for row in methods["calls"])

    contexts = {
        marker
        for node in iter_nodes(result.ast)
        if (marker := facts.node_context_marker(node)) is not None
    }
    assert {"function", "method", "if", "switch", "for_range", "for_in", "while"} <= contexts


def test_semantic_fact_expression_and_type_helpers_cover_all_public_shapes() -> None:
    member = MemberAccessExpr(SPAN, _id("Side"), "left")
    generic = GenericInstantiationExpr(SPAN, MemberAccessExpr(SPAN, _id("array"), "new"), [])
    call = CallExpr(SPAN, MemberAccessExpr(SPAN, _id("math"), "max"), [_arg(_lit(1, "int"))])
    tuple_expr = TupleExpr(SPAN, [_lit(1, "int"), _id("close"), member])
    conditional = ConditionalExpr(SPAN, _lit(True, "bool"), _lit(1, "int"), _lit(0, "int"))

    assert facts.span_dict(SPAN) == SPAN.to_dict()
    assert facts.span_dict(object()) is None
    assert facts.expr_summary(_lit(1, "int")) == 1
    assert facts.expr_summary(_id("close")) == "close"
    assert facts.expr_summary(member) == "Side.left"
    assert facts.expr_summary(generic) == "array.new<int>" or facts.expr_summary(
        generic
    ).startswith("array.new")
    assert facts.expr_summary(tuple_expr) == [1, "close", "Side.left"]
    assert facts.expr_summary(call) == {"call": "math.max", "arg_count": 1}
    assert facts.expr_summary(conditional) == {"kind": "ConditionalExpr", "condition": True}
    assert facts.expr_summary(SimpleNamespace(kind="synthetic")) == {"kind": "synthetic"}

    assert facts.collection_kind_from_type("array<float>") == "array"
    assert facts.collection_kind_from_type("float") is None
    assert facts.collection_method_function_form("array<float>", "get") == "array.get"
    assert facts.collection_method_function_form("float", "get") is None
    assert facts._type_parameters_for_collection("array<float>") == {"T": "float"}
    assert facts._type_parameters_for_collection("matrix<int>") == {"T": "int"}
    assert facts._type_parameters_for_collection("map<string,float>") == {
        "K": "string",
        "V": "float",
    }
    assert facts._type_parameters_for_collection("float") == {
        "T": "unknown",
        "K": "unknown",
        "V": "unknown",
    }
    assert facts._specialize_param_type(None, {"T": "float"}) is None
    assert facts._specialize_param_type("array<T>", {"T": "float"}) == "array<float>"
    assert facts.collection_method_parameter_specs("map<string,float>", "put")[0]["name"] == "key"
    assert facts._collection_return_type("matrix<float>", "get") == "float"
    assert facts._symbol_kind(SimpleNamespace(kind=SimpleNamespace(value="variable"))) == "variable"
    assert facts._symbol_kind(SimpleNamespace(kind="function")) == "function"
    assert facts._symbols(None) is None
    assert facts._literal_bool(_lit(True, "bool")) is True
    assert facts._literal_bool(_lit(1, "int")) is None


def test_udt_constructor_fact_reports_missing_unknown_duplicate_and_extra_bindings() -> None:
    result = _result()
    fields = facts._udt_field_map(result.ast)
    profile = result.ast.version_context

    early_call = CallExpr(SPAN, _id("not_a_member"), [])
    assert (
        facts._udt_constructor_fact(
            early_call,
            context=(),
            fields_by_type=fields,
            profile=profile,
            semantic_model=result.semantic_model,
        )
        is None
    )
    wrong_member = CallExpr(SPAN, MemberAccessExpr(SPAN, _id("Point"), "copy"), [])
    assert (
        facts._udt_constructor_fact(
            wrong_member,
            context=(),
            fields_by_type=fields,
            profile=profile,
            semantic_model=result.semantic_model,
        )
        is None
    )
    nested_owner = MemberAccessExpr(SPAN, MemberAccessExpr(SPAN, _id("pkg"), "Point"), "new")
    assert (
        facts._udt_constructor_fact(
            CallExpr(SPAN, nested_owner, []),
            context=(),
            fields_by_type=fields,
            profile=profile,
            semantic_model=result.semantic_model,
        )
        is None
    )
    unknown_type = CallExpr(SPAN, MemberAccessExpr(SPAN, _id("Unknown"), "new"), [])
    assert (
        facts._udt_constructor_fact(
            unknown_type,
            context=(),
            fields_by_type=fields,
            profile=profile,
            semantic_model=result.semantic_model,
        )
        is None
    )

    no_args = CallExpr(SPAN, MemberAccessExpr(SPAN, _id("Point"), "new"), [])
    missing = facts._udt_constructor_fact(
        no_args,
        context=("function",),
        fields_by_type=fields,
        profile=profile,
        semantic_model=result.semantic_model,
    )
    assert missing is not None
    assert missing["local_scope"] is True
    # Pine gives uninitialized UDT fields implicit defaults; y is not required.
    # https://www.tradingview.com/pine-script-docs/language/type-system/
    assert missing["missing_required_fields"] == []
    assert missing["field_count"] == 2

    mutant = CallExpr(
        SPAN,
        MemberAccessExpr(SPAN, _id("Point"), "new"),
        [
            _arg(_lit(1.0, "float")),
            _arg(_lit(2, "int")),
            _arg(_lit(3, "int")),
            _arg(_lit(4.0, "float"), "x"),
            _arg(_lit(5, "int"), "missing"),
            _arg(_lit(6.0, "float"), "x"),
        ],
    )
    row = facts._udt_constructor_fact(
        mutant,
        context=(),
        fields_by_type=fields,
        profile=profile,
        semantic_model=result.semantic_model,
    )
    assert row is not None
    assert row["too_many_positional"] is True
    assert row["unknown_fields"] == ["missing"]
    assert row["duplicate_fields"] == ["x", "x"]
    assert {arg["binding"] for arg in row["arguments"]} == {
        "positional",
        "extra_positional",
        "named",
        "unknown_named",
    }


def test_method_argument_binding_and_receiver_matching_fail_closed_edges() -> None:
    result = _result()
    engine = facts._engine(result.ast.version_context, result.semantic_model)
    args = [
        _arg(_lit(1.0, "float")),
        _arg(_lit(2.0, "float"), "value"),
        _arg(_lit(3, "int"), "unknown"),
        _arg(_lit(4, "int")),
    ]
    specs = [
        {"name": "value", "type": "float"},
        {"name": "count", "type": "int"},
    ]
    rows = facts.bind_arguments_to_specs(args, specs, engine)
    assert [row["binding"] for row in rows] == [
        "positional",
        "named",
        "unknown_named",
        "extra_positional",
    ]
    assert rows[1]["duplicate_positional_named"] is True
    assert rows[2]["expected_type"] is None

    assert facts._receiver_matches(None, "Point") is True
    assert facts._receiver_matches("unknown", "Point") is True
    assert facts._receiver_matches("Point", "Point") is True
    assert facts._receiver_matches("array<float>", "array") is True
    assert facts._receiver_matches("array<float>", "matrix") is False

    methods = facts._method_declarations(result.ast)
    assert methods
    assert facts._matching_user_method(methods, "move", "Point") is methods[0]
    assert facts._matching_user_method(methods, "missing", "Point") is None
    assert facts._method_return_type(methods[0], result.semantic_model) == "float"
    assert facts._method_return_type(methods[0], None) is None
    fake_model = SimpleNamespace(symbols={"move": SimpleNamespace(type="method")})
    assert facts._method_return_type(methods[0], fake_model) is None
