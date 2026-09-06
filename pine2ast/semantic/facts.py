"""Semantic fact extraction for OpenPine-facing contracts.

This module is intentionally read-only: it consumes the parsed AST plus an
optional SemanticModel and produces JSON-safe facts. Keeping these facts outside
``SemanticAnalyzer`` gives Release 4.0 a safe migration seam for UDT/enum/method and
collection-contract work without changing the AST schema.
"""

from __future__ import annotations

from typing import Any, Iterable

from pine2ast.ast.base import ASTNode
from pine2ast.contract_ids import SECTION_CONTRACTS

from pine2ast.ast.nodes import (
    Argument,
    Block,
    CallExpr,
    ConditionalExpr,
    EnumDeclaration,
    ForInStructure,
    ForRangeStructure,
    FunctionDeclaration,
    GenericInstantiationExpr,
    Identifier,
    IfStructure,
    OnceStructure,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    Program,
    SwitchStructure,
    TupleExpr,
    TypeDeclaration,
    WhileStructure,
)
from pine2ast.ast.walk import iter_child_nodes, iter_nodes
from pine2ast.versioning import PineVersionContext
from pine2ast.semantic.inference import PineInferenceEngine
from pine2ast.semantic.collection_signatures import (
    collection_return_type as _collection_signature_return_type,
    is_collection_method as _is_signature_collection_method,
    method_parameter_specs as _collection_method_parameter_specs,
)
from pine2ast.semantic.type_helpers import generic_type_parts, is_assignable_type, type_ref_name
from pine2ast.semantic.type_infer import callee_name

Context = tuple[str, ...]

_VALUE_COLLECTION_METHODS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "array": {
        "get": [("index", "int")],
        "set": [("index", "int"), ("value", "T")],
        "push": [("value", "T")],
        "unshift": [("value", "T")],
        "includes": [("value", "T")],
        "indexof": [("value", "T")],
        "pop": [],
        "shift": [],
        "first": [],
        "last": [],
        "size": [],
        "clear": [],
        "copy": [],
    },
    "matrix": {
        "get": [("row", "int"), ("column", "int")],
        "set": [("row", "int"), ("column", "int"), ("value", "T")],
        "add_row": [("row", "int"), ("array_id", "array<T>")],
        "add_col": [("column", "int"), ("array_id", "array<T>")],
        "remove_row": [("row", "int")],
        "remove_col": [("column", "int")],
        "rows": [],
        "columns": [],
        "copy": [],
    },
    "map": {
        "put": [("key", "K"), ("value", "V")],
        "get": [("key", "K")],
        "remove": [("key", "K")],
        "contains": [("key", "K")],
        "keys": [],
        "values": [],
        "size": [],
        "clear": [],
        "copy": [],
    },
}

_COLLECTION_MUTATION_MEMBERS = {
    "array": {"push", "unshift", "set", "pop", "shift", "clear"},
    "matrix": {"set", "add_row", "add_col", "remove_row", "remove_col"},
    "map": {"put", "remove", "clear"},
}


def span_dict(node_or_span: Any) -> dict[str, int] | None:
    span = getattr(node_or_span, "span", node_or_span)
    return span.to_dict() if hasattr(span, "to_dict") else None


def expr_summary(expr: Any) -> Any:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, MemberAccessExpr):
        return callee_name(expr)
    if isinstance(expr, GenericInstantiationExpr):
        return callee_name(expr)
    if isinstance(expr, TupleExpr):
        return [expr_summary(item) for item in expr.elements]
    if isinstance(expr, CallExpr):
        return {"call": callee_name(expr.callee), "arg_count": len(expr.arguments)}
    if isinstance(expr, ConditionalExpr):
        return {"kind": expr.kind, "condition": expr_summary(expr.condition)}
    return {"kind": getattr(expr, "kind", type(expr).__name__)}


def node_context_marker(node: ASTNode) -> str | None:
    if isinstance(node, FunctionDeclaration):
        return "function"
    if isinstance(node, MethodDeclaration):
        return "method"
    if isinstance(node, OnceStructure):
        return "once"
    if isinstance(node, IfStructure):
        return "if"
    if isinstance(node, SwitchStructure):
        return "switch"
    if isinstance(node, ForRangeStructure):
        return "for_range"
    if isinstance(node, ForInStructure):
        return "for_in"
    if isinstance(node, WhileStructure):
        return "while"
    return None


