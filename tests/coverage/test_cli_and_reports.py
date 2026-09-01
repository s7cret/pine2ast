from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast import cli
from pine2ast.benchmark import (
    _avg,
    _parse_once,
    bench_corpus,
    bench_corpus_json,
    perf_baseline,
    perf_baseline_json,
)
from pine2ast.cli_commands import (
    _exit_code,
    _parse_options,
    _script_dict,
    _span_dict,
    _unsupported_features,
)
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics.reports import diff_diagnostic_reports, summarize_diagnostics
from pine2ast.distribution import build_distribution_manifest
from pine2ast.inspect_contract import inspect_exit_code, inspect_file_payload
from pine2ast.quality import quality_gate, quality_gate_json
from pine2ast.release import build_release_manifest
from pine2ast.semantic.reports import semantic_report
from pine2ast.semantic.signature_coverage import (
    CategorySignatureCoverage,
    build_signature_coverage_report,
    main as signature_coverage_main,
    signature_coverage_json,
)
from pine2ast.semantic.snapshot import build_semantic_snapshot_json, build_semantic_snapshot_payload

VALID = """//@version=6
indicator("coverage cli")
length = input.int(14, "Length", minval=1, maxval=100, step=1)
value = request.security("AAPL", "D", ta.sma(close, length))
plot(value)
alertcondition(value > 0, "positive")
"""
INVALID = '//@version=99\nindicator("bad")\n'


def _write_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    valid = tmp_path / "valid.pine"
    invalid = tmp_path / "invalid.pine"
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    valid.write_text(VALID, encoding="utf-8")
    invalid.write_text(INVALID, encoding="utf-8")
    (corpus / "a.pine").write_text(VALID, encoding="utf-8")
    (corpus / "b.pine").write_text(
        "//@version=5\nindicator('v5')\nx=ta.sma(close,3)\n", encoding="utf-8"
    )
    return valid, invalid, corpus


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_primary_commands_and_serialized_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    valid, invalid, _ = _write_sources(tmp_path)
    commands = [
        (["parse", str(valid), "--json", str(tmp_path / "ast.json"), "--tokens"], 0),
        (["parse", str(valid)], 0),
        (["parse", str(invalid), "--json", str(tmp_path / "bad.json")], 1),
        (["tokens", str(valid)], 0),
        (["validate", str(valid)], 0),
        (["validate", str(invalid)], 1),
        (["dump-symbols", str(valid), "--json"], 0),
        (["dump-symbols", str(valid)], 0),
        (["test-fixture", str(valid)], 0),
        (["test-fixture", str(invalid)], 1),
        (
            [
                "inspect",
                str(valid),
                "--json",
                str(tmp_path / "inspect.json"),
                "--openpine-contract",
                "--semantic-snapshot",
            ],
            0,
        ),
        (
            [
                "semantic-snapshot",
                str(valid),
                "--json",
                str(tmp_path / "snapshot.json"),
                "--no-node-facts",
            ],
            0,
        ),
        (["contract-check", str(valid), "--json", str(tmp_path / "contract.json")], 0),
        (["schema-check", str(valid), "--json", str(tmp_path / "schema.json")], 0),
        (["schema-check", str(invalid), "--json", str(tmp_path / "bad-schema.json")], 1),
        (["diagnostics-report", str(valid), "--json", str(tmp_path / "diagnostics.json")], 0),
        (["diagnostics-report", str(invalid)], 1),
        (["sarif", str(valid), "--json", str(tmp_path / "diagnostics.sarif.json")], 0),
        (
            [
                "semantic-report",
                str(valid),
                "--json",
                str(tmp_path / "semantic.json"),
                "--include-builtins",
            ],
            0,
        ),
        (["quality-gate", str(valid), "--json", str(tmp_path / "quality.json")], 0),
        (["contract-schema", "--json", str(tmp_path / "contract-schema.json")], 0),
        (["catalog-coverage", "--json", str(tmp_path / "catalog-coverage.json")], 0),
    ]
    for argv, expected in commands:
        code, _, _ = _run(argv, capsys)
        assert code == expected, argv
    assert json.loads((tmp_path / "ast.json").read_text())["kind"] == "Program"
    assert json.loads((tmp_path / "inspect.json").read_text())["ok"] is True
    assert json.loads((tmp_path / "contract.json").read_text())["contract_ok"] is True


