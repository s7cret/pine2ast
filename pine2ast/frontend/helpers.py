from __future__ import annotations

from typing import Any, Iterable

from pine2ast.ast.base import ASTNode
from pine2ast.ast.walk import (
    iter_child_nodes as _walk_iter_child_nodes,
    iter_nodes as _walk_iter_nodes,
)
from pine2ast.ast.nodes import (
    Argument,
    CallExpr,
    DeclarationStatement,
    EnumDeclaration,
    ForRangeStructure,
    FunctionDeclaration,
    GenericInstantiationExpr,
    Literal,
    MethodDeclaration,
    Program,
    TypeDeclaration,
    VarDeclaration,
)
from pine2ast.versioning import PineVersionContext
from pine2ast.catalog import load_catalog_readonly_view
from pine2ast.semantic.facts import (
    expr_summary as _expr_summary,
    iter_calls_with_context as _iter_calls_with_context,
    span_dict as _span_dict,
)
from pine2ast.semantic.inference import PineInferenceEngine
from pine2ast.semantic.signatures import SignatureResolver
from pine2ast.semantic.type_helpers import collection_value_type, is_assignable_type, type_ref_name
from pine2ast.semantic.type_infer import callee_name

Context = tuple[str, ...]

_REQUEST_CONTEXT_PARAMETER_NAMES = {
    "symbol",
    "ticker",
    "timeframe",
    "currency",
    "financial_id",
    "period",
    "field",
    "gaps",
    "lookahead",
}

_ORDER_CALLS = {"strategy.entry", "strategy.order"}
_EXIT_CALLS = {"strategy.exit"}
_MANAGEMENT_CALLS = {
    "strategy.close",
    "strategy.close_all",
    "strategy.cancel",
    "strategy.cancel_all",
}
_RISK_CALL_PREFIX = "strategy.risk."


def _literal_bool(expr: Any) -> bool | None:
    if isinstance(expr, Literal) and expr.literal_type == "bool":
        return bool(expr.value)
    return None


def _arg_by_name(args: list[Argument], name: str) -> Argument | None:
    return next((arg for arg in args if arg.name == name), None)


def _declaration_title(declaration: DeclarationStatement | None) -> str | None:
    if declaration is None or not declaration.call.arguments:
        return None
    first = declaration.call.arguments[0]
    if first.name is None and isinstance(first.value, Literal):
        return str(first.value.value)
    title = _arg_by_name(declaration.call.arguments, "title")
    if title is not None and isinstance(title.value, Literal):
        return str(title.value.value)
    return None


def _declaration_dynamic_requests(
    program: Program,
    profile: PineVersionContext,
) -> dict[str, Any]:
    default = profile.dynamic_requests_default
    explicit: bool | None = None
    if isinstance(program.declaration, DeclarationStatement):
        arg = _arg_by_name(program.declaration.call.arguments, "dynamic_requests")
        if arg is not None:
            explicit = _literal_bool(arg.value)
    return {
        "default": default,
        "explicit": explicit,
        "enabled": default if explicit is None else explicit,
    }


def _inference_engine(
    profile: PineVersionContext,
    symbols: dict[str, Any] | None,
) -> PineInferenceEngine:
    return PineInferenceEngine(version_context=profile, symbols=symbols)


def _iter_child_nodes(node: ASTNode) -> Iterable[ASTNode]:
    return _walk_iter_child_nodes(node)


def _iter_nodes(node: ASTNode) -> Iterable[ASTNode]:
    return _walk_iter_nodes(node)


def _bound_arguments(
    name: str,
    args: list[Argument],
    *,
    profile: PineVersionContext,
    symbols: dict[str, Any] | None,
    call_span: Any | None = None,
) -> list[dict[str, Any]]:
    registry = load_catalog_readonly_view(pine_version=profile.pine_version)
    engine = PineInferenceEngine(version_context=profile, symbols=symbols, registry=registry)
    entry = registry.get("functions", {}).get(name)
    resolved_by_id: dict[int, tuple[dict[str, Any] | None, int | None, str]] = {}
    if entry:
        resolution = SignatureResolver(version_context=profile).resolve_builtin(
            name,
            entry,
            args,
            call_span or (args[0].span if args else None),
            kind="builtin",
            infer_arg_type=lambda argument: engine.infer_type(argument.value),
            infer_arg_qualifier=lambda argument: engine.infer_qualifier(argument.value),
        )
        for resolved in resolution.resolved_arguments:
            resolved_by_id[id(resolved.argument)] = (
                resolved.parameter,
                resolved.parameter_index,
                resolved.binding,
            )
    result: list[dict[str, Any]] = []
    for index, arg in enumerate(args):
        param, param_index, binding = resolved_by_id.get(id(arg), (None, None, "unknown"))
        parameter_name = param.get("name") if param else arg.name
        semantic = engine.infer_value(arg.value)
        result.append(
            {
                "position": index,
                "name": arg.name,
                "parameter": parameter_name,
                "binding": binding,
                "type": semantic.type_name,
                "qualifier": semantic.qualifier,
                "can_be_na": semantic.can_be_na,
                "is_reference": semantic.is_reference,
                "is_collection": semantic.is_collection,
                "value": _expr_summary(arg.value),
                "expr_kind": getattr(arg.value, "kind", type(arg.value).__name__),
                "span": _span_dict(arg),
            }
        )
    return result


