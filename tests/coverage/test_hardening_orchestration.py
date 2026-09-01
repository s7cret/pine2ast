from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pine2ast.hardening import (
    cli,
    hygiene,
    performance,
    release_gate,
    stage5_cli,
    stage5_release_gate,
)
from pine2ast.hardening.model import GateFinding, GateResult


def _gate(name: str = "test", *, ok: bool = True) -> GateResult:
    findings = [] if ok else [GateFinding("FAIL", "failed")]
    return GateResult(name, "PASS" if ok else "FAIL", findings, {"name": name})


def test_hygiene_gate_scans_only_shipping_sources_and_reports_paths_and_symbols(
    tmp_path: Path,
) -> None:
    package = tmp_path / "pine2ast"
    package.mkdir()
    (package / "clean.py").write_text("value = 1\n", encoding="utf-8")
    (package / "hardening").mkdir()
    (package / "hardening" / "hygiene.py").write_text("strict_v6 = True\n", encoding="utf-8")
    (package / "legacy.py").write_text("target_version = 6\n", encoding="utf-8")
    (package / "ignored.txt").write_text("strict_v6\n", encoding="utf-8")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "ignored.py").write_text("strict_v6 = True\n", encoding="utf-8")
    legacy_dir = package / "compatibility"
    legacy_dir.mkdir()
    (legacy_dir / "module.py").write_text("value = 1\n", encoding="utf-8")

    result = hygiene.run_hygiene_gate(tmp_path)
    assert not result.ok
    codes = [finding.code for finding in result.findings]
    assert "S4_LEGACY_PATH" in codes
    assert "S4_LEGACY_SYMBOL" in codes
    # The dedicated hygiene source is intentionally ignored to avoid self-matches.
    assert all(
        "pine2ast/hardening/hygiene.py" not in finding.message for finding in result.findings
    )
    assert result.metrics["scanned_files"] == 4

    (package / "legacy.py").write_text("value = 2\n", encoding="utf-8")
    (legacy_dir / "module.py").unlink()
    legacy_dir.rmdir()
    assert hygiene.run_hygiene_gate(tmp_path).ok


def test_performance_helpers_measure_success_error_and_threshold_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = performance.generate_script(3, version=5)
    assert script.splitlines() == [
        "//@version=5",
        'indicator("perf-3")',
        "x0 = close",
        "x1 = x0 + 1",
        "x2 = x1 + 1",
    ]

    monkeypatch.setattr(
        performance, "parse_source", lambda *args, **kwargs: SimpleNamespace(ok=True)
    )
    monkeypatch.setattr(performance, "result_ok", lambda result: result.ok)
    samples = iter([1_000_000, 1_500_000, 2_000_000, 2_500_000])
    monkeypatch.setattr(performance.time, "perf_counter_ns", lambda: next(samples))
    monkeypatch.setattr(performance.tracemalloc, "get_traced_memory", lambda: (0, 1234))
    measured = performance._measure("source", repeats=2)
    assert measured["samples_ns"] == [500_000, 500_000]
    assert measured["median_ms"] == 0.5
    assert measured["peak_bytes"] == 1234

    monkeypatch.setattr(performance, "result_ok", lambda result: False)
    error_samples = iter([10, 20])
    monkeypatch.setattr(performance.time, "perf_counter_ns", lambda: next(error_samples))
    with pytest.raises(RuntimeError, match="failed to parse"):
        performance._measure("source", repeats=1)

    sequence = iter(
        [
            {"median_ms": 1.0, "pmax_ms": 2.0, "peak_bytes": 100, "samples_ns": [1]},
            {
                "median_ms": 21_000.0,
                "pmax_ms": 22_000.0,
                "peak_bytes": 513 * 1024 * 1024,
                "samples_ns": [2],
            },
        ]
    )
    monkeypatch.setattr(performance, "_measure", lambda source, repeats: next(sequence))
    monkeypatch.setattr(
        performance, "parse_source", lambda *args, **kwargs: SimpleNamespace(ok=True)
    )
    result = performance.run_performance_gate(repeats=1, small_lines=10, large_lines=20)
    assert not result.ok
    assert {finding.code for finding in result.findings} == {
        "S4_PERF_TIME",
        "S4_PERF_MEMORY",
        "S4_PERF_SCALING",
    }


