from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from pine2ast.ast.nodes import CallExpr
from pine2ast.ast.nodes import Program
from pine2ast.ast.visitors import walk
from pine2ast.diagnostics import codes
from pine2ast.semantic.builtin_registry import load_builtin_registry
from pine2ast.semantic.type_infer import callee_name

_CONTRACT_FIXTURE = (
    Path(__file__).resolve().parent / "runtime_contract_v1_4" / "frontend_node_mapping.json"
)


def load_runtime_contract_mapping(path: Path | None = None) -> dict[str, Any]:
    """Load the machine-readable runtime_contract_v1.4 frontend mapping."""

    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        text = (
            resources.files("pine2ast") / "runtime_contract_v1_4" / "frontend_node_mapping.json"
        ).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        text = _CONTRACT_FIXTURE.read_text(encoding="utf-8")
    return json.loads(text)


def unsupported_features_for_program(
    program: Program, *, mapping: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Return stable unsupported-feature markers for schema-valid AST nodes.

    This is intentionally separate from parser diagnostics so existing parse/golden
    contracts do not drift. Downstream consumers that target `runtime_contract_v1.4`
    can call this helper and fail/route explicitly before runtime.
    """

    mapping = mapping or load_runtime_contract_mapping()
    unsupported_by_kind = {
        item["kind"]: item
        for item in mapping["nodes"]
        if not item["ast2python_lowerable"] or not item["pinelib_runtime_support"]
    }
    runtime_unsupported_builtins = {
        name: entry
        for name, entry in load_builtin_registry().get("functions", {}).items()
        if entry.get("runtime_contract_unsupported")
    }
    features: list[dict[str, Any]] = []
    for node in walk(program):
        item = unsupported_by_kind.get(node.kind)
        if item is not None:
            features.append(
                {
                    "kind": node.kind,
                    "code": item.get("unsupported_diagnostic_code") or codes.UNSUPPORTED_FEATURE,
                    "severity": "WARNING",
                    "message": item["notes"],
                    "span": node.span.to_dict(),
                }
            )
        if isinstance(node, CallExpr):
            name = callee_name(node.callee)
            entry = runtime_unsupported_builtins.get(name)
            if entry is not None:
                features.append(
                    {
                        "kind": "CallExpr",
                        "code": entry.get("unsupported_diagnostic_code")
                        or codes.UNSUPPORTED_FEATURE,
                        "severity": "WARNING",
                        "message": f"Builtin {name} has no runtime-equivalent visual output under runtime_contract v1.4.",
                        "span": node.span.to_dict(),
                    }
                )
    return features