def iter_calls_with_context(
    node: ASTNode, context: Context = ()
) -> Iterable[tuple[CallExpr, Context]]:
    if isinstance(node, CallExpr):
        yield node, context
    marker = node_context_marker(node)
    child_context = context + ((marker,) if marker else ())
    if isinstance(node, Block):
        child_context = context
    for child in iter_child_nodes(node):
        yield from iter_calls_with_context(child, child_context)


def collection_kind_from_type(type_name: str | None) -> str | None:
    base, _ = generic_type_parts(type_name)
    return base if base in {"array", "matrix", "map"} else None


def collection_method_function_form(receiver_type: str | None, method: str) -> str | None:
    kind = collection_kind_from_type(receiver_type)
    if kind and _is_signature_collection_method(receiver_type, method):
        return f"{kind}.{method}"
    return None


def _type_parameters_for_collection(type_name: str | None) -> dict[str, str]:
    base, args = generic_type_parts(type_name)
    if base in {"array", "matrix"} and args:
        return {"T": args[0]}
    if base == "map" and len(args) >= 2:
        return {"K": args[0], "V": args[1]}
    return {"T": "unknown", "K": "unknown", "V": "unknown"}


def _specialize_param_type(template: str | None, replacements: dict[str, str]) -> str | None:
    if template is None:
        return None
    result = template
    for name, value in replacements.items():
        result = result.replace(name, value)
    return result


def collection_method_parameter_specs(
    receiver_type: str | None, method: str
) -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in _collection_method_parameter_specs(receiver_type, method)]


def _collection_return_type(receiver_type: str | None, method: str) -> str | None:
    return _collection_signature_return_type(receiver_type, method)


def _symbols(semantic_model: Any | None) -> dict[str, Any] | None:
    return getattr(semantic_model, "symbols", None)


def _symbol_kind(symbol: Any | None) -> str | None:
    kind = getattr(symbol, "kind", None)
    return getattr(kind, "value", kind)


def _engine(profile: PineVersionContext, semantic_model: Any | None) -> PineInferenceEngine:
    return PineInferenceEngine(version_context=profile, symbols=_symbols(semantic_model))


def _literal_bool(expr: Any) -> bool | None:
    if isinstance(expr, Literal) and expr.literal_type == "bool":
        return bool(expr.value)
    return None


def _declared_type_names(program: Program) -> set[str]:
    return {node.name for node in iter_nodes(program) if isinstance(node, TypeDeclaration)}


def _declared_enum_names(program: Program) -> set[str]:
    return {node.name for node in iter_nodes(program) if isinstance(node, EnumDeclaration)}


def _udt_field_map(program: Program) -> dict[str, list[Any]]:
    return {
        node.name: list(node.fields)
        for node in iter_nodes(program)
        if isinstance(node, TypeDeclaration)
    }


def _method_declarations(program: Program) -> list[MethodDeclaration]:
    return [node for node in iter_nodes(program) if isinstance(node, MethodDeclaration)]


