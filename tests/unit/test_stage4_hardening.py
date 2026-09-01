from __future__ import annotations
import pytest
from pine2ast.hardening.completeness import run_static_completeness_gate
from pine2ast.hardening.consumer_bundle import (
    ConsumerBundleError,
    build_consumer_bundle,
    verify_consumer_bundle,
)
from pine2ast.hardening.corpus import load_case_source, run_corpus_gate
from pine2ast.hardening.differential import run_differential_gate
from pine2ast.hardening.fuzzing import run_fuzz_gate
from pine2ast.hardening.mutation import run_contract_mutation_gate
from pine2ast.hardening.release_gate import run_stage4_gate


def test_static_completeness():
    assert run_static_completeness_gate().ok


def test_corpus():
    assert run_corpus_gate().ok


def test_differential():
    assert run_differential_gate().ok


def test_fuzz_quick():
    assert run_fuzz_gate(cases=120, seed=1234).ok


def test_bundle_roundtrip():
    source = load_case_source("v6_strategy_orders.pine")
    b = build_consumer_bundle(source)
    verify_consumer_bundle(b, source=source)


def test_bundle_tamper_rejected():
    source = load_case_source("v6_strategy_orders.pine")
    b = build_consumer_bundle(source)
    b["ast"]["kind"] = "Mutated"
    with pytest.raises(ConsumerBundleError):
        verify_consumer_bundle(b, source=source)


def test_contract_mutations_all_killed():
    source = load_case_source("v6_strategy_orders.pine")
    b = build_consumer_bundle(source)
    r = run_contract_mutation_gate(b, source=source)
    assert r.ok
    assert not r.metrics["survived"]


@pytest.mark.performance
def test_release_gate_quick(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    report = run_stage4_gate(root, fuzz_cases=60, performance_repeats=1)
    assert report["producer_status"] == "PASS"
    assert report["coordinated_status"] == "PENDING_COORDINATED_CONSUMER"
    assert report["claims"]["ast2python_rc6_acceptance"] is False
