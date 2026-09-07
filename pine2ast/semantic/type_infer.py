from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pine2ast.ast.nodes import (
    BinaryExpr,
    CallExpr,
    ConditionalExpr,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    IfStructure,
    ForRangeStructure,
    ForInStructure,
    WhileStructure,
    Literal,
    MemberAccessExpr,
    SwitchStructure,
    TupleExpr,
    UnaryExpr,
)
from pine2ast.semantic.type_helpers import split_type_args

Registry = Mapping[str, Any]


def callee_name(expr: Any) -> str:
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, Literal) and expr.literal_type == "na":
        return "na"
    if isinstance(expr, MemberAccessExpr):
        return callee_name(expr.object) + "." + expr.member
    if isinstance(expr, GenericInstantiationExpr):
        args = ",".join(_type_ref_name(item) for item in expr.type_args)
        return f"{callee_name(expr.base)}<{args}>"
    return "<expr>"


def _type_ref_name(type_ref: Any) -> str:
    if getattr(type_ref, "template_args", None):
        return (
            f"{type_ref.name}<"
            + ",".join(_type_ref_name(item) for item in type_ref.template_args)
            + ">"
        )
    return str(type_ref.name)


def _symbol_type(name: str, symbols: Mapping[str, object] | None) -> str | None:
    if not symbols:
        return None
    symbol = symbols.get(name)
    return None if symbol is None else (getattr(symbol, "type", None) or "unknown")


def _symbol_kind(name: str, symbols: Mapping[str, object] | None) -> str | None:
    if not symbols:
        return None
    symbol = symbols.get(name)
    kind = getattr(symbol, "kind", None) if symbol is not None else None
    return getattr(kind, "value", kind)


def _member_field_type(
    expr: MemberAccessExpr,
    symbols: Mapping[str, object] | None,
    registry: Registry | None,
) -> str | None:
    if not symbols:
        return None
    if isinstance(expr.object, Identifier):
        owner_type = _symbol_type(expr.object.name, symbols)
    else:
        owner_type = infer_type(expr.object, symbols, registry=registry)
    return _symbol_type(f"{owner_type}.{expr.member}", symbols) if owner_type else None


def _udt_constructor_return(expr: CallExpr, symbols: Mapping[str, object] | None) -> str | None:
    callee = expr.callee
    if (
        isinstance(callee, MemberAccessExpr)
        and callee.member == "new"
        and isinstance(callee.object, Identifier)
        and _symbol_kind(callee.object.name, symbols) in {"TYPE", "type"}
    ):
        return callee.object.name
    return None


def _collection_element_type(type_name: str, *, map_value: bool = True) -> str | None:
    if type_name.startswith("array<") and type_name.endswith(">"):
        return type_name[6:-1].strip() or "unknown"
    if type_name.startswith("matrix<") and type_name.endswith(">"):
        return type_name[7:-1].strip() or "unknown"
    if type_name.startswith("map<") and type_name.endswith(">"):
        parts = split_type_args(type_name[4:-1])
        if len(parts) >= 2:
            return parts[1] if map_value else parts[0]
    return None


def _array_from_return(
    expr: CallExpr,
    symbols: Mapping[str, object] | None,
    registry: Registry | None,
) -> str | None:
    if callee_name(expr.callee) != "array.from" or not expr.arguments:
        return None
    types = [infer_type(item.value, symbols, registry=registry) for item in expr.arguments]
    known = [item for item in types if item not in {"unknown", "na"}]
    if not known:
        return "array<unknown>"
    if all(item == known[0] for item in known):
        return f"array<{known[0]}>"
    if set(known) <= {"int", "float"}:
        return "array<float>"
    return "array<mixed>"


def _collection_call_return(
    expr: CallExpr,
    symbols: Mapping[str, object] | None,
    registry: Registry | None,
) -> str | None:
    name = callee_name(expr.callee)
    value_methods = {
        "array.get",
        "array.pop",
        "array.shift",
        "array.first",
        "array.last",
        "matrix.get",
        "map.get",
    }
    if name in value_methods and expr.arguments:
        owner = infer_type(expr.arguments[0].value, symbols, registry=registry)
        return _collection_element_type(owner)
    if isinstance(expr.callee, MemberAccessExpr) and expr.callee.member in {
        "get",
        "pop",
        "shift",
        "first",
        "last",
    }:
        owner = infer_type(expr.callee.object, symbols, registry=registry)
        return _collection_element_type(owner)
    return None


