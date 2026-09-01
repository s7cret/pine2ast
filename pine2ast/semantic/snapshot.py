"""JSON-safe semantic model snapshots for Pine2AST 4.0.

The snapshot is a diagnostics/debugging contract, not the AST contract.  It is
safe for OpenPine integration smoke tests because it exposes stable facts
(symbols, scopes, node type/qualifier rows, and semantic pass deltas) without
requiring consumers to import Python dataclasses from the analyzer internals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pine2ast._version import __version__
from pine2ast.ast.base import ASTNode
from pine2ast.ast.walk import iter_nodes
from pine2ast.diagnostics import Severity
from pine2ast.versioning import PineVersionContext
from pine2ast.semantic.pipeline import PASS_PIPELINE

SEMANTIC_SNAPSHOT_CONTRACT = "pine2ast.semantic_snapshot.v1"


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _span_dict(span: Any) -> dict[str, int] | None:
    return span.to_dict() if hasattr(span, "to_dict") else None


def _node_kind(node: ASTNode) -> str:
    return getattr(node, "kind", type(node).__name__)


def _diagnostic_summary(diagnostics: list[Any]) -> dict[str, int]:
    counts = {"fatal": 0, "error": 0, "warning": 0, "info": 0, "total": len(diagnostics)}
    for diagnostic in diagnostics:
        severity = getattr(diagnostic, "severity", None)
        value = str(_enum_value(severity)).lower()
        if value == Severity.FATAL.value.lower():
            counts["fatal"] += 1
        elif value == Severity.ERROR.value.lower():
            counts["error"] += 1
        elif value == Severity.WARNING.value.lower():
            counts["warning"] += 1
        else:
            counts["info"] += 1
    return counts


def _profile_dict(profile: PineVersionContext | None) -> dict[str, Any] | None:
    return profile.to_dict() if profile is not None else None


def symbol_rows(semantic_model: Any | None) -> list[dict[str, Any]]:
    symbols = getattr(semantic_model, "symbols", {}) or {}
    rows: list[dict[str, Any]] = []
    for symbol in sorted(
        symbols.values(), key=lambda item: (getattr(item, "id", 0), getattr(item, "name", ""))
    ):
        rows.append(
            {
                "id": getattr(symbol, "id", None),
                "name": getattr(symbol, "name", None),
                "kind": _enum_value(getattr(symbol, "kind", None)),
                "type": getattr(symbol, "type", None),
                "qualifier": getattr(symbol, "qualifier", None),
                "scope_id": getattr(symbol, "scope_id", None),
                "declared_at": _span_dict(getattr(symbol, "declared_at", None)),
            }
        )
    return rows


def scope_rows(semantic_model: Any | None) -> list[dict[str, Any]]:
    scopes = getattr(semantic_model, "scopes", []) or []
    rows: list[dict[str, Any]] = []
    for scope in sorted(scopes, key=lambda item: getattr(item, "id", 0)):
        symbols = getattr(scope, "symbols", {}) or {}
        rows.append(
            {
                "id": getattr(scope, "id", None),
                "kind": _enum_value(getattr(scope, "kind", None)),
                "parent_id": getattr(scope, "parent_id", None),
                "symbols": dict(sorted(symbols.items())),
                "non_na_symbols": sorted(getattr(scope, "non_na_symbols", set()) or []),
            }
        )
    return rows


def node_fact_rows(program: ASTNode | None, semantic_model: Any | None) -> list[dict[str, Any]]:
    if program is None or semantic_model is None:
        return []
    node_types = getattr(semantic_model, "node_types", {}) or {}
    node_qualifiers = getattr(semantic_model, "node_qualifiers", {}) or {}
    rows: list[dict[str, Any]] = []
    for index, node in enumerate(iter_nodes(program)):
        node_id = id(node)
        type_name = node_types.get(node_id)
        qualifier = node_qualifiers.get(node_id)
        if type_name is None and qualifier is None:
            continue
        rows.append(
            {
                "index": index,
                "kind": _node_kind(node),
                "type": type_name,
                "qualifier": qualifier,
                "span": _span_dict(getattr(node, "span", None)),
            }
        )
    return rows


def pass_rows(semantic_model: Any | None) -> list[dict[str, Any]]:
    # Analyzer stores pass results on the analyzer, not on SemanticModel. 4.0 keeps
    # this row deterministic even when a caller passes a model produced by older code.
    analyzer_results = getattr(semantic_model, "pass_results", None) or ()
    if analyzer_results:
        return [
            {
                "name": getattr(row, "name", None),
                "diagnostics_before": getattr(row, "diagnostics_before", None),
                "diagnostics_after": getattr(row, "diagnostics_after", None),
            }
            for row in analyzer_results
        ]
    return [
        {"name": name, "diagnostics_before": None, "diagnostics_after": None}
        for name in PASS_PIPELINE
    ]


def build_semantic_snapshot_payload(
    result: Any,
    *,
    source_path: str | Path = "<memory>",
    source_name: str | None = None,
    profile: PineVersionContext | None = None,
    include_node_facts: bool = True,
) -> dict[str, Any]:
    program = getattr(result, "ast", None)
    semantic_model = getattr(result, "semantic_model", None)
    actual_profile = profile or (program.version_context if program is not None else None)
    diagnostics = list(getattr(result, "diagnostics", []) or [])
    path = Path(source_path)
    symbols = symbol_rows(semantic_model)
    scopes = scope_rows(semantic_model)
    node_facts = node_fact_rows(program, semantic_model) if include_node_facts else []
    return {
        "schema_version": 1,
        "contract": SEMANTIC_SNAPSHOT_CONTRACT,
        "producer": {"name": "pine2ast", "version": __version__},
        "source": {"path": str(source_path), "name": source_name or path.name},
        "ok": bool(getattr(result, "ok", False)),
        "profile": _profile_dict(actual_profile),
        "diagnostics": _diagnostic_summary(diagnostics),
        "counts": {
            "symbols": len(symbols),
            "scopes": len(scopes),
            "node_facts": len(node_facts),
        },
        "passes": pass_rows(semantic_model),
        "symbols": symbols,
        "scopes": scopes,
        "node_facts": node_facts,
    }


def build_semantic_snapshot_json(result: Any, *, indent: int = 2, **kwargs: Any) -> str:
    import json

    return json.dumps(
        build_semantic_snapshot_payload(result, **kwargs),
        ensure_ascii=False,
        indent=indent,
    )


__all__ = [
    "SEMANTIC_SNAPSHOT_CONTRACT",
    "build_semantic_snapshot_json",
    "build_semantic_snapshot_payload",
    "node_fact_rows",
    "pass_rows",
    "scope_rows",
    "symbol_rows",
]
