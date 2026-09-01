from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from tools.build_deterministic_sdist import selected_files
from tools.stage6_mutation_gate import SOURCE_MUTATIONS, run_source_mutation_gate
from tools.stage6_traceability_gate import execute_pytest_evidence
from tools.stage6_semantic_review import traceability_attestation_issues
from tools.stage6_integrity import (
    canonical_source_hash,
    scan_shipping_ast_for_legacy_markers,
    verify_official_source_manifest,
    verify_traceability,
)


def test_catalog_migration_input_manifest_matches_actual_inputs() -> None:
    root = Path(__file__).resolve().parents[2]
    inputs_root = root / "catalog_migration_inputs/rc5"
    manifest = json.loads((inputs_root / "INPUT_MANIFEST.json").read_text(encoding="utf-8"))
    for version in (5, 6):
        data = (inputs_root / f"builtins_v{version}.rc5.json").read_bytes()
        row = manifest["inputs"][str(version)]
        git_blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        assert row == {
            "bytes": len(data),
            "git_blob_sha1": git_blob,
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        }


def test_legacy_scanner_uses_shipping_boundary(tmp_path: Path) -> None:
    package = tmp_path / "pine2ast"
    tests = tmp_path / "tests"
    package.mkdir()
    tests.mkdir()
    (package / "clean.py").write_text("value = 1\n", encoding="utf-8")
    (tests / "fixture.py").write_text("strict_v6 = True\n", encoding="utf-8")
    assert scan_shipping_ast_for_legacy_markers(tmp_path, {"strict_v6"}) == []
    (package / "legacy.py").write_text("strict_v6 = True\n", encoding="utf-8")
    findings = scan_shipping_ast_for_legacy_markers(tmp_path, {"strict_v6"})
    assert [(item["path"], item["marker"]) for item in findings] == [
        ("pine2ast/legacy.py", "strict_v6")
    ]


def test_traceability_requires_collected_passing_node_and_implementation(tmp_path: Path) -> None:
    implementation = tmp_path / "pine2ast" / "feature.py"
    implementation.parent.mkdir()
    implementation.write_text("ENABLED = True\n", encoding="utf-8")
    node = "tests/test_feature.py::test_feature"
    manifest = {
        "requirements": [
            {
                "requirement_id": "REQ-1",
                "catalog_test_id": "stage6.req.1",
                "implementation_refs": ["pine2ast/feature.py"],
                "pytest_nodes": [node],
            }
        ]
    }
    passed = verify_traceability(manifest, {node}, {node: "passed"}, root=tmp_path)
    assert passed["status"] == "PASS"
    assert verify_traceability(manifest, set(), {node: "passed"}, root=tmp_path)["status"] == "FAIL"
    assert (
        verify_traceability(manifest, {node}, {node: "failed"}, root=tmp_path)["status"] == "FAIL"
    )


def test_canonical_source_hash_ignores_evidence_but_tracks_source(tmp_path: Path) -> None:
    source = tmp_path / "pine2ast" / "feature.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    first = canonical_source_hash(tmp_path)
    evidence = tmp_path / "evidence" / "report.json"
    evidence.parent.mkdir()
    evidence.write_text('{"result": "PASS"}', encoding="utf-8")
    generated_report = tmp_path / "stage6_reports" / "performance-gate.json"
    generated_report.parent.mkdir()
    generated_report.write_text('{"result": "PASS"}', encoding="utf-8")
    assert canonical_source_hash(tmp_path) == first
    source.write_text("VALUE = 2\n", encoding="utf-8")
    assert canonical_source_hash(tmp_path) != first


def test_official_source_manifest_verifies_repository_records() -> None:
    root = Path(__file__).resolve().parents[2]
    requirements = json.loads(
        (root / "pine2ast/semantic/version_semantic_requirements.json").read_text(encoding="utf-8")
    )["requirements"]
    required_urls = {str(row["docs_ref"]) for row in requirements if row.get("owner") == "pine2ast"}
    report = verify_official_source_manifest(root, required_urls=required_urls)
    assert report["status"] == "PASS", report
    assert report["source_count"] == 8
    assert report["verified_count"] == 8
    assert report["missing_required_urls"] == []


