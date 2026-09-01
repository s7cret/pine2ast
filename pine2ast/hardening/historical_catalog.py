from __future__ import annotations

from typing import Any

from pine2ast.catalog import CatalogRepository

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
_EXPECTED_HISTORICAL_BASIS = (
    "official_historical_migration_guides_and_archived_manual_conservative_snapshot"
)


def _same_symbol(
    left: dict[str, Any], left_name: str, right: dict[str, Any], right_name: str
) -> bool:
    return left["symbol_id"] == right["symbol_id"]


def run_historical_catalog_gate() -> GateResult:
    repo = CatalogRepository.default()
    views = {version: repo.view(version) for version in range(1, 7)}
    raw = {version: version_pack(version) for version in range(1, 7)}
    findings: list[GateFinding] = []
    identities: list[dict[str, Any]] = []

    for version in range(1, 7):
        if raw[version].get("status") != _EXPECTED_STATUS[version]:
            findings.append(GateFinding("S5_CATALOG_STATUS", f"Pine v{version}: unexpected status"))
        if version <= 4:
            if raw[version].get("coverage_basis") != _EXPECTED_HISTORICAL_BASIS:
                findings.append(
                    GateFinding(
                        "S5_CATALOG_BASIS", f"Pine v{version}: historical coverage basis missing"
                    )
                )
            refs = raw[version].get("provenance_sources")
            if not isinstance(refs, list) or not refs:
                findings.append(
                    GateFinding(
                        "S5_CATALOG_PROVENANCE", f"Pine v{version}: provenance_sources missing"
                    )
                )

    checks = [
        (4, "functions", "study", 5, "functions", "indicator"),
        (4, "functions", "sma", 5, "functions", "ta.sma"),
        (4, "functions", "security", 5, "functions", "request.security"),
        (3, "variables", "tickerid", 5, "variables", "syminfo.tickerid"),
        (3, "variables", "n", 5, "variables", "bar_index"),
    ]
    for lv, ls, ln, rv, rs, rn in checks:
        left = views[lv][ls].get(ln)
        right = views[rv][rs].get(rn)
        if left is None or right is None:
            findings.append(
                GateFinding("S5_CATALOG_IDENTITY_MISSING", f"missing identity pair {ln} -> {rn}")
            )
            continue
        same = _same_symbol(left, ln, right, rn)
        if not same:
            findings.append(
                GateFinding(
                    "S5_CATALOG_IDENTITY_SPLIT", f"historical rename split identity: {ln} -> {rn}"
                )
            )
        identities.append(
            {
                "left": f"v{lv}:{ls}.{ln}",
                "right": f"v{rv}:{rs}.{rn}",
                "symbol_id": left["symbol_id"],
                "same": same,
            }
        )

    availability = [
        (1, "keywords", "if", False),
        (2, "keywords", "if", True),
        (3, "types", "array", False),
        (4, "types", "array", True),
        (4, "functions", "ta.sma", False),
        (5, "functions", "ta.sma", True),
        (4, "functions", "study", True),
        (5, "functions", "study", False),
    ]
    for version, section, name, expected in availability:
        actual = name in views[version][section]
        if actual != expected:
            findings.append(
                GateFinding(
                    "S5_CATALOG_AVAILABILITY",
                    f"Pine v{version} {section}.{name}: expected {expected}, got {actual}",
                )
            )

    hashes = {version: raw[version]["catalog_hash"] for version in range(1, 7)}
    if len(set(hashes.values())) != 6:
        findings.append(
            GateFinding("S5_CATALOG_HASH_COLLAPSE", "six version pack identities must be distinct")
        )
    return GateResult(
        "stage5.historical-catalog",
        "PASS" if not findings else "FAIL",
        findings,
        {
            "catalog_hashes": hashes,
            "identity_checks": identities,
            "availability_check_count": len(availability),
            "gate_input_hash": content_hash({"checks": checks, "availability": availability}),
        },
    )


__all__ = ["run_historical_catalog_gate"]
