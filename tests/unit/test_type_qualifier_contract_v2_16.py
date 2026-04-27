from __future__ import annotations

from pine2ast.ast.nodes import (
    Argument,
    BinaryExpr,
    Block,
    CallExpr,
    ConditionalExpr,
    ExpressionStatement,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    IfStructure,
    Literal,
    MemberAccessExpr,
    SwitchCase,
    SwitchStructure,
    TupleExpr,
    UnaryExpr,
)
from pine2ast.ast.types import TypeRef
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.qualifier_infer import infer_qualifier
from pine2ast.semantic.symbols import Symbol, SymbolKind
from pine2ast.semantic.type_infer import callee_name, infer_type

S = SourceSpan.zero()


def lit(value: object, typ: str) -> Literal:
    return Literal(S, value, typ)


def ident(name: str) -> Identifier:
    return Identifier(S, name)


def arg(expr) -> Argument:
    return Argument(S, None, expr)


def sym(name: str, kind: SymbolKind, typ: str | None, qualifier: str | None = "series") -> Symbol:
    return Symbol(1, name, kind, S, typ, qualifier, 0)


def test_type_inference_collection_udt_security_and_generic_paths():
    symbols = {
        "Point": sym("Point", SymbolKind.TYPE, "type"),
        "p": sym("p", SymbolKind.VARIABLE, "Point"),
        "Point.x": sym("Point.x", SymbolKind.FIELD, "float"),
        "arr": sym("arr", SymbolKind.VARIABLE, "array<int>"),
        "mat": sym("mat", SymbolKind.VARIABLE, "matrix<float>"),
        "m": sym("m", SymbolKind.VARIABLE, "map<string,color>"),
        "lib.score": sym("lib.score", SymbolKind.FUNCTION, "float"),
    }

    assert (
        infer_type(CallExpr(S, MemberAccessExpr(S, ident("Point"), "new"), []), symbols) == "Point"
    )
    assert infer_type(MemberAccessExpr(S, ident("p"), "x"), symbols) == "float"
    assert (
        infer_type(
            CallExpr(S, MemberAccessExpr(S, ident("arr"), "get"), [arg(lit(0, "int"))]), symbols
        )
        == "int"
    )
    assert (
        infer_type(
            CallExpr(
                S,
                MemberAccessExpr(S, ident("mat"), "get"),
                [arg(lit(0, "int")), arg(lit(0, "int"))],
            ),
            symbols,
        )
        == "float"
    )
    assert (
        infer_type(
            CallExpr(S, ident("map.get"), [arg(ident("m")), arg(lit("k", "string"))]), symbols
        )
        == "color"
    )
    assert (
        infer_type(
            CallExpr(S, ident("array.from"), [arg(lit(1, "int")), arg(lit(2.0, "float"))]), symbols
        )
        == "array<float>"
    )
    assert (
        infer_type(
            CallExpr(S, ident("array.from"), [arg(lit("x", "string")), arg(lit(2, "int"))]), symbols
        )
        == "array<mixed>"
    )
    assert (
        infer_type(
            CallExpr(
                S,
                ident("request.security"),
                [
                    arg(ident("ticker")),
                    arg(lit("D", "string")),
                    arg(TupleExpr(S, [lit(1, "int"), lit(2.0, "float")])),
                ],
            ),
            symbols,
        )
        == "tuple<int,float>"
    )
    assert (
        infer_type(CallExpr(S, MemberAccessExpr(S, ident("lib"), "score"), []), symbols) == "float"
    )
    assert (
        infer_type(
            CallExpr(
                S,
                GenericInstantiationExpr(
                    S, MemberAccessExpr(S, ident("array"), "new"), [TypeRef("float")]
                ),
                [],
            )
        )
        == "array<float>"
    )
    assert (
        infer_type(
            CallExpr(
                S,
                GenericInstantiationExpr(
                    S,
                    MemberAccessExpr(S, ident("map"), "new"),
                    [TypeRef("string"), TypeRef("float")],
                ),
                [],
            )
        )
        == "map<string,float>"
    )
    assert (
        infer_type(
            CallExpr(
                S,
                GenericInstantiationExpr(
                    S, MemberAccessExpr(S, ident("matrix"), "new"), [TypeRef("color")]
                ),
                [],
            )
        )
        == "matrix<color>"
    )
    assert (
        infer_type(GenericInstantiationExpr(S, ident("array"), [TypeRef("float")]))
        == "array<float>"
    )
    assert (
        callee_name(
            GenericInstantiationExpr(
                S, MemberAccessExpr(S, ident("array"), "new"), [TypeRef("int")]
            )
        )
        == "array.new<int>"
    )


