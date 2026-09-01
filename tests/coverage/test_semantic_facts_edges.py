from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pine2ast import parse_code
from pine2ast.ast.nodes import (
    Argument,
    CallExpr,
    ConditionalExpr,
    EnumDeclaration,
    EnumMember,
    ExpressionStatement,
    FieldDeclaration,
    GenericInstantiationExpr,
    Identifier,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    TupleExpr,
    TypeDeclaration,
)
from pine2ast.ast.types import TypeRef
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic import facts

SPAN = SourceSpan(0, 1, 1, 1, 1, 2)


def _identifier(name: str) -> Identifier:
    return Identifier(SPAN, name)


def _literal(value: object, literal_type: str) -> Literal:
    return Literal(SPAN, value, literal_type)  # type: ignore[arg-type]


def _arg(value: Any, name: str | None = None) -> Argument:
    return Argument(SPAN, name, value)


def _member(owner: Any, name: str) -> MemberAccessExpr:
    return MemberAccessExpr(SPAN, owner, name)


def _call(callee: Any, *args: Argument) -> CallExpr:
    return CallExpr(SPAN, callee, list(args))


class _Engine:
    def __init__(self) -> None:
        self.types = {
            "p": "Point",
            "a": "array<float>",
            "m": "map<string,float>",
            "unknown": "unknown",
        }

    def infer_type(self, value: Any) -> str:
        if isinstance(value, Identifier):
            return self.types.get(value.name, "unknown")
        if isinstance(value, Literal):
            return value.literal_type
        if isinstance(value, MemberAccessExpr):
            if value.member in {"x", "bump", "get"}:
                return "float"
        if isinstance(value, CallExpr):
            if isinstance(value.callee, MemberAccessExpr) and value.callee.member in {
                "bump",
                "get",
            }:
                return "float"
        return "unknown"

    def infer_qualifier(self, value: Any) -> str:
        return "const" if isinstance(value, Literal) else "series"

    def infer_value(self, value: Any) -> SimpleNamespace:
        type_name = self.infer_type(value)
        return SimpleNamespace(
            type_name=type_name,
            qualifier=self.infer_qualifier(value),
            can_be_na=type_name in {"float", "unknown"},
        )


def _synthetic_program() -> tuple[Any, TypeDeclaration, MethodDeclaration]:
    program = parse_code('//@version=6\nindicator("facts")\n').ast
    point = TypeDeclaration(
        SPAN,
        "Point",
        [
            FieldDeclaration(SPAN, "x", TypeRef("float", [], SPAN), None),
            FieldDeclaration(
                SPAN, "name", TypeRef("string", [], SPAN), _literal("origin", "string")
            ),
            FieldDeclaration(SPAN, "x", TypeRef("int", [], SPAN), _literal("bad", "string")),
        ],
    )
    side = EnumDeclaration(
        SPAN,
        "Side",
        [EnumMember(SPAN, "left", "Left"), EnumMember(SPAN, "left", None)],
    )
    method = MethodDeclaration(
        SPAN,
        "bump",
        TypeRef("Point", [], SPAN),
        "self",
        [],
        _literal(1.0, "float"),
    )
    constructor_positional = _call(
        _member(_identifier("Point"), "new"),
        _arg(_literal(1.0, "float")),
        _arg(_literal("name", "string")),
        _arg(_literal(3, "int")),
        _arg(_literal(4, "int")),
    )
    constructor_named = _call(
        _member(_identifier("Point"), "new"),
        _arg(_literal(1.0, "float"), "x"),
        _arg(_literal(2.0, "float"), "x"),
        _arg(_literal(3, "int"), "missing"),
    )
    nodes = [
        point,
        side,
        method,
        ExpressionStatement(SPAN, _member(_identifier("Side"), "left")),
        ExpressionStatement(SPAN, _member(_identifier("Side"), "right")),
        ExpressionStatement(SPAN, _member(_identifier("p"), "x")),
        ExpressionStatement(SPAN, _member(_identifier("p"), "missing")),
        ExpressionStatement(SPAN, constructor_positional),
        ExpressionStatement(SPAN, constructor_named),
        ExpressionStatement(
            SPAN, _call(_member(_identifier("p"), "bump"), _arg(_literal(2.0, "float")))
        ),
        ExpressionStatement(
            SPAN, _call(_member(_identifier("a"), "get"), _arg(_literal(0, "int")))
        ),
        ExpressionStatement(SPAN, _call(_member(_identifier("Point"), "new"))),
        ExpressionStatement(SPAN, _call(_member(_identifier("unknown"), "not_a_method"))),
    ]
    program.items.extend(nodes)
    return program, point, method


