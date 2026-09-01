from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

from .consumer_bundle import build_consumer_bundle, verify_consumer_bundle
from .completeness import run_static_completeness_gate
from .corpus import load_case_source, run_corpus_gate
from .differential import run_differential_gate
from .fuzzing import run_fuzz_gate
from .hygiene import run_hygiene_gate
from .model import GateFinding, GateResult, content_hash
from .mutation import run_contract_mutation_gate
from .performance import run_performance_gate


def _catalog_gate(root: Path) -> GateResult:
    tool = root / "tools" / "catalog" / "build_catalog.py"
    if not tool.exists():
        return GateResult(
            "stage4.catalog",
            "FAIL",
            [GateFinding("S4_CATALOG_TOOL", "catalog builder missing")],
            {},
        )
    run = subprocess.run(
        [sys.executable, str(tool), "--check"], cwd=root, text=True, capture_output=True
    )
    findings = (
        []
        if run.returncode == 0
        else [
            GateFinding(
                "S4_CATALOG_DRIFT",
                "catalog --check failed",
                details={"stdout": run.stdout, "stderr": run.stderr},
            )
        ]
    )
    return GateResult(
        "stage4.catalog",
        "PASS" if not findings else "FAIL",
        findings,
        {
            "returncode": run.returncode,
            "stdout_hash": content_hash(run.stdout),
            "stderr_hash": content_hash(run.stderr),
        },
    )


def _consumer_gate() -> tuple[GateResult, dict[str, Any], str]:
    source = load_case_source("v6_strategy_orders.pine")
    try:
        bundle = build_consumer_bundle(source, source_name="v6_strategy_orders.pine")
        verify_consumer_bundle(bundle, source=source)
        findings: list[GateFinding] = []
    except Exception as exc:
        return (
            GateResult(
                "stage4.consumer-producer",
                "FAIL",
                [GateFinding("S4_CONSUMER_BUNDLE", str(exc))],
                {},
            ),
            {},
            source,
        )
    metrics = {
        "bundle_hash": bundle["content_hash"],
        "ast_hash": bundle["artifacts"]["ast_hash"],
        "semantic_facts_hash": bundle["artifacts"]["semantic_facts_hash"],
        "node_count": len(bundle["node_index"]),
    }
    return GateResult("stage4.consumer-producer", "PASS", findings, metrics), bundle, source


def run_stage4_gate(
    root: str | Path = ".",
    *,
    fuzz_cases: int = 2000,
    performance_repeats: int = 3,
    coordinated: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    gates = []
    gates.append(_catalog_gate(root_path))
    gates.append(run_static_completeness_gate())
    gates.append(run_hygiene_gate(root_path))
    gates.append(run_corpus_gate())
    gates.append(run_differential_gate())
    gates.append(run_fuzz_gate(cases=fuzz_cases))
    consumer, bundle, source = _consumer_gate()
    gates.append(consumer)
    if bundle:
        gates.append(run_contract_mutation_gate(bundle, source=source))
    gates.append(run_performance_gate(repeats=performance_repeats))
    producer_ok = all(g.ok for g in gates)
    coordinated_status = "PENDING_COORDINATED_CONSUMER"
    coordinated_findings = []
    if coordinated:
        coordinated_findings.append(
            GateFinding(
                "S4_AST2PYTHON_RC6_ACCEPTANCE_REQUIRED",
                "Ast2Python 5.0.0rc6 must independently accept the exact consumer bundle; Pine2AST cannot self-authorize this boundary.",
            )
        )
    report = {
        "schema_id": "pine2ast.stage4.release_gate.v1",
        "package_version": __import__("pine2ast").__version__,
        "producer_status": "PASS" if producer_ok else "FAIL",
        "coordinated_status": coordinated_status,
        "producer_review_ready": producer_ok,
        "release_authorized": False,
        "claims": {
            "frontend_hardening": "producer gates only",
            "tradingview_runtime_parity": False,
            "ast2python_rc6_acceptance": False,
        },
        "gates": [g.to_dict() for g in gates],
        "coordinated_findings": [f.to_dict() for f in coordinated_findings],
    }
    report["content_hash"] = content_hash(report)
    return report
