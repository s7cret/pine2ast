from __future__ import annotations

from pine2ast.ast.nodes import (
    BinaryExpr,
    CallExpr,
    ConditionalExpr,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    IfStructure,
    Literal,
    MemberAccessExpr,
    SwitchStructure,
    TupleExpr,
    UnaryExpr,
)
from pine2ast.semantic.type_infer import callee_name

_ORDER = {"const": 0, "input": 1, "simple": 2, "series": 3}


def _join_qualifiers(*values: str) -> str:
    return max(values or ("series",), key=lambda q: _ORDER.get(q, 3))


def _symbol_qualifier(name: str, symbols: dict[str, object] | None) -> str | None:
    if not symbols:
        return None
    sym = symbols.get(name)
    if sym is None:
        return None
    return getattr(sym, "qualifier", None) or "series"


def infer_qualifier(expr, symbols: dict[str, object] | None = None) -> str:
    if isinstance(expr, Literal):
        return "const"
    if isinstance(expr, TupleExpr):
        return _join_qualifiers(*(infer_qualifier(item, symbols) for item in expr.elements))
    if isinstance(expr, UnaryExpr):
        return infer_qualifier(expr.operand, symbols)
    if isinstance(expr, BinaryExpr):
        return _join_qualifiers(infer_qualifier(expr.left, symbols), infer_qualifier(expr.right, symbols))
    if isinstance(expr, ConditionalExpr):
        return _join_qualifiers(
            infer_qualifier(expr.condition, symbols),
            infer_qualifier(expr.if_true, symbols),
            infer_qualifier(expr.if_false, symbols),
        )
    if isinstance(expr, HistoryRefExpr):
        return "series"
    if isinstance(expr, IfStructure):
        values = []
        if expr.then_block.statements:
            values.append(_last_statement_qualifier(expr.then_block.statements[-1], symbols))
        for br in expr.else_if_branches:
            if br.block.statements:
                values.append(_last_statement_qualifier(br.block.statements[-1], symbols))
        if expr.else_block and expr.else_block.statements:
            values.append(_last_statement_qualifier(expr.else_block.statements[-1], symbols))
        return _join_qualifiers(*values) if values else "series"
    if isinstance(expr, SwitchStructure):
        values = [_case_body_qualifier(case.body, symbols) for case in expr.cases]
        return _join_qualifiers(*values) if values else "series"
    if isinstance(expr, CallExpr):
        name = callee_name(expr.callee)
        if name.startswith("input."):
            return "input"
        if name in {"na", "str.tostring", "array.from"} and expr.arguments:
            return _join_qualifiers(*(infer_qualifier(a.value, symbols) for a in expr.arguments))
        return "series"
    if isinstance(expr, GenericInstantiationExpr):
        return infer_qualifier(expr.base, symbols)
    if isinstance(expr, MemberAccessExpr):
        full = callee_name(expr)
        return _symbol_qualifier(full, symbols) or infer_qualifier(expr.object, symbols)
    if isinstance(expr, Identifier):
        return _symbol_qualifier(expr.name, symbols) or "series"
    return "series"


def _last_statement_qualifier(statement, symbols: dict[str, object] | None) -> str:
    expression = getattr(statement, "expression", None)
    if expression is not None:
        return infer_qualifier(expression, symbols)
    initializer = getattr(statement, "initializer", None)
    if initializer is not None:
        return infer_qualifier(initializer, symbols)
    value = getattr(statement, "value", None)
    if value is not None:
        return infer_qualifier(value, symbols)
    return "series"


def _case_body_qualifier(body, symbols: dict[str, object] | None) -> str:
    statements = getattr(body, "statements", None)
    if statements:
        return _last_statement_qualifier(statements[-1], symbols)
    return infer_qualifier(body, symbols)
