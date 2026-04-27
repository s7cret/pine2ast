from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Any

from pine2ast.diagnostics.diagnostic import Diagnostic, Severity


def _level(severity: Severity) -> str:
    if severity is Severity.FATAL or severity is Severity.ERROR:
        return "error"
    if severity is Severity.WARNING:
        return "warning"
    return "note"


def diagnostics_to_sarif(
    diagnostics: Iterable[Diagnostic],
    *,
    source_name: str = "<memory>",
    tool_name: str = "pine2ast",
    tool_version: str | None = None,
) -> dict[str, Any]:
    """Convert Pine2AST diagnostics to SARIF 2.1.0.

    The output is intentionally compact but valid enough for GitHub Code Scanning,
    CI quality dashboards and static-analysis baselines. The converter does not
    read files or execute user code; it only maps existing diagnostics.
    """
    diag_list = list(diagnostics)
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    uri = str(source_name)
    for diag in diag_list:
        rules.setdefault(
            diag.code,
            {
                "id": diag.code,
                "name": diag.code,
                "shortDescription": {"text": diag.code},
                "helpUri": diag.doc_url or "",
            },
        )
        span = diag.span
        region = {
            "startLine": span.start_line,
            "startColumn": span.start_col,
            "endLine": span.end_line,
            "endColumn": max(span.end_col, span.start_col + 1),
        }
        result: dict[str, Any] = {
            "ruleId": diag.code,
            "level": _level(diag.severity),
            "message": {"text": diag.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": region,
                    }
                }
            ],
        }
        if diag.hint:
            result["properties"] = {"hint": diag.hint}
        results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "semanticVersion": tool_version or "0.0.0",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def diagnostics_to_sarif_json(
    diagnostics: Iterable[Diagnostic],
    *,
    source_name: str = "<memory>",
    tool_name: str = "pine2ast",
    tool_version: str | None = None,
    indent: int = 2,
) -> str:
    return json.dumps(
        diagnostics_to_sarif(
            diagnostics,
            source_name=source_name,
            tool_name=tool_name,
            tool_version=tool_version,
        ),
        ensure_ascii=False,
        indent=indent,
    )


def write_sarif(path: str | Path, diagnostics: Iterable[Diagnostic], **kwargs: Any) -> None:
    Path(path).write_text(diagnostics_to_sarif_json(diagnostics, **kwargs), encoding="utf-8")