def test_official_source_manifest_fails_closed_on_tamper_and_missing_url(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    canonical = root / "pine2ast/catalog/sources"
    docs = root / "docs/official_sources"
    shutil.copytree(canonical, tmp_path / "pine2ast/catalog/sources")
    shutil.copytree(docs, tmp_path / "docs/official_sources")
    manifest = json.loads(
        (tmp_path / "pine2ast/catalog/sources/source_manifest.json").read_text(encoding="utf-8")
    )
    required_urls = {str(row["url"]) for row in manifest["sources"]}
    assert (
        verify_official_source_manifest(tmp_path, required_urls=required_urls)["status"] == "PASS"
    )

    record = tmp_path / str(manifest["sources"][0]["evidence_path"])
    record.write_text(record.read_text(encoding="utf-8") + " ", encoding="utf-8")
    tampered = verify_official_source_manifest(tmp_path, required_urls=required_urls)
    assert tampered["status"] == "FAIL"
    assert tampered["verified_count"] == 7

    missing = verify_official_source_manifest(
        tmp_path,
        required_urls={*required_urls, "https://www.tradingview.com/pine-script-docs/missing/"},
    )
    assert missing["status"] == "FAIL"
    assert missing["missing_required_urls"] == [
        "https://www.tradingview.com/pine-script-docs/missing/"
    ]


def test_deterministic_sdist_excludes_generated_evidence(tmp_path: Path) -> None:
    source = tmp_path / "pine2ast" / "feature.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    generated = [
        tmp_path / "stage6_reports" / "performance-gate.json",
        tmp_path / "evidence" / "pytest-junit.xml",
    ]
    for path in generated:
        path.parent.mkdir(exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")
    selected = {path.relative_to(tmp_path).as_posix() for path in selected_files(tmp_path)}
    assert selected == {"pine2ast/feature.py"}


def test_canonical_source_hash_tracks_executable_mode(tmp_path: Path) -> None:
    source = tmp_path / "pine2ast" / "feature.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    source.chmod(0o644)
    regular_hash = canonical_source_hash(tmp_path)

    source.chmod(0o755)

    assert canonical_source_hash(tmp_path) != regular_hash


def test_deterministic_sdist_rejects_symlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    package = tmp_path / "pine2ast"
    package.mkdir()
    (package / "leak.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        selected_files(tmp_path)


def test_traceability_evidence_is_executed_by_gate(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-q"\n', encoding="utf-8"
    )
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    collected, outcomes, evidence = execute_pytest_evidence(tmp_path, tmp_path / "evidence")

    assert "test_ok.py::test_ok" in collected
    assert outcomes["test_ok.py::test_ok"] == "passed"
    assert evidence["origin"] == "gate_executed_pytest"
    assert evidence["collect_exit_code"] == 0
    assert evidence["test_exit_code"] == 0


def test_semantic_review_rejects_unattested_traceability() -> None:
    report = {"status": "PASS", "source_root_hash": "sha256:source"}

    issues = traceability_attestation_issues(report, "sha256:source")

    assert "traceability evidence was not executed by the gate" in issues


def test_mutation_gate_kills_real_parser_and_semantic_mutants_without_touching_source(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    target_paths = {root / mutation.target for mutation in SOURCE_MUTATIONS}
    before = {path: path.read_bytes() for path in target_paths}

    report = run_source_mutation_gate(root, work_dir=tmp_path)

    assert len(SOURCE_MUTATIONS) >= 6
    assert all(mutation.target.startswith("pine2ast/") for mutation in SOURCE_MUTATIONS)
    assert {mutation.layer for mutation in SOURCE_MUTATIONS} >= {"parser", "semantic"}
    assert report["mutation_kind"] == "production_source"
    assert report["killed"] == report["mutants"]
    assert report["survivors"] == []
    assert {path: path.read_bytes() for path in target_paths} == before