def test_type_inference_expression_structures_merge_and_unknown_paths():
    assert infer_type(BinaryExpr(S, "+", lit(1, "int"), lit(2.0, "float"))) == "float"
    assert infer_type(BinaryExpr(S, "+", lit("a", "string"), lit("b", "string"))) == "string"
    assert infer_type(BinaryExpr(S, "<", lit(1, "int"), lit(2, "int"))) == "bool"
    assert infer_type(UnaryExpr(S, "not", ident("x"))) == "bool"
    assert (
        infer_type(ConditionalExpr(S, ident("cond"), lit(1, "int"), lit(2.0, "float"))) == "float"
    )
    assert infer_type(HistoryRefExpr(S, lit(1, "int"), lit(1, "int"))) == "int"

    if_expr = IfStructure(
        S,
        ident("cond"),
        Block(S, [ExpressionStatement(S, lit(1, "int"))]),
        [],
        Block(S, [ExpressionStatement(S, lit(2.0, "float"))]),
    )
    assert infer_type(if_expr) == "float"

    switch_expr = SwitchStructure(
        S,
        ident("mode"),
        [SwitchCase(S, lit("a", "string"), lit(1, "int")), SwitchCase(S, None, lit(2, "int"))],
    )
    assert infer_type(switch_expr) == "int"
    assert infer_type(MemberAccessExpr(S, ident("unknown"), "field")) == "unknown"


def test_qualifier_inference_covers_joining_calls_and_structures():
    symbols = {
        "a": sym("a", SymbolKind.VARIABLE, "int", "input"),
        "b": sym("b", SymbolKind.VARIABLE, "float", "simple"),
        "ns.value": sym("ns.value", SymbolKind.VARIABLE, "float", "const"),
    }
    assert infer_qualifier(lit(1, "int"), symbols) == "const"
    assert infer_qualifier(BinaryExpr(S, "+", ident("a"), ident("b")), symbols) == "simple"
    assert (
        infer_qualifier(CallExpr(S, ident("input.int"), [arg(lit(1, "int"))]), symbols) == "input"
    )
    assert (
        infer_qualifier(CallExpr(S, ident("str.tostring"), [arg(ident("a"))]), symbols) == "input"
    )
    assert infer_qualifier(HistoryRefExpr(S, ident("a"), lit(1, "int")), symbols) == "series"
    assert (
        infer_qualifier(GenericInstantiationExpr(S, ident("a"), [TypeRef("int")]), symbols)
        == "input"
    )
    assert infer_qualifier(MemberAccessExpr(S, ident("ns"), "value"), symbols) == "const"

    if_expr = IfStructure(
        S,
        ident("cond"),
        Block(S, [ExpressionStatement(S, ident("a"))]),
        [],
        Block(S, [ExpressionStatement(S, HistoryRefExpr(S, ident("b"), lit(1, "int")))]),
    )
    assert infer_qualifier(if_expr, symbols) == "series"

    switch_expr = SwitchStructure(
        S,
        None,
        [SwitchCase(S, None, Block(S, [ExpressionStatement(S, ident("a"))]))],
    )
    assert infer_qualifier(switch_expr, symbols) == "input"
