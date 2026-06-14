from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pine2ast.internal.fs import pine_files

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


def quality_gate(path: str | Path, *, run_semantic: bool = True) -> QualityGateReport:
    root = Path(path)
    files = pine_files(root)
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


def duplicate_function_report(path: str | Path = "pine2ast") -> dict[str, Any]:
    """Return a small exact-duplicate implementation report for maintainers.

    This intentionally ignores methods and tiny functions to avoid reporting
    protocol/pass boilerplate. It is a lightweight Stage 1 guard, not a clone
    detector.
    """

    import ast
    import hashlib

    root = Path(path)
    groups: dict[str, list[dict[str, Any]]] = {}
    for py_file in sorted(root.rglob("*.py") if root.is_dir() else [root]):
        if "__pycache__" in py_file.parts:
            continue
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(parents.get(node), ast.ClassDef):
                continue
            if node.end_lineno is None or node.end_lineno - node.lineno < 5:
                continue
            normalized = ast.dump(
                ast.Module(body=[*node.body], type_ignores=[]),
                include_attributes=False,
            )
            args_shape = ast.dump(node.args, include_attributes=False)
            digest = hashlib.sha256((args_shape + "\n" + normalized).encode("utf-8")).hexdigest()
            groups.setdefault(digest, []).append(
                {"file": str(py_file), "name": node.name, "line": node.lineno}
            )
    duplicates = [items for items in groups.values() if len(items) > 1]
    return {
        "schema_version": "pine2ast.quality.duplicates.v1",
        "path": str(root),
        "duplicate_group_count": len(duplicates),
        "duplicates": duplicates,
    }


def duplicates_json(path: str | Path = "pine2ast", *, indent: int = 2) -> str:
    return json.dumps(duplicate_function_report(path), ensure_ascii=False, indent=indent)


@dataclass(slots=True)
class ArchitectureBudgetFile:
    file: str
    line_count: int
    max_lines: int

    @property
    def ok(self) -> bool:
        return self.line_count <= self.max_lines

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line_count": self.line_count,
            "max_lines": self.max_lines,
            "ok": self.ok,
        }


@dataclass(slots=True)
class ArchitectureBudgetReport:
    schema_version: str
    path: str
    max_lines: int
    file_count: int
    oversized: list[ArchitectureBudgetFile]

    @property
    def ok(self) -> bool:
        return not self.oversized

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "path": self.path,
            "max_lines": self.max_lines,
            "file_count": self.file_count,
            "oversized_count": len(self.oversized),
            "oversized": [row.to_dict() for row in self.oversized],
        }


def architecture_budget_report(
    path: str | Path = "pine2ast",
    *,
    max_lines: int = 700,
    exclude: tuple[str, ...] = ("__pycache__",),
) -> ArchitectureBudgetReport:
    """Return a lightweight module-size budget report for release hygiene.

    The gate is intentionally simple: it keeps frontend modules small enough for
    code review after the 4.0 semantic-mixin split. Generated JSON files and test
    fixtures are outside this report; only Python modules below ``path`` are
    counted.
    """

    root = Path(path)
    py_files = sorted(root.rglob("*.py") if root.is_dir() else [root])
    checked: list[Path] = []
    oversized: list[ArchitectureBudgetFile] = []
    for py_file in py_files:
        if any(part in exclude for part in py_file.parts):
            continue
        checked.append(py_file)
        line_count = sum(1 for _ in py_file.open(encoding="utf-8"))
        if line_count > max_lines:
            oversized.append(
                ArchitectureBudgetFile(
                    file=str(py_file),
                    line_count=line_count,
                    max_lines=max_lines,
                )
            )
    return ArchitectureBudgetReport(
        schema_version="pine2ast.quality.architecture_budget.v1",
        path=str(root),
        max_lines=max_lines,
        file_count=len(checked),
        oversized=oversized,
    )


def architecture_budget_json(
    path: str | Path = "pine2ast", *, max_lines: int = 700, indent: int = 2
) -> str:
    return json.dumps(
        architecture_budget_report(path, max_lines=max_lines).to_dict(),
        ensure_ascii=False,
        indent=indent,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m pine2ast.quality")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_duplicates = sub.add_parser("duplicates")
    p_duplicates.add_argument("path", nargs="?", default="pine2ast")
    p_duplicates.add_argument("--json", dest="json_path")

    p_architecture = sub.add_parser("architecture")
    p_architecture.add_argument("path", nargs="?", default="pine2ast")
    p_architecture.add_argument("--max-lines", type=int, default=700)
    p_architecture.add_argument("--json", dest="json_path")

    p_architecture_budget = sub.add_parser("architecture-budget")
    p_architecture_budget.add_argument("path", nargs="?", default="pine2ast")
    p_architecture_budget.add_argument("--max-lines", type=int, default=700)
    p_architecture_budget.add_argument("--json", dest="json_path")

    args = parser.parse_args(argv)
    if args.cmd == "duplicates":
        output = duplicates_json(args.path)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        payload = json.loads(output)
        return 0 if payload.get("duplicate_group_count") == 0 else 1
    if args.cmd in {"architecture", "architecture-budget"}:
        output = architecture_budget_json(args.path, max_lines=args.max_lines)
        if args.json_path:
            Path(args.json_path).write_text(output, encoding="utf-8")
            print(args.json_path)
        else:
            print(output)
        payload = json.loads(output)
        return 0 if payload.get("ok") is True else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
