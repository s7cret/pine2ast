"""Honest, multi-axis Pine version coverage reporting.

The report intentionally separates verified frontend requirements from internal
catalog completeness and from downstream/runtime parity.  It never derives an
official TradingView coverage percentage from the size of an internal catalog.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pine2ast.semantic.version_semantics import requirements_for_version, requirements_hash


def _stable_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _hash(value: object) -> str:
    return "sha256:" + sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _find_pack(version: int) -> Path:
    root = _package_root()
    patterns = (
        f"**/pine_v{version}.pack.json",
        f"**/pine-v{version}.pack.json",
        f"**/v{version}.pack.json",
        f"**/pine_v{version}.json",
    )
    found: list[Path] = []
    for pattern in patterns:
        found.extend(root.glob(pattern))
    unique = sorted({path.resolve() for path in found if path.is_file()})
    if len(unique) != 1:
        raise FileNotFoundError(
            f"expected exactly one Pine v{version} materialized pack, found {unique}"
        )
    return unique[0]


def _walk(value: object):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _walk(child)


def _entry_count(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if (
        isinstance(value, Mapping)
        or isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
    ):
        return len(value)
    return None


def _pack_metrics(version: int) -> dict[str, Any]:
    path = _find_pack(version)
    raw_bytes = path.read_bytes()
    payload = json.loads(raw_bytes)
    symbol_count = _entry_count(payload, "symbols")
    operator_count = _entry_count(payload, "operators")
    callable_count = 0
    callable_sections = False
    for key in ("functions", "methods", "declarations", "callables"):
        count = _entry_count(payload, key)
        if count is not None:
            callable_sections = True
            callable_count += count
    if symbol_count is None:
        seen_ids: set[str] = set()
        callable_ids: set[str] = set()
        operator_ids: set[str] = set()
        for node in _walk(payload):
            sid = node.get("symbol_id")
            if isinstance(sid, str):
                seen_ids.add(sid)
                kind = str(node.get("kind", "")).lower()
                if kind in {"function", "method", "declaration", "callable"}:
                    callable_ids.add(sid)
                if kind == "operator":
                    operator_ids.add(sid)
        symbol_count = len(seen_ids)
        if not callable_sections:
            callable_count = len(callable_ids)
        if operator_count is None:
            operator_count = len(operator_ids)
    status = (
        payload.get("support_status")
        or payload.get("status")
        or payload.get("completeness_status")
        or "UNKNOWN"
    )
    return {
        "pack_path": str(path.relative_to(_package_root())),
        "pack_sha256": "sha256:" + sha256(raw_bytes).hexdigest(),
        "pack_declared_hash": payload.get("content_hash") or payload.get("pack_hash"),
        "status": str(status),
        "symbol_count": int(symbol_count or 0),
        "callable_count": int(callable_count or 0),
        "operator_count": int(operator_count or 0),
    }


def build_version_coverage_report(
    *,
    verified_test_ids: set[str] | None = None,
    full_test_suite_passed: bool = False,
    catalog_gate_passed: bool = False,
    differential_gate_passed: bool = False,
) -> dict[str, Any]:
    verified_test_ids = set(verified_test_ids or ())
    versions: dict[str, Any] = {}
    for version in range(1, 7):
        frontend = requirements_for_version(version, owner="pine2ast")
        downstream = tuple(
            row for row in requirements_for_version(version) if row.owner != "pine2ast"
        )
        verified = tuple(row for row in frontend if row.test_id in verified_test_ids)
        frontend_total = len(frontend)
        verified_count = len(verified)
        versions[str(version)] = {
            "pine_version": version,
            "version_resolution": {
                "verified": full_test_suite_passed,
                "coverage_percent": 100.0 if full_test_suite_passed else 0.0,
            },
            "normative_static_frontend": {
                "requirements_total": frontend_total,
                "implemented": frontend_total,
                "verified": verified_count,
                "coverage_percent": (
                    round(100.0 * verified_count / frontend_total, 2) if frontend_total else 100.0
                ),
                "requirement_ids": [row.requirement_id for row in frontend],
                "verification_test_ids": [row.test_id for row in verified],
            },
            "internal_catalog": {
                **_pack_metrics(version),
                "structural_gate_passed": catalog_gate_passed,
                "internal_structural_coverage_percent": 100.0 if catalog_gate_passed else 0.0,
            },
            "official_reference_symbol_coverage": {
                "coverage_percent": None,
                "status": "NOT_CLAIMED",
                "reason": "No complete versioned official machine-readable historical symbol corpus is pinned; internal pack size is not an official denominator.",
            },
            "downstream_semantics": {
                "requirements_total": len(downstream),
                "verified_by_pine2ast": 0,
                "status": "DECLARED_NOT_VERIFIED_BY_FRONTEND",
                "requirements": [
                    {
                        "requirement_id": row.requirement_id,
                        "owner": row.owner,
                        "category": row.category,
                    }
                    for row in downstream
                ],
            },
            "tradingview_runtime_oracle": {
                "coverage_percent": 0.0,
                "status": "NOT_RUN_IN_PINE2AST",
            },
        }
    report = {
        "schema_id": "pine2ast.version_coverage.v2",
        "schema_version": "2.0.0",
        "scope": "Pine2AST parser, binder, type/qualifier/overload analysis and static version rules",
        "requirements_hash": requirements_hash(),
        "full_test_suite_passed": full_test_suite_passed,
        "catalog_gate_passed": catalog_gate_passed,
        "differential_gate_passed": differential_gate_passed,
        "coverage_policy": {
            "separate_axes": True,
            "internal_catalog_is_not_official_coverage": True,
            "runtime_parity_not_claimed": True,
            "downstream_requirements_excluded_from_frontend_percentage": True,
        },
        "versions": versions,
    }
    report["content_hash"] = _hash(report)
    return report


def validate_version_coverage_report(report: Mapping[str, Any]) -> tuple[str, ...]:
    """Return invariant violations for a Stage 6 coverage report."""
    issues: list[str] = []
    if report.get("schema_id") != "pine2ast.version_coverage.v2":
        issues.append("schema_id")
    content_hash = report.get("content_hash")
    if not isinstance(content_hash, str):
        issues.append("content_hash_missing")
    else:
        body = dict(report)
        body.pop("content_hash", None)
        if content_hash != _hash(body):
            issues.append("content_hash_mismatch")
    versions = report.get("versions")
    if not isinstance(versions, Mapping) or set(versions) != {str(v) for v in range(1, 7)}:
        issues.append("version_set")
        return tuple(issues)
    for version, row in versions.items():
        if not isinstance(row, Mapping):
            issues.append(f"v{version}.row")
            continue
        static = row.get("normative_static_frontend")
        if not isinstance(static, Mapping):
            issues.append(f"v{version}.static")
        else:
            total = static.get("requirements_total")
            verified = static.get("verified")
            percent = static.get("coverage_percent")
            if (
                type(total) is not int
                or type(verified) is not int
                or total < 0
                or verified < 0
                or verified > total
            ):
                issues.append(f"v{version}.static_counts")
            else:
                expected = round(100.0 * verified / total, 2) if total else 100.0
                if percent != expected:
                    issues.append(f"v{version}.static_percent")
        official = row.get("official_reference_symbol_coverage")
        if (
            not isinstance(official, Mapping)
            or official.get("coverage_percent") is not None
            or official.get("status") != "NOT_CLAIMED"
        ):
            issues.append(f"v{version}.official_claim")
        oracle = row.get("tradingview_runtime_oracle")
        if (
            not isinstance(oracle, Mapping)
            or oracle.get("coverage_percent") != 0.0
            or oracle.get("status") != "NOT_RUN_IN_PINE2AST"
        ):
            issues.append(f"v{version}.oracle_claim")
        downstream = row.get("downstream_semantics")
        if not isinstance(downstream, Mapping) or downstream.get("verified_by_pine2ast") != 0:
            issues.append(f"v{version}.downstream_claim")
    return tuple(issues)


__all__ = ["build_version_coverage_report", "validate_version_coverage_report"]