def _user_method_call_return(expr: CallExpr, symbols: Mapping[str, object] | None) -> str | None:
    if not isinstance(expr.callee, MemberAccessExpr):
        return None
    name = expr.callee.member
    if _symbol_kind(name, symbols) not in {"METHOD", "method"}:
        return None
    result = _symbol_type(name, symbols)
    return None if result in {None, "method", "function", "unknown"} else result


def _generic_collection_constructor_return(expr: CallExpr) -> str | None:
    if not isinstance(expr.callee, GenericInstantiationExpr):
        return None
    base = callee_name(expr.callee.base)
    args = [_type_ref_name(item) for item in expr.callee.type_args]
    if base.startswith("array.new") and args:
        return f"array<{args[0]}>"
    if base == "matrix.new" and args:
        return f"matrix<{args[0]}>"
    if base == "map.new" and len(args) >= 2:
        return f"map<{args[0]},{args[1]}>"
    return None


def request_expression_argument(expr: CallExpr) -> Any | None:
    """Resolve the expression by source binding, not incidental argument order."""
    named = [arg.value for arg in expr.arguments if arg.name == "expression"]
    positional = [arg.value for arg in expr.arguments if arg.name is None]
    if named:
        return named[0] if len(named) == 1 else None
    return positional[2] if len(positional) >= 3 else None


def _request_return(
    expr: CallExpr, symbols: Mapping[str, object] | None, registry: Registry | None
) -> str | None:
    name = callee_name(expr.callee)
    if name not in {"security", "request.security", "request.security_lower_tf"}:
        return None
    expression = request_expression_argument(expr)
    if expression is None:
        return None
    requested = infer_type(expression, symbols, registry=registry)
    if name != "request.security_lower_tf":
        return requested
    if requested.startswith("tuple<") and requested.endswith(">"):
        return (
            "tuple<" + ",".join(f"array<{item}>" for item in split_type_args(requested[6:-1])) + ">"
        )
    return f"array<{requested}>"


def _merge_types(types: list[str]) -> str:
    known = [item for item in types if item not in {"unknown", "na", None}]
    if not known:
        return "unknown"
    if all(item == known[0] for item in known):
        return known[0]
    if set(known) <= {"int", "float"}:
        return "float"
    return "unknown"


def _registry_return(name: str, registry: Registry | None) -> str | None:
    if registry is None:
        return None
    entry = registry.get("functions", {}).get(name)
    if not isinstance(entry, Mapping):
        return None
    value = entry.get("returns")
    if not isinstance(value, str):
        return None
    if value.startswith("series<") and value.endswith(">"):
        return value[7:-1]
    if value.startswith("series "):
        return value[7:]
    return value


def _entry_for_call(expr: CallExpr, registry: Registry | None) -> Mapping[str, Any] | None:
    if registry is None:
        return None
    raw = callee_name(expr.callee)
    functions = registry.get("functions", {})
    entry = functions.get(raw)
    if isinstance(entry, Mapping):
        return entry
    # Method syntax resolves through the receiver's generic base.
    if isinstance(expr.callee, MemberAccessExpr):
        receiver_type = infer_type(expr.callee.object, registry=registry)
        base = receiver_type.split("<", 1)[0] if receiver_type else ""
        candidate = registry.get("methods", {}).get(f"{base}.{expr.callee.member}")
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _parametric_return_rule(
    expr: CallExpr,
    symbols: Mapping[str, object] | None,
    registry: Registry | None,
) -> str | None:
    entry = _entry_for_call(expr, registry)
    if not entry:
        return None
    rule = entry.get("return_rule_id")
    if not isinstance(rule, str):
        return None
    name = callee_name(expr.callee)
    receiver_type: str | None = None
    if isinstance(expr.callee, MemberAccessExpr):
        receiver_type = infer_type(expr.callee.object, symbols, registry=registry)
    elif expr.arguments and name.startswith(("array.", "map.", "matrix.")):
        receiver_type = infer_type(expr.arguments[0].value, symbols, registry=registry)

    if rule == "return.void.v1":
        return "void"
    if rule == "return.reference.box.v1":
        return "box"
    if rule == "return.reference.label.v1":
        return "label"
    if rule == "return.reference.line.v1":
        return "line"
    if rule == "return.reference.linefill.v1":
        return "linefill"
    if rule in {"return.input.defval_type.v1", "return.input.enum_type.v1"}:
        return (
            infer_type(expr.arguments[0].value, symbols, registry=registry)
            if expr.arguments
            else "unknown"
        )
    if rule == "return.array.explicit_element_type.v1":
        raw = callee_name(expr.callee)
        if "<" in raw and raw.endswith(">"):
            return f"array<{raw.rsplit('<', 1)[1][:-1]}>"
        return "array<unknown>"
    if rule == "return.array.from_arguments.v1":
        return _array_from_return(expr, symbols, registry)
    if rule in {
        "return.collection.element.v1",
        "return.collection.numeric_sum.v1",
        "return.collection.numeric_average.v1",
        "return.map.value.v1",
        "return.matrix.element.v1",
    }:
        element = _collection_element_type(receiver_type or "")
        if rule == "return.collection.numeric_average.v1":
            return "float" if element in {"int", "float"} else element
        return element or "unknown"
    return None


