from __future__ import annotations

# ruff: noqa: F403,F405

from typing import Any

from pine2ast.ast.nodes import MemberAccessExpr, Program
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.semantic.type_helpers import type_ref_name
from pine2ast.frontend.helpers import *


def extract_callable_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineLanguageProfile | None = None,
) -> dict[str, Any]:
    profile = profile or pine_language_profile(program.version or program.language_version)
    symbols = getattr(semantic_model, "symbols", None)
    engine = _inference_engine(profile, symbols)
    _type_map, _enum_map, function_map, method_map = _build_type_maps(program)

    functions = [
        {
            "name": declaration.name,
            "exported": declaration.is_exported,
            "span": _span_dict(declaration),
            "parameters": [_parameter_dict(param) for param in declaration.parameters],
            "return_type": (
                getattr(symbols.get(declaration.name), "type", None) if symbols else None
            ),
        }
        for declaration in function_map.values()
    ]
    methods = [
        {
            "name": declaration.name,
            "exported": declaration.is_exported,
            "span": _span_dict(declaration),
            "receiver": {
                "name": declaration.receiver_name,
                "type": (
                    type_ref_name(declaration.receiver_type)
                    if declaration.receiver_type is not None
                    else None
                ),
            },
            "parameters": [_parameter_dict(param) for param in declaration.parameters],
            "return_type": (
                getattr(symbols.get(declaration.name), "type", None) if symbols else None
            ),
        }
        for declarations in method_map.values()
        for declaration in declarations
    ]

    function_calls: list[dict[str, Any]] = []
    method_calls: list[dict[str, Any]] = []
    for call, context in _iter_calls_with_context(program):
        name = _call_base_name(call)
        if isinstance(call.callee, MemberAccessExpr):
            receiver_type = engine.infer_type(call.callee.object)
            method_name = call.callee.member
            declarations = method_map.get(method_name, [])
            declaration = next(
                (
                    item
                    for item in declarations
                    if item.receiver_type is not None
                    and type_ref_name(item.receiver_type) == receiver_type
                ),
                declarations[0] if declarations else None,
            )
            if declaration is not None:
                method_calls.append(
                    {
                        "name": method_name,
                        "span": _span_dict(call),
                        "context": list(context),
                        "receiver_type": receiver_type,
                        "return_type": engine.infer_type(call),
                        "arguments": _declared_arg_bindings(
                            declaration.parameters, call.arguments, engine=engine
                        ),
                    }
                )
        elif name in function_map:
            function_declaration = function_map[name]
            function_calls.append(
                {
                    "name": name,
                    "span": _span_dict(call),
                    "context": list(context),
                    "return_type": engine.infer_type(call),
                    "arguments": _declared_arg_bindings(
                        function_declaration.parameters, call.arguments, engine=engine
                    ),
                }
            )

    return {
        "contract": "openpine.callables.v1",
        "profile": f"pine_v{profile.version}",
        "functions": functions,
        "methods": methods,
        "function_calls": function_calls,
        "method_calls": method_calls,
    }
