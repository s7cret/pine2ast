from __future__ import annotations

import json
import os
import time
import tracemalloc
from pathlib import Path
from typing import Any

from pine2ast.ast.visitors import walk
from pine2ast.lexer import Lexer
from pine2ast.layout import LayoutProcessor
from pine2ast.parser import Parser
from pine2ast.semantic import SemanticAnalyzer
from pine2ast.source import SourceNormalizer


def _parse_once(source: str | bytes, *, source_name: str, run_semantic: bool = True) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    t0 = time.perf_counter()
    normalized = SourceNormalizer().normalize(source, source_name=source_name)
    metrics["normalizer_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    lexed = Lexer(normalized.text, source_name=source_name).lex()
    metrics["lexer_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    layout = LayoutProcessor().process(lexed.tokens)
    metrics["layout_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    parsed = Parser(layout.tokens).parse()
    metrics["parser_ms"] = (time.perf_counter() - t0) * 1000

    semantic_diagnostics = []
    semantic_model = None
    t0 = time.perf_counter()
    if run_semantic and parsed.program is not None:
        semantic_model = SemanticAnalyzer().analyze(parsed.program)
        semantic_diagnostics = semantic_model.diagnostics
    metrics["semantic_ms"] = (time.perf_counter() - t0) * 1000

    diagnostics = normalized.diagnostics + lexed.diagnostics + layout.diagnostics + parsed.diagnostics + semantic_diagnostics
    metrics["token_count"] = len(layout.tokens)
    metrics["ast_node_count"] = sum(1 for _ in walk(parsed.program)) if parsed.program else 0
    metrics["diagnostic_count"] = len(diagnostics)
    metrics["ok"] = parsed.program is not None and not any(getattr(d, "severity", None).value in {"ERROR", "FATAL"} for d in diagnostics)
    return metrics


def _avg(rows: list[dict[str, Any]], key: str) -> float:
    return sum(float(r.get(key, 0.0)) for r in rows) / max(1, len(rows))


def _pine_files(root: Path) -> list[Path]:
    if root.suffix == ".pine":
        return [root]
    rows: list[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for filename in filenames:
            if filename.endswith(".pine"):
                rows.append(Path(dirpath) / filename)
    return sorted(rows)


def bench_corpus(path: str | Path, *, repeat: int = 20, baseline: dict[str, Any] | None = None, run_semantic: bool = True) -> dict[str, Any]:
    root = Path(path)
    files = _pine_files(root)
    baseline_by_file = {row.get("file"): row for row in (baseline or {}).get("files", [])}
    rows: list[dict[str, Any]] = []

    for file in files:
        src = file.read_bytes()
        rel = str(file.relative_to(root)) if root.suffix != ".pine" else str(file)
        measurements: list[dict[str, Any]] = []
        tracemalloc.start()
        total_start = time.perf_counter()
        for _ in range(max(1, repeat)):
            m = _parse_once(src, source_name=str(file), run_semantic=run_semantic)
            m["total_ms"] = sum(float(m.get(k, 0.0)) for k in ("normalizer_ms", "lexer_ms", "layout_ms", "parser_ms", "semantic_ms"))
            measurements.append(m)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        elapsed_total = (time.perf_counter() - total_start) * 1000
        last = measurements[-1]
        row = {
            "file": rel,
            "source_bytes": len(src),
            "line_count": src.count(b"\n") + 1,
            "token_count": last["token_count"],
            "ast_node_count": last["ast_node_count"],
            "diagnostic_count": last["diagnostic_count"],
            "normalizer_ms": _avg(measurements, "normalizer_ms"),
            "lexer_ms": _avg(measurements, "lexer_ms"),
            "layout_ms": _avg(measurements, "layout_ms"),
            "parser_ms": _avg(measurements, "parser_ms"),
            "semantic_ms": _avg(measurements, "semantic_ms"),
            "total_ms": _avg(measurements, "total_ms"),
            "wall_ms_total": elapsed_total,
            "peak_memory_mb": peak / (1024 * 1024),
            "ok": last["ok"],
        }
        base = baseline_by_file.get(rel)
        if base and float(base.get("total_ms", 0.0)) > 0:
            growth = (row["total_ms"] - float(base["total_ms"])) / float(base["total_ms"])
            row["baseline_growth_pct"] = growth * 100
            if growth > 0.25:
                row["regression_warning"] = True
        rows.append(row)

    total_files = len(rows)
    result = {
        "schema_version": 1,
        "repeat": repeat,
        "run_semantic": run_semantic,
        "files": rows,
        "summary": {
            "file_count": total_files,
            "ok_count": sum(1 for r in rows if r.get("ok")),
            "diagnostic_count": sum(int(r.get("diagnostic_count", 0)) for r in rows),
            "total_ms_avg": _avg(rows, "total_ms") if rows else 0.0,
            "peak_memory_mb_max": max((float(r.get("peak_memory_mb", 0.0)) for r in rows), default=0.0),
        },
    }
    return result


def bench_corpus_json(path: str | Path, *, repeat: int = 20, baseline_path: str | Path | None = None, run_semantic: bool = True, indent: int = 2) -> str:
    baseline = None
    if baseline_path:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    return json.dumps(bench_corpus(path, repeat=repeat, baseline=baseline, run_semantic=run_semantic), ensure_ascii=False, indent=indent)