def infer_type(
    expr: Any,
    symbols: Mapping[str, object] | None = None,
    *,
    registry: Registry | None = None,
) -> str:
    """Infer one Pine expression type without selecting a language version.

    Version selection is intentionally absent. Callers that need built-in return
    types must supply the catalog view already selected by PineVersionContext.
    """

    def recur(item: Any) -> str:
        return infer_type(item, symbols, registry=registry)

    if isinstance(expr, Literal):
        return expr.literal_type
    if isinstance(expr, TupleExpr):
        return "tuple<" + ",".join(recur(item) for item in expr.elements) + ">"
    if isinstance(expr, BinaryExpr):
        if expr.op in {"<", "<=", ">", ">=", "==", "!=", "and", "or"}:
            return "bool"
        left, right = recur(expr.left), recur(expr.right)
        if "float" in {left, right}:
            return "float"
        if "int" in {left, right}:
            return "int"
        if left == right and left in {"string", "color"} and expr.op == "+":
            return left
        return "unknown"
    if isinstance(expr, UnaryExpr):
        return "bool" if expr.op == "not" else recur(expr.operand)
    if isinstance(expr, ConditionalExpr):
        return _merge_types([recur(expr.if_true), recur(expr.if_false)])
    if isinstance(expr, HistoryRefExpr):
        return recur(expr.base)
    if isinstance(
        expr, (IfStructure, SwitchStructure, ForRangeStructure, ForInStructure, WhileStructure)
    ):
        from pine2ast.semantic.control_values import returned_expressions

        values = [
            infer_type(value, symbols, registry=registry) for value in returned_expressions(expr)
        ]
        return (
            _merge_types(values)
            if values
            else (
                "unknown"
                if isinstance(expr, (ForRangeStructure, ForInStructure, WhileStructure))
                else "void"
            )
        )
    if isinstance(expr, CallExpr):
        inferred = _generic_collection_constructor_return(expr)
        if inferred:
            return inferred
        inferred = _udt_constructor_return(expr, symbols)
        if inferred:
            return inferred
        inferred = _array_from_return(expr, symbols, registry)
        if inferred:
            return inferred
        inferred = _collection_call_return(expr, symbols, registry)
        if inferred:
            return inferred
        inferred = _user_method_call_return(expr, symbols)
        if inferred:
            return inferred
        inferred = _request_return(expr, symbols, registry)
        if inferred:
            return inferred
        inferred = _parametric_return_rule(expr, symbols, registry)
        if inferred and inferred != "unknown":
            return inferred
        name = callee_name(expr.callee)
        symbol_type = _symbol_type(name, symbols)
        symbol_kind = _symbol_kind(name, symbols)
        if symbol_kind in {"FUNCTION", "METHOD", "function", "method"} and symbol_type not in {
            None,
            "function",
            "method",
            "unknown",
        }:
            return str(symbol_type)
        if name in {"math.min", "math.max"}:
            merged = _merge_types([recur(item.value) for item in expr.arguments])
            if merged in {"int", "float"}:
                return merged
        return _registry_return(name, registry) or "unknown"
    if isinstance(expr, GenericInstantiationExpr):
        return callee_name(expr)
    if isinstance(expr, MemberAccessExpr):
        full = callee_name(expr)
        return (
            _symbol_type(full, symbols) or _member_field_type(expr, symbols, registry) or "unknown"
        )
    if isinstance(expr, Identifier):
        return _symbol_type(expr.name, symbols) or "unknown"
    return "unknown"


def _last_statement_type(
    statement: Any,
    symbols: Mapping[str, object] | None,
    registry: Registry | None,
) -> str:
    for field in ("expression", "initializer", "value"):
        value = getattr(statement, field, None)
        if value is not None:
            return infer_type(value, symbols, registry=registry)
    return "unknown"


def _case_body_type(
    body: Any,
    symbols: Mapping[str, object] | None,
    registry: Registry | None,
) -> str:
    statements = getattr(body, "statements", None)
    if statements:
        return _last_statement_type(statements[-1], symbols, registry)
    return infer_type(body, symbols, registry=registry)


__all__ = ["callee_name", "infer_type"]
