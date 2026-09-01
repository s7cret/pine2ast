from __future__ import annotations

from typing import Any

from pine2ast.semantic.completeness import pinned_catalog_static_completeness

from .introspection import version_pack
from .model import GateFinding, GateResult, content_hash

_EXPECTED_STATUS = {
    1: "HISTORICAL_STATIC_SNAPSHOT",
    2: "HISTORICAL_STATIC_SNAPSHOT",
    3: "HISTORICAL_STATIC_SNAPSHOT",
    4: "HISTORICAL_STATIC_SNAPSHOT",
    5: "STATIC_COMPLETE",
    6: "STATIC_COMPLETE",
}


def run_static_completeness_gate() -> GateResult:
    findings: list[GateFinding] = []
    metrics: dict[str, Any] = {}
    pack_hashes: dict[int, str] = {}

    for version in range(1, 7):
        pack = version_pack(version)
        pack_hash = content_hash(pack)
        pack_hashes[version] = pack_hash
        status = str(pack.get("status") or "")
        if status != _EXPECTED_STATUS[version]:
            findings.append(
                GateFinding(
                    "S5_CATALOG_STATUS",
                    f"Pine v{version}: expected {_EXPECTED_STATUS[version]}, got {status!r}",
                )
            )
        try:
            report = pinned_catalog_static_completeness(version)
        except Exception as exc:  # fail closed at release boundary
            findings.append(
                GateFinding(
                    "S5_STATIC_COMPLETENESS_EXCEPTION",
                    f"Pine v{version}: {exc}",
                )
            )
            metrics[f"v{version}"] = {"pack_hash": pack_hash, "status": status}
            continue
        for gap in report.gaps:
            findings.append(
                GateFinding(
                    "S5_STATIC_COMPLETENESS_GAP",
                    f"Pine v{version}: {gap['path']}: {gap['message']}",
                    details=dict(gap),
                )
            )
        metrics[f"v{version}"] = {
            "pack_hash": pack_hash,
            "catalog_hash": report.catalog_hash,
            "status": status,
            "coverage_basis": report.coverage_basis,
            "scope": report.scope,
            "symbol_count": report.symbol_count,
            "callable_count": report.callable_count,
            "operator_count": report.operator_count,
            "checked_field_count": report.checked_field_count,
            "coverage_ratio": report.coverage_ratio,
            "gap_count": len(report.gaps),
        }

    if len(set(pack_hashes.values())) != 6:
        findings.append(
            GateFinding(
                "S5_VERSION_PACK_COLLAPSE",
                "All six Pine version packs must have distinct content identities",
            )
        )

    return GateResult(
        "stage5.static-completeness",
        "PASS" if not findings else "FAIL",
        findings,
        metrics,
    )


__all__ = ["run_static_completeness_gate"]
