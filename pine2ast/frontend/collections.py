from __future__ import annotations

# ruff: noqa: F403,F405

from typing import Any

from pine2ast.ast.nodes import Argument, CallExpr, MemberAccessExpr, Program
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.semantic.collection_signatures import (
    collection_return_type as _collection_return_type,
    resolve_collection_call as _resolve_collection_call,
)
from pine2ast.semantic.facts import (
    bind_arguments_to_specs,
    collection_method_function_form,
    collection_method_parameter_specs,
    expr_summary as _expr_summary,
    iter_calls_with_context as _iter_calls_with_context,
    span_dict as _span_dict,
)
from pine2ast.semantic.inference import PineInferenceEngine
from pine2ast.semantic.type_helpers import is_assignable_type, is_valid_map_key_type, type_ref_name
from pine2ast.frontend.helpers import *

_COLLECTION_LIMITS = {
    "array_elements": 100_000,
    "matrix_elements": 100_000,
    "map_pairs": 50_000,
    "map_elements": 100_000,
    "array_max_elements": 100_000,
    "matrix_max_elements": 100_000,
    "map_max_pairs": 50_000,
    "map_max_elements": 100_000,
}


def _collection_argument_rows_from_resolution(
    resolution: Any, engine: PineInferenceEngine
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, binding in enumerate(resolution.bindings):
        arg = binding.argument
        parameter = binding.parameter
        semantic = engine.infer_value(arg.value)
        expected_type = binding.expected_type
        parameter_name = parameter.name if parameter is not None else None
        rows.append(
            {
                "position": index,
                "name": arg.name,
                "parameter": parameter_name,
                "field_or_parameter": parameter_name,
                "binding": binding.binding,
                "expected_type": expected_type,
                "type": semantic.type_name,
                "qualifier": semantic.qualifier,
                "can_be_na": semantic.can_be_na,
                "type_ok": is_assignable_type(expected_type, semantic.type_name),
                "value": _expr_summary(arg.value),
                "span": _span_dict(arg),
            }
        )
    return rows


def _collection_binding_for_role(resolution: Any, role: str) -> Any | None:
    for binding in resolution.bindings:
        parameter = binding.parameter
        if parameter is not None and parameter.role == role:
            return binding
    return None


def _collection_descriptor_from_resolution(
    call: CallExpr,
    resolution: Any,
    *,
    symbols: dict[str, Any] | None,
    context: Context,
    profile: PineLanguageProfile,
    include_result: bool,
) -> dict[str, Any] | None:
    engine = _inference_engine(profile, symbols)
    if resolution.form == "method" and isinstance(call.callee, MemberAccessExpr):
        target_expr = call.callee.object
    elif resolution.form == "function" and call.arguments:
        target_expr = call.arguments[0].value
    else:
        return None
    target = _target_descriptor(target_expr, symbols, profile=profile)
    method_specs = [spec.to_dict() for spec in resolution.parameters]
    item: dict[str, Any] = {
        "operation": resolution.operation,
        "function_form": resolution.function_form,
        "span": _span_dict(call),
        "context": list(context),
        "local_scope": bool(context),
        "target": target,
        "method_parameters": method_specs,
        "arguments": _collection_argument_rows_from_resolution(resolution, engine),
    }
    if include_result:
        item["result_type"] = resolution.return_type or engine.infer_type(call)
        item["result_qualifier"] = engine.infer_qualifier(call)

    role_map = {
        "key": "key",
        "index": "index",
        "row": "row",
        "column": "column",
        "value": "value",
    }
    for role, output_name in role_map.items():
        binding = _collection_binding_for_role(resolution, role)
        if binding is None:
            continue
        if output_name in {"index", "row", "column"}:
            item[output_name] = _expr_descriptor(binding.argument.value, engine)
            continue
        semantic = engine.infer_value(binding.argument.value)
        item[output_name] = {
            "type": semantic.type_name,
            "qualifier": semantic.qualifier,
            "expected_type": binding.expected_type,
            "type_ok": is_assignable_type(binding.expected_type, semantic.type_name),
            "value": _expr_summary(binding.argument.value),
            "span": _span_dict(binding.argument),
        }
    return item


def _collection_mutation_descriptor(
    call: CallExpr,
    *,
    symbols: dict[str, Any] | None,
    context: Context,
    profile: PineLanguageProfile,
) -> dict[str, Any] | None:
    name = _call_base_name(call)
    engine = _inference_engine(profile, symbols)
    resolution = _resolve_collection_call(call, engine=engine)
    if resolution is not None and resolution.is_mutation:
        return _collection_descriptor_from_resolution(
            call,
            resolution,
            symbols=symbols,
            context=context,
            profile=profile,
            include_result=False,
        )
    args = call.arguments
    operation: str | None = None
    binding_name: str | None = None
    target_expr = None
    key_arg: Argument | None = None
    value_arg: Argument | None = None
    index_arg: Argument | None = None
    row_arg: Argument | None = None
    column_arg: Argument | None = None

    if name in {"array.push", "array.unshift"} and len(args) >= 2:
        operation = name.split(".", 1)[1]
        binding_name = name
        target_expr = args[0].value
        value_arg = args[1]
    elif name == "array.set" and len(args) >= 3:
        operation = "set"
        binding_name = name
        target_expr = args[0].value
        index_arg = args[1]
        value_arg = args[2]
    elif name == "matrix.set" and len(args) >= 4:
        operation = "set"
        binding_name = name
        target_expr = args[0].value
        row_arg = args[1]
        column_arg = args[2]
        value_arg = args[3]
    elif name == "map.put" and len(args) >= 3:
        operation = name.split(".", 1)[1]
        binding_name = name
        target_expr = args[0].value
        key_arg = args[1]
        value_arg = args[2]
    elif name in {"map.remove"} and len(args) >= 2:
        operation = "remove"
        binding_name = name
        target_expr = args[0].value
        key_arg = args[1]
    elif name in {"array.clear", "map.clear", "matrix.clear"} and args:
        operation = "clear"
        binding_name = name
        target_expr = args[0].value
    elif isinstance(call.callee, MemberAccessExpr):
        member = call.callee.member
        receiver_type = engine.infer_type(call.callee.object)
        collection_kind = _collection_kind_from_type(receiver_type)
        if collection_kind == "array" and member in {"push", "unshift"} and args:
            operation = member
            target_expr = call.callee.object
            value_arg = args[0]
        elif collection_kind == "array" and member == "set" and len(args) >= 2:
            operation = "set"
            target_expr = call.callee.object
            index_arg = args[0]
            value_arg = args[1]
        elif collection_kind == "matrix" and member == "set" and len(args) >= 3:
            operation = "set"
            target_expr = call.callee.object
            row_arg = args[0]
            column_arg = args[1]
            value_arg = args[2]
        elif collection_kind == "map" and member == "put" and len(args) >= 2:
            operation = "put"
            target_expr = call.callee.object
            key_arg = args[0]
            value_arg = args[1]
        elif collection_kind == "map" and member == "remove" and args:
            operation = "remove"
            target_expr = call.callee.object
            key_arg = args[0]
        elif collection_kind in {"array", "map", "matrix"} and member == "clear":
            operation = "clear"
            target_expr = call.callee.object

    if operation is None or target_expr is None:
        return None

    target = _target_descriptor(target_expr, symbols, profile=profile)
    function_form = binding_name or collection_method_function_form(target.get("type"), operation)
    if binding_name is None and function_form is not None:
        method_specs = collection_method_parameter_specs(target.get("type"), operation)
        bound_arguments = bind_arguments_to_specs(args, method_specs, engine)
    else:
        method_specs = []
        bound_arguments = _bound_arguments(
            binding_name or operation, args, profile=profile, symbols=symbols, call_span=call.span
        )
    item: dict[str, Any] = {
        "operation": operation,
        "function_form": function_form,
        "span": _span_dict(call),
        "context": list(context),
        "local_scope": bool(context),
        "target": target,
        "method_parameters": method_specs,
        "arguments": bound_arguments,
    }
    if key_arg is not None:
        key_value = engine.infer_value(key_arg.value)
        expected_key_type = target.get("key_type")
        item["key"] = {
            "type": key_value.type_name,
            "qualifier": key_value.qualifier,
            "expected_type": expected_key_type,
            "type_ok": is_assignable_type(expected_key_type, key_value.type_name),
            "value": _expr_summary(key_arg.value),
            "span": _span_dict(key_arg),
        }
    if index_arg is not None:
        item["index"] = _expr_descriptor(index_arg.value, engine)
    if row_arg is not None:
        item["row"] = _expr_descriptor(row_arg.value, engine)
    if column_arg is not None:
        item["column"] = _expr_descriptor(column_arg.value, engine)
    if value_arg is not None:
        semantic_value = engine.infer_value(value_arg.value)
        expected_value_type = target.get("value_type") or target.get("element_type")
        item["value"] = {
            "type": semantic_value.type_name,
            "qualifier": semantic_value.qualifier,
            "expected_type": expected_value_type,
            "type_ok": is_assignable_type(expected_value_type, semantic_value.type_name),
            "value": _expr_summary(value_arg.value),
            "span": _span_dict(value_arg),
        }
    return item


def extract_collection_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineLanguageProfile | None = None,
) -> dict[str, Any]:
    profile = profile or pine_language_profile(program.version or program.language_version)
    symbols = getattr(semantic_model, "symbols", None)
    constructor_assignees: dict[int, list[dict[str, Any]]] = {}
    declarations: list[dict[str, Any]] = []
    enum_types = _enum_type_names(program)

    for declaration in _iter_var_declarations(program):
        explicit_type = (
            type_ref_name(declaration.type_ref) if declaration.type_ref is not None else None
        )
        inferred_type = getattr(symbols.get(declaration.name), "type", None) if symbols else None
        initializer = declaration.initializer
        if explicit_type and _collection_kind_from_type(explicit_type):
            parts = _collection_type_parts(explicit_type)
            map_key_valid = True
            if parts["kind"] == "map":
                map_key_valid = is_valid_map_key_type(parts["key_type"], enum_types=enum_types)
            declarations.append(
                {
                    "name": declaration.name,
                    "span": _span_dict(declaration),
                    "mode": declaration.mode,
                    "explicit_qualifier": declaration.explicit_qualifier,
                    "explicit_type": explicit_type,
                    "inferred_type": inferred_type,
                    "map_key_valid": map_key_valid,
                    **parts,
                }
            )
        if isinstance(initializer, CallExpr) and _collection_constructor_base(initializer):
            constructor_assignees.setdefault(id(initializer), []).append(
                {
                    "name": declaration.name,
                    "declared_type": explicit_type,
                    "symbol_type": inferred_type,
                    "span": _span_dict(declaration),
                }
            )

    constructors: list[dict[str, Any]] = []
    mutations: list[dict[str, Any]] = []
    accesses: list[dict[str, Any]] = []
    for call, context in _iter_calls_with_context(program):
        constructor_base = _collection_constructor_base(call)
        if constructor_base:
            result_type = _constructor_result_type(call, symbols, profile=profile)
            parts = _collection_type_parts(result_type)
            generic_args = _generic_type_args(call)
            map_key_valid = True
            if parts["kind"] == "map":
                map_key_valid = is_valid_map_key_type(parts["key_type"], enum_types=enum_types)
            constructors.append(
                {
                    **parts,
                    "kind": constructor_base,
                    "collection_kind": parts.get("kind"),
                    "span": _span_dict(call),
                    "context": list(context),
                    "local_scope": bool(context),
                    "generic_args": generic_args,
                    "result_type": result_type,
                    "map_key_valid": map_key_valid,
                    "assigned_to": constructor_assignees.get(id(call), []),
                    "arguments": _bound_arguments(
                        _call_base_name(call),
                        call.arguments,
                        profile=profile,
                        symbols=symbols,
                        call_span=call.span,
                    ),
                }
            )
        mutation = _collection_mutation_descriptor(
            call, symbols=symbols, context=context, profile=profile
        )
        if mutation is not None:
            mutations.append(mutation)
        access = _collection_access_descriptor(
            call, symbols=symbols, context=context, profile=profile
        )
        if access is not None:
            accesses.append(access)

    return {
        "contract": "openpine.collections.v1",
        "profile": f"pine_v{profile.version}",
        "limits": dict(_COLLECTION_LIMITS),
        "declarations": declarations,
        "constructors": constructors,
        "mutations": mutations,
        "accesses": accesses,
    }


