"""Bounded AST detection of the declaration-identity function-overload contract."""

from __future__ import annotations
from typing import Any, Mapping
from pine2ast.ast.decode import ASTAdmissionBudget, ASTDecodeError

FUNCTION_OVERLOAD_CAPABILITY = "user_function_overloads_v1"
LIBRARY_OVERLOAD_CAPABILITY = "library_function_overloads_v1"
LIBRARY_OVERLOAD_PROFILE = "same_version_function_overloads_v6"


def function_overload_feature(
    ast: Mapping[str, Any], context: Mapping[str, Any], *, budget: ASTAdmissionBudget
) -> bool:
    program = ast.get("program", ast)
    items = program.get("items", []) if isinstance(program, dict) else []
    seen = set()
    found = False
    for node in items:
        budget.charge()
        if isinstance(node, dict) and node.get("kind") == "FunctionDeclaration":
            name = node.get("name")
            if isinstance(name, str):
                found |= name in seen
                seen.add(name)
    if found and (
        type(context.get("pine_version")) is not int or context["pine_version"] not in {5, 6}
    ):
        raise ASTDecodeError("function overloads are admitted by the v5/v6 profile only")
    return found


def library_overload_feature(context) -> bool:
    return (
        isinstance(context, Mapping)
        and isinstance(context.get("linkage_receipt"), Mapping)
        and context["linkage_receipt"].get("profile") == LIBRARY_OVERLOAD_PROFILE
    )