def test_semantic_fact_helpers_cover_expression_and_type_specialization() -> None:
    generic = GenericInstantiationExpr(
        SPAN,
        _member(_identifier("array"), "new"),
        [TypeRef("float", [], SPAN)],
    )
    tuple_expr = TupleExpr(SPAN, [_literal(1, "int"), _identifier("x")])
    conditional = ConditionalExpr(
        SPAN, _literal(True, "bool"), _literal(1, "int"), _literal(0, "int")
    )

    assert facts.expr_summary(generic) == "array.new<float>"
    assert facts.expr_summary(tuple_expr) == [1, "x"]
    assert facts.expr_summary(conditional) == {"kind": "ConditionalExpr", "condition": True}
    assert facts.expr_summary(SimpleNamespace(kind="Synthetic")) == {"kind": "Synthetic"}
    assert facts.span_dict(SPAN) == SPAN.to_dict()
    assert facts.span_dict(object()) is None

    assert facts._type_parameters_for_collection("array<float>") == {"T": "float"}
    assert facts._type_parameters_for_collection("matrix<int>") == {"T": "int"}
    assert facts._type_parameters_for_collection("map<string,array<float>>") == {
        "K": "string",
        "V": "array<float>",
    }
    assert facts._type_parameters_for_collection("float") == {
        "T": "unknown",
        "K": "unknown",
        "V": "unknown",
    }
    assert facts._specialize_param_type(None, {"T": "float"}) is None
    assert facts._specialize_param_type("array<T>", {"T": "float"}) == "array<float>"
    assert facts._literal_bool(_literal(True, "bool")) is True
    assert facts._literal_bool(_literal(1, "int")) is None
    assert facts._symbol_kind(SimpleNamespace(kind=SimpleNamespace(value="METHOD"))) == "METHOD"
    assert facts._symbol_kind(SimpleNamespace(kind="FUNCTION")) == "FUNCTION"


def test_receiver_matching_and_argument_binding_cover_all_binding_modes() -> None:
    engine = _Engine()
    assert facts._receiver_matches("Point", None)
    assert facts._receiver_matches("unknown", "Point")
    assert facts._receiver_matches("Point", "Point")
    assert facts._receiver_matches("array<float>", "array")
    assert not facts._receiver_matches("map<string,float>", "array")

    specs = [
        {"name": "first", "type": "float"},
        {"name": "second", "type": "int"},
    ]
    rows = facts.bind_arguments_to_specs(
        [
            _arg(_literal(1.0, "float")),
            _arg(_literal(2, "int"), "first"),
            _arg(_literal(3, "int"), "missing"),
            _arg(_literal(4, "int")),
        ],
        specs,
        engine,  # type: ignore[arg-type]
    )
    assert [row["binding"] for row in rows] == [
        "positional",
        "named",
        "unknown_named",
        "extra_positional",
    ]
    assert rows[1]["duplicate_positional_named"] is True
    assert rows[2]["expected_type"] is None
    assert rows[3]["field_or_parameter"] is None