def test_stage4_catalog_and_consumer_gates_cover_pass_and_fail_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not release_gate._catalog_gate(tmp_path).ok
    tool = tmp_path / "tools" / "catalog" / "build_catalog.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("pass\n", encoding="utf-8")

    monkeypatch.setattr(
        release_gate.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    assert release_gate._catalog_gate(tmp_path).ok
    monkeypatch.setattr(
        release_gate.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="drift", stderr="bad"),
    )
    failed = release_gate._catalog_gate(tmp_path)
    assert not failed.ok and failed.findings[0].details == {"stdout": "drift", "stderr": "bad"}

    source = "//@version=6\nindicator('x')\n"
    bundle = {
        "content_hash": "sha256:bundle",
        "artifacts": {"ast_hash": "sha256:ast", "semantic_facts_hash": "sha256:facts"},
        "node_index": [1, 2],
    }
    monkeypatch.setattr(release_gate, "load_case_source", lambda name: source)
    monkeypatch.setattr(release_gate, "build_consumer_bundle", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(release_gate, "verify_consumer_bundle", lambda *args, **kwargs: None)
    result, actual_bundle, actual_source = release_gate._consumer_gate()
    assert result.ok and actual_bundle is bundle and actual_source == source
    assert result.metrics["node_count"] == 2

    monkeypatch.setattr(
        release_gate,
        "verify_consumer_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("tampered")),
    )
    result, actual_bundle, _ = release_gate._consumer_gate()
    assert not result.ok and actual_bundle == {}


def test_stage4_release_orchestration_pass_fail_and_coordinated_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pass_gate = _gate()
    for name in (
        "_catalog_gate",
        "run_static_completeness_gate",
        "run_hygiene_gate",
        "run_corpus_gate",
        "run_differential_gate",
        "run_fuzz_gate",
        "run_performance_gate",
        "run_contract_mutation_gate",
    ):
        monkeypatch.setattr(release_gate, name, lambda *args, **kwargs: pass_gate)
    monkeypatch.setattr(release_gate, "_consumer_gate", lambda: (pass_gate, {"x": 1}, "source"))
    report = release_gate.run_stage4_gate(tmp_path, fuzz_cases=1, performance_repeats=1)
    assert report["producer_status"] == "PASS"
    assert report["producer_review_ready"] is True
    assert report["coordinated_findings"] == []

    coordinated = release_gate.run_stage4_gate(tmp_path, coordinated=True)
    assert coordinated["coordinated_status"] == "PENDING_COORDINATED_CONSUMER"
    assert coordinated["coordinated_findings"][0]["code"].endswith("ACCEPTANCE_REQUIRED")

    monkeypatch.setattr(release_gate, "_consumer_gate", lambda: (_gate(ok=False), {}, "source"))
    failed = release_gate.run_stage4_gate(tmp_path)
    assert failed["producer_status"] == "FAIL"


def _bundle(version: int, *, catalog: str | None = None) -> dict[str, Any]:
    return {
        "content_hash": f"sha256:bundle-{version}",
        "version_context": {
            "pine_version": version,
            "catalog_hash": catalog or f"sha256:catalog-{version}",
        },
        "artifacts": {
            "ast_hash": f"sha256:ast-{version}",
            "semantic_facts_hash": f"sha256:facts-{version}",
        },
        "node_index": [version],
    }


def test_stage5_catalog_sources_consumer_mutants_and_collapse_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not stage5_release_gate._catalog_gate(tmp_path).ok
    tool = tmp_path / "tools" / "catalog" / "build_catalog.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(
        stage5_release_gate.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    assert stage5_release_gate._catalog_gate(tmp_path).ok
    monkeypatch.setattr(
        stage5_release_gate.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="", stderr="drift"),
    )
    assert not stage5_release_gate._catalog_gate(tmp_path).ok

    monkeypatch.setattr(
        stage5_release_gate, "load_historical_source", lambda name: f"source:{name}"
    )
    assert stage5_release_gate._consumer_source(1)[0].startswith("v1-")
    assert "version=5" in stage5_release_gate._consumer_source(5)[1]
    assert "version=6" in stage5_release_gate._consumer_source(6)[1]

    current = {"version": 0}

    def source(version: int) -> tuple[str, str]:
        current["version"] = version
        return f"v{version}.pine", f"source-{version}"

    monkeypatch.setattr(stage5_release_gate, "_consumer_source", source)
    monkeypatch.setattr(
        stage5_release_gate,
        "build_consumer_bundle",
        lambda *args, **kwargs: _bundle(current["version"]),
    )
    monkeypatch.setattr(stage5_release_gate, "verify_consumer_bundle", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        stage5_release_gate,
        "run_contract_mutation_gate",
        lambda *args, **kwargs: GateResult("mutation", "PASS", [], {"killed": [1, 2]}),
    )
    result, bundles = stage5_release_gate.run_all_version_consumer_gate(mutate=True)
    assert result.ok and set(bundles) == set(range(1, 7))
    assert result.metrics["v1"]["mutants_killed"] == 2

    # No mutation path and a version mismatch are both recorded.
    monkeypatch.setattr(
        stage5_release_gate,
        "build_consumer_bundle",
        lambda *args, **kwargs: _bundle(99, catalog="sha256:same"),
    )
    mismatch, _ = stage5_release_gate.run_all_version_consumer_gate(mutate=False)
    assert not mismatch.ok
    assert "S5_CONSUMER_VERSION" in {finding.code for finding in mismatch.findings}
    assert "S5_CONSUMER_CATALOG_COLLAPSE" in {finding.code for finding in mismatch.findings}

    # Producer failure and mutation failure paths fail closed.
    calls = {"count": 0}

    def build_or_fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            raise ValueError("bad source")
        return _bundle(current["version"])

    monkeypatch.setattr(stage5_release_gate, "build_consumer_bundle", build_or_fail)
    monkeypatch.setattr(
        stage5_release_gate,
        "run_contract_mutation_gate",
        lambda *args, **kwargs: GateResult(
            "mutation", "FAIL", [GateFinding("SURVIVED", "survived")], {"killed": []}
        ),
    )
    failed, _ = stage5_release_gate.run_all_version_consumer_gate(mutate=True)
    assert {finding.code for finding in failed.findings} >= {
        "S5_CONSUMER_BUNDLE",
        "S5_CONSUMER_MUTATION",
    }


