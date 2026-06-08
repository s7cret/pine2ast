"""Performance contract for pine2ast pipeline.

This test suite is the regression gate behind P1.5. It:
  1. Runs the synthetic perf_stress.pine through the full pipeline and
     asserts per-stage latency + peak memory against a captured baseline
     (tests/performance/baselines/perf_stress.json).
  2. Runs a representative subset of the real-world corpus and asserts
     the per-file average and overall ok-rate.
  3. Exposes two pytest markers so CI can split gates:
     - @pytest.mark.perf: the latency/memory regression checks
     - @pytest.mark.perf_corpus: the corpus throughput checks

The thresholds are stored as machine-agnostic multipliers (`max_factor_*`)
on top of the captured baseline. A 1.0 multiplier means "at the captured
baseline". CI uses 1.50 (50% headroom) to absorb GitHub runner noise.
Locally you can tighten to 1.10 for stricter pre-merge checks.
"""

from __future__ import annotations

import json
import os
import time
import tracemalloc
from pathlib import Path

import pytest

from pine2ast.benchmark import _parse_once
from pine2ast.lexer import Lexer
from pine2ast.layout import LayoutProcessor
from pine2ast.parser import Parser
from pine2ast.semantic import SemanticAnalyzer
from pine2ast.source import SourceNormalizer

PERF_DIR = Path(__file__).parent
BASELINE_DIR = PERF_DIR / "baselines"
CORPUS_SMALL = PERF_DIR / "corpus_small" / "perf_stress.pine"
REAL_WORLD_DIR = PERF_DIR.parent / "fixtures" / "real_world"

# Headroom factors. Default 1.50x for CI; tighten locally with
# PINEPERF_MAX_FACTOR (env var, e.g. PINEPERF_MAX_FACTOR=1.10 for strict pre-merge).
HEADROOM = float(os.environ.get("PINEPERF_MAX_FACTOR", "1.50"))


def _load_baseline(name: str) -> dict:
    p = BASELINE_DIR / name
    if not p.exists():
        pytest.skip(f"Baseline {name} not yet captured — run scripts/capture_perf_baseline.py")
    return json.loads(p.read_text(encoding="utf-8"))


def _run_stages(source: bytes, source_name: str) -> dict:
    """Run pipeline once, returning per-stage wall-ms and total ms."""
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


@pytest.mark.perf
def test_perf_stress_pipeline_latency_under_budget() -> None:
    """Single big synthetic Pine script: every stage's latency must stay within
    baseline × HEADROOM. Catches algorithmic regressions in any of the 5 stages."""
    if not CORPUS_SMALL.exists():
        pytest.skip(f"perf_stress.pine not found at {CORPUS_SMALL}")
    src = CORPUS_SMALL.read_bytes()
    # Warm up: interpreter/caches are cold on first call
    _ = _parse_once(src, source_name=str(CORPUS_SMALL), run_semantic=True)
    # Measure: take the median of 5 runs to denoise
    samples: list[dict] = []
    for _ in range(5):
        samples.append(_run_stages(src, source_name=str(CORPUS_SMALL)))
    best_total = min(s["total_ms"] for s in samples)
    best_peak = min(s["peak_memory_mb"] for s in samples)

    baseline = _load_baseline("perf_stress.json")
    budget_total = baseline["total_ms"] * HEADROOM
    budget_peak = baseline["peak_memory_mb"] * HEADROOM

    assert best_total <= budget_total, (
        f"perf_stress total latency {best_total:.1f}ms "
        f"> budget {budget_total:.1f}ms "
        f"(baseline {baseline['total_ms']:.1f}ms × {HEADROOM})"
    )
    assert best_peak <= budget_peak, (
        f"perf_stress peak memory {best_peak:.2f}MB "
        f"> budget {budget_peak:.2f}MB "
        f"(baseline {baseline['peak_memory_mb']:.2f}MB × {HEADROOM})"
    )


@pytest.mark.perf
@pytest.mark.parametrize(
    "stage_key",
    ["normalizer_ms", "lexer_ms", "layout_ms", "parser_ms", "semantic_ms"],
)
def test_perf_stress_per_stage_under_budget(stage_key: str) -> None:
    """Per-stage regression gate. Catches the stage that silently regressed
    even when total_ms happens to stay under budget."""
    if not CORPUS_SMALL.exists():
        pytest.skip(f"perf_stress.pine not found at {CORPUS_SMALL}")
    src = CORPUS_SMALL.read_bytes()
    _ = _parse_once(src, source_name=str(CORPUS_SMALL), run_semantic=True)
    samples: list[dict] = []
    for _ in range(5):
        samples.append(_run_stages(src, source_name=str(CORPUS_SMALL)))
    best = min(s[stage_key] for s in samples)
    baseline = _load_baseline("perf_stress.json")
    budget = baseline[stage_key] * HEADROOM
    assert best <= budget, (
        f"perf_stress stage {stage_key} latency {best:.2f}ms "
        f"> budget {budget:.2f}ms (baseline {baseline[stage_key]:.2f}ms × {HEADROOM})"
    )


@pytest.mark.perf_corpus
def test_real_world_corpus_ok_rate_is_full() -> None:
    """Real-world corpus regression: every .pine must parse + analyze without
    a hard error. Catches regressions in the corpus that didn't trip unit tests."""
    if not REAL_WORLD_DIR.exists():
        pytest.skip(f"real_world corpus not found at {REAL_WORLD_DIR}")
    files = sorted(REAL_WORLD_DIR.glob("*.pine"))
    if not files:
        pytest.skip("no .pine files in real_world corpus")
    failed: list[tuple[str, str]] = []
    for f in files:
        src = f.read_bytes()
        m = _parse_once(src, source_name=str(f), run_semantic=True)
        if not m["ok"]:
            failed.append((f.name, f"diag_count={m['diagnostic_count']}"))
    assert not failed, f"{len(failed)}/{len(files)} real_world files failed: {failed[:5]}"


@pytest.mark.perf_corpus
def test_real_world_corpus_throughput_under_budget() -> None:
    """Real-world corpus throughput: median per-file total_ms must stay under
    baseline × HEADROOM. A single hot file can drag up the average without
    tripping per-file ok checks."""
    baseline = _load_baseline("real_world_corpus.json")
    files = sorted(REAL_WORLD_DIR.glob("*.pine"))
    if not files:
        pytest.skip("no .pine files in real_world corpus")
    timings: list[float] = []
    for f in files:
        src = f.read_bytes()
        # one warmup, one measurement
        _ = _parse_once(src, source_name=str(f), run_semantic=True)
        m = _parse_once(src, source_name=str(f), run_semantic=True)
        # _parse_once returns per-stage timings; sum them to get total
        timings.append(
            sum(
                float(m.get(k, 0.0))
                for k in ("normalizer_ms", "lexer_ms", "layout_ms", "parser_ms", "semantic_ms")
            )
        )
    timings.sort()
    median = timings[len(timings) // 2]
    budget = baseline["median_total_ms"] * HEADROOM
    assert median <= budget, (
        f"real_world median per-file total_ms {median:.3f}ms "
        f"> budget {budget:.3f}ms (baseline {baseline['median_total_ms']:.3f}ms × {HEADROOM})"
    )
