from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Any

from .completeness import run_static_completeness_gate
from .consumer_bundle import build_consumer_bundle, verify_consumer_bundle
from .corpus import run_corpus_gate
from .differential import run_differential_gate
from .fuzzing import run_fuzz_gate
from .historical import load_historical_source, run_historical_corpus_gate
from .historical_catalog import run_historical_catalog_gate
from .historical_differential import run_historical_differential_gate
from .hygiene import run_hygiene_gate
from .model import GateFinding, GateResult, content_hash
from .mutation import run_contract_mutation_gate
from .performance import run_performance_gate

_CONSUMER_CASES = {
    1: "v1-self-bool-security.pine",
    2: "v2-control-flow.pine",
    3: "v3-security-default.pine",
    4: "v4-arrays-var-compound.pine",
    5: None,
    6: None,
}


def _catalog_gate(root: Path) -> GateResult:
    tool = root / "tools" / "catalog" / "build_catalog.py"
    if not tool.is_file():
        return GateResult(
            "stage5.catalog-build",
            "FAIL",
            [GateFinding("S5_CATALOG_TOOL", "catalog builder missing")],
            {},
        )
    run = subprocess.run(
        [sys.executable, str(tool), "--root", str(root), "--check"],
        cwd=Path("/tmp"),
        text=True,
        capture_output=True,
    )
    findings = (
        []
        if run.returncode == 0
        else [
            GateFinding(
                "S5_CATALOG_DRIFT",
                "catalog --check failed",
                details={"stdout": run.stdout, "stderr": run.stderr},
            )
        ]
    )
    return GateResult(
        "stage5.catalog-build",
        "PASS" if not findings else "FAIL",
        findings,
        {
            "returncode": run.returncode,
            "stdout_hash": content_hash(run.stdout),
            "stderr_hash": content_hash(run.stderr),
        },
    )


def _consumer_source(version: int) -> tuple[str, str]:
    if version <= 4:
        filename = _CONSUMER_CASES[version]
        assert filename is not None
        return filename, load_historical_source(filename)
    if version == 5:
        return "v5-consumer.pine", "//@version=5\nindicator('v5 consumer')\nx = ta.sma(close, 5)\n"
    return "v6-consumer.pine", "//@version=6\nindicator('v6 consumer')\nx = ta.sma(close, 5)\n"


def run_all_version_consumer_gate(
    *, mutate: bool = True
) -> tuple[GateResult, dict[int, dict[str, Any]]]:
    findings: list[GateFinding] = []
    bundles: dict[int, dict[str, Any]] = {}
    metrics: dict[str, Any] = {}
    for version in range(1, 7):
        filename, source = _consumer_source(version)
        try:
            bundle = build_consumer_bundle(source, source_name=filename)
            verify_consumer_bundle(bundle, source=source)
        except Exception as exc:
            findings.append(GateFinding("S5_CONSUMER_BUNDLE", f"Pine v{version}: {exc}"))
            continue
        actual = int(bundle["version_context"]["pine_version"])
        if actual != version:
            findings.append(
                GateFinding("S5_CONSUMER_VERSION", f"Pine v{version}: bundle reports v{actual}")
            )
        mutation = run_contract_mutation_gate(bundle, source=source) if mutate else None
        if mutation is not None and not mutation.ok:
            findings.append(
                GateFinding(
                    "S5_CONSUMER_MUTATION",
                    f"Pine v{version}: contract mutant survived",
                    details=mutation.to_dict(),
                )
            )
        bundles[version] = bundle
        metrics[f"v{version}"] = {
            "bundle_hash": bundle["content_hash"],
            "catalog_hash": bundle["version_context"]["catalog_hash"],
            "ast_hash": bundle["artifacts"]["ast_hash"],
            "semantic_facts_hash": bundle["artifacts"]["semantic_facts_hash"],
            "node_count": len(bundle["node_index"]),
            "mutants_killed": (len(mutation.metrics["killed"]) if mutation is not None else None),
        }
    if (
        len(bundles) == 6
        and len({bundle["version_context"]["catalog_hash"] for bundle in bundles.values()}) != 6
    ):
        findings.append(
            GateFinding(
                "S5_CONSUMER_CATALOG_COLLAPSE",
                "consumer bundles do not preserve six catalog identities",
            )
        )
    return (
        GateResult(
            "stage5.consumer-all-versions", "PASS" if not findings else "FAIL", findings, metrics
        ),
        bundles,
    )


def run_stage5_gate(
    root: str | Path = ".",
    *,
    fuzz_cases: int = 2000,
    performance_repeats: int = 3,
    mutate_consumers: bool = True,
    coordinated: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    gates: list[GateResult] = [
        _catalog_gate(root_path),
        run_static_completeness_gate(),
        run_hygiene_gate(root_path),
        run_corpus_gate(),
        run_differential_gate(),
        run_historical_corpus_gate(),
        run_historical_differential_gate(),
        run_historical_catalog_gate(),
        run_fuzz_gate(cases=fuzz_cases),
    ]
    consumer_gate, _ = run_all_version_consumer_gate(mutate=mutate_consumers)
    gates.append(consumer_gate)
    gates.append(run_performance_gate(repeats=performance_repeats))
    producer_ok = all(gate.ok for gate in gates)
    coordinated_findings: list[GateFinding] = []
    if coordinated:
        coordinated_findings.append(
            GateFinding(
                "S5_AST2PYTHON_RC6_ACCEPTANCE_REQUIRED",
                "Ast2Python 5.0.0rc6 must independently accept exact v1-v6 consumer bundles; Pine2AST cannot self-authorize the consumer boundary.",
            )
        )
    report: dict[str, Any] = {
        "schema_id": "pine2ast.stage5.release_gate.v1",
        "schema_version": "1.0.0",
        "package_version": __import__("pine2ast").__version__,
        "producer_status": "PASS" if producer_ok else "FAIL",
        "producer_review_ready": producer_ok,
        "coordinated_status": "PENDING_COORDINATED_CONSUMER",
        "release_authorized": False,
        "claims": {
            "pine_v1_v4_historical_static_semantics": producer_ok,
            "historical_catalog_scope": "conservative_documented_snapshot_not_exhaustive_reference_manual",
            "pine_v5_v6_static_frontend": producer_ok,
            "tradingview_runtime_parity": False,
            "ast2python_rc6_acceptance": False,
        },
        "gates": [gate.to_dict() for gate in gates],
        "coordinated_findings": [finding.to_dict() for finding in coordinated_findings],
    }
    report["content_hash"] = content_hash(report)
    return report


__all__ = ["run_all_version_consumer_gate", "run_stage5_gate"]
