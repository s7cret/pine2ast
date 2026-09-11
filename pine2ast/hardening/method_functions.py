"""Capability admission for function-notation calls of user-defined methods.

The syntax is ordinary Pine. Its new lowering contract must nevertheless be
explicit so older consumers cannot silently omit the receiver. Detection is
AST-based (not based on trusted-looking producer call facts).
"""
from __future__ import annotations

from typing import Any, Mapping

from pine2ast.ast.decode import ASTAdmissionBudget, ASTDecodeError

METHOD_FUNCTION_CAPABILITY = "user_method_function_calls_v1"


def method_function_feature(
    ast: Mapping[str, Any], context: Mapping[str, Any], *, budget: ASTAdmissionBudget
) -> bool:
    methods: set[str] = set()
    functions: set[str] = set()
    calls: set[str] = set()
    pending: list[Any] = [ast]
    while pending:
        value = pending.pop()
        budget.charge()
        if isinstance(value, dict):
            kind = value.get("kind")
            name = value.get("name")
            if kind == "MethodDeclaration" and isinstance(name, str):
                methods.add(name)
            elif kind == "FunctionDeclaration" and isinstance(name, str):
                functions.add(name)
            elif kind == "CallExpr":
                callee = value.get("callee")
                if isinstance(callee, dict) and callee.get("kind") == "Identifier":
                    name = callee.get("name")
                    if isinstance(name, str):
                        calls.add(name)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    found = bool((methods - functions) & calls)
    if found and (type(context.get("pine_version")) is not int or context["pine_version"] not in {5, 6}):
        raise ASTDecodeError("user method function calls require Pine v5/v6")
    return found