def _parameter(
    args: list[dict[str, Any]], name: str, fallback_position: int | None = None
) -> dict[str, Any] | None:
    for arg in args:
        if arg["parameter"] == name or arg["name"] == name:
            return arg
    if fallback_position is not None and fallback_position < len(args):
        return args[fallback_position]
    return None


def _call_base_name(call: CallExpr) -> str:
    if isinstance(call.callee, GenericInstantiationExpr):
        return callee_name(call.callee.base)
    return callee_name(call.callee)


def _generic_type_args(call: CallExpr) -> list[str]:
    if isinstance(call.callee, GenericInstantiationExpr):
        return [type_ref_name(arg) for arg in call.callee.type_args]
    return []


def _collection_constructor_base(call: CallExpr) -> str | None:
    base = _call_base_name(call)
    if base in {"array.from", "array.new", "matrix.new", "map.new"}:
        return base
    if base.startswith("array.new_"):
        return base
    return None


def _collection_kind_from_type(typ: str | None) -> str | None:
    from pine2ast.semantic.facts import collection_kind_from_type

    return collection_kind_from_type(typ)


def _constructor_result_type(
    call: CallExpr,
    symbols: dict[str, Any] | None,
    *,
    profile: PineVersionContext,
) -> str:
    inferred = _inference_engine(profile, symbols).infer_type(call)
    if inferred != "unknown":
        return inferred
    base = _call_base_name(call)
    generic_args = _generic_type_args(call)
    if base in {"array.new", "array.from"} and generic_args:
        return f"array<{generic_args[0]}>"
    if base == "matrix.new" and generic_args:
        return f"matrix<{generic_args[0]}>"
    if base == "map.new" and len(generic_args) >= 2:
        return f"map<{generic_args[0]},{generic_args[1]}>"
    return inferred


def _collection_type_parts(typ: str | None) -> dict[str, Any]:
    kind = _collection_kind_from_type(typ)
    if kind is None:
        return {"kind": None, "element_type": None, "key_type": None, "value_type": None}
    if kind in {"array", "matrix"}:
        value_type = collection_value_type(typ)
        return {
            "kind": kind,
            "element_type": value_type,
            "key_type": None,
            "value_type": value_type,
        }
    return {
        "kind": kind,
        "element_type": None,
        "key_type": collection_value_type(typ, key=True),
        "value_type": collection_value_type(typ, key=False),
    }


def _iter_var_declarations(node: ASTNode) -> Iterable[VarDeclaration]:
    if isinstance(node, VarDeclaration):
        yield node
    for child in _walk_iter_child_nodes(node):
        yield from _iter_var_declarations(child)


def _enum_type_names(node: ASTNode) -> set[str]:
    result: set[str] = set()
    if isinstance(node, EnumDeclaration):
        result.add(node.name)
    for child in _walk_iter_child_nodes(node):
        result.update(_enum_type_names(child))
    return result


def _target_descriptor(
    expr: Any,
    symbols: dict[str, Any] | None,
    *,
    profile: PineVersionContext,
) -> dict[str, Any]:
    typ = _inference_engine(profile, symbols).infer_type(expr)
    return {
        "expr": _expr_summary(expr),
        "type": typ,
        **_collection_type_parts(typ),
    }


def _parameter_dict(param: Any) -> dict[str, Any]:
    return {
        "name": getattr(param, "name", None),
        "type": (
            type_ref_name(getattr(param, "type_ref", None))
            if getattr(param, "type_ref", None) is not None
            else None
        ),
        "qualifier": getattr(param, "explicit_qualifier", None),
        "has_default": getattr(param, "default_value", None) is not None,
        "default": (
            _expr_summary(getattr(param, "default_value", None))
            if getattr(param, "default_value", None) is not None
            else None
        ),
        "span": _span_dict(param),
    }


def _field_dict(field: Any, engine: PineInferenceEngine) -> dict[str, Any]:
    default_value = getattr(field, "default_value", None)
    default_semantic = engine.infer_value(default_value) if default_value is not None else None
    return {
        "name": getattr(field, "name", None),
        "type": (
            type_ref_name(getattr(field, "type_ref", None))
            if getattr(field, "type_ref", None) is not None
            else None
        ),
        "has_default": default_value is not None,
        "default": _expr_summary(default_value) if default_value is not None else None,
        "default_type": default_semantic.type_name if default_semantic else None,
        "default_qualifier": default_semantic.qualifier if default_semantic else None,
        "span": _span_dict(field),
    }


