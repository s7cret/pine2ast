from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pine2ast.api import ParseOptions, parse_file
from pine2ast.ast.schema import validate_ast_schema
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics.reports import summarize_diagnostics


@dataclass(slots=True)
class QualityFileReport:
    file: str
    parse_ok: bool
    schema_ok: bool
    diagnostic_count: int
    error_count: int
    fatal_count: int
    warning_count: int
    node_count: int
    codes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.parse_ok and self.schema_ok and self.error_count == 0 and self.fatal_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "ok": self.ok,
            "parse_ok": self.parse_ok,
            "schema_ok": self.schema_ok,
            "diagnostic_count": self.diagnostic_count,
            "error_count": self.error_count,
            "fatal_count": self.fatal_count,
            "warning_count": self.warning_count,
            "node_count": self.node_count,
            "codes": self.codes,
        }


@dataclass(slots=True)
class QualityGateReport:
    schema_version: int
    path: str
    file_count: int
    ok_count: int
    error_count: int
    fatal_count: int
    warning_count: int
    schema_error_count: int
    diagnostic_summary: dict[str, Any]
    files: list[QualityFileReport]

    @property
    def ok(self) -> bool:
        return (
            self.file_count == self.ok_count
            and self.error_count == 0
            and self.fatal_count == 0
            and self.schema_error_count == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "path": self.path,
            "file_count": self.file_count,
            "ok_count": self.ok_count,
            "error_count": self.error_count,
            "fatal_count": self.fatal_count,
            "warning_count": self.warning_count,
            "schema_error_count": self.schema_error_count,
            "diagnostic_summary": self.diagnostic_summary,
            "files": [row.to_dict() for row in self.files],
        }


def _pine_files(root: Path) -> list[Path]:
    if root.suffix == ".pine":
        return [root]
    rows: list[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if filename.endswith(".pine"):
                rows.append(Path(dirpath) / filename)
    return sorted(rows)


def quality_gate(path: str | Path, *, run_semantic: bool = True) -> QualityGateReport:
    root = Path(path)
    files = _pine_files(root)
    rows: list[QualityFileReport] = []
    all_diagnostics = []
    for file in files:
        rel = str(file.relative_to(root)) if root.suffix != ".pine" else str(file)
        result = parse_file(
            str(file), ParseOptions(source_name=str(file), run_semantic=run_semantic)
        )
        all_diagnostics.extend(result.diagnostics)
        schema_report = validate_ast_schema(result.ast) if result.ast else None
        fatal_count = sum(1 for d in result.diagnostics if d.severity is Severity.FATAL)
        error_count = sum(1 for d in result.diagnostics if d.severity is Severity.ERROR)
        warning_count = sum(1 for d in result.diagnostics if d.severity is Severity.WARNING)
        rows.append(
            QualityFileReport(
                file=rel,
                parse_ok=result.ok,
                schema_ok=bool(schema_report and schema_report.ok),
                diagnostic_count=len(result.diagnostics),
                error_count=error_count,
                fatal_count=fatal_count,
                warning_count=warning_count,
                node_count=schema_report.node_count if schema_report else 0,
                codes=[d.code for d in result.diagnostics],
            )
        )
    summary = summarize_diagnostics(all_diagnostics).to_dict()
    return QualityGateReport(
        schema_version=1,
        path=str(root),
        file_count=len(rows),
        ok_count=sum(1 for row in rows if row.ok),
        error_count=sum(row.error_count for row in rows),
        fatal_count=sum(row.fatal_count for row in rows),
        warning_count=sum(row.warning_count for row in rows),
        schema_error_count=sum(0 if row.schema_ok else 1 for row in rows),
        diagnostic_summary=summary,
        files=rows,
    )


def quality_gate_json(path: str | Path, *, run_semantic: bool = True, indent: int = 2) -> str:
    return json.dumps(
        quality_gate(path, run_semantic=run_semantic).to_dict(), ensure_ascii=False, indent=indent
    )
