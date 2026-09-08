from __future__ import annotations

from collections.abc import Mapping

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

_CONST_PROPAGATING_CALLS = {
    "int",
    "float",
    "bool",
    "string",
    "math.abs",
    "math.ceil",
    "math.floor",
    "math.max",
    "math.min",
    "math.pow",
    "math.round",
    "math.sqrt",
    "math.log",
    "math.exp",
    "math.sin",
    "math.cos",
    "str.tostring",
    "str.tonumber",
    "str.length",
    "str.contains",
    "str.startswith",
    "str.endswith",
    "str.replace",
    "timestamp",
}


def _join_qualifiers(*values: str) -> str:
    return max(values or ("series",), key=lambda q: _ORDER.get(q, 3))


def _symbol_qualifier(name: str, symbols: Mapping[str, object] | None) -> str | None:
    if not symbols:
        return None
    sym = symbols.get(name)
    if sym is None:
        return None
    return getattr(sym, "qualifier", None) or "series"


def infer_qualifier(expr, symbols: Mapping[str, object] | None = None) -> str:
    if isinstance(expr, Literal):
        return "const"
    if isinstance(expr, TupleExpr):
        return _join_qualifiers(*(infer_qualifier(item, symbols) for item in expr.elements))
    if isinstance(expr, UnaryExpr):
        return infer_qualifier(expr.operand, symbols)
    if isinstance(expr, BinaryExpr):
        return _join_qualifiers(
            infer_qualifier(expr.left, symbols), infer_qualifier(expr.right, symbols)
        )
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
        symbol = symbols.get(name) if symbols else None
        kind = getattr(symbol, "kind", None)
        bound = getattr(symbol, "qualifier", None)
        if getattr(kind, "value", kind) in {"function", "FUNCTION"} and bound is not None:
            return bound
        if name == "input" or name.startswith("input."):
            # Source selectors are series; scalar legacy input() is input just
            # like its namespaced successors. Never let input.source launder a
            # price series into a simple-only risk/length argument.
            if name == "input.source":
                return "series"
            if name == "input":
                named = {a.name: a.value for a in expr.arguments if a.name is not None}
                positional = [a.value for a in expr.arguments if a.name is None]
                source_type = named.get("type", positional[2] if len(positional) > 2 else None)
                default = named.get("defval", positional[0] if positional else None)
                if callee_name(source_type) == "input.source" or (
                    default is not None and infer_qualifier(default, symbols) == "series"
                ):
                    return "series"
            return "input"
        if name in {"na", "array.from"} and expr.arguments:
            return _join_qualifiers(*(infer_qualifier(a.value, symbols) for a in expr.arguments))
        if name in _CONST_PROPAGATING_CALLS and expr.arguments:
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


def _last_statement_qualifier(statement, symbols: Mapping[str, object] | None) -> str:
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


def _case_body_qualifier(body, symbols: Mapping[str, object] | None) -> str:
    statements = getattr(body, "statements", None)
    if statements:
        return _last_statement_qualifier(statements[-1], symbols)
    return infer_qualifier(body, symbols)