def test_stage5_release_orchestration_and_cli_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pass_gate = _gate()
    for name in (
        "_catalog_gate",
        "run_static_completeness_gate",
        "run_hygiene_gate",
        "run_corpus_gate",
        "run_differential_gate",
        "run_historical_corpus_gate",
        "run_historical_differential_gate",
        "run_historical_catalog_gate",
        "run_fuzz_gate",
        "run_performance_gate",
    ):
        monkeypatch.setattr(stage5_release_gate, name, lambda *args, **kwargs: pass_gate)
    monkeypatch.setattr(
        stage5_release_gate,
        "run_all_version_consumer_gate",
        lambda **kwargs: (pass_gate, {}),
    )
    report = stage5_release_gate.run_stage5_gate(tmp_path, coordinated=True)
    assert report["producer_status"] == "PASS"
    assert report["coordinated_findings"]
    monkeypatch.setattr(
        stage5_release_gate,
        "run_all_version_consumer_gate",
        lambda **kwargs: (_gate(ok=False), {}),
    )
    assert stage5_release_gate.run_stage5_gate(tmp_path)["producer_status"] == "FAIL"

    stage4_report = {"producer_status": "PASS"}
    monkeypatch.setattr(cli, "run_stage4_gate", lambda *args, **kwargs: stage4_report)
    assert cli.main(["gate", "--root", str(tmp_path), "--fuzz-cases", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == stage4_report
    assert cli.main(["gate", "--coordinated"]) == 1
    assert json.loads(capsys.readouterr().out) == stage4_report
    stage4_json = tmp_path / "stage4.json"
    assert cli.main(["gate", "--json", str(stage4_json)]) == 0
    assert json.loads(stage4_json.read_text()) == stage4_report
    assert capsys.readouterr().out == ""

    source = tmp_path / "source.pine"
    source.write_text("//@version=6\nindicator('x')\n", encoding="utf-8")
    written: dict[str, str] = {}
    monkeypatch.setattr(
        cli,
        "write_consumer_bundle",
        lambda output, text, source_name: written.update(
            {"output": str(output), "text": text, "source_name": source_name}
        ),
    )
    assert cli.main(["consumer-bundle", str(source), "--output", str(tmp_path / "b.json")]) == 0
    assert written["source_name"] == "source.pine"

    stage5_report = {"producer_status": "PASS"}
    monkeypatch.setattr(stage5_cli, "run_stage5_gate", lambda *args, **kwargs: stage5_report)
    assert stage5_cli.main(["gate", "--no-consumer-mutations"]) == 0
    assert json.loads(capsys.readouterr().out) == stage5_report
    stage5_json = tmp_path / "stage5.json"
    assert stage5_cli.main(["gate", "--json", str(stage5_json)]) == 0
    assert json.loads(stage5_json.read_text()) == stage5_report

    bundles = {1: {"v": 1}, 2: {"v": 2}}
    monkeypatch.setattr(
        stage5_cli,
        "run_all_version_consumer_gate",
        lambda mutate: (pass_gate, bundles),
    )
    vectors = tmp_path / "vectors"
    assert stage5_cli.main(["consumer-vectors", "--output", str(vectors)]) == 0
    assert json.loads((vectors / "pine-v1-consumer-bundle.json").read_text()) == {"v": 1}
    assert json.loads((vectors / "acceptance.json").read_text())["status"] == "PASS"