def _collection_access_descriptor(
    call: CallExpr,
    *,
    symbols: dict[str, Any] | None,
    context: Context,
    profile: PineLanguageProfile,
) -> dict[str, Any] | None:
    name = _call_base_name(call)
    engine = _inference_engine(profile, symbols)
    resolution = _resolve_collection_call(call, engine=engine)
    if resolution is not None and resolution.is_access:
        return _collection_descriptor_from_resolution(
            call, resolution, symbols=symbols, context=context, profile=profile, include_result=True
        )
    args = call.arguments
    operation: str | None = None
    target_expr = None
    key_arg: Argument | None = None
    index_arg: Argument | None = None
    row_arg: Argument | None = None
    column_arg: Argument | None = None
    value_arg: Argument | None = None

    if (
        name
        in {
            "array.get",
            "array.first",
            "array.last",
            "array.size",
            "array.copy",
            "array.includes",
            "array.indexof",
        }
        and args
    ):
        operation = name.split(".", 1)[1]
        target_expr = args[0].value
        if name == "array.get" and len(args) >= 2:
            index_arg = args[1]
        elif name in {"array.includes", "array.indexof"} and len(args) >= 2:
            value_arg = args[1]
    elif name in {"matrix.get"} and len(args) >= 3:
        operation = "get"
        target_expr = args[0].value
        row_arg = args[1]
        column_arg = args[2]
    elif name in {"matrix.rows", "matrix.columns", "matrix.copy"} and args:
        operation = name.split(".", 1)[1]
        target_expr = args[0].value
    elif name in {"map.get", "map.contains", "map.remove"} and len(args) >= 2:
        operation = name.split(".", 1)[1]
        target_expr = args[0].value
        key_arg = args[1]
    elif name in {"map.keys", "map.values", "map.size", "map.copy"} and args:
        operation = name.split(".", 1)[1]
        target_expr = args[0].value
    elif isinstance(call.callee, MemberAccessExpr):
        member = call.callee.member
        receiver_type = engine.infer_type(call.callee.object)
        collection_kind = _collection_kind_from_type(receiver_type)
        if collection_kind == "array" and member in {
            "get",
            "first",
            "last",
            "size",
            "copy",
            "includes",
            "indexof",
        }:
            operation = member
            target_expr = call.callee.object
            if member == "get" and args:
                index_arg = args[0]
            elif member in {"includes", "indexof"} and args:
                value_arg = args[0]
        elif collection_kind == "matrix" and member == "get" and len(args) >= 2:
            operation = "get"
            target_expr = call.callee.object
            row_arg = args[0]
            column_arg = args[1]
        elif collection_kind == "matrix" and member in {"rows", "columns", "copy"}:
            operation = member
            target_expr = call.callee.object
        elif collection_kind == "map" and member in {"get", "contains", "remove"} and args:
            operation = member
            target_expr = call.callee.object
            key_arg = args[0]
        elif collection_kind == "map" and member in {"keys", "values", "size", "copy"}:
            operation = member
            target_expr = call.callee.object

    if operation is None or target_expr is None:
        return None
    target = _target_descriptor(target_expr, symbols, profile=profile)
    if (
        isinstance(call.callee, MemberAccessExpr)
        and collection_method_function_form(target.get("type"), operation) is not None
    ):
        function_form = collection_method_function_form(target.get("type"), operation)
    else:
        function_form = (
            name if "." in name else collection_method_function_form(target.get("type"), operation)
        )
    if isinstance(call.callee, MemberAccessExpr) and function_form is not None:
        method_specs = collection_method_parameter_specs(target.get("type"), operation)
        bound_arguments = bind_arguments_to_specs(args, method_specs, engine)
    else:
        method_specs = []
        bound_arguments = _bound_arguments(
            name, args, profile=profile, symbols=symbols, call_span=call.span
        )
    inferred_result_type = engine.infer_type(call)
    if inferred_result_type == "unknown":
        inferred_result_type = (
            _collection_return_type(target.get("type"), operation) or inferred_result_type
        )
    item: dict[str, Any] = {
        "operation": operation,
        "function_form": function_form,
        "span": _span_dict(call),
        "context": list(context),
        "local_scope": bool(context),
        "target": target,
        "result_type": inferred_result_type,
        "result_qualifier": engine.infer_qualifier(call),
        "method_parameters": method_specs,
        "arguments": bound_arguments,
    }
    if key_arg is not None:
        key_value = engine.infer_value(key_arg.value)
        expected_key_type = target.get("key_type")
        item["key"] = {
            "type": key_value.type_name,
            "qualifier": key_value.qualifier,
            "expected_type": expected_key_type,
            "type_ok": is_assignable_type(expected_key_type, key_value.type_name),
            "value": _expr_summary(key_arg.value),
            "span": _span_dict(key_arg),
        }
    if index_arg is not None:
        item["index"] = _expr_descriptor(index_arg.value, engine)
    if row_arg is not None:
        item["row"] = _expr_descriptor(row_arg.value, engine)
    if column_arg is not None:
        item["column"] = _expr_descriptor(column_arg.value, engine)
    if value_arg is not None:
        value = engine.infer_value(value_arg.value)
        expected_value_type = target.get("value_type") or target.get("element_type")
        item["value"] = {
            "type": value.type_name,
            "qualifier": value.qualifier,
            "expected_type": expected_value_type,
            "type_ok": is_assignable_type(expected_value_type, value.type_name),
            "value": _expr_summary(value_arg.value),
            "span": _span_dict(value_arg),
        }
    return item
