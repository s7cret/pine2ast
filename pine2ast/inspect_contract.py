from __future__ import annotations

from pathlib import Path
from typing import Any

from pine2ast._version import __version__
from pine2ast.api import ParseOptions, ParseResult, parse_file
from pine2ast.ast.nodes import DeclarationStatement, Literal
from pine2ast.diagnostics import Severity
from pine2ast.semantic.extractors import (
    extract_alertconditions,
    extract_dependencies,
    extract_drawing_calls,
    extract_inputs,
    extract_plots,
    extract_request_calls,
    extract_strategy_calls,
)
from pine2ast.semantic.type_infer import callee_name


def span_dict(span: Any) -> dict[str, int] | None:
    return span.to_dict() if hasattr(span, "to_dict") else None


def simple_call(node: Any) -> dict[str, Any]:
    return {
        "name": callee_name(node.callee),
        "arg_count": len(node.arguments),
        "span": span_dict(node.span),
    }


def dependency_dict(dep: Any) -> dict[str, Any]:
    return {
        "imports": dep.imports,
        "import_aliases": dep.import_aliases,
        "namespaces": dep.namespaces,
        "builtin_calls": dep.builtin_calls,
        "user_function_calls": dep.user_function_calls,
        "method_calls": dep.method_calls,
        "udt_constructors": dep.udt_constructors,
        "external_calls": dep.external_calls,
        "unknown_calls": dep.unknown_calls,
    }


def input_dict(item: Any) -> dict[str, Any]:
    return {
        "name": item.name,
        "title": item.title,
        "input_function": item.input_function,
        "default_value": item.default_value,
        "minval": item.minval,
        "maxval": item.maxval,
        "step": item.step,
        "options": item.options,
        "span": span_dict(item.span),
    }


def script_dict(ast: Any) -> dict[str, Any]:
    if ast is None or not isinstance(ast.declaration, DeclarationStatement):
        return {"type": None, "title": None, "pine_version": None}
    title = None
    if ast.declaration.call.arguments:
        first_arg = ast.declaration.call.arguments[0]
        if first_arg.name is None and isinstance(first_arg.value, Literal):
            title = first_arg.value.value
    return {
        "type": ast.declaration.script_type,
        "title": title,
        "pine_version": ast.version or ast.language_version,
    }


def unsupported_features(result: ParseResult) -> list[dict[str, Any]]:
    return [
        {
            "code": d.code,
            "severity": d.severity.value,
            "message": d.message,
            "span": span_dict(d.span),
        }
        for d in result.diagnostics
        if d.code.startswith("P2A") and d.severity.value in {"ERROR", "FATAL"}
    ]


def build_inspect_payload(
    result: ParseResult,
    *,
    source_path: str | Path = "<memory>",
    source_name: str | None = None,
    include_openpine_contract: bool = False,
    include_semantic_snapshot: bool = False,
) -> dict[str, Any]:
    path = Path(source_path)
    payload = {
        "schema_version": 1,
        "contract": "pine2ast.inspect.optimizer.v1",
        "producer": {
            "name": "pine2ast",
            "version": __version__,
            "contract": "pine2ast.inspect.optimizer.v1",
        },
        "tool": {"name": "pine2ast", "version": __version__},
        "source": {"path": str(source_path), "name": source_name or path.name},
        "script": script_dict(result.ast),
        "ok": result.ok,
        "unsupported_features": unsupported_features(result),
        "diagnostics": [d.to_dict() for d in result.diagnostics],
        "inputs": (
            [input_dict(i) for i in extract_inputs(result.ast, result.semantic_model)]
            if result.ast
            else []
        ),
        "strategy_calls": (
            [
                {"name": c.name, "arg_count": len(c.arguments), "span": span_dict(c.span)}
                for c in extract_strategy_calls(result.ast)
            ]
            if result.ast
            else []
        ),
        "request_calls": (
            [simple_call(c) for c in extract_request_calls(result.ast)] if result.ast else []
        ),
        "plots": [simple_call(c) for c in extract_plots(result.ast)] if result.ast else [],
        "alerts": (
            [
                {"name": c.name, "arg_count": len(c.arguments), "span": span_dict(c.span)}
                for c in extract_alertconditions(result.ast)
            ]
            if result.ast
            else []
        ),
        "drawings": (
            [
                {"name": c.name, "arg_count": len(c.arguments), "span": span_dict(c.span)}
                for c in extract_drawing_calls(result.ast)
            ]
            if result.ast
            else []
        ),
        "dependencies": (
            dependency_dict(extract_dependencies(result.ast, result.semantic_model))
            if result.ast
            else None
        ),
    }
    if include_openpine_contract:
        from pine2ast.openpine_contract import build_openpine_contract_payload

        payload["openpine_contract"] = build_openpine_contract_payload(
            result, source_path=source_path, source_name=source_name or path.name
        )
    if include_semantic_snapshot:
        from pine2ast.semantic.snapshot import build_semantic_snapshot_payload

        payload["semantic_snapshot"] = build_semantic_snapshot_payload(
            result, source_path=source_path, source_name=source_name or path.name
        )
    return payload


def inspect_file_payload(path: str | Path, options: ParseOptions | None = None) -> dict[str, Any]:
    result = parse_file(str(path), options or ParseOptions(source_name=str(path)))
    return build_inspect_payload(result, source_path=str(path), source_name=Path(path).name)


def inspect_exit_code(result: ParseResult) -> int:
    if any(d.severity is Severity.FATAL for d in result.diagnostics):
        return 2
    if any(d.severity is Severity.ERROR for d in result.diagnostics):
        return 1
    return 0
