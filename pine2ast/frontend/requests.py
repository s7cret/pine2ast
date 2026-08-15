from __future__ import annotations

# ruff: noqa: F403,F405

from typing import Any

from pine2ast.ast.nodes import Program
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.semantic.type_infer import callee_name
from pine2ast.frontend.helpers import *


def extract_request_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineLanguageProfile | None = None,
) -> dict[str, Any]:
    profile = profile or pine_language_profile(program.version or program.language_version)
    symbols = getattr(semantic_model, "symbols", None)
    dynamic_requests = _declaration_dynamic_requests(program, profile)
    requests: list[dict[str, Any]] = []

    for call, context in _iter_calls_with_context(program):
        name = callee_name(call.callee)
        if not name.startswith("request."):
            continue
        bound = _bound_arguments(
            name, call.arguments, profile=profile, symbols=symbols, call_span=call.span
        )
        context_args = [
            arg for arg in bound if arg.get("parameter") in _REQUEST_CONTEXT_PARAMETER_NAMES
        ]
        local_scope = any(
            c in {"if", "switch", "for_range", "for_in", "while", "function", "method"}
            for c in context
        )
        series_context_args = [
            arg["parameter"] for arg in context_args if arg.get("qualifier") == "series"
        ]
        requires_dynamic = local_scope or bool(series_context_args)
        enabled = bool(dynamic_requests["enabled"])
        disabled_reasons: list[str] = []
        if requires_dynamic and not enabled:
            if local_scope:
                disabled_reasons.append("local_scope")
            if series_context_args:
                disabled_reasons.append("series_context_argument")
        symbol = _parameter(bound, "symbol", 0) or _parameter(bound, "ticker", 0)
        timeframe = _parameter(bound, "timeframe", 1)
        expression = _parameter(bound, "expression", 2)
        requests.append(
            {
                "kind": name,
                "span": _span_dict(call),
                "context": list(context),
                "local_scope": local_scope,
                "dynamic": {
                    "enabled": enabled,
                    "default": dynamic_requests["default"],
                    "explicit": dynamic_requests["explicit"],
                    "requires_dynamic": requires_dynamic,
                    "static_ok": not disabled_reasons,
                    "disabled_reasons": disabled_reasons,
                },
                "symbol": symbol,
                "timeframe": timeframe,
                "expression": expression,
                "context_arguments": context_args,
                "arguments": bound,
            }
        )
    return {
        "contract": "openpine.requests.v1",
        "profile": f"pine_v{profile.version}",
        "dynamic_requests": dynamic_requests,
        "requests": requests,
    }
