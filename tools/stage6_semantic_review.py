#!/usr/bin/env python3
"""Stage 6 semantic review and honest per-version coverage gate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pine2ast import parse_code  # noqa: E402
from pine2ast.semantic.version_coverage import build_version_coverage_report  # noqa: E402
from pine2ast.hardening.hygiene import FORBIDDEN_SYMBOLS  # noqa: E402
from pine2ast.semantic.version_semantics import (  # noqa: E402
    load_semantic_requirements,
)
from tools.stage6_integrity import (  # noqa: E402
    canonical_source_hash,
    scan_shipping_ast_for_legacy_markers,
    verify_official_source_manifest,
)


def stable_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def digest(value: object) -> str:
    return "sha256:" + sha256(stable_json(value).encode("utf-8")).hexdigest()


def diag_codes(source: str) -> set[str]:
    return {item.code for item in parse_code(source).diagnostics}


def has_error(source: str) -> bool:
    return any(item.severity.value in {"ERROR", "FATAL"} for item in parse_code(source).diagnostics)


def minimal(version: int) -> str:
    if version == 1:
        return 'study("v1")\nx = close\n'
    declaration = "study" if version <= 4 else "indicator"
    return f'//@version={version}\n{declaration}("v{version}")\nx = close\n'


def run_direct_probes() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    for version in range(1, 7):
        result = parse_code(minimal(version))
        context = result.ast.version_context if result.ast is not None else None
        checks[f"version_{version}_identity"] = bool(
            context is not None
            and context.pine_version == version
            and isinstance(context.catalog_hash, str)
            and context.catalog_hash.startswith("sha256:")
        )
    checks["missing_version_defaults_v1"] = (
        parse_code('study("x")\nx=close\n').ast.version_context.pine_version == 1
    )
    future = parse_code('//@version=7\nindicator("x")\nx=close\n')
    checks["future_version_fail_closed"] = future.ast is None or has_error(
        '//@version=7\nindicator("x")\nx=close\n'
    )
    cases = {
        "v1_function_rejected": (
            'study("x")\nf(x)=>x\ny=f(close)\n',
            "P2A2101",
        ),
        "v1_reassignment_rejected": (
            'study("x")\nx=close\nx:=open\n',
            "P2A2101",
        ),
        "v4_modern_namespace_rejected": (
            '//@version=4\nstudy("x")\nx=ta.sma(close,3)\n',
            "P2A2108",
        ),
        "v4_map_rejected": (
            '//@version=4\nstudy("x")\nx=map.new<string,float>()\n',
            "P2A2102",
        ),
        "v5_legacy_spelling_rejected": (
            '//@version=5\nindicator("x")\nx=sma(close,3)\n',
            "P2A2109",
        ),
        "v5_resolution_rejected": (
            '//@version=5\nindicator("x",resolution="D")\nx=close\n',
            "P2A2103",
        ),
        "v6_when_rejected": (
            '//@version=6\nstrategy("x")\nstrategy.entry("L",strategy.long,when=close>open)\n',
            "P2A2103",
        ),
        "v6_transp_rejected": (
            '//@version=6\nindicator("x")\nplot(close,transp=50)\n',
            "P2A2103",
        ),
    }
    for name, (source, expected) in cases.items():
        actual = diag_codes(source)
        checks[name] = expected in actual
        details[name] = sorted(actual)
    checks["v2_self_reference_allowed"] = not has_error('//@version=2\nstudy("x")\nx=nz(x[1])\n')
    checks["v3_self_reference_rejected"] = has_error('//@version=3\nstudy("x")\nx=nz(x[1])\n')
    checks["v2_forward_reference_allowed"] = not has_error(
        '//@version=2\nstudy("x")\nx=y\ny=close\n'
    )
    checks["v3_forward_reference_rejected"] = has_error('//@version=3\nstudy("x")\nx=y\ny=close\n')
    checks["v2_bool_arithmetic_allowed"] = not has_error('//@version=2\nstudy("x")\nx=true+1\n')
    checks["v3_bool_arithmetic_rejected"] = has_error('//@version=3\nstudy("x")\nx=true+1\n')
    checks["v4_na_untyped_rejected"] = has_error('//@version=4\nstudy("x")\nx=na\n')
    checks["v4_na_typed_allowed"] = not has_error('//@version=4\nstudy("x")\nfloat x=na\n')
    checks["v5_numeric_condition_allowed"] = not has_error(
        '//@version=5\nindicator("x")\nif close\n    x=1\n'
    )
    checks["v6_numeric_condition_rejected"] = has_error(
        '//@version=6\nindicator("x")\nif close\n    x=1\n'
    )
    checks["v5_bool_na_allowed"] = not has_error('//@version=5\nindicator("x")\nbool x=na\n')
    checks["v6_bool_na_rejected"] = has_error('//@version=6\nindicator("x")\nbool x=na\n')
    checks["v5_exit_without_effect_rejected"] = has_error(
        '//@version=5\nstrategy("x")\nstrategy.exit("X","E")\n'
    )
    checks["v5_named_constant_rule"] = has_error(
        '//@version=5\nindicator("x")\nplot(close,style=5)\n'
    )
    checks["v6_multiline_string"] = not has_error('//@version=6\nindicator("x")\ns="""a\nb"""\n')
    checks["v6_historical_tick_setting"] = not has_error(
        '//@version=6\nstrategy("x",calc_on_every_history_tick=true)\nx=close\n'
    )
    checks["v6_bid_ask"] = not any(
        code in {"P2A1101", "P2A1506"}
        for code in diag_codes('//@version=6\nindicator("x")\nx=bid+ask\n')
    )
    return {
        "ok": all(checks.values()),
        "check_count": len(checks),
        "passed": sum(checks.values()),
        "failed": sorted(name for name, value in checks.items() if not value),
        "checks": checks,
        "diagnostic_details": details,
    }


def scan_forbidden_legacy(root: Path) -> dict[str, Any]:
    """Scan shipped Python syntax, excluding fixtures, comments, and prose.

    The canonical marker registry necessarily contains the forbidden literals,
    so that one definition file is excluded explicitly.  Everything else under
    the shipped ``pine2ast`` package is parsed as Python and inspected by syntax
    role rather than by a text regex.
    """

    findings = scan_shipping_ast_for_legacy_markers(
        root,
        FORBIDDEN_SYMBOLS,
        excluded_paths=("pine2ast/hardening/hygiene.py",),
    )
    return {"ok": not findings, "finding_count": len(findings), "findings": findings}


def official_sources_gate(root: Path, required_urls: set[str]) -> dict[str, Any]:
    return verify_official_source_manifest(root, required_urls=required_urls)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Pine2AST 5.0.0rc6 — Stage 6 semantic coverage",
        "",
        "Coverage is intentionally split into independent axes. Internal catalog completeness is not treated as official TradingView API coverage, and Pine2AST does not claim runtime or Broker Emulator parity.",
        "",
        "| Pine | Verified static requirements | Static coverage | Internal symbols | Internal callables | Internal operators | Official symbol coverage | Runtime oracle |",
        "|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for version, row in report["coverage"]["versions"].items():
        static = row["normative_static_frontend"]
        catalog = row["internal_catalog"]
        lines.append(
            f"| v{version} | {static['verified']}/{static['requirements_total']} | {static['coverage_percent']:.2f}% | {catalog['symbol_count']} | {catalog['callable_count']} | {catalog['operator_count']} | NOT_CLAIMED | NOT_RUN |"
        )
    lines.extend(
        [
            "",
            "## Review verdict",
            "",
            f"- Verdict: **{report['verdict']}**",
            f"- Findings: **{len(report['findings'])}**",
            f"- Direct semantic probes: **{report['direct_probes']['passed']}/{report['direct_probes']['check_count']}**",
            f"- Full test suite: **{'PASS' if report['inputs']['full_test_suite_passed'] else 'FAIL'}**",
            f"- Catalog gate: **{'PASS' if report['inputs']['catalog_gate_passed'] else 'FAIL'}**",
            f"- Producer review ready: **{'YES' if report['producer_review_ready'] else 'NO'}**",
            f"- Coordinated consumer status: **{report['coordinated_consumer_status']}**",
            f"- Release authorized: **{'YES' if report['release_authorized'] else 'NO'}**",
            "",
            "## Deliberate non-claims",
            "",
            "- No percentage is claimed for the completeness of the official historical TradingView symbol universe.",
            "- No PineLib runtime, request alignment, realtime rollback, Broker Emulator, strategy-fill or TradingView oracle result is counted as Pine2AST coverage.",
            "- v1–v4 remain pinned historical static snapshots; they are not presented as exhaustive archives of every undocumented historical TradingView behavior.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def traceability_attestation_issues(report: dict[str, Any], expected_source_hash: str) -> list[str]:
    """Reject status files unless this gate executed pytest against this source."""

    issues: list[str] = []
    evidence = report.get("pytest_evidence")
    if not isinstance(evidence, dict) or evidence.get("origin") != "gate_executed_pytest":
        issues.append("traceability evidence was not executed by the gate")
        return issues
    if evidence.get("collect_exit_code") != 0:
        issues.append("traceability pytest collection failed")
    if evidence.get("test_exit_code") != 0:
        issues.append("traceability pytest execution failed")
    if report.get("source_root_hash") != expected_source_hash:
        issues.append("traceability evidence is bound to a different source root")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--pytest-status", help=argparse.SUPPRESS)
    parser.add_argument("--catalog-status", help=argparse.SUPPRESS)
    parser.add_argument("--traceability-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--markdown", required=True)
    args = parser.parse_args()
    if args.pytest_status is not None or args.catalog_status is not None:
        parser.error("external PASS status files are no longer accepted")
    root = Path(args.root).resolve()
    source_root_hash = canonical_source_hash(root)
    traceability_report = json.loads(Path(args.traceability_report).read_text(encoding="utf-8"))
    pytest_evidence = traceability_report.get("pytest_evidence", {})
    pytest_passed = bool(
        isinstance(pytest_evidence, dict)
        and pytest_evidence.get("origin") == "gate_executed_pytest"
        and pytest_evidence.get("collect_exit_code") == 0
        and pytest_evidence.get("test_exit_code") == 0
    )
    # The traceability gate now runs the complete suite, including catalog tests.
    catalog_passed = pytest_passed
    probes = run_direct_probes()
    legacy = scan_forbidden_legacy(root)
    requirements = load_semantic_requirements()
    required_docs_urls = {row.docs_ref for row in requirements if row.owner == "pine2ast"}
    official = official_sources_gate(root, required_docs_urls)
    frontend_requirements = {
        row.requirement_id: row.test_id for row in requirements if row.owner == "pine2ast"
    }
    verified_rows = [
        row
        for row in traceability_report.get("requirements", [])
        if isinstance(row, dict) and row.get("status") == "VERIFIED"
    ]
    traceability_ids = {
        str(row.get("requirement_id")): str(row.get("catalog_test_id"))
        for row in verified_rows
        if row.get("requirement_id") and row.get("catalog_test_id")
    }
    traceability_issues = traceability_attestation_issues(traceability_report, source_root_hash)
    if traceability_report.get("status") != "PASS":
        traceability_issues.append("traceability gate did not pass")
    if traceability_report.get("requirements_total") != len(frontend_requirements):
        traceability_issues.append("frontend requirement count mismatch")
    if traceability_report.get("requirements_verified") != len(frontend_requirements):
        traceability_issues.append("not every frontend requirement is verified")
    if traceability_report.get("source_root_hash") != source_root_hash:
        traceability_issues.append("traceability evidence is bound to a different source root")
    if set(traceability_ids) != set(frontend_requirements):
        traceability_issues.append("traceability requirement IDs do not match the source catalog")
    mismatched_test_ids = sorted(
        requirement_id
        for requirement_id, expected_test_id in frontend_requirements.items()
        if traceability_ids.get(requirement_id) != expected_test_id
    )
    if mismatched_test_ids:
        traceability_issues.append(
            f"catalog test IDs mismatch for {len(mismatched_test_ids)} requirement(s)"
        )
    verified_test_ids = set(traceability_ids.values()) if not traceability_issues else set()
    traceability = {
        "ok": not traceability_issues,
        "requirement_count": traceability_report.get("requirements_total", 0),
        "verified_count": traceability_report.get("requirements_verified", 0),
        "failed_count": traceability_report.get("requirements_failed", 0),
        "source_root_hash": traceability_report.get("source_root_hash"),
        "expected_source_root_hash": source_root_hash,
        "issues": traceability_issues,
        "frontend_count": len(frontend_requirements),
        "downstream_count": sum(row.owner != "pine2ast" for row in requirements),
    }
    coverage = build_version_coverage_report(
        verified_test_ids=verified_test_ids,
        full_test_suite_passed=pytest_passed,
        catalog_gate_passed=catalog_passed,
        differential_gate_passed=probes["ok"],
    )
    findings: list[dict[str, Any]] = []
    local_gates = {
        "full_test_suite": pytest_passed,
        "catalog": catalog_passed,
        "direct_probes": probes["ok"],
        "legacy_scan": legacy["ok"],
        "traceability": traceability["ok"],
    }
    coordinated_consumer_status = "PENDING_COORDINATED_CONSUMER"
    gates: dict[str, Any] = {
        **local_gates,
        "official_sources": official["ok"],
        "ast2python_consumer_acceptance": coordinated_consumer_status,
    }
    for name, value in local_gates.items():
        if not value:
            findings.append({"severity": "BLOCKER", "gate": name})
    for version, row in coverage["versions"].items():
        if row["normative_static_frontend"]["coverage_percent"] != 100.0:
            findings.append({"severity": "BLOCKER", "gate": f"version_{version}_coverage"})
    external_pending: list[dict[str, Any]] = [
        {
            "severity": "PENDING_EXTERNAL",
            "gate": "ast2python_consumer_acceptance",
            "status": coordinated_consumer_status,
        }
    ]
    if not official["ok"]:
        findings.append({"severity": "BLOCKER", "gate": "official_sources"})
    report = {
        "schema_id": "pine2ast.stage6_semantic_review.v1",
        "schema_version": "1.0.0",
        "reviewed_at": "2026-08-28",
        "scope": "Pine2AST static frontend semantics for Pine v1-v6",
        "source_root_hash": source_root_hash,
        "verdict": "PASS" if not findings else "FAIL",
        "producer_review_ready": not findings,
        "coordinated_consumer_status": coordinated_consumer_status,
        "release_authorized": False,
        "external_pending": external_pending,
        "inputs": {
            "full_test_suite_passed": pytest_passed,
            "catalog_gate_passed": catalog_passed,
        },
        "gates": gates,
        "direct_probes": probes,
        "legacy_scan": legacy,
        "official_sources": official,
        "traceability": traceability,
        "coverage": coverage,
        "findings": findings,
        "known_limits": [
            "Official historical symbol completeness is not measurable from an internal catalog and is not claimed.",
            "Runtime execution, market-data alignment, realtime rollback and Broker Emulator behavior are owned by downstream libraries.",
            "TradingView oracle tests are not available inside Pine2AST and remain zero by design.",
        ],
    }
    report["content_hash"] = digest(report)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, Path(args.markdown))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
