from __future__ import annotations

# ruff: noqa: F403,F405

from typing import Any

from pine2ast.ast.nodes import DeclarationStatement, Program
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.semantic.type_infer import callee_name
from pine2ast.frontend.helpers import *


def _strategy_call_bucket(name: str) -> str:
    if name in _ORDER_CALLS:
        return "orders"
    if name in _EXIT_CALLS:
        return "exits"
    if name in _MANAGEMENT_CALLS:
        return "management"
    if name.startswith(_RISK_CALL_PREFIX):
        return "risk_rules"
    return "other"


def extract_strategy_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineLanguageProfile | None = None,
) -> dict[str, Any]:
    profile = profile or pine_language_profile(program.version or program.language_version)
    symbols = getattr(semantic_model, "symbols", None)
    declaration = (
        program.declaration if isinstance(program.declaration, DeclarationStatement) else None
    )
    contract: dict[str, Any] = {
        "contract": "openpine.strategy.v1",
        "profile": f"pine_v{profile.version}",
        "script": {
            "type": declaration.script_type if declaration else None,
            "title": _declaration_title(declaration),
            "pine_version": program.version or program.language_version,
        },
        "orders": [],
        "exits": [],
        "management": [],
        "risk_rules": [],
        "other": [],
    }
    for call, context in _iter_calls_with_context(program):
        name = callee_name(call.callee)
        if not name.startswith("strategy."):
            continue
        bound = _bound_arguments(
            name, call.arguments, profile=profile, symbols=symbols, call_span=call.span
        )
        bucket = _strategy_call_bucket(name)
        item = {
            "kind": name,
            "span": _span_dict(call),
            "context": list(context),
            "local_scope": bool(context),
            "id": _parameter(bound, "id", 0),
            "direction": _parameter(bound, "direction", 1) if bucket == "orders" else None,
            "from_entry": _parameter(bound, "from_entry"),
            "uses_removed_when_parameter": any(arg.get("name") == "when" for arg in bound),
            "arguments": bound,
        }
        contract[bucket].append(item)
    return contract
