from __future__ import annotations

# ruff: noqa: F403,F405

from typing import Any

from pine2ast.ast.nodes import (
    ForInStructure,
    ForRangeStructure,
    HistoryRefExpr,
    IfStructure,
    Program,
    SwitchStructure,
    WhileStructure,
)
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.openpine_contracts.helpers import *


def extract_control_flow_contract(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineLanguageProfile | None = None,
) -> dict[str, Any]:
    profile = profile or pine_language_profile(program.version or program.language_version)
    symbols = getattr(semantic_model, "symbols", None)
    engine = _inference_engine(profile, symbols)
    loops: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    history_refs: list[dict[str, Any]] = []

    for node in _iter_nodes(program):
        if isinstance(node, IfStructure):
            conditions.append(
                {
                    "kind": "if",
                    "span": _span_dict(node),
                    "condition": _expr_descriptor(node.condition, engine),
                    "branch_count": 1 + len(node.else_if_branches) + (1 if node.else_block else 0),
                }
            )
            for branch in node.else_if_branches:
                conditions.append(
                    {
                        "kind": "else_if",
                        "span": _span_dict(branch),
                        "condition": _expr_descriptor(branch.condition, engine),
                    }
                )
        elif isinstance(node, WhileStructure):
            conditions.append(
                {
                    "kind": "while",
                    "span": _span_dict(node),
                    "condition": _expr_descriptor(node.condition, engine),
                }
            )
            loops.append(
                {
                    "kind": "while",
                    "span": _span_dict(node),
                    "condition": _expr_descriptor(node.condition, engine),
                    "static_iterations": None,
                    "dynamic_boundary": True,
                }
            )
        elif isinstance(node, ForRangeStructure):
            start = _expr_descriptor(node.start, engine)
            end = _expr_descriptor(node.end, engine)
            step = _expr_descriptor(node.step, engine) if node.step is not None else None
            loops.append(
                {
                    "kind": "for_range",
                    "span": _span_dict(node),
                    "variable": node.variable,
                    "start": start,
                    "end": end,
                    "step": step,
                    "static_iterations": _for_range_static_iterations(node),
                    "dynamic_boundary": any(
                        part["qualifier"] == "series"
                        for part in [start, end, step]
                        if part is not None
                    ),
                }
            )
        elif isinstance(node, ForInStructure):
            iterable = _expr_descriptor(node.iterable, engine)
            loops.append(
                {
                    "kind": "for_in",
                    "span": _span_dict(node),
                    "targets": list(node.target.names),
                    "iterable": iterable,
                    "iterable_collection_kind": _collection_kind_from_type(iterable["type"]),
                    "static_iterations": None,
                    "dynamic_boundary": True,
                }
            )
        elif isinstance(node, SwitchStructure):
            conditions.append(
                {
                    "kind": "switch",
                    "span": _span_dict(node),
                    "expression": (
                        _expr_descriptor(node.expression, engine)
                        if node.expression is not None
                        else None
                    ),
                    "case_count": len(node.cases),
                }
            )
        elif isinstance(node, HistoryRefExpr):
            static_offset = _literal_int_value(node.offset)
            history_refs.append(
                {
                    "span": _span_dict(node),
                    "base": _expr_descriptor(node.base, engine),
                    "offset": _expr_descriptor(node.offset, engine),
                    "static_offset": static_offset,
                    "negative_offset": static_offset is not None and static_offset < 0,
                    "result_type": engine.infer_type(node),
                }
            )

    return {
        "contract": "openpine.control_flow.v1",
        "profile": f"pine_v{profile.version}",
        "loops": loops,
        "conditions": conditions,
        "history_refs": history_refs,
    }
