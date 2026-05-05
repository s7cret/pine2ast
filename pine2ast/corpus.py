from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pine2ast.api import ParseOptions, parse_file
from pine2ast.diagnostics import Severity


def _pine_files(root: Path) -> list[Path]:
    if root.suffix == ".pine":
        return [root]
    rows: list[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if filename.endswith(".pine"):
                rows.append(Path(dirpath) / filename)
    return sorted(rows)


def validate_corpus(path: str | Path, *, run_semantic: bool = True) -> dict[str, Any]:
    root = Path(path)
    files = _pine_files(root)
    rows: list[dict[str, Any]] = []
    for file in files:
        result = parse_file(
            str(file), ParseOptions(source_name=str(file), run_semantic=run_semantic)
        )
        print(f"DEBUG corpus: {file} -> ok={result.ok}, diag_count={len(result.diagnostics)}")
        for d in result.diagnostics:
            print(f"  diag: {d}")
        errors = [d for d in result.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]
        rel = str(file.relative_to(root)) if root.suffix != ".pine" else str(file)
        rows.append(
            {
                "file": rel,
                "ok": result.ok,
                "diagnostic_count": len(result.diagnostics),
                "error_count": len(errors),
                "codes": [d.code for d in result.diagnostics],
            }
        )
    return {
        "schema_version": 1,
        "file_count": len(rows),
        "ok_count": sum(1 for r in rows if r["ok"]),
        "error_count": sum(int(r["error_count"]) for r in rows),
        "files": rows,
    }


def validate_corpus_json(path: str | Path, *, run_semantic: bool = True, indent: int = 2) -> str:
    return json.dumps(
        validate_corpus(path, run_semantic=run_semantic), ensure_ascii=False, indent=indent
    )
