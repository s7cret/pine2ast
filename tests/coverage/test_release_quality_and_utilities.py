from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import pytest

from pine2ast import parse_code
from pine2ast.ast.base import _to_plain
from pine2ast.ast.schema import validate_ast_schema
from pine2ast.audit import (
    AuditHookRunner,
    SecurityAuditEvent,
    is_security_audit_code,
    make_event,
)
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics.formatter import format_diagnostic
from pine2ast.diagnostics.reports import DiagnosticReport, summarize_diagnostics
from pine2ast.diagnostics.sarif import diagnostics_to_sarif, diagnostics_to_sarif_json
from pine2ast.distribution import (
    DistributionFinding,
    DistributionManifest,
    _is_excluded,
    _zip_info,
    build_distribution_manifest,
    create_source_zip,
    create_source_zip_json,
    distribution_manifest_json,
    iter_release_files,
    main as distribution_main,
)
from pine2ast.frontend.schema import (
    ContractSchemaIssue,
    openpine_contract_schema,
    validate_openpine_contract_payload,
    validate_openpine_contract_payload_dict,
)
from pine2ast.internal.fs import pine_files
from pine2ast.quality import (
    ArchitectureBudgetFile,
    ArchitectureBudgetReport,
    QualityFileReport,
    QualityGateReport,
    architecture_budget_json,
    architecture_budget_report,
    duplicate_function_report,
    duplicates_json,
    main as quality_main,
    quality_gate,
    quality_gate_json,
)
from pine2ast.release import (
    ReleaseManifest,
    build_release_manifest,
    main as release_main,
    release_manifest_json,
)
from pine2ast.security import (
    ABSOLUTE_MAX_FILE_SIZE_BYTES,
    clamp_int,
    find_overflowing_float_literals,
    safe_resolve_path,
    sanitize_source_name,
)
from pine2ast.semantic import signature_coverage as signatures
from pine2ast.semantic.snapshot import (
    _diagnostic_summary,
    _enum_value,
    _node_kind,
    _profile_dict,
    _span_dict,
    build_semantic_snapshot_json,
    build_semantic_snapshot_payload,
    node_fact_rows,
    pass_rows,
    scope_rows,
    symbol_rows,
)
from pine2ast.testing.ast_compare import strip_spans
from pine2ast.testing.compile_oracle import (
    CompileOracleMetadata,
    build_compile_oracle_report,
    report_to_dict,
)
from pine2ast.testing.fixtures import read_fixture
from pine2ast.testing.golden import (
    compare_diagnostics,
    compare_golden,
    diagnostics_to_contract_payload,
    generate_golden,
    validate_invalid_diagnostic_contract,
)
from pine2ast.testing.oracle import (
    OracleCase,
    OracleCaseResult,
    OracleReport,
    load_oracle_manifest,
    oracle_report_json,
    run_oracle_cases,
)
from pine2ast.lexer.token import SourceSpan

VALID = '//@version=6\nindicator("ok")\nx = close\nplot(x)\n'
INVALID = '//@version=7\nindicator("bad")\nx = close\n'


def _diag(
    severity: Severity = Severity.ERROR,
    code: str = "P2A9999",
    *,
    hint: str | None = None,
    doc_url: str | None = None,
) -> Diagnostic:
    return Diagnostic(
        severity=severity,
        code=code,
        message="problem",
        span=SourceSpan(0, 3, 1, 1, 1, 4),
        hint=hint,
        doc_url=doc_url,
    )


