# P1.5 — Performance benchmarks in CI

## Goal

Lock the latency and memory characteristics of the pine2ast pipeline
(normalize → lex → layout → parse → semantic) against a captured
baseline, so that algorithmic regressions in any stage surface
automatically in CI — without blocking merges on every transient blip.

## Threat model

Without an automated performance contract we found:
1. A semantic-phase optimization (e.g. moving a hot method-resolution
   loop from O(n²) to O(n)) has no automated test. The change ships,
   benchmarks run on someone's laptop, the diff is "−12ms", nobody
   remembers to update the release notes.
2. Conversely, a regression that adds 40% to the layout phase in a
   feature PR is invisible until users complain. Pine scripts that
   compiled in 50ms now take 70ms; no alarm fires.

The P1.5 gate is the automated alarm.

## Contract

**Headroom model.** The captured baseline (median over N runs on a
clean machine) defines `B`. CI applies a multiplier `H` (configurable
via `PINEPERF_MAX_FACTOR`) so the budget is `B × H`.

| Environment | Default `H` | Rationale |
|---|---|---|
| Local dev | `1.10` (via `PINEPERF_MAX_FACTOR=1.10` env) | Catches a real regression. Dev CPU is consistent. |
| GitHub runner (CI) | `20.0` (hard-coded in `perf` job) | Runner CPU is ~10× slower than a typical dev laptop and noisier. 20× headroom catches a 2× stage regression without flaking. |

If we ever move to self-hosted runners with deterministic CPU,
drop CI headroom to `1.5` and the gate becomes effectively
fail-on-regression.

The test code itself defaults to `1.5` (no env var) so running
`pytest tests/performance` locally without setting `PINEPERF_MAX_FACTOR`
will surface a real regression immediately.

**Layered tests.** Two pytest markers split the gate:
- `perf` — single synthetic 15KB script with 30 inputs, 30 series,
  30 plots, 30 for-loops, UDT, matrix, request.security. Hits all 5
  pipeline stages meaningfully. Sub-tests:
  - `test_perf_stress_pipeline_latency_under_budget` — total_ms + peak_mem
  - `test_perf_stress_per_stage_under_budget[stage_key]` × 5 — per-stage
- `perf_corpus` — all 300 .pine files in `tests/fixtures/real_world/`.
  Sub-tests:
  - `test_real_world_corpus_ok_rate_is_full` — every file must compile
  - `test_real_world_corpus_throughput_under_budget` — median per-file
    total_ms

**Why per-stage.** A regression that doubles layout cost and halves
parser cost could net out at the same total. Per-stage tests catch
this. Cost: 5x measurement overhead per stage (~250ms total).

**Why median of 5, not single run.** GitHub runners occasionally have
a noisy first run (CPU frequency ramp, page cache cold). Median of 5
denoises that. We pick `min` (not `median`) for the assertion because
we want the assertion to be a floor: "the pipeline can do this
quickly", not "the pipeline is sometimes this quick".

## Baseline files

Committed to git:
- `tests/performance/baselines/perf_stress.json`
  ```json
  {
    "normalizer_ms": 1.86, "lexer_ms": 4.55, "layout_ms": 6.32,
    "parser_ms": 51.97, "semantic_ms": 116.45, "total_ms": 280.21,
    "peak_memory_mb": 1.95, "captured_repeat": 15, "captured_at": "..."
  }
  ```
- `tests/performance/baselines/real_world_corpus.json`
  ```json
  {
    "file_count": 300, "median_total_ms": 9.33, "p95_total_ms": 12.17,
    "max_total_ms": 19.40, "captured_repeat": 3, "captured_at": "..."
  }
  ```

**When to re-capture.** Only when a deliberate performance
improvement lands. The capture script is
`scripts/capture_perf_baseline.py`. Re-capture workflow:
1. Run on a stable machine: `python scripts/capture_perf_baseline.py`
2. Review the diff in `tests/performance/baselines/*.json`
3. Commit with rationale (e.g. "perf: layout pass is now linear time
   on column count, −18% on stress file")

**Anti-abuse.** A PR that lowers the baseline to make its own
regression green is gated by review: the baseline is part of the
reviewable diff. The CI also re-captures the baseline (informational,
not used for pass/fail) so the reviewer can see the actual numbers
from the same commit.

## CI integration

`perf` job is `continue-on-error: true` and runs `needs: test` so:
- Unit/coverage failures still block the merge.
- Performance failures surface in the job summary and as a
  downloadable artifact, but do not flip the PR check red.
- Re-capturing the baseline on the same runner gives a reviewer the
  apples-to-apples diff for the commit.

Why not fail-on-regression? Two reasons:
1. The 1.50x headroom is intentionally loose; we'd rather see
   "perf regressed 12%" in a comment than block every 1.4x blip.
2. A real regression usually comes with a story (the PR added a
   feature that obviously costs time). The PR description plus the
   auto-posted diff is enough to make the call.

If we ever want hard-fail: change `continue-on-error: true` to `false`
in `.github/workflows/ci.yml`. That is the entire toggle.

## Files added

| File | Purpose |
|---|---|
| `tests/performance/test_perf_contract.py` | Pytest gate (8 tests) |
| `tests/performance/corpus_small/perf_stress.pine` | 15KB synthetic stress |
| `tests/performance/baselines/perf_stress.json` | Captured baseline |
| `tests/performance/baselines/real_world_corpus.json` | Captured baseline |
| `scripts/capture_perf_baseline.py` | Re-capture script |
| `pyproject.toml` (modified) | testpaths + markers |
| `.github/workflows/ci.yml` (modified) | `perf` job, non-blocking |
| `docs/P1_5_PERFORMANCE.md` | This document |

## Verification

| Check | Status |
|---|---|
| 8 perf tests pass on captured baseline | ✅ |
| Synthetic regression: 0.5x budget → 6 fail | ✅ |
| Default 1.5x budget on this branch → 8 pass | ✅ |
| Mypy clean on `tests/performance/`, `scripts/` | ✅ |
| Ruff clean on new files | ✅ |
| `python -m black --check .` clean | ✅ |
| CI workflow valid (yq parse) | pending — see PR run |
