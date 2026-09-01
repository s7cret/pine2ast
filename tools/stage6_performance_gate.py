#!/usr/bin/env python3
"""Repeatable Stage 6 performance gate with process-isolated samples.

Large ASTs retain substantial allocator state while ``tracemalloc`` is active.
Running every sample in the gate process can therefore turn later repetitions
into measurements of allocator history rather than frontend performance.  Each
sample is executed in a fresh interpreter, while still warming the catalog and
frontend once before the measured parse.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "stage6_reports"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SIZES = (120, 900, 3000)
REPEATS = 3
WORKER_TIMEOUT_SECONDS = 90


def source(lines: int) -> str:
    body = ["//@version=6", 'indicator("perf")']
    for index in range(lines):
        body.append(f"x{index}=ta.sma(close,{2 + (index % 20)})")
    return "\n".join(body) + "\n"


def _peak_rss_bytes() -> int:
    """Return process peak resident memory in bytes on supported CI platforms."""

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KiB; macOS reports bytes.  Stage 6 CI runs on Linux, while
    # this normalization keeps local macOS runs comparable.
    return value if sys.platform == "darwin" else value * 1024


def measure_once(lines: int) -> dict[str, int | float]:
    """Measure one cold-process parse without profiler-induced distortion."""

    # Keep the orchestration process lightweight.  Importing the frontend only
    # inside workers avoids cross-sample catalog, allocator, and AST state.
    from pine2ast import parse_code

    script = source(lines)
    started = time.perf_counter()
    result = parse_code(script)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if result.ast is None:
        raise RuntimeError("performance measurement did not produce an AST")
    return {
        "elapsed_ms": round(elapsed_ms, 3),
        "peak_bytes": _peak_rss_bytes(),
    }


def run_isolated_sample(lines: int) -> dict[str, int | float]:
    """Run one sample in a fresh interpreter and validate its JSON contract."""

    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker-lines", str(lines)],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=WORKER_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"performance worker failed for {lines} lines: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    payload = json.loads(completed.stdout)
    if payload.get("lines") != lines:
        raise RuntimeError(f"performance worker returned mismatched size for {lines} lines")
    elapsed = payload.get("elapsed_ms")
    peak = payload.get("peak_bytes")
    if not isinstance(elapsed, (int, float)) or elapsed <= 0:
        raise RuntimeError(f"performance worker returned invalid elapsed_ms for {lines} lines")
    if not isinstance(peak, int) or peak <= 0:
        raise RuntimeError(f"performance worker returned invalid peak_bytes for {lines} lines")
    return {"elapsed_ms": float(elapsed), "peak_bytes": peak}


def build_report() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for size in SIZES:
        samples = [run_isolated_sample(size) for _ in range(REPEATS)]
        timings = [float(sample["elapsed_ms"]) for sample in samples]
        peaks = [int(sample["peak_bytes"]) for sample in samples]
        rows.append(
            {
                "lines": size + 2,
                "repeats": REPEATS,
                "isolation": "fresh_process_per_sample",
                "median_ms": round(statistics.median(timings), 3),
                "max_ms": round(max(timings), 3),
                "peak_bytes": max(peaks),
                "samples": samples,
            }
        )

    base = rows[0]
    large = rows[-1]
    line_ratio = float(large["lines"]) / float(base["lines"])
    time_ratio = float(large["median_ms"]) / float(base["median_ms"])
    report: dict[str, Any] = {
        "schema_id": "pine2ast.stage6.performance.v2",
        "measurement_policy": {
            "cache_state": "cold frontend process per sample; no cross-sample state",
            "sample_isolation": "fresh interpreter per sample",
            "latency_instrumentation": "perf_counter only; no tracemalloc distortion",
            "memory_instrumentation": "process peak RSS after the measured parse",
            "repeats_per_size": REPEATS,
            "worker_timeout_seconds": WORKER_TIMEOUT_SECONDS,
        },
        "measurements": rows,
        "line_ratio": round(line_ratio, 3),
        "time_ratio": round(time_ratio, 3),
        "limits": {
            "max_3000_line_ms": 30000,
            "max_peak_bytes": 768 * 1024 * 1024,
            "max_growth_multiplier": 4.0,
        },
    }
    report["checks"] = {
        "latency": float(large["median_ms"]) < 30000,
        "memory": max(int(row["peak_bytes"]) for row in rows) < 768 * 1024 * 1024,
        "growth": time_ratio <= line_ratio * 4.0,
    }
    report["ok"] = all(report["checks"].values())
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-lines", type=int, choices=SIZES, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.worker_lines is not None:
        payload = {"lines": args.worker_lines, **measure_once(args.worker_lines)}
        print(json.dumps(payload, sort_keys=True))
        return 0

    REPORTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    (REPORTS / "performance-gate.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
