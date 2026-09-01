from __future__ import annotations

from typing import Any, TypedDict

from pine2ast.catalog.repository import CatalogRepository

# Curated frontend confidence sets. They are deliberately not represented as an
# official-completeness claim.
INTERNAL_EXPECTED_NAMESPACE_MEMBERS: dict[str, set[str]] = {
    "ta": {
        "sma",
        "ema",
        "bb",
        "macd",
        "rsi",
        "atr",
        "highest",
        "lowest",
        "crossover",
        "crossunder",
        "change",
        "valuewhen",
    },
    "math": {
        "abs",
        "max",
        "min",
        "round",
        "floor",
        "ceil",
        "sqrt",
        "pow",
        "log",
        "exp",
        "sin",
        "cos",
    },
    "str": {
        "tostring",
        "tonumber",
        "format",
        "contains",
        "startswith",
        "endswith",
        "replace",
        "split",
        "length",
    },
    "color": {"new", "rgb", "from_gradient"},
    "request": {
        "currency_rate",
        "dividends",
        "economic",
        "earnings",
        "financial",
        "footprint",
        "quandl",
        "security",
        "security_lower_tf",
        "seed",
        "splits",
    },
}
OFFICIAL_UNMAPPED_NAMESPACE_MEMBERS: dict[str, set[str]] = {}
KNOWN_DEFERRED_NAMESPACE_MEMBERS: dict[str, set[str]] = {}
KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS: dict[str, set[str]] = {
    "log": {"error", "info", "warning"},
    "request": {"economic"},
    "runtime": {"error"},
}


class CatalogCoverageReport(TypedDict):
    pine_version: int
    catalog_hash: str
    status: str
    section_counts: dict[str, int]
    missing_internal_expected_count: int
    namespaces: dict[str, Any]


def _full_names(namespace: str, members: set[str]) -> set[str]:
    return {f"{namespace}.{member}" for member in members}


def catalog_coverage_report(pine_version: int = 6) -> CatalogCoverageReport:
    view = CatalogRepository.default().view(pine_version)
    all_entries: set[str] = set()
    for section in ("functions", "variables", "constants", "methods"):
        all_entries.update(view.get(section, {}))
    namespaces = set(view.get("namespaces", {})) | set(INTERNAL_EXPECTED_NAMESPACE_MEMBERS)
    reports: dict[str, Any] = {}
    missing_count = 0
    for namespace in sorted(namespaces):
        prefix = namespace + "."
        entries = sorted(name for name in all_entries if name.startswith(prefix))
        expected = _full_names(namespace, INTERNAL_EXPECTED_NAMESPACE_MEMBERS.get(namespace, set()))
        missing = sorted(expected - set(entries))
        missing_count += len(missing)
        reports[namespace] = {
            "entries": entries,
            "entry_count": len(entries),
            "internal_expected_count": len(expected),
            "missing_internal_expected": missing,
            "coverage_basis": "curated_frontend_confidence_set_not_official_complete",
        }
    return {
        "pine_version": pine_version,
        "catalog_hash": str(view["catalog_hash"]),
        "status": str(view["catalog_status"]),
        "section_counts": {
            section: len(value)
            for section, value in view.items()
            if isinstance(value, dict) and section not in {"rules"}
        },
        "missing_internal_expected_count": missing_count,
        "namespaces": reports,
    }


__all__ = [
    "INTERNAL_EXPECTED_NAMESPACE_MEMBERS",
    "KNOWN_DEFERRED_NAMESPACE_MEMBERS",
    "KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS",
    "OFFICIAL_UNMAPPED_NAMESPACE_MEMBERS",
    "CatalogCoverageReport",
    "catalog_coverage_report",
]
