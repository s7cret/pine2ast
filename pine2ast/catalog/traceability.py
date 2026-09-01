"""Machine-readable provenance and lifecycle evidence for Pine v1-v6 catalogs.

The artifact describes only materialized static frontend packs.  In particular,
historical v1-v4 profiles remain non-exhaustive snapshots and the external
TradingView runtime/compile oracle is explicitly not run.
"""

from __future__ import annotations

from typing import Any, Mapping

from pine2ast.catalog.hashing import seal_hash, verify_hash
from pine2ast.catalog.repository import CatalogRepository


def _active_symbols(pack: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    active: dict[str, dict[str, str]] = {}
    sections = pack.get("sections")
    if not isinstance(sections, Mapping):
        return active
    for section_name, section in sections.items():
        if not isinstance(section, Mapping):
            continue
        for name, definition in section.items():
            if not isinstance(definition, Mapping):
                continue
            symbol_id = definition.get("symbol_id")
            if isinstance(symbol_id, str):
                active[symbol_id] = {
                    "section": str(section_name),
                    "name": str(name),
                }
    return active


def _negative_profile(
    *,
    adjacent_version: int | None,
    must_be_absent: set[str],
    adjacent_symbols: set[str],
) -> dict[str, Any]:
    if adjacent_version is None:
        return {
            "adjacent_version": None,
            "status": "NOT_APPLICABLE",
            "must_be_absent_symbol_ids": [],
        }
    verified = not (must_be_absent & adjacent_symbols)
    return {
        "adjacent_version": adjacent_version,
        "status": "VERIFIED" if verified else "FAILED",
        "must_be_absent_symbol_ids": sorted(must_be_absent),
    }


def build_catalog_traceability_artifact(
    repository: CatalogRepository | None = None,
) -> dict[str, Any]:
    """Build deterministic source, lifecycle, and adjacent-negative evidence."""

    repo = repository or CatalogRepository.default()
    packs = {version: repo.pack(version) for version in range(1, 7)}
    symbols = {version: _active_symbols(pack) for version, pack in packs.items()}
    profiles: dict[str, Any] = {}

    for version in range(1, 7):
        pack = packs[version]
        current = set(symbols[version])
        previous = set(symbols[version - 1]) if version > 1 else set()
        following = set(symbols[version + 1]) if version < 6 else set()
        introduced = current - previous
        removed = previous - current
        removed_before_next = current - following if version < 6 else set()
        profiles[str(version)] = {
            "pine_version": version,
            "status": pack["status"],
            "coverage_basis": pack["coverage_basis"],
            "coverage_claim": (
                "NON_EXHAUSTIVE_HISTORICAL_STATIC_SNAPSHOT"
                if version <= 4
                else "PINNED_OFFICIAL_NAME_SNAPSHOT"
            ),
            "spec_snapshot_ref": pack["spec_snapshot_ref"],
            "catalog_hash": pack["catalog_hash"],
            "source_manifest_hash": pack["source_manifest_hash"],
            "historical_projection_hash": pack["historical_projection_hash"],
            "provenance_sources": pack["provenance_sources"],
            "active_symbol_ids": sorted(current),
            "transition_from_previous": {
                "previous_version": version - 1 if version > 1 else None,
                "introduced_symbol_ids": sorted(introduced),
                "removed_symbol_ids": sorted(removed),
            },
            "adjacent_negative_profiles": {
                "previous": _negative_profile(
                    adjacent_version=version - 1 if version > 1 else None,
                    must_be_absent=introduced,
                    adjacent_symbols=previous,
                ),
                "next": _negative_profile(
                    adjacent_version=version + 1 if version < 6 else None,
                    must_be_absent=removed_before_next,
                    adjacent_symbols=following,
                ),
            },
            "tradingview_runtime_oracle": {
                "status": "NOT_RUN",
                "evidence_id": None,
            },
        }

    all_symbol_ids = sorted(set().union(*(set(items) for items in symbols.values())))
    lifecycles: dict[str, Any] = {}
    for symbol_id in all_symbol_ids:
        observed = [version for version in range(1, 7) if symbol_id in symbols[version]]
        spellings = {str(version): symbols[version][symbol_id] for version in observed}
        last = max(observed)
        lifecycles[symbol_id] = {
            "introduced_in": min(observed),
            "last_observed_in": last,
            "removed_after": last if last < 6 else None,
            "observed_versions": observed,
            "absent_versions": [version for version in range(1, 7) if version not in observed],
            "active_spellings": spellings,
        }

    return seal_hash(
        {
            "schema_id": "pine.catalog.traceability.v1",
            "schema_version": "1.0.0",
            "scope": "static_frontend_catalog_only",
            "historical_policy": (
                "v1-v4 are conservative historical static snapshots, not exhaustive "
                "reference-manual scrapes"
            ),
            "versions": profiles,
            "symbol_lifecycles": lifecycles,
        }
    )


def validate_catalog_traceability_artifact(artifact: Mapping[str, Any]) -> tuple[str, ...]:
    """Return fail-closed invariant violations for a traceability artifact."""

    issues: list[str] = []
    plain = dict(artifact)
    if plain.get("schema_id") != "pine.catalog.traceability.v1":
        issues.append("schema_id")
    if not verify_hash(plain):
        issues.append("content_hash")
    versions = plain.get("versions")
    if not isinstance(versions, Mapping) or set(versions) != {str(v) for v in range(1, 7)}:
        issues.append("version_set")
        return tuple(issues)

    active_by_version: dict[int, set[str]] = {}
    for version in range(1, 7):
        profile = versions[str(version)]
        if not isinstance(profile, Mapping):
            issues.append(f"v{version}.profile")
            continue
        active = profile.get("active_symbol_ids")
        if not isinstance(active, list) or any(not isinstance(item, str) for item in active):
            issues.append(f"v{version}.active_symbol_ids")
            continue
        active_by_version[version] = set(active)
        if not profile.get("provenance_sources"):
            issues.append(f"v{version}.provenance_sources")
        oracle = profile.get("tradingview_runtime_oracle")
        if oracle != {"status": "NOT_RUN", "evidence_id": None}:
            issues.append(f"v{version}.oracle_claim")

    if len(active_by_version) != 6:
        return tuple(issues)
    for version in range(1, 7):
        profile = versions[str(version)]
        transition = profile.get("transition_from_previous")
        negatives = profile.get("adjacent_negative_profiles")
        if not isinstance(transition, Mapping) or not isinstance(negatives, Mapping):
            issues.append(f"v{version}.transition")
            continue
        current = active_by_version[version]
        previous = active_by_version.get(version - 1, set())
        following = active_by_version.get(version + 1, set())
        if set(transition.get("introduced_symbol_ids", [])) != current - previous:
            issues.append(f"v{version}.introduced")
        if set(transition.get("removed_symbol_ids", [])) != previous - current:
            issues.append(f"v{version}.removed")
        previous_negative = negatives.get("previous")
        next_negative = negatives.get("next")
        if not isinstance(previous_negative, Mapping) or not isinstance(next_negative, Mapping):
            issues.append(f"v{version}.adjacent_negative_profiles")
            continue
        if set(previous_negative.get("must_be_absent_symbol_ids", [])) & previous:
            issues.append(f"v{version}.previous_negative")
        if set(next_negative.get("must_be_absent_symbol_ids", [])) & following:
            issues.append(f"v{version}.next_negative")

    lifecycles = plain.get("symbol_lifecycles")
    expected_ids = set().union(*active_by_version.values())
    if not isinstance(lifecycles, Mapping) or set(lifecycles) != expected_ids:
        issues.append("symbol_lifecycles")
    return tuple(issues)


__all__ = [
    "build_catalog_traceability_artifact",
    "validate_catalog_traceability_artifact",
]
