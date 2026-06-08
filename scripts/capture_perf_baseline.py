"""Capture the current performance baseline.

Run on a stable machine (dedicated runner, no other load) and commit the
resulting JSON files to tests/performance/baselines/. The pytest contract
test_perf_contract.py reads them as ground truth.

Usage:
    python scripts/capture_perf_baseline.py
    python scripts/capture_perf_baseline.py --stress-repeat 30 --corpus-repeat 5
    python scripts/capture_perf_baseline.py --output-dir /tmp/my-baseline

Output:
    tests/performance/baselines/perf_stress.json       (single big file)
    tests/performance/baselines/real_world_corpus.json  (300-file median)

The capture intentionally uses a higher repeat count than the test gate
to make the captured numbers robust against one-off noise. The gate then
applies a 1.50x headroom factor (PINEPERF_MAX_FACTOR env var).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

# Make pine2ast importable when run as `python scripts/capture_perf_baseline.py`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # noqa: E402

from pine2ast.lexer import Lexer  # noqa: E402
from pine2ast.layout import LayoutProcessor  # noqa: E402
from pine2ast.parser import Parser  # noqa: E402
from pine2ast.semantic import SemanticAnalyzer  # noqa: E402
from pine2ast.source import SourceNormalizer  # noqa: E402

CORPUS_SMALL = ROOT / "tests" / "performance" / "corpus_small" / "perf_stress.pine"
REAL_WORLD_DIR = ROOT / "tests" / "fixtures" / "real_world"
DEFAULT_OUTPUT = ROOT / "tests" / "performance" / "baselines"


def _run_stages(source: bytes, source_name: str) -> dict:
    """Identical stage instrumentation as test_perf_contract.py."""
    metrics: dict[str, float] = {}
    tracemalloc.start()
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

    t0 = time.perf_counter()
    if parsed.program is not None:
        SemanticAnalyzer().analyze(parsed.program)
    metrics["semantic_ms"] = (time.perf_counter() - t0) * 1000

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    metrics["peak_memory_mb"] = peak / (1024 * 1024)
    metrics["total_ms"] = sum(
        metrics[k] for k in ("normalizer_ms", "lexer_ms", "layout_ms", "parser_ms", "semantic_ms")
    )
    return metrics


def capture_stress(repeat: int) -> dict:
    """Capture the synthetic stress file: run repeat times, take median of
    stage timings and peak memory."""
    if not CORPUS_SMALL.exists():
        raise FileNotFoundError(f"perf_stress.pine not found at {CORPUS_SMALL}")
    src = CORPUS_SMALL.read_bytes()
    # Warm up once
    _run_stages(src, source_name=str(CORPUS_SMALL))
    # Median of N runs
    samples: list[dict] = []
    for _ in range(repeat):
        samples.append(_run_stages(src, source_name=str(CORPUS_SMALL)))
    stage_keys = (
        "normalizer_ms",
        "lexer_ms",
        "layout_ms",
        "parser_ms",
        "semantic_ms",
        "total_ms",
        "peak_memory_mb",
    )
    median: dict[str, float] = {}
    for k in stage_keys:
        median[k] = statistics.median(float(s[k]) for s in samples)
    median["captured_repeat"] = float(repeat)
    median["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return median


def capture_corpus(repeat: int) -> dict:
    """Capture real_world corpus: run each file repeat times, take median of
    per-file total_ms. Output the global median + p95."""
    if not REAL_WORLD_DIR.exists():
        raise FileNotFoundError(f"real_world corpus not found at {REAL_WORLD_DIR}")
    files = sorted(REAL_WORLD_DIR.glob("*.pine"))
    if not files:
        raise RuntimeError("no .pine files in real_world corpus")
    # Warm up: one pass
    for f in files:
        _ = _run_stages(f.read_bytes(), source_name=str(f))
    per_file_medians: list[float] = []
    for f in files:
        src = f.read_bytes()
        timings: list[float] = []
        for _ in range(repeat):
            m = _run_stages(src, source_name=str(f))
            timings.append(m["total_ms"])
        per_file_medians.append(statistics.median(timings))
    per_file_medians.sort()
    return {
        "file_count": len(files),
        "captured_repeat": repeat,
        "median_total_ms": statistics.median(per_file_medians),
        "p95_total_ms": per_file_medians[int(0.95 * len(per_file_medians))],
        "max_total_ms": per_file_medians[-1],
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stress-repeat", type=int, default=15)
    ap.add_argument("--corpus-repeat", type=int, default=3)
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument(
        "--skip-corpus",
        action="store_true",
        help="Skip real-world corpus capture (faster; useful for local sanity)",
    )
    ns = ap.parse_args()

    ns.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Capturing stress baseline (repeat={ns.stress_repeat})...", file=sys.stderr)
    stress = capture_stress(ns.stress_repeat)
    stress_out = ns.output_dir / "perf_stress.json"
    stress_out.write_text(json.dumps(stress, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  → {stress_out}", file=sys.stderr)
    print(
        f"  total_ms={stress['total_ms']:.2f}  peak_mem_mb={stress['peak_memory_mb']:.2f}",
        file=sys.stderr,
    )

    if not ns.skip_corpus:
        print(f"Capturing corpus baseline (repeat={ns.corpus_repeat})...", file=sys.stderr)
        corpus = capture_corpus(ns.corpus_repeat)
        corpus_out = ns.output_dir / "real_world_corpus.json"
        corpus_out.write_text(json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  → {corpus_out}", file=sys.stderr)
        print(
            f"  median={corpus['median_total_ms']:.3f}ms  p95={corpus['p95_total_ms']:.3f}ms",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