def test_cli_catalog_official_diagnostics_and_golden(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    valid, _, _ = _write_sources(tmp_path)
    ref_root = Path(__file__).resolve().parents[2] / "pine2ast" / "reference_catalog"
    official = ref_root / "official_pine_v6_reference_index.json"
    baseline = ref_root / "official_pine_v6_gap_baseline.json"

    for argv in (
        ["catalog", "validate"],
        ["catalog", "export-md", str(tmp_path / "catalog.md")],
        ["matrix", "validate"],
        [
            "official-reference",
            "fetch",
            "--official-json",
            str(official),
            "--json",
            str(tmp_path / "official.json"),
        ],
        [
            "official-reference",
            "diff",
            "--official-json",
            str(official),
            "--json",
            str(tmp_path / "official-diff.json"),
        ],
        [
            "official-reference",
            "gate",
            "--official-json",
            str(official),
            "--baseline",
            str(baseline),
            "--json",
            str(tmp_path / "official-gate.json"),
        ],
    ):
        code, _, _ = _run(argv, capsys)
        assert code == 0, argv

    ast_path = tmp_path / "golden.ast.json"
    diag_path = tmp_path / "golden.diag.json"
    code, _, _ = _run(
        ["golden", str(valid), "--ast", str(ast_path), "--diagnostics", str(diag_path)], capsys
    )
    assert code == 0
    code, _, _ = _run(
        ["golden", str(valid), "--ast", str(ast_path), "--compare", "--ignore-spans"], capsys
    )
    assert code == 0

    current = tmp_path / "current.json"
    base = tmp_path / "base.json"
    current.write_text(json.dumps({"summary": {"total": 0, "by_code": {}}}), encoding="utf-8")
    base.write_text(json.dumps({"summary": {"total": 0, "by_code": {}}}), encoding="utf-8")
    code, out, _ = _run(["diagnostics-diff", str(current), str(base)], capsys)
    assert code == 0 and json.loads(out)["ok"] is True
    current.write_text(json.dumps({"summary": {"total": 1, "by_code": {"X": 1}}}), encoding="utf-8")
    code, _, _ = _run(["diagnostics-diff", str(current), str(base)], capsys)
    assert code == 1


def test_cli_corpus_benchmark_and_release_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    valid, _, corpus = _write_sources(tmp_path)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(bench_corpus_json(valid, repeat=1), encoding="utf-8")
    for argv in (
        ["validate-corpus", str(corpus), "--json", str(tmp_path / "corpus.json")],
        [
            "bench",
            str(valid),
            "--repeat",
            "1",
            "--baseline",
            str(baseline),
            "--json",
            str(tmp_path / "bench.json"),
        ],
        [
            "perf-baseline",
            str(valid),
            "--repeat",
            "1",
            "--baseline",
            str(baseline),
            "--json",
            str(tmp_path / "perf.json"),
        ],
        [
            "release-report",
            "--root",
            str(Path(__file__).resolve().parents[2]),
            "--min-v5-signature-ready-ratio",
            "0",
            "--min-v6-signature-ready-ratio",
            "0",
            "--json",
            str(tmp_path / "release.json"),
        ],
    ):
        code, _, _ = _run(argv, capsys)
        assert code == 0, argv
    assert json.loads((tmp_path / "corpus.json").read_text())["file_count"] == 2


def test_cli_helpers_reports_and_direct_public_apis(tmp_path: Path) -> None:
    valid, invalid, corpus = _write_sources(tmp_path)
    result = parse_code(VALID, ParseOptions(collect_tokens=True))
    assert result.ast is not None and result.semantic_model is not None

    assert _span_dict(None) is None
    assert _span_dict(result.ast.span)["start_line"] == 1
    assert _script_dict(None) == {"type": None, "title": None, "pine_version": None}
    assert _script_dict(result.ast)["pine_version"] == 6
    assert _unsupported_features(result) == []
    assert _exit_code(result) == 0
    assert inspect_exit_code(result) == 0
    failed = parse_code(INVALID)
    assert _exit_code(failed) == 1
    assert inspect_exit_code(failed) == 1

    args = SimpleNamespace(
        path=str(valid), tokens=True, no_semantic=True, strict_builtin_namespaces=True
    )
    options = _parse_options(args, max_diagnostics=3)
    assert options.collect_tokens and not options.run_semantic and options.max_diagnostics == 3

    payload = inspect_file_payload(valid)
    assert payload["ok"] is True
    snapshot = build_semantic_snapshot_payload(
        result, source_path=str(valid), include_node_facts=True
    )
    assert snapshot["counts"]["symbols"] > 0
    assert json.loads(build_semantic_snapshot_json(result))["contract"].startswith(
        "pine2ast.semantic"
    )

    report = semantic_report(result.semantic_model)
    assert report.symbol_count > 0 and report.to_dict()["scope_count"] > 0
    assert semantic_report(None).symbol_count == 0

    diagnostics = [
        Diagnostic(Severity.INFO, "I", "info", result.ast.span),
        Diagnostic(Severity.WARNING, "W", "warn", result.ast.span),
        Diagnostic(Severity.ERROR, "E", "error", result.ast.span),
    ]
    summary = summarize_diagnostics(diagnostics)
    assert not summary.ok and summary.max_severity == "ERROR"
    same = diff_diagnostic_reports(summary, summary.to_dict())
    assert same.ok
    changed = diff_diagnostic_reports(
        {"total": 1, "by_code": {"N": 1}}, {"total": 1, "by_code": {"O": 1}}
    )
    assert (
        not changed.ok and changed.added_by_code == {"N": 1} and changed.removed_by_code == {"O": 1}
    )

    direct = _parse_once(VALID, source_name="inline.pine", run_semantic=False)
    denied = _parse_once(INVALID, source_name="bad.pine")
    assert direct["token_count"] > 0 and denied["ok"] is False
    assert _avg([], "x") == 0
    bench = bench_corpus(corpus, repeat=1, run_semantic=False)
    assert bench["summary"]["file_count"] == 2
    baseline = {"files": [{"file": "a.pine", "total_ms": 1e-12}]}
    assert (
        bench_corpus(corpus, repeat=1, baseline=baseline)["files"][0].get("regression_warning")
        is True
    )
    perf = perf_baseline(valid, repeat=1)
    assert perf["ok"] is True
    assert (
        json.loads(perf_baseline_json(valid, repeat=1))["report"] == "pine2ast.performance_baseline"
    )

    quality = quality_gate(valid)
    assert quality.ok
    assert json.loads(quality_gate_json(valid))["ok"] is True
    distribution = build_distribution_manifest(Path(__file__).resolve().parents[2])
    assert distribution.ok and distribution.to_dict()["ok"] is True
    release = build_release_manifest(
        Path(__file__).resolve().parents[2],
        min_v5_signature_ready_ratio=0,
        min_v6_signature_ready_ratio=0,
    )
    assert release.ok and release.to_dict()["ok"] is True


def test_signature_coverage_models_and_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    category = CategorySignatureCoverage(
        category="functions",
        official_count=2,
        registry_count=2,
        implemented_count=2,
        signature_ready_count=1,
        missing=(),
        registry_extra=("extra",),
        signature_pending=("pending",),
    )
    assert category.name_coverage_ratio == 1.0
    assert category.signature_ready_ratio == 0.5
    assert category.to_dict()["signature_pending_count"] == 1
    empty = CategorySignatureCoverage("x", 0, 0, 0)
    assert empty.name_coverage_ratio == empty.signature_ready_ratio == 1.0

    report5 = build_signature_coverage_report(5)
    report6 = build_signature_coverage_report(6)
    assert report5.pine_version == 5 and report6.pine_version == 6
    assert json.loads(signature_coverage_json(6))["schema_version"].startswith("pine2ast")
    output = tmp_path / "sig.json"
    assert signature_coverage_main(["--version", "6", "--json", str(output)]) == 0
    assert output.is_file()
    assert (
        signature_coverage_main(["--version", "6", "--fail-under-signature-ready-ratio", "1.1"])
        == 1
    )
    capsys.readouterr()
