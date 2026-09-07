from __future__ import annotations


from typing import Any

from pine2ast.ast.nodes import Identifier, MemberAccessExpr, Program
from pine2ast.versioning import PineVersionContext
from pine2ast.semantic.type_helpers import type_ref_name
from pine2ast.semantic.type_infer import callee_name
from pine2ast.frontend.helpers import (
    _bound_arguments,
    _build_type_maps,
    _constructor_assignees,
    _declared_arg_bindings,
    _field_dict,
    _inference_engine,
    _iter_calls_with_context,
    _iter_nodes,
    _span_dict,
    _target_descriptor,
)
from pine2ast.frontend.ids import SECTION_CONTRACTS


def extract_type_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineVersionContext | None = None,
) -> dict[str, Any]:
    """Extract UDT/enum constructor and reference facts for OpenPine runtime layers."""

    profile = profile or program.version_context
    symbols = getattr(semantic_model, "symbols", None)
    engine = _inference_engine(profile, symbols)
    type_map, enum_map, _function_map, method_map = _build_type_maps(program)
    assignees = _constructor_assignees(program)

    declarations: list[dict[str, Any]] = []
    for name, declaration in type_map.items():
        declarations.append(
            {
                "name": name,
                "exported": declaration.is_exported,
                "span": _span_dict(declaration),
                "fields": [_field_dict(field, engine) for field in declaration.fields],
            }
        )

    enums: list[dict[str, Any]] = []
    for name, enum_declaration in enum_map.items():
        enums.append(
            {
                "name": name,
                "exported": enum_declaration.is_exported,
                "span": _span_dict(enum_declaration),
                "members": [
                    {"name": member.name, "title": member.title, "span": _span_dict(member)}
                    for member in enum_declaration.members
                ],
            }
        )

    constructors: list[dict[str, Any]] = []
    enum_references: list[dict[str, Any]] = []
    field_accesses: list[dict[str, Any]] = []
    method_calls: list[dict[str, Any]] = []

    for call, context in _iter_calls_with_context(program):
        if (
            isinstance(call.callee, MemberAccessExpr)
            and call.callee.member == "new"
            and isinstance(call.callee.object, Identifier)
            and call.callee.object.name in type_map
        ):
            type_name = call.callee.object.name
            declaration = type_map[type_name]
            fields = declaration.fields
            field_names = [field.name for field in fields]
            positional = [arg for arg in call.arguments if arg.name is None]
            named = {arg.name for arg in call.arguments if arg.name}
            supplied = set(field_names[: len(positional)]) | (named & set(field_names))
            required: list[str] = []
            bindings = _declared_arg_bindings(fields, call.arguments, engine=engine)
            constructors.append(
                {
                    "type": type_name,
                    "span": _span_dict(call),
                    "context": list(context),
                    "local_scope": bool(context),
                    "assigned_to": assignees.get(id(call), []),
                    "result_type": engine.infer_type(call),
                    "field_order": field_names,
                    "required_fields": required,
                    "supplied_fields": sorted(supplied),
                    "missing_fields": [field for field in required if field not in supplied],
                    "unknown_fields": sorted(
                        name for name in named if name not in set(field_names)
                    ),
                    "too_many_positionals": len(positional) > len(fields),
                    "arguments": bindings,
                }
            )

        if isinstance(call.callee, MemberAccessExpr):
            member = call.callee.member
            receiver = call.callee.object
            receiver_type = engine.infer_type(receiver)
            candidates = method_map.get(member, [])
            user_candidate = next(
                (
                    method
                    for method in candidates
                    if method.receiver_type is not None
                    and type_ref_name(method.receiver_type) == receiver_type
                ),
                None,
            )
            if user_candidate is not None or receiver_type not in {"unknown", "external", None}:
                params = user_candidate.parameters if user_candidate is not None else []
                method_calls.append(
                    {
                        "name": member,
                        "qualified_name": callee_name(call.callee),
                        "span": _span_dict(call),
                        "context": list(context),
                        "local_scope": bool(context),
                        "receiver": _target_descriptor(receiver, symbols, profile=profile),
                        "user_defined": user_candidate is not None,
                        "declared_receiver_type": (
                            type_ref_name(user_candidate.receiver_type)
                            if user_candidate is not None
                            and user_candidate.receiver_type is not None
                            else None
                        ),
                        "return_type": engine.infer_type(call),
                        "arguments": (
                            _declared_arg_bindings(params, call.arguments, engine=engine)
                            if params
                            else _bound_arguments(
                                member,
                                call.arguments,
                                profile=profile,
                                symbols=symbols,
                                call_span=call.span,
                            )
                        ),
                    }
                )

    for node in _iter_nodes(program):
        if not isinstance(node, MemberAccessExpr):
            continue
        if isinstance(node.object, Identifier):
            enum_decl = enum_map.get(node.object.name)
            if enum_decl is not None:
                member_names = {member.name for member in enum_decl.members}
                enum_references.append(
                    {
                        "enum": node.object.name,
                        "member": node.member,
                        "qualified_name": f"{node.object.name}.{node.member}",
                        "known": node.member in member_names,
                        "type": engine.infer_type(node),
                        "qualifier": engine.infer_qualifier(node),
                        "span": _span_dict(node),
                    }
                )
                continue
        owner_type = engine.infer_type(node.object)
        if owner_type in type_map and node.member != "new":
            field = next(
                (item for item in type_map[owner_type].fields if item.name == node.member), None
            )
            field_accesses.append(
                {
                    "path": callee_name(node),
                    "owner_type": owner_type,
                    "field": node.member,
                    "known": field is not None,
                    "type": type_ref_name(field.type_ref) if field is not None else None,
                    "qualifier": engine.infer_qualifier(node),
                    "span": _span_dict(node),
                }
            )

    return {
        "contract": SECTION_CONTRACTS["types"],
        "profile": f"pine_v{profile.pine_version}",
        "udts": declarations,
        "enums": enums,
        "constructors": constructors,
        "field_accesses": field_accesses,
        "enum_references": enum_references,
        "enum_member_uses": enum_references,
        "method_calls": method_calls,
    }