def test_udt_constructor_fact_rejects_non_constructors_and_records_all_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program, point, _method = _synthetic_program()
    engine = _Engine()
    monkeypatch.setattr(facts, "_engine", lambda *args, **kwargs: engine)
    fields = {"Point": list(point.fields)}
    profile = program.version_context

    assert (
        facts._udt_constructor_fact(
            _call(_identifier("f")),
            context=(),
            fields_by_type=fields,
            profile=profile,
            semantic_model=None,
        )
        is None
    )
    assert (
        facts._udt_constructor_fact(
            _call(_member(_identifier("Point"), "copy")),
            context=(),
            fields_by_type=fields,
            profile=profile,
            semantic_model=None,
        )
        is None
    )
    assert (
        facts._udt_constructor_fact(
            _call(_member(_literal("Point", "string"), "new")),
            context=(),
            fields_by_type=fields,
            profile=profile,
            semantic_model=None,
        )
        is None
    )
    assert (
        facts._udt_constructor_fact(
            _call(_member(_identifier("Missing"), "new")),
            context=(),
            fields_by_type=fields,
            profile=profile,
            semantic_model=None,
        )
        is None
    )

    call = _call(
        _member(_identifier("Point"), "new"),
        _arg(_literal(1.0, "float")),
        _arg(_literal(2.0, "float"), "x"),
        _arg(_literal(3.0, "float"), "x"),
        _arg(_literal(4, "int"), "unknown"),
        _arg(_literal(5, "int")),
    )
    row = facts._udt_constructor_fact(
        call,
        context=("function",),
        fields_by_type=fields,
        profile=profile,
        semantic_model=None,
    )
    assert row is not None
    assert row["local_scope"] is True
    assert row["too_many_positional"] is False
    assert row["duplicate_fields"] == ["x", "x"]
    assert row["unknown_fields"] == ["unknown"]
    assert "name" in row["missing_required_fields"] or row["missing_required_fields"] == []


def test_type_and_method_contracts_expose_duplicates_members_and_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program, _point, method = _synthetic_program()
    engine = _Engine()
    monkeypatch.setattr(facts, "_engine", lambda *args, **kwargs: engine)
    semantic_model = SimpleNamespace(
        symbols={
            "p": SimpleNamespace(type="Point", kind="VARIABLE"),
            "a": SimpleNamespace(type="array<float>", kind="VARIABLE"),
            "Side.left": SimpleNamespace(type="Side", kind="ENUM_VALUE"),
            "bump": SimpleNamespace(type="float", kind="METHOD"),
        }
    )

    type_contract = facts.extract_type_contract(program, semantic_model=semantic_model)
    assert type_contract["udts"][0]["duplicate_fields"] == ["x"]
    assert type_contract["enums"][0]["duplicate_members"] == ["left"]
    assert {row["known"] for row in type_contract["field_accesses"]} == {True, False}
    assert {row["known"] for row in type_contract["enum_member_uses"]} == {True, False}
    assert len(type_contract["constructors"]) == 3
    assert any(row["too_many_positional"] for row in type_contract["constructors"])
    assert any(row["unknown_fields"] for row in type_contract["constructors"])

    assert facts._method_return_type(method, semantic_model) == "float"
    assert (
        facts._method_return_type(
            method, SimpleNamespace(symbols={"bump": SimpleNamespace(type="method")})
        )
        is None
    )
    assert facts._matching_user_method([method], "bump", "Point") is method
    assert facts._matching_user_method([method], "other", "Point") is None

    method_contract = facts.extract_method_contract(program, semantic_model=semantic_model)
    assert method_contract["declarations"][0]["return_type"] == "float"
    assert {row["kind"] for row in method_contract["calls"]} == {
        "user_defined",
        "builtin_collection",
    }
    user_call = next(row for row in method_contract["calls"] if row["kind"] == "user_defined")
    assert user_call["receiver"]["type_ok"] is True
    assert user_call["local_scope"] is False

    combined = facts.extract_semantic_facts(program, semantic_model=semantic_model)
    assert combined["schema_version"] == 1
    assert combined["types"]["udts"]
    assert combined["methods"]["calls"]
