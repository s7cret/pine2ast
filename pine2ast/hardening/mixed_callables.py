"""Bounded declaration/context detection, independent of claimed semantic facts."""

from __future__ import annotations
from typing import Any, Mapping
from pine2ast.ast.decode import ASTAdmissionBudget, ASTDecodeError

MIXED_CALLABLE_CAPABILITY = "mixed_user_callable_families_v1"
MIXED_LIBRARY_PROFILE = "same_version_mixed_callables_v7"


def mixed_callable_feature(
    ast: Mapping[str, Any],
    context: Mapping[str, Any],
    library_context: Any,
    *,
    budget: ASTAdmissionBudget,
) -> bool:
    program = ast.get("program", ast)
    functions, methods = set(), set()
    for node in program.get("items", []) if isinstance(program, Mapping) else ():
        budget.charge()
        if not isinstance(node, Mapping) or not isinstance(node.get("name"), str):
            continue
        if node.get("kind") == "FunctionDeclaration":
            functions.add(node["name"])
        elif node.get("kind") == "MethodDeclaration":
            methods.add(node["name"])
    projected = (
        isinstance(library_context, Mapping)
        and isinstance(library_context.get("linkage_receipt"), Mapping)
        and library_context["linkage_receipt"].get("profile") == MIXED_LIBRARY_PROFILE
    )
    found = bool(functions & methods) or projected
    if found and (
        type(context.get("pine_version")) is not int or context["pine_version"] not in {5, 6}
    ):
        raise ASTDecodeError("mixed user-callable families require Pine v5/v6")
    return found
