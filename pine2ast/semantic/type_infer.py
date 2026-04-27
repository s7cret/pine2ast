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
from pine2ast.semantic.builtin_registry import load_builtin_registry


def callee_name(expr) -> str:
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, Literal) and expr.literal_type == "na":
        return "na"
    if isinstance(expr, MemberAccessExpr):
        return callee_name(expr.object) + "." + expr.member
    if isinstance(expr, GenericInstantiationExpr):
        args = ",".join(_type_ref_name(t) for t in expr.type_args)
        return f"{callee_name(expr.base)}<{args}>"
    return "<expr>"


def _type_ref_name(type_ref) -> str:
    if getattr(type_ref, "template_args", None):
        return (
            f"{type_ref.name}<" + ",".join(_type_ref_name(t) for t in type_ref.template_args) + ">"
        )
    return type_ref.name


def _symbol_type(name: str, symbols: Mapping[str, object] | None) -> str | None:
    if not symbols:
        return None
    sym = symbols.get(name)
    if sym is None:
        return None
    return getattr(sym, "type", None) or "unknown"


def _symbol_kind(name: str, symbols: Mapping[str, object] | None) -> str | None:
    if not symbols:
        return None
    sym = symbols.get(name)
    kind = getattr(sym, "kind", None) if sym is not None else None
    return getattr(kind, "value", kind)


def _member_field_type(expr: MemberAccessExpr, symbols: Mapping[str, object] | None) -> str | None:
    if not symbols:
        return None
    if isinstance(expr.object, Identifier):
        owner_type = _symbol_type(expr.object.name, symbols)
        if owner_type:
            return _symbol_type(f"{owner_type}.{expr.member}", symbols)
    if isinstance(expr.object, MemberAccessExpr):
        owner_type = infer_type(expr.object, symbols)
        if owner_type:
            return _symbol_type(f"{owner_type}.{expr.member}", symbols)
    return None


def _udt_constructor_return(expr: CallExpr, symbols: Mapping[str, object] | None) -> str | None:
    callee = expr.callee
    if (
        isinstance(callee, MemberAccessExpr)
        and callee.member == "new"
        and isinstance(callee.object, Identifier)
    ):
        type_name = callee.object.name
        if _symbol_kind(type_name, symbols) == "TYPE":
            return type_name
    return None


def _split_type_args(inner: str) -> list[str]:
    result: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(inner):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            result.append(inner[start:idx].strip() or "unknown")
            start = idx + 1
    tail = inner[start:].strip()
    if tail:
        result.append(tail)
    return result


def _collection_element_type(typ: str, *, map_value: bool = True) -> str | None:
    if typ.startswith("array<") and typ.endswith(">"):
        return typ[len("array<") : -1].strip() or "unknown"
    if typ.startswith("matrix<") and typ.endswith(">"):
        return typ[len("matrix<") : -1].strip() or "unknown"
    if typ.startswith("map<") and typ.endswith(">"):
        parts = _split_type_args(typ[len("map<") : -1])
        if len(parts) >= 2:
            return parts[1] if map_value else parts[0]
    return None


def _array_from_return(expr: CallExpr, symbols: Mapping[str, object] | None) -> str | None:
    name = callee_name(expr.callee)
    if name != "array.from" or not expr.arguments:
        return None
    types = [infer_type(arg.value, symbols) for arg in expr.arguments]
    known = [t for t in types if t not in {"unknown", "na"}]
    if not known:
        return "array<unknown>"
    if all(t == known[0] for t in known):
        return f"array<{known[0]}>"
    if set(known) <= {"int", "float"}:
        return "array<float>"
    return "array<mixed>"


def _collection_call_return(expr: CallExpr, symbols: Mapping[str, object] | None) -> str | None:
    name = callee_name(expr.callee)
    if (
        name
        in {
            "array.get",
            "array.pop",
            "array.shift",
            "array.first",
            "array.last",
            "matrix.get",
            "map.get",
        }
        and expr.arguments
    ):
        return _collection_element_type(infer_type(expr.arguments[0].value, symbols))
    if isinstance(expr.callee, MemberAccessExpr) and expr.callee.member in {
        "get",
        "pop",
        "shift",
        "first",
        "last",
    }:
        return _collection_element_type(infer_type(expr.callee.object, symbols))
    return None


def _generic_collection_constructor_return(expr: CallExpr) -> str | None:
    """Infer collection constructors represented as generic call callees.

    Pine collection constructors are commonly written as `array.new<float>()`,
    `matrix.new<float>()`, and `map.new<string, float>()`. The parser keeps the
    generic part on the callee expression, so builtin-registry lookup by raw
    callee name cannot recover the element/key/value types. Preserve those
    shapes here without introducing any new AST node kind.
    """

    if not isinstance(expr.callee, GenericInstantiationExpr):
        return None
    base_name = callee_name(expr.callee.base)
    type_args = [_type_ref_name(type_arg) for type_arg in expr.callee.type_args]
    if (
        base_name
        in {
            "array.new",
            "array.new_bool",
            "array.new_color",
            "array.new_float",
            "array.new_int",
            "array.new_string",
        }
        and type_args
    ):
        return f"array<{type_args[0]}>"
    if base_name == "matrix.new" and type_args:
        return f"matrix<{type_args[0]}>"
    if base_name == "map.new" and len(type_args) >= 2:
        return f"map<{type_args[0]},{type_args[1]}>"
    return None