def _parameter_facts(
    parameters: Iterable[Any], engine: PineInferenceEngine
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, param in enumerate(parameters):
        default = getattr(param, "default_value", None)
        default_value = engine.infer_value(default) if default is not None else None
        rows.append(
            {
                "position": index,
                "name": getattr(param, "name", None),
                "type": (
                    type_ref_name(getattr(param, "type_ref", None))
                    if getattr(param, "type_ref", None) is not None
                    else None
                ),
                "qualifier": getattr(param, "explicit_qualifier", None),
                "required": default is None,
                "default": expr_summary(default) if default is not None else None,
                "default_type": default_value.type_name if default_value else None,
                "default_qualifier": default_value.qualifier if default_value else None,
                "span": span_dict(param),
            }
        )
    return rows


def _argument_fact(
    arg: Argument,
    *,
    position: int,
    field_or_param: str | None,
    expected_type: str | None,
    binding: str,
    engine: PineInferenceEngine,
) -> dict[str, Any]:
    semantic = engine.infer_value(arg.value)
    return {
        "position": position,
        "name": arg.name,
        "field_or_parameter": field_or_param,
        "binding": binding,
        "expected_type": expected_type,
        "type": semantic.type_name,
        "qualifier": semantic.qualifier,
        "can_be_na": semantic.can_be_na,
        "type_ok": is_assignable_type(expected_type, semantic.type_name),
        "value": expr_summary(arg.value),
        "span": span_dict(arg),
    }


def _receiver_matches(actual: str | None, expected: str | None) -> bool:
    if not expected or actual in {None, "unknown"}:
        return True
    if actual == expected:
        return True
    expected_base, _ = generic_type_parts(expected)
    actual_base, _ = generic_type_parts(actual)
    return bool(expected_base and expected_base == actual_base and expected == expected_base)


def _udt_constructor_fact(
    call: CallExpr,
    *,
    context: Context,
    fields_by_type: dict[str, list[Any]],
    profile: PineVersionContext,
    semantic_model: Any | None,
) -> dict[str, Any] | None:
    if not isinstance(call.callee, MemberAccessExpr) or call.callee.member != "new":
        return None
    if not isinstance(call.callee.object, Identifier):
        return None
    type_name = call.callee.object.name
    fields = fields_by_type.get(type_name)
    if fields is None:
        return None
    engine = _engine(profile, semantic_model)
    field_names = [field.name for field in fields]
    field_by_name = {field.name: field for field in fields}
    positional = [arg for arg in call.arguments if arg.name is None]
    supplied: set[str] = set(field_names[: len(positional)])
    unknown_fields: list[str] = []
    duplicate_fields: list[str] = []
    seen_named: set[str] = set()
    rows: list[dict[str, Any]] = []
    for index, arg in enumerate(call.arguments):
        if arg.name is None:
            field = fields[index] if index < len(fields) else None
            field_name = field.name if field is not None else None
            expected = type_ref_name(field.type_ref) if field is not None else None
            binding = "positional" if field is not None else "extra_positional"
        else:
            field = field_by_name.get(arg.name)
            field_name = arg.name
            expected = type_ref_name(field.type_ref) if field is not None else None
            binding = "named" if field is not None else "unknown_named"
            if field is None:
                unknown_fields.append(arg.name)
            elif arg.name in seen_named or arg.name in supplied:
                duplicate_fields.append(arg.name)
            if field is not None:
                supplied.add(arg.name)
            seen_named.add(arg.name)
        rows.append(
            _argument_fact(
                arg,
                position=index,
                field_or_param=field_name,
                expected_type=expected,
                binding=binding,
                engine=engine,
            )
        )
    required = [field.name for field in fields if getattr(field, "default_value", None) is None]
    return {
        "type": type_name,
        "kind": f"{type_name}.new",
        "result_type": type_name,
        "span": span_dict(call),
        "context": list(context),
        "local_scope": bool(context),
        "field_count": len(fields),
        "arguments": rows,
        "missing_required_fields": [name for name in required if name not in supplied],
        "unknown_fields": unknown_fields,
        "duplicate_fields": duplicate_fields,
        "too_many_positional": len(positional) > len(fields),
    }


def extract_type_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineVersionContext | None = None,
) -> dict[str, Any]:
    actual_profile = profile or program.version_context
    engine = _engine(actual_profile, semantic_model)
    symbols = _symbols(semantic_model) or {}
    fields_by_type = _udt_field_map(program)
    enum_names = _declared_enum_names(program)
    udts: list[dict[str, Any]] = []
    enums: list[dict[str, Any]] = []
    field_accesses: list[dict[str, Any]] = []
    enum_member_uses: list[dict[str, Any]] = []
    constructors: list[dict[str, Any]] = []

    for node in iter_nodes(program):
        if isinstance(node, TypeDeclaration):
            field_rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            duplicate_fields: list[str] = []
            for index, field in enumerate(node.fields):
                field_type = type_ref_name(field.type_ref)
                default = field.default_value
                default_value = engine.infer_value(default) if default is not None else None
                if field.name in seen:
                    duplicate_fields.append(field.name)
                seen.add(field.name)
                field_rows.append(
                    {
                        "position": index,
                        "name": field.name,
                        "type": field_type,
                        "has_default": default is not None,
                        "default": expr_summary(default) if default is not None else None,
                        "default_type": default_value.type_name if default_value else None,
                        "default_qualifier": default_value.qualifier if default_value else None,
                        "default_type_ok": (
                            True
                            if default_value is None
                            else is_assignable_type(field_type, default_value.type_name)
                        ),
                        "span": span_dict(field),
                    }
                )
            udts.append(
                {
                    "name": node.name,
                    "span": span_dict(node),
                    "is_exported": node.is_exported,
                    "field_count": len(node.fields),
                    "duplicate_fields": duplicate_fields,
                    "fields": field_rows,
                }
            )
        elif isinstance(node, EnumDeclaration):
            members = []
            seen_members: set[str] = set()
            duplicate_members: list[str] = []
            for index, member in enumerate(node.members):
                if member.name in seen_members:
                    duplicate_members.append(member.name)
                seen_members.add(member.name)
                members.append(
                    {
                        "position": index,
                        "name": member.name,
                        "qualified_name": f"{node.name}.{member.name}",
                        "title": member.title,
                        "type": node.name,
                        "qualifier": "const",
                        "span": span_dict(member),
                    }
                )
            enums.append(
                {
                    "name": node.name,
                    "span": span_dict(node),
                    "is_exported": node.is_exported,
                    "member_count": len(node.members),
                    "duplicate_members": duplicate_members,
                    "members": members,
                }
            )
        elif isinstance(node, MemberAccessExpr):
            owner_name = node.object.name if isinstance(node.object, Identifier) else None
            if owner_name in enum_names:
                enum_member_uses.append(
                    {
                        "enum": owner_name,
                        "member": node.member,
                        "qualified_name": f"{owner_name}.{node.member}",
                        "known": f"{owner_name}.{node.member}" in symbols,
                        "type": owner_name,
                        "qualifier": "const",
                        "span": span_dict(node),
                    }
                )
                continue
            owner_type = engine.infer_type(node.object)
            if owner_type in fields_by_type and node.member != "new":
                field_match = next(
                    (item for item in fields_by_type[owner_type] if item.name == node.member), None
                )
                field_accesses.append(
                    {
                        "path": callee_name(node),
                        "owner_type": owner_type,
                        "field": node.member,
                        "known": field_match is not None,
                        "type": (
                            type_ref_name(field_match.type_ref) if field_match is not None else None
                        ),
                        "qualifier": engine.infer_qualifier(node),
                        "span": span_dict(node),
                    }
                )

    for call, context in iter_calls_with_context(program):
        constructor = _udt_constructor_fact(
            call,
            context=context,
            fields_by_type=fields_by_type,
            profile=actual_profile,
            semantic_model=semantic_model,
        )
        if constructor is not None:
            constructors.append(constructor)

    return {
        "contract": SECTION_CONTRACTS["types"],
        "profile": f"pine_v{actual_profile.pine_version}",
        "udts": udts,
        "constructors": constructors,
        "field_accesses": field_accesses,
        "enums": enums,
        "enum_member_uses": enum_member_uses,
    }