def _declared_arg_bindings(
    params: list[Any],
    args: list[Argument],
    *,
    engine: PineInferenceEngine,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    positional_count = 0
    by_name = {getattr(param, "name", None): param for param in params}
    for position, arg in enumerate(args):
        binding = "named" if arg.name else "positional"
        param = None
        parameter_index = None
        if arg.name:
            param = by_name.get(arg.name)
            if param is not None:
                parameter_index = params.index(param)
        else:
            if positional_count < len(params):
                param = params[positional_count]
                parameter_index = positional_count
            positional_count += 1
        expected = (
            type_ref_name(getattr(param, "type_ref", None))
            if param is not None and getattr(param, "type_ref", None) is not None
            else None
        )
        semantic = engine.infer_value(arg.value)
        result.append(
            {
                "position": position,
                "name": arg.name,
                "parameter": getattr(param, "name", None) if param is not None else arg.name,
                "parameter_index": parameter_index,
                "binding": binding if param is not None else "unknown",
                "expected_type": expected,
                "type": semantic.type_name,
                "qualifier": semantic.qualifier,
                "can_be_na": semantic.can_be_na,
                "type_ok": is_assignable_type(expected, semantic.type_name),
                "value": _expr_summary(arg.value),
                "expr_kind": getattr(arg.value, "kind", type(arg.value).__name__),
                "span": _span_dict(arg),
            }
        )
    return result


def _literal_int_value(expr: Any) -> int | None:
    if isinstance(expr, Literal) and expr.literal_type == "int":
        try:
            return int(str(expr.value))
        except (TypeError, ValueError):
            return None
    if getattr(expr, "kind", None) == "UnaryExpr" and getattr(expr, "op", None) == "-":
        inner = _literal_int_value(getattr(expr, "operand", None))
        return -inner if inner is not None else None
    return None


def _for_range_static_iterations(node: ForRangeStructure) -> int | None:
    start = _literal_int_value(node.start)
    end = _literal_int_value(node.end)
    step = _literal_int_value(node.step) if node.step is not None else 1
    if start is None or end is None or step is None or step == 0:
        return None
    distance = end - start
    if distance == 0:
        return 1
    if (distance > 0 and step < 0) or (distance < 0 and step > 0):
        return 0
    return abs(distance) // abs(step) + 1


def _expr_descriptor(expr: Any, engine: PineInferenceEngine) -> dict[str, Any]:
    semantic = engine.infer_value(expr)
    return {
        "expr": _expr_summary(expr),
        "expr_kind": getattr(expr, "kind", type(expr).__name__),
        "type": semantic.type_name,
        "qualifier": semantic.qualifier,
        "can_be_na": semantic.can_be_na,
        "span": _span_dict(expr),
    }


def _build_type_maps(
    program: Program,
) -> tuple[
    dict[str, TypeDeclaration],
    dict[str, EnumDeclaration],
    dict[str, FunctionDeclaration],
    dict[str, list[MethodDeclaration]],
]:
    types: dict[str, TypeDeclaration] = {}
    enums: dict[str, EnumDeclaration] = {}
    functions: dict[str, FunctionDeclaration] = {}
    methods: dict[str, list[MethodDeclaration]] = {}
    for node in _iter_nodes(program):
        if isinstance(node, TypeDeclaration):
            types[node.name] = node
        elif isinstance(node, EnumDeclaration):
            enums[node.name] = node
        elif isinstance(node, FunctionDeclaration):
            functions[node.name] = node
        elif isinstance(node, MethodDeclaration):
            methods.setdefault(node.name, []).append(node)
    return types, enums, functions, methods


def _constructor_assignees(program: Program) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for declaration in _iter_var_declarations(program):
        initializer = declaration.initializer
        if isinstance(initializer, CallExpr):
            result.setdefault(id(initializer), []).append(
                {
                    "name": declaration.name,
                    "declared_type": (
                        type_ref_name(declaration.type_ref)
                        if declaration.type_ref is not None
                        else None
                    ),
                    "span": _span_dict(declaration),
                }
            )
    return result


__all__ = [
    "Context",
    "_REQUEST_CONTEXT_PARAMETER_NAMES",
    "_ORDER_CALLS",
    "_EXIT_CALLS",
    "_MANAGEMENT_CALLS",
    "_RISK_CALL_PREFIX",
    "_literal_bool",
    "_arg_by_name",
    "_declaration_title",
    "_declaration_dynamic_requests",
    "_inference_engine",
    "_iter_child_nodes",
    "_iter_nodes",
    "_iter_calls_with_context",
    "_span_dict",
    "_expr_summary",
    "_bound_arguments",
    "_parameter",
    "_call_base_name",
    "_generic_type_args",
    "_collection_constructor_base",
    "_collection_kind_from_type",
    "_constructor_result_type",
    "_collection_type_parts",
    "_iter_var_declarations",
    "_enum_type_names",
    "_target_descriptor",
    "_parameter_dict",
    "_field_dict",
    "_declared_arg_bindings",
    "_literal_int_value",
    "_for_range_static_iterations",
    "_expr_descriptor",
    "_build_type_maps",
    "_constructor_assignees",
]