def _write_minimal_release(root: Path) -> None:
    files = {
        "README.md": "readme\n",
        "CHANGELOG.md": "changes\n",
        "LICENSE": "license\n",
        "pyproject.toml": "[project]\nname='pine2ast'\nversion='5.0.0rc6'\n",
        "pine2ast/__init__.py": "\n",
        "pine2ast/_version.py": '__version__ = "5.0.0rc6"\n',
        "docs/README.md": "docs\n",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_audit_events_hooks_and_failure_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    event = SecurityAuditEvent(
        timestamp="2026-08-27T00:00:00Z",
        code="P2A9201",
        severity="ERROR",
        source_name="sample.pine",
        span_start=0,
        span_end=3,
        message="unsafe path",
    )
    assert event.to_dict()["code"] == "P2A9201"
    assert is_security_audit_code("P2A9201")
    assert not is_security_audit_code("P2A0001")

    monkeypatch.setattr("pine2ast.audit.time.strftime", lambda *args: "fixed")
    built = make_event(_diag(code="P2A9201"), source_name="sample.pine")
    assert built.timestamp == "fixed"
    assert built.severity == "ERROR"

    received: list[SecurityAuditEvent] = []
    runner = AuditHookRunner(received.append)
    runner.emit(_diag(code="P2A9201"), source_name="sample.pine")
    runner.emit(_diag(code="P2A0001"), source_name="sample.pine")
    assert runner.observed == 1
    assert len(received) == 1

    none_runner = AuditHookRunner(None)
    none_runner.emit(_diag(code="P2A9201"), source_name="sample.pine")
    assert none_runner.observed == 0

    def explode(_: SecurityAuditEvent) -> None:
        raise RuntimeError("hook failure")

    broken = AuditHookRunner(explode)
    broken.emit(_diag(code="P2A9201"), source_name="sample.pine")
    assert broken.observed == 0


def test_diagnostic_formatting_reports_and_sarif() -> None:
    diagnostics = [
        _diag(Severity.FATAL, "P2A0001", hint="fix it", doc_url="https://example.test/doc"),
        _diag(Severity.ERROR, "P2A0002"),
        _diag(Severity.WARNING, "P2A0002"),
        _diag(Severity.INFO, "P2A0003"),
    ]
    text = format_diagnostic(diagnostics[0], "sample.pine")
    assert "FATAL P2A0001 at sample.pine:1:1" in text
    assert "Hint: fix it" in text
    assert diagnostics[0].is_error
    assert not diagnostics[-1].is_error
    assert diagnostics[0].to_dict()["doc_url"] == "https://example.test/doc"

    report = summarize_diagnostics(diagnostics)
    assert isinstance(report, DiagnosticReport)
    payload = report.to_dict()
    assert payload["total"] == 4
    assert payload["by_severity"] == {
        "ERROR": 1,
        "FATAL": 1,
        "INFO": 1,
        "WARNING": 1,
    }
    assert payload["by_code"] == {"P2A0001": 1, "P2A0002": 2, "P2A0003": 1}

    sarif = diagnostics_to_sarif(diagnostics, source_name="sample.pine")
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert len(run["tool"]["driver"]["rules"]) == 3
    assert run["results"][0]["level"] == "error"
    assert run["results"][2]["level"] == "warning"
    assert run["results"][3]["level"] == "note"
    assert json.loads(diagnostics_to_sarif_json(diagnostics, source_name="sample.pine"))["runs"]


def test_security_limits_source_names_float_literals_and_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ABSOLUTE_MAX_FILE_SIZE_BYTES > 0
    assert clamp_int(4, ceiling=10, field="limit") == 4
    assert clamp_int(20, ceiling=10, field="limit") == 10
    with pytest.raises(ValueError, match="non-negative"):
        clamp_int(-1, ceiling=10, field="limit")

    assert sanitize_source_name("") == "<memory>"
    assert "\x00" not in sanitize_source_name("bad\x00name")
    deep_name = "/".join(["segment"] * 10 + ["file.pine"])
    assert sanitize_source_name(deep_name).startswith(".../")
    assert sanitize_source_name("x" * 600).endswith("...")

    texts = find_overflowing_float_literals("x=1e500\ny=-1e309\nz=1e308\na=1.5\n")
    assert [row[2] for row in texts] == ["1e500", "-1e309", "1e308"]

    regular = tmp_path / "file.pine"
    regular.write_text(VALID, encoding="utf-8")
    assert safe_resolve_path(regular) == regular.resolve()
    future = tmp_path / "future.pine"
    assert safe_resolve_path(future, must_exist=False) == future.resolve()
    with pytest.raises(FileNotFoundError):
        safe_resolve_path(future)
    with pytest.raises(ValueError, match="regular file"):
        safe_resolve_path(tmp_path)

    link = tmp_path / "link.pine"
    try:
        link.symlink_to(regular)
    except (OSError, NotImplementedError):
        pass
    else:
        with pytest.raises(ValueError, match="symlink"):
            safe_resolve_path(link)

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        safe_resolve_path("../outside.pine", must_exist=False)


def test_distribution_manifest_selection_and_reproducible_zip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "source"
    _write_minimal_release(root)
    (root / ".git").mkdir()
    (root / ".git" / "ignored").write_text("x", encoding="utf-8")
    (root / "cache.pyc").write_bytes(b"x")
    (root / "build.log").write_text("x", encoding="utf-8")
    (root / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")

    selected = iter_release_files(root)
    selected_names = {path.relative_to(root).as_posix() for path in selected}
    assert "extra.py" in selected_names
    assert ".git/ignored" not in selected_names
    assert "cache.pyc" not in selected_names
    assert iter_release_files(tmp_path / "missing") == ()
    assert _is_excluded(root / "cache.pyc", root)
    assert not _is_excluded(root / "extra.py", root)

    manifest = build_distribution_manifest(root)
    assert manifest.ok
    assert manifest.to_dict()["selected_file_count"] == len(selected)
    assert json.loads(distribution_manifest_json(root))["ok"] is True

    finding = DistributionFinding("x", "code", "message")
    failed = DistributionManifest("schema", "root", "1", 0, 0, (finding,))
    assert not failed.ok
    assert failed.to_dict()["findings"] == [finding.to_dict()]

    missing = build_distribution_manifest(tmp_path / "missing")
    assert not missing.ok
    assert any(row.code == "missing_root" for row in missing.findings)

    zip1 = tmp_path / "one.zip"
    zip2 = tmp_path / "two.zip"
    payload1 = create_source_zip(root, zip1, root_name="source")
    payload2 = create_source_zip(root, zip2, root_name="source")
    assert payload1["file_count"] == payload2["file_count"]
    assert zip1.read_bytes() == zip2.read_bytes()
    with ZipFile(zip1) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
    assert json.loads(create_source_zip_json(root, tmp_path / "three.zip"))["ok"] is True

    info = _zip_info("x", root / "extra.py")
    assert info.date_time == (1980, 1, 1, 0, 0, 0)

    manifest_path = tmp_path / "manifest.json"
    assert distribution_main(["manifest", "--root", str(root), "--json", str(manifest_path)]) == 0
    assert manifest_path.is_file()
    assert distribution_main(["manifest", "--root", str(root)]) == 0
    assert '"ok": true' in capsys.readouterr().out
    zip_report = tmp_path / "zip-report.json"
    assert (
        distribution_main(
            [
                "build-zip",
                "--root",
                str(root),
                "--output",
                str(tmp_path / "cli.zip"),
                "--root-name",
                "cli",
                "--json",
                str(zip_report),
            ]
        )
        == 0
    )


def test_release_manifest_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "source"
    _write_minimal_release(root)
    manifest = build_release_manifest(root)
    assert manifest.ok
    payload = manifest.to_dict()
    assert payload["package_version"] == "5.0.0rc6"
    assert len(payload["catalog_versions"]) == 6
    assert all(row["catalog_hash"].startswith("sha256:") for row in payload["catalog_versions"])
    assert json.loads(release_manifest_json(root))["ok"] is True

    with pytest.raises(ValueError, match="v5"):
        build_release_manifest(root, min_v5_signature_ready_ratio=-0.1)
    with pytest.raises(ValueError, match="v6"):
        build_release_manifest(root, min_v6_signature_ready_ratio=1.1)

    failing = ReleaseManifest(
        schema_version="x",
        package_version="x",
        contracts={},
        catalog_versions=({"catalog_hash": "bad"},),
        distribution={"ok": False},
        static_coverage={"ok": False},
    )
    assert not failing.ok
    assert failing.to_dict()["ok"] is False

    output = tmp_path / "release.json"
    assert release_main(["--root", str(root), "--json", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["ok"] is True
    assert release_main(["--root", str(root)]) == 0
    assert '"schema_version": "pine2ast.release_manifest.v2"' in capsys.readouterr().out


def test_quality_gate_duplicate_detection_and_architecture_budget(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pine_dir = tmp_path / "pine"
    pine_dir.mkdir()
    (pine_dir / "ok.pine").write_text(VALID, encoding="utf-8")
    report = quality_gate(pine_dir)
    assert report.ok
    assert report.file_count == 1
    assert report.files[0].ok
    assert json.loads(quality_gate_json(pine_dir))["ok"] is True

    (pine_dir / "bad.pine").write_text(INVALID, encoding="utf-8")
    failed = quality_gate(pine_dir)
    assert not failed.ok
    assert failed.error_count + failed.fatal_count > 0

    manual_file = QualityFileReport("x", False, False, 1, 1, 0, 0, 0, ["P2A"])
    manual = QualityGateReport(1, "x", 1, 0, 1, 0, 0, 1, {}, [manual_file])
    assert not manual_file.ok and not manual.ok
    assert manual.to_dict()["files"][0]["codes"] == ["P2A"]

    source = tmp_path / "dupes"
    source.mkdir()
    body = """def duplicate(value):\n    total = value + 1\n    total *= 2\n    total -= 3\n    total += 4\n    return total\n"""
    (source / "a.py").write_text(body, encoding="utf-8")
    (source / "b.py").write_text(body.replace("duplicate", "same_body"), encoding="utf-8")
    duplicate_report = duplicate_function_report(source)
    assert duplicate_report["duplicate_group_count"] == 1
    assert json.loads(duplicates_json(source))["duplicate_group_count"] == 1

    budget_file = ArchitectureBudgetFile("x.py", 3, 2)
    assert not budget_file.ok
    assert budget_file.to_dict()["ok"] is False
    budget = architecture_budget_report(source, max_lines=4)
    assert not budget.ok
    assert budget.oversized
    assert json.loads(architecture_budget_json(source, max_lines=4))["ok"] is False
    manual_budget = ArchitectureBudgetReport("x", "x", 10, 0, [])
    assert manual_budget.ok

    output = tmp_path / "budget.json"
    assert (
        quality_main(
            ["architecture-budget", str(source), "--max-lines", "100", "--json", str(output)]
        )
        == 0
    )
    assert quality_main(["architecture", str(source), "--max-lines", "100"]) == 0
    assert '"ok": true' in capsys.readouterr().out
    duplicate_output = tmp_path / "dupes.json"
    assert quality_main(["duplicates", str(source), "--json", str(duplicate_output)]) == 1


def test_internal_file_discovery_and_fixture_reader(tmp_path: Path) -> None:
    single = tmp_path / "single.pine"
    single.write_text(VALID, encoding="utf-8")
    assert pine_files(single) == [single]
    assert pine_files(tmp_path / "missing") == []
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.PINE").write_text(VALID, encoding="utf-8")
    (nested / "a.pine").write_text(VALID, encoding="utf-8")
    assert [p.name for p in pine_files(nested)] == ["a.pine"]
    assert read_fixture(single) == VALID


def test_golden_generation_comparison_and_invalid_contracts(tmp_path: Path) -> None:
    valid = tmp_path / "valid.pine"
    valid.write_text(VALID, encoding="utf-8")
    generated = generate_golden(valid, ignore_spans=True)
    assert generated["ok"]
    assert generated["ast_path"].is_file()
    assert generated["diagnostics_path"].is_file()
    assert compare_golden(valid, ignore_spans=True) == (True, "OK")
    assert compare_diagnostics(
        valid, diagnostics_path=generated["diagnostics_path"], ignore_spans=True
    ) == (True, "OK")

    ast_data = json.loads(generated["ast_path"].read_text(encoding="utf-8"))
    ast_data["kind"] = "Mutated"
    generated["ast_path"].write_text(json.dumps(ast_data), encoding="utf-8")
    assert compare_golden(valid, ignore_spans=True)[1] == "Golden AST mismatch"
    generated["ast_path"].unlink()
    assert compare_golden(valid)[1].startswith("Golden AST does not exist")

    generated["diagnostics_path"].write_text("[]", encoding="utf-8")
    assert compare_diagnostics(valid, diagnostics_path=generated["diagnostics_path"])[0]
    generated["diagnostics_path"].unlink()
    assert compare_diagnostics(valid, diagnostics_path=generated["diagnostics_path"])[1].startswith(
        "Golden diagnostics does not exist"
    )

    invalid = tmp_path / "invalid.pine"
    invalid.write_text(INVALID, encoding="utf-8")
    result = parse_code(INVALID)
    codes = [diag.code for diag in result.diagnostics]
    contract = invalid.with_suffix(".diagnostics.json")
    contract.write_text(
        json.dumps(
            {
                "expected_codes": codes[:1],
                "expected_min_severity": "ERROR",
            }
        ),
        encoding="utf-8",
    )
    assert validate_invalid_diagnostic_contract(invalid) == (True, "OK")

    contract.write_text("[]", encoding="utf-8")
    assert (
        validate_invalid_diagnostic_contract(invalid)[1]
        == "Diagnostic contract root must be an object"
    )
    contract.write_text("{}", encoding="utf-8")
    assert (
        validate_invalid_diagnostic_contract(invalid)[1]
        == "Diagnostic contract has no expected_codes"
    )
    contract.write_text(
        json.dumps({"expected_codes": ["MISSING"], "expected_min_severity": "ERROR"}),
        encoding="utf-8",
    )
    assert validate_invalid_diagnostic_contract(invalid)[1].startswith("Missing expected")
    contract.write_text(
        json.dumps({"expected_codes": codes[:1], "expected_min_severity": "UNKNOWN"}),
        encoding="utf-8",
    )
    assert validate_invalid_diagnostic_contract(invalid)[1].startswith("Unsupported")
    contract.unlink()
    assert validate_invalid_diagnostic_contract(invalid)[1].startswith(
        "Diagnostic contract does not exist"
    )

    diagnostic_payload = diagnostics_to_contract_payload(result.diagnostics, ignore_spans=True)
    assert diagnostic_payload and "span" not in diagnostic_payload[0]
    assert strip_spans({"span": 1, "items": [{"span": 2, "x": 3}]}) == {"items": [{"x": 3}]}


def test_compile_oracle_metadata_states_and_payload(tmp_path: Path) -> None:
    root = tmp_path / "oracle"
    root.mkdir()
    (root / "ok.pine").write_text(VALID, encoding="utf-8")
    metadata = {
        "checked_at": "2026-08-27T00:00:00Z",
        "policy": [
            {
                "fixture": "ok.pine",
                "tradingview_status": "pass",
                "pine2ast_status": "pass",
                "expected": "compile",
            },
            {"fixture": "missing.pine", "tradingview_status": "pending_external_oracle"},
            {"fixture": "ok.pine", "tradingview_status": "platform_blocked"},
            "invalid",
            {"fixture": "ok.pine", "tradingview_status": "unsupported"},
        ],
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    report = build_compile_oracle_report(root)
    assert report.metadata_count == 1
    assert report.fixture_count == 5
    assert report.ok_count == 1
    assert report.pending_count == 1
    assert report.platform_blocked_count == 1
    assert not report.ok
    payload = report_to_dict(report)
    assert payload["entries"][0]["checked_at"] == "2026-08-27T00:00:00Z"
    assert payload["invalid_count"] >= 1
    assert CompileOracleMetadata().version == 6

    bad = root / "bad" / "metadata.json"
    bad.parent.mkdir()
    bad.write_text("[]", encoding="utf-8")
    defensive = build_compile_oracle_report(root)
    assert any(entry.fixture == "<metadata>" for entry in defensive.entries)


def test_oracle_cases_manifest_and_reports(tmp_path: Path) -> None:
    valid_case = OracleCase("valid", VALID, expect_ok=True, version=6, description="valid")
    invalid_result = parse_code(INVALID)
    expected_code = next(diag.code for diag in invalid_result.diagnostics if diag.is_error)
    invalid_case = OracleCase(
        "invalid",
        INVALID,
        expect_ok=False,
        expected_error_codes=(expected_code,),
        version=6,
    )
    report = run_oracle_cases([valid_case, invalid_case])
    assert report.ok and report.case_count == 2 and report.failure_count == 0
    assert report.to_dict()["results"][0]["actual_ok"] is True
    assert json.loads(oracle_report_json([valid_case]))["ok"] is True

    failing_case = OracleCase("failing", VALID, expect_ok=False, expected_error_codes=("NOPE",))
    failing = run_oracle_cases([failing_case])
    assert not failing.ok
    row = failing.results[0]
    assert row.unexpected_ok_mismatch
    assert row.missing_expected_codes == ("NOPE",)

    manual_result = OracleCaseResult(valid_case, True, True, (), ())
    manual_report = OracleReport("x", (manual_result,))
    assert manual_report.ok and manual_report.failure_count == 0

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "loaded",
                        "source": VALID,
                        "version": 5,
                        "expect_ok": True,
                        "expected_error_codes": [],
                        "description": "loaded",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    loaded = load_oracle_manifest(manifest)
    assert loaded[0].version == 5
    assert loaded[0].to_dict()["description"] == "loaded"


def test_frontend_schema_validates_generated_and_malformed_payloads() -> None:
    result = parse_code(VALID)
    assert result.frontend_artifact is not None
    payload = dict(result.frontend_artifact["frontend"])
    assert validate_openpine_contract_payload(payload) == ()
    assert validate_openpine_contract_payload_dict(payload)["ok"] is True

    schema = openpine_contract_schema()
    assert schema["schema_id"] == "pine.frontend.v3"
    assert schema["catalog_schema"]["additionalProperties"] is True

    bad: dict[str, Any] = {
        "contract": "bad",
        "schema_version": 2,
        "producer": {"name": "other", "version": ""},
        "source": {},
        "diagnostics": {},
        "static_validation": [],
        "requests": {"contract": "bad"},
    }
    issues = validate_openpine_contract_payload(bad)
    paths = {issue.path for issue in issues}
    assert {"contract", "schema_version", "producer", "source.name", "diagnostics"} <= paths
    assert "static_validation" in paths
    assert "requests.contract" in paths
    issue = ContractSchemaIssue("x", "bad")
    assert issue.to_dict() == {"path": "x", "message": "bad"}


def test_semantic_snapshot_rows_for_real_and_fallback_models() -> None:
    result = parse_code(VALID)
    assert result.ast is not None
    payload = build_semantic_snapshot_payload(result, source_path="path/sample.pine")
    assert payload["contract"] == "pine2ast.semantic_snapshot.v1"
    assert payload["counts"]["symbols"] == len(payload["symbols"])
    assert payload["counts"]["scopes"] == len(payload["scopes"])
    assert payload["profile"]["pine_version"] == 6
    assert json.loads(build_semantic_snapshot_json(result))["ok"] is True

    assert _enum_value(Severity.ERROR) == "ERROR"
    assert _enum_value("plain") == "plain"
    assert _span_dict(SourceSpan.zero()) == SourceSpan.zero().to_dict()
    assert _span_dict(None) is None
    assert _node_kind(result.ast) == "Program"
    assert _profile_dict(None) is None
    summary = _diagnostic_summary(
        [
            _diag(Severity.FATAL),
            _diag(Severity.ERROR),
            _diag(Severity.WARNING),
            _diag(Severity.INFO),
        ]
    )
    assert summary == {"fatal": 1, "error": 1, "warning": 1, "info": 1, "total": 4}

    assert symbol_rows(None) == []
    assert scope_rows(None) == []
    assert node_fact_rows(None, None) == []
    fallback = pass_rows(SimpleNamespace(pass_results=[]))
    assert fallback
    custom = pass_rows(
        SimpleNamespace(
            pass_results=[SimpleNamespace(name="x", diagnostics_before=1, diagnostics_after=2)]
        )
    )
    assert custom == [{"name": "x", "diagnostics_before": 1, "diagnostics_after": 2}]

    class FakeNode:
        kind = "Fake"

    assert _node_kind(FakeNode()) == "Fake"

    class PlainNode:
        pass

    assert _node_kind(PlainNode()) == "PlainNode"


def test_signature_coverage_helpers_report_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = {
        "functions": {
            "ready": {"parameters": []},
            "overloaded": {"overloads": [{}]},
            "pending": {"_signature_pending": True},
            "extra": {"parameters": []},
        },
        "methods": {"method.ready": {}, "method.pending": {"_signature_pending": True}},
        "variables": {"close": {"type": "float"}, "unknown": {}},
        "constants": {"color.red": {"qualifier": "const"}},
        "types": {"float": {}},
        "operators": {"+": {}},
        "keywords": {"if": {}},
        "annotations": {"version": {}},
    }
    official = {
        "source": {"url": "official"},
        "categories": {
            "functions": ["ready", "overloaded", "pending", "missing"],
            "methods": ["method.ready", "method.pending"],
            "variables": ["close", "unknown"],
            "constants": ["color.red"],
            "types": ["float"],
            "operators": ["+"],
            "keywords": ["if"],
            "annotations": ["version"],
        },
    }
    monkeypatch.setattr(signatures, "load_catalog_view", lambda **kwargs: registry)
    monkeypatch.setattr(signatures, "load_official_reference_index", lambda version: official)
    monkeypatch.setattr(signatures, "collection_function_names", lambda: {"collection.fn"})

    assert signatures._registry_names({"x": ["a", "b"]}, "x") == {"a", "b"}
    assert signatures._registry_names({"x": 3}, "x") == set()
    assert signatures._official_names(official, "functions") == {
        "ready",
        "overloaded",
        "pending",
        "missing",
    }
    assert signatures._entry_signature_ready("variables", "x", {"type": "float"})
    assert not signatures._entry_signature_ready("variables", "x", {})
    assert signatures._entry_signature_ready("types", "x", {})
    assert signatures._entry_signature_ready("operators", "+", None)
    assert signatures._entry_signature_ready("methods", "collection.fn", None)
    assert not signatures._entry_signature_ready("methods", "x", None)
    assert signatures._entry_signature_ready("functions", "ready", {"parameters": []})
    assert not signatures._entry_signature_ready(
        "functions", "pending", {"_signature_pending": True}
    )
    assert not signatures._entry_signature_ready("other", "x", None)
    assert signatures._registry_entry(registry, "functions", "ready") == {"parameters": []}
    assert signatures._registry_entry({"functions": []}, "functions", "x") is None

    report = signatures.build_signature_coverage_report(4)
    assert report.pine_version == 6
    assert not report.ok
    assert report.summary["missing_count"] == 1
    assert report.summary["signature_pending_count"] >= 2
    payload = report.to_dict()
    assert payload["categories"]["functions"]["registry_extra"] == ["extra"]
    assert json.loads(signatures.signature_coverage_json(6))["pine_version"] == 6

    empty = signatures.CategorySignatureCoverage("empty", 0, 0, 0)
    assert empty.name_coverage_ratio == 1.0
    assert empty.signature_ready_ratio == 1.0
    assert empty.to_dict()["missing_count"] == 0

    output = tmp_path / "signatures.json"
    assert signatures.main(["--version", "6", "--json", str(output)]) == 0
    assert output.is_file()
    assert signatures.main(["--version", "6", "--fail-on-missing"]) == 1
    assert signatures.main(["--version", "6", "--fail-under-signature-ready-ratio", "0.99"]) == 1
    assert capsys.readouterr().out


def test_ast_schema_and_plain_conversion_cover_defensive_shapes() -> None:
    result = parse_code(VALID)
    assert result.ast is not None
    report = validate_ast_schema(result.ast)
    assert report.ok
    assert report.to_dict()["node_count"] > 0

    plain = _to_plain(
        {
            "span": SourceSpan.zero(),
            "severity": Severity.WARNING,
            "tuple": (1, 2),
            "list": [3],
        }
    )
    assert plain["severity"] == "WARNING"
    assert plain["tuple"] == [1, 2]
    assert plain["span"]["start_line"] == 1
