from __future__ import annotations

import gc
import platform
import statistics
import time
import tracemalloc
from typing import Any

from .introspection import parse_source, result_ok
from .model import GateFinding, GateResult, content_hash


def generate_script(lines: int, *, version: int = 6) -> str:
    body = [f"//@version={version}", f'indicator("perf-{lines}")', "x0 = close"]
    for i in range(1, lines):
        body.append(f"x{i} = x{i - 1} + 1")
    return "\n".join(body) + "\n"


def _measure(source: str, repeats: int) -> dict[str, Any]:
    samples = []
    peaks = []
    for _ in range(repeats):
        gc.collect()
        tracemalloc.start()
        start = time.perf_counter_ns()
        result = parse_source(source, source_name="performance.pine")
        elapsed = time.perf_counter_ns() - start
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if not result_ok(result):
            raise RuntimeError("performance corpus failed to parse")
        samples.append(elapsed)
        peaks.append(peak)
    return {
        "median_ms": statistics.median(samples) / 1_000_000,
        "pmax_ms": max(samples) / 1_000_000,
        "peak_bytes": max(peaks),
        "samples_ns": samples,
    }


def run_performance_gate(
    *, repeats: int = 3, small_lines: int = 120, large_lines: int = 900
) -> GateResult:
    # Warmup removes one-time import/cache effects without hiding per-parse allocations.
    parse_source(generate_script(20), source_name="warmup.pine")
    small = _measure(generate_script(small_lines), repeats)
    large = _measure(generate_script(large_lines), repeats)
    findings = []
    ratio = large["median_ms"] / max(small["median_ms"], 0.001)
    line_ratio = large_lines / small_lines
    # These are portability-oriented hard ceilings, not machine-specific promises.
    if large["median_ms"] > 20_000:
        findings.append(
            GateFinding("S4_PERF_TIME", "900-line static frontend pass exceeded 20 seconds")
        )
    if large["peak_bytes"] > 512 * 1024 * 1024:
        findings.append(
            GateFinding("S4_PERF_MEMORY", "900-line static frontend pass exceeded 512 MiB")
        )
    if ratio > line_ratio * 4.0:
        findings.append(
            GateFinding(
                "S4_PERF_SCALING",
                f"superlinear regression ratio {ratio:.2f} for line ratio {line_ratio:.2f}",
            )
        )
    metrics = {
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "small": {"lines": small_lines, **small},
        "large": {"lines": large_lines, **large},
        "time_ratio": ratio,
        "line_ratio": line_ratio,
    }
    metrics["benchmark_hash"] = content_hash(
        {"small_lines": small_lines, "large_lines": large_lines, "repeats": repeats}
    )
    return GateResult("stage4.performance", "PASS" if not findings else "FAIL", findings, metrics)