def _request_security_return(expr: CallExpr, symbols: Mapping[str, object] | None) -> str | None:
    name = callee_name(expr.callee)
    if name not in {"request.security", "request.security_lower_tf"} or len(expr.arguments) < 3:
        return None
    # Pine returns the expression shape requested from another context. Preserve tuple shapes
    # for AST2Python/optimizer instead of collapsing everything to unknown.
    return infer_type(expr.arguments[2].value, symbols)


def _merge_types(types: list[str]) -> str:
    known = [t for t in types if t not in {"unknown", "na", None}]
    if not known:
        return "unknown"
    if all(t == known[0] for t in known):
        return known[0]
    if set(known) <= {"int", "float"}:
        return "float"
    return "unknown"


def infer_type(expr, symbols: Mapping[str, object] | None = None) -> str:
    if isinstance(expr, Literal):
        return expr.literal_type
    if isinstance(expr, TupleExpr):
        return "tuple<" + ",".join(infer_type(item, symbols) for item in expr.elements) + ">"
    if isinstance(expr, BinaryExpr):
        if expr.op in {"<", "<=", ">", ">=", "==", "!=", "and", "or"}:
            return "bool"
        lt = infer_type(expr.left, symbols)
        rt = infer_type(expr.right, symbols)
        if "float" in {lt, rt}:
            return "float"
        if "int" in {lt, rt}:
            return "int"
        if lt == rt and lt in {"string", "color"} and expr.op == "+":
            return lt
        return "unknown"
    if isinstance(expr, UnaryExpr):
        if expr.op == "not":
            return "bool"
        return infer_type(expr.operand, symbols)
    if isinstance(expr, ConditionalExpr):
        t = infer_type(expr.if_true, symbols)
        f = infer_type(expr.if_false, symbols)
        return _merge_types([t, f])
    if isinstance(expr, HistoryRefExpr):
        return infer_type(expr.base, symbols)
    if isinstance(expr, IfStructure):
        branch_types = []
        if expr.then_block.statements:
            branch_types.append(_last_statement_type(expr.then_block.statements[-1], symbols))
        for br in expr.else_if_branches:
            if br.block.statements:
                branch_types.append(_last_statement_type(br.block.statements[-1], symbols))
        if expr.else_block and expr.else_block.statements:
            branch_types.append(_last_statement_type(expr.else_block.statements[-1], symbols))
        return _merge_types(branch_types)
    if isinstance(expr, SwitchStructure):
        case_types = [_case_body_type(case.body, symbols) for case in expr.cases]
        return _merge_types(case_types)
    if isinstance(expr, CallExpr):
        generic_collection_type = _generic_collection_constructor_return(expr)
        if generic_collection_type:
            return generic_collection_type
        udt_type = _udt_constructor_return(expr, symbols)
        if udt_type:
            return udt_type
        array_from_type = _array_from_return(expr, symbols)
        if array_from_type:
            return array_from_type
        collection_type = _collection_call_return(expr, symbols)
        if collection_type:
            return collection_type
        security_type = _request_security_return(expr, symbols)
        if security_type:
            return security_type
        name = callee_name(expr.callee)
        sym_type = _symbol_type(name, symbols)
        sym_kind = _symbol_kind(name, symbols)
        if (
            sym_kind in {"FUNCTION", "METHOD"}
            and sym_type
            and sym_type not in {"function", "method", "unknown"}
        ):
            return sym_type
        entry = load_builtin_registry().get("functions", {}).get(name)
        if entry:
            ret = entry.get("returns", "unknown")
            if isinstance(ret, str) and ret.startswith("series<") and ret.endswith(">"):
                return ret[len("series<") : -1]
            return ret
        return "unknown"
    if isinstance(expr, GenericInstantiationExpr):
        return callee_name(expr)
    if isinstance(expr, MemberAccessExpr):
        full = callee_name(expr)
        return _symbol_type(full, symbols) or _member_field_type(expr, symbols) or "unknown"
    if isinstance(expr, Identifier):
        return _symbol_type(expr.name, symbols) or "unknown"
    return "unknown"


def _last_statement_type(statement, symbols: Mapping[str, object] | None) -> str:
    expression = getattr(statement, "expression", None)
    if expression is not None:
        return infer_type(expression, symbols)
    initializer = getattr(statement, "initializer", None)
    if initializer is not None:
        return infer_type(initializer, symbols)
    value = getattr(statement, "value", None)
    if value is not None:
        return infer_type(value, symbols)
    return "unknown"


def _case_body_type(body, symbols: Mapping[str, object] | None) -> str:
    statements = getattr(body, "statements", None)
    if statements:
        return _last_statement_type(statements[-1], symbols)
    return infer_type(body, symbols)
