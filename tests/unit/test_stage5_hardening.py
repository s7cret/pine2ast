from __future__ import annotations

from pathlib import Path

import pytest

from pine2ast.hardening.historical import run_historical_corpus_gate
from pine2ast.hardening.historical_catalog import run_historical_catalog_gate
from pine2ast.hardening.historical_differential import run_historical_differential_gate
from pine2ast.hardening.stage5_release_gate import run_all_version_consumer_gate, run_stage5_gate


def test_stage5_historical_corpus():
    result = run_historical_corpus_gate()
    assert result.ok, result.to_dict()


def test_stage5_historical_differentials():
    result = run_historical_differential_gate()
    assert result.ok, result.to_dict()


def test_stage5_historical_catalog_identity():
    result = run_historical_catalog_gate()
    assert result.ok, result.to_dict()


def test_stage5_all_version_consumer_bundles_and_mutations():
    result, bundles = run_all_version_consumer_gate(mutate=True)
    assert result.ok, result.to_dict()
    assert set(bundles) == set(range(1, 7))


@pytest.mark.performance
def test_stage5_release_gate_quick():
    root = Path(__file__).resolve().parents[2]
    report = run_stage5_gate(root, fuzz_cases=66, performance_repeats=1, mutate_consumers=False)
    assert report["producer_status"] == "PASS", report
    assert report["coordinated_status"] == "PENDING_COORDINATED_CONSUMER"
    assert report["release_authorized"] is False
    assert report["claims"]["tradingview_runtime_parity"] is False
