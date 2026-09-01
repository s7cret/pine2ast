from __future__ import annotations

from types import SimpleNamespace

import pytest

from tools import stage6_performance_gate as performance_gate


def test_performance_source_has_exact_requested_body_size() -> None:
    script = performance_gate.source(3)
    assert script.splitlines() == [
        "//@version=6",
        'indicator("perf")',
        "x0=ta.sma(close,2)",
        "x1=ta.sma(close,3)",
        "x2=ta.sma(close,4)",
    ]


def test_isolated_sample_validates_worker_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = SimpleNamespace(
        returncode=0,
        stdout='{"elapsed_ms": 12.5, "lines": 120, "peak_bytes": 4096}',
        stderr="",
    )
    monkeypatch.setattr(performance_gate.subprocess, "run", lambda *args, **kwargs: completed)
    assert performance_gate.run_isolated_sample(120) == {
        "elapsed_ms": 12.5,
        "peak_bytes": 4096,
    }

    completed.stdout = '{"elapsed_ms": 12.5, "lines": 900, "peak_bytes": 4096}'
    with pytest.raises(RuntimeError, match="mismatched size"):
        performance_gate.run_isolated_sample(120)


def test_report_aggregates_process_isolated_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    elapsed = {120: 10.0, 900: 40.0, 3000: 100.0}

    def fake_sample(lines: int) -> dict[str, int | float]:
        return {"elapsed_ms": elapsed[lines], "peak_bytes": lines * 1024}

    monkeypatch.setattr(performance_gate, "run_isolated_sample", fake_sample)
    report = performance_gate.build_report()

    assert report["schema_id"] == "pine2ast.stage6.performance.v2"
    assert report["measurement_policy"]["sample_isolation"] == "fresh interpreter per sample"
    assert report["ok"] is True
    assert report["checks"] == {"growth": True, "latency": True, "memory": True}
    assert [row["repeats"] for row in report["measurements"]] == [3, 3, 3]
    assert all(len(row["samples"]) == 3 for row in report["measurements"])