def _method_return_type(method: MethodDeclaration, semantic_model: Any | None) -> str | None:
    symbols = _symbols(semantic_model) or {}
    sym = symbols.get(method.name)
    typ = getattr(sym, "type", None)
    if typ and typ not in {"method", "function", "unknown"}:
        return typ
    return None


def _matching_user_method(
    declarations: list[MethodDeclaration], method_name: str, receiver_type: str | None
) -> MethodDeclaration | None:
    for declaration in declarations:
        if declaration.name != method_name:
            continue
        expected = type_ref_name(declaration.receiver_type) if declaration.receiver_type else None
        if _receiver_matches(receiver_type, expected):
            return declaration
    return None


def bind_arguments_to_specs(
    args: list[Argument], specs: list[dict[str, Any]], engine: PineInferenceEngine
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    positional = [arg for arg in args if arg.name is None]
    positional_names = [spec.get("name") for spec in specs[: len(positional)]]
    for index, arg in enumerate(args):
        spec: dict[str, Any] | None = None
        if arg.name is None and index < len(specs):
            spec = specs[index]
            param_name = spec.get("name")
            expected = spec.get("type")
            binding = "positional"
        elif arg.name is not None:
            spec = next((item for item in specs if item.get("name") == arg.name), None)
            param_name = arg.name
            expected = spec.get("type") if spec else None
            binding = "named" if spec else "unknown_named"
        else:
            param_name = None
            expected = None
            binding = "extra_positional"
        fact = _argument_fact(
            arg,
            position=index,
            field_or_param=param_name,
            expected_type=expected,
            binding=binding,
            engine=engine,
        )
        fact["duplicate_positional_named"] = bool(arg.name and arg.name in positional_names)
        rows.append(fact)
    return rows


def extract_method_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineVersionContext | None = None,
) -> dict[str, Any]:
    actual_profile = profile or program.version_context
    engine = _engine(actual_profile, semantic_model)
    declarations = _method_declarations(program)
    declaration_rows = []
    call_rows = []
    for declaration in declarations:
        receiver_type = (
            type_ref_name(declaration.receiver_type) if declaration.receiver_type else None
        )
        declaration_rows.append(
            {
                "name": declaration.name,
                "span": span_dict(declaration),
                "is_exported": declaration.is_exported,
                "receiver": {
                    "name": declaration.receiver_name,
                    "type": receiver_type,
                    "span": (
                        span_dict(declaration.receiver_type) if declaration.receiver_type else None
                    ),
                },
                "parameters": _parameter_facts(declaration.parameters, engine),
                "return_type": _method_return_type(declaration, semantic_model),
            }
        )

    for call, context in iter_calls_with_context(program):
        if not isinstance(call.callee, MemberAccessExpr):
            continue
        if call.callee.member == "new" and isinstance(call.callee.object, Identifier):
            continue
        receiver_type = engine.infer_type(call.callee.object)
        function_form = collection_method_function_form(receiver_type, call.callee.member)
        user_method = _matching_user_method(declarations, call.callee.member, receiver_type)
        if user_method is None and function_form is None:
            continue
        if user_method is not None:
            expected_receiver = (
                type_ref_name(user_method.receiver_type) if user_method.receiver_type else None
            )
            specs = [
                {
                    "name": parameter.name,
                    "type": type_ref_name(parameter.type_ref) if parameter.type_ref else None,
                    "required": parameter.default_value is None,
                }
                for parameter in user_method.parameters
            ]
            method_kind = "user_defined"
            return_type = _method_return_type(user_method, semantic_model)
        else:
            expected_receiver = receiver_type
            specs = collection_method_parameter_specs(receiver_type, call.callee.member)
            method_kind = "builtin_collection"
            return_type = _collection_return_type(
                receiver_type, call.callee.member
            ) or engine.infer_type(call)
        call_rows.append(
            {
                "kind": method_kind,
                "name": call.callee.member,
                "function_form": function_form,
                "span": span_dict(call),
                "context": list(context),
                "local_scope": bool(context),
                "receiver": {
                    "expr": expr_summary(call.callee.object),
                    "type": receiver_type,
                    "expected_type": expected_receiver,
                    "type_ok": _receiver_matches(receiver_type, expected_receiver),
                    "span": span_dict(call.callee.object),
                },
                "return_type": return_type,
                "arguments": bind_arguments_to_specs(call.arguments, specs, engine),
            }
        )

    return {
        "contract": SECTION_CONTRACTS["methods"],
        "profile": f"pine_v{actual_profile.pine_version}",
        "declarations": declaration_rows,
        "calls": call_rows,
    }


def extract_semantic_facts(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineVersionContext | None = None,
) -> dict[str, Any]:
    actual_profile = profile or program.version_context
    return {
        "schema_version": 1,
        "profile": f"pine_v{actual_profile.pine_version}",
        "types": extract_type_contract(
            program, semantic_model=semantic_model, profile=actual_profile
        ),
        "methods": extract_method_contract(
            program, semantic_model=semantic_model, profile=actual_profile
        ),
    }


__all__ = [
    "Context",
    "collection_kind_from_type",
    "bind_arguments_to_specs",
    "collection_method_function_form",
    "collection_method_parameter_specs",
    "expr_summary",
    "extract_method_contract",
    "extract_semantic_facts",
    "extract_type_contract",
    "iter_calls_with_context",
    "node_context_marker",
    "span_dict",
]
