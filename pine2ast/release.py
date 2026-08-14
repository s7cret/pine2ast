"""Release-readiness helpers for the Pine2AST 4.0 release line.

The project intentionally separates frontend compatibility from TradingView runtime
parity.  This module turns that boundary into a small machine-readable manifest
that can be used by CI, release scripts, and OpenPine integration checks.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from pine2ast._version import __version__
from pine2ast.contracts import validate_contract_payload
from pine2ast.compatibility.release_features import (
    load_v6_release_features,
    release_feature_summary,
    validate_release_feature_matrix,
)
from pine2ast.semantic.builtin_registry import load_builtin_registry
from pine2ast.semantic.signature_coverage import build_signature_coverage_report
from pine2ast.api import ParseOptions, parse_code
from pine2ast.inspect_contract import build_inspect_payload
from pine2ast.semantic.snapshot import SEMANTIC_SNAPSHOT_CONTRACT
from pine2ast.quality import architecture_budget_report
from pine2ast.distribution import build_distribution_manifest
from pine2ast.testing.oracle import load_oracle_manifest, run_oracle_cases

RELEASE_LINE = "4.0"
RELEASE_VERSION = "4.0.2"
AST_CONTRACT_VERSION = "pine.ast_contract.v1"
OPENPINE_CONTRACT_VERSION = "openpine.frontend.v1"
RUNTIME_CONTRACT_PROFILE = "runtime_contract_v1_4"
SEMANTIC_SNAPSHOT_CONTRACT_VERSION = SEMANTIC_SNAPSHOT_CONTRACT

CANONICAL_DOCS = (
    "README.md",
    "ARCHITECTURE.md",
    "COMPATIBILITY.md",
    "DEVELOPMENT.md",
    "OPENPINE_CONTRACT.md",
    "RELEASE_4_0.md",
    "ROADMAP.md",
    "SECURITY.md",
)

LEGACY_DOC_PREFIXES = (
    "P1_",
    "P2_",
    "SPEC_",
    "STAGE",
    "TZ_",
)


@dataclass(frozen=True, slots=True)
class ReleaseCheck:
    """One deterministic readiness check in the release manifest."""

    name: str
    ok: bool
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """Machine-readable release state for the Pine2AST 4.0 frontend line."""

    schema_version: str
    package_version: str
    release_line: str
    ast_contract: str
    openpine_contract: str
    runtime_contract_profile: str
    docs: tuple[str, ...]
    checks: tuple[ReleaseCheck, ...]
    signature_coverage: Mapping[str, Any]
    release_features: Mapping[str, Any]
    compatibility: Mapping[str, Any]
    oracle: Mapping[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "package_version": self.package_version,
            "release_line": self.release_line,
            "contracts": {
                "ast": self.ast_contract,
                "openpine": self.openpine_contract,
                "runtime_contract_profile": self.runtime_contract_profile,
                "semantic_snapshot": SEMANTIC_SNAPSHOT_CONTRACT_VERSION,
            },
            "docs": list(self.docs),
            "checks": [check.to_dict() for check in self.checks],
            "signature_coverage": dict(self.signature_coverage),
            "release_features": dict(self.release_features),
            "compatibility": dict(self.compatibility),
            "oracle": dict(self.oracle) if self.oracle is not None else None,
        }


def _read_pyproject_version(root: Path) -> str | None:
    path = root / "pyproject.toml"
    if not path.exists():
        return None
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    return str(payload.get("project", {}).get("version") or "") or None


def _read_lock_version(root: Path) -> str | None:
    path = root / "uv.lock"
    if not path.exists():
        return None
    in_project = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[[package]]":
            in_project = False
            continue
        if stripped == 'name = "pine2ast"':
            in_project = True
            continue
        if in_project and stripped.startswith("version = "):
            return stripped.split("=", 1)[1].strip().strip('"')
    return None


def _docs_inventory(root: Path) -> tuple[str, ...]:
    docs = root / "docs"
    if not docs.exists():
        return ()
    return tuple(sorted(path.name for path in docs.glob("*.md") if path.is_file()))


def _legacy_docs(docs: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in docs if name.startswith(LEGACY_DOC_PREFIXES))


def _readme_checks(root: Path) -> tuple[ReleaseCheck, ...]:
    path = root / "README.md"
    if not path.exists():
        return (ReleaseCheck("readme_present", False, "README.md is missing"),)
    text = path.read_text(encoding="utf-8")
    checks = [
        ReleaseCheck(
            "readme_mentions_release_line",
            RELEASE_VERSION in text or f"{RELEASE_LINE}.x" in text,
            "README describes the 4.0 release line",
        ),
        ReleaseCheck(
            "readme_no_stage_snapshot_links",
            "docs/STAGE" not in text and "This snapshot" not in text,
            "README no longer links to intermediate Stage snapshot docs",
        ),
        ReleaseCheck(
            "readme_scope_boundary",
            "TradingView runtime" in text and "OpenPine" in text,
            "README states the frontend/runtime boundary",
        ),
    ]
    return tuple(checks)


_COMPATIBILITY_AXES = ("parser", "semantic", "codegen", "runtime", "golden")
_COMPATIBILITY_STATUSES = {
    "DONE_VERIFIED",
    "IMPLEMENTED_UNVERIFIED",
    "UNSUPPORTED_DIAGNOSTIC",
    "PARTIAL",
    "NOT_STARTED",
}


def _compatibility_matrix_status(root_path: Path) -> tuple[bool, dict[str, Any]]:
    """Validate the shipped capability matrix and expose its frontend-only scope."""

    matrix_path = root_path / "pine2ast" / "compatibility" / "compatibility_matrix.json"
    errors: list[str] = []
    payload: Any = None
    try:
        payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read compatibility matrix: {exc}")

    summary: dict[str, dict[str, int]] = {axis: {} for axis in _COMPATIBILITY_AXES}
    item_count = 0
    frontend_ready = False
    source_scope: Any = None
    if not isinstance(payload, dict):
        if not errors:
            errors.append("compatibility matrix must be an object")
    else:
        source_scope = payload.get("scope")
        if payload.get("schema_version") != "openpine.compatibility_matrix.v1":
            errors.append("unsupported compatibility matrix schema")
        if source_scope != "amended_6pkg_p0":
            errors.append("compatibility matrix scope must be amended_6pkg_p0")
        if payload.get("axes") != list(_COMPATIBILITY_AXES):
            errors.append("compatibility matrix axes are incomplete or out of order")
        status_values = payload.get("status_values")
        if not isinstance(status_values, list) or set(status_values) != _COMPATIBILITY_STATUSES:
            errors.append("compatibility matrix status values are incomplete")

        items = payload.get("items")
        declared_summary = payload.get("summary")
        if not isinstance(items, list) or not items:
            errors.append("compatibility matrix items must be a non-empty array")
            items = []
        if not isinstance(declared_summary, dict):
            errors.append("compatibility matrix summary must be an object")
            declared_summary = {}

        item_count = len(items)
        seen_items: set[tuple[str, str]] = set()
        recomputed: dict[str, Counter[str]] = {axis: Counter() for axis in _COMPATIBILITY_AXES}
        frontend_statuses: list[str] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"items[{index}] must be an object")
                continue
            item_id = item.get("id")
            category = item.get("category")
            if not isinstance(item_id, str) or not item_id:
                errors.append(f"items[{index}].id must be a non-empty string")
            if not isinstance(category, str) or not category:
                errors.append(f"items[{index}].category must be a non-empty string")
            if isinstance(item_id, str) and item_id and isinstance(category, str) and category:
                item_key = (category, item_id)
                if item_key in seen_items:
                    errors.append(f"duplicate compatibility item: {category}:{item_id}")
                else:
                    seen_items.add(item_key)
            for axis in _COMPATIBILITY_AXES:
                key = "oracle" if axis == "golden" else axis
                status = item.get(key)
                if status not in _COMPATIBILITY_STATUSES:
                    errors.append(f"items[{index}].{key} has invalid status {status!r}")
                    continue
                recomputed[axis][status] += 1
                if axis in {"parser", "semantic"}:
                    frontend_statuses.append(status)

        summary = {axis: dict(recomputed[axis]) for axis in _COMPATIBILITY_AXES}
        for axis in _COMPATIBILITY_AXES:
            if declared_summary.get(axis) != summary[axis]:
                errors.append(f"compatibility summary mismatch for {axis}")
        frontend_ready = bool(frontend_statuses) and all(
            status in {"DONE_VERIFIED", "UNSUPPORTED_DIAGNOSTIC"} for status in frontend_statuses
        )
        if not frontend_ready:
            errors.append("frontend parser/semantic capability set is not release-ready")

    details: dict[str, Any] = {
        "scope": "frontend_only",
        "source_scope": source_scope,
        "full_pipeline_parity_claimed": False,
        "item_count": item_count,
        "frontend_ready": frontend_ready,
        "summary": summary,
        "errors": errors,
    }
    return not errors, details


def build_release_manifest(
    root: str | Path = ".",
    *,
    strict_docs: bool = True,
    min_v5_signature_ready_ratio: float = 1.0,
    min_v6_signature_ready_ratio: float = 1.0,
    oracle_manifest: str | Path | None = None,
) -> ReleaseManifest:
    """Build a deterministic manifest for the 4.0 release candidate.

    The manifest does not claim full Pine runtime parity.  It validates the repo
    metadata, canonical docs inventory, release-feature matrix, official-name
    coverage, machine-readable signature-readiness floor, and optional oracle
    corpus health.
    """

    root_path = Path(root).resolve()
    checks: list[ReleaseCheck] = []
    compatibility_ok, compatibility = _compatibility_matrix_status(root_path)

    pyproject_version = _read_pyproject_version(root_path)
    lock_version = _read_lock_version(root_path)
    checks.append(
        ReleaseCheck(
            "version_metadata",
            __version__ == RELEASE_VERSION
            and pyproject_version == RELEASE_VERSION
            and (lock_version in {None, RELEASE_VERSION}),
            f"package, pyproject, and uv.lock versions are aligned for {RELEASE_VERSION}",
            {
                "package": __version__,
                "pyproject": pyproject_version,
                "uv_lock": lock_version,
                "expected": RELEASE_VERSION,
            },
        )
    )

    docs = _docs_inventory(root_path)
    legacy = _legacy_docs(docs)
    expected = set(CANONICAL_DOCS)
    actual = set(docs)
    docs_ok = not legacy and expected.issubset(actual)
    if strict_docs:
        docs_ok = docs_ok and actual == expected
    checks.append(
        ReleaseCheck(
            "canonical_docs_inventory",
            docs_ok,
            "docs/ contains the canonical 4.0 documentation set and no legacy planning docs",
            {
                "expected": list(CANONICAL_DOCS),
                "actual": list(docs),
                "legacy": list(legacy),
                "strict": strict_docs,
            },
        )
    )
    checks.extend(_readme_checks(root_path))
    checks.append(
        ReleaseCheck(
            "compatibility_scope_truthfulness",
            compatibility_ok,
            "frontend capabilities are complete and downstream gaps remain explicit",
            compatibility,
        )
    )

    release_payload = load_v6_release_features()
    release_errors = validate_release_feature_matrix(release_payload)
    release_summary = release_feature_summary(release_payload)
    checks.append(
        ReleaseCheck(
            "v6_release_feature_matrix",
            not release_errors,
            "v6 release-feature matrix has no unknown, duplicate, or not_started items",
            {"errors": list(release_errors), "summary": release_summary},
        )
    )

    signature_reports = {
        "v5": build_signature_coverage_report(5).to_dict(),
        "v6": build_signature_coverage_report(6).to_dict(),
    }
    v5_summary = signature_reports["v5"]["summary"]
    v6_summary = signature_reports["v6"]["summary"]
    checks.append(
        ReleaseCheck(
            "official_name_coverage",
            bool(signature_reports["v5"].get("ok")) and bool(signature_reports["v6"].get("ok")),
            "v5/v6 official names are present in the bundled registries",
            {"v5": v5_summary, "v6": v6_summary},
        )
    )

    runtime_registry_details: dict[str, dict[str, Any]] = {}
    for version in (5, 6):
        runtime_registry = load_builtin_registry(version)
        constants = runtime_registry.get("constants", {})
        semantic_values = runtime_registry.get("variables", {})
        missing_runtime_values = sorted(set(constants) - set(semantic_values))
        mismatched_runtime_values = sorted(
            name
            for name in set(constants) & set(semantic_values)
            if semantic_values[name].get("type") != constants[name].get("type")
            or semantic_values[name].get("qualifier") != constants[name].get("qualifier")
        )
        runtime_registry_details[f"v{version}"] = {
            "constant_count": len(constants),
            "semantic_value_count": len(semantic_values),
            "missing": missing_runtime_values,
            "mismatched": mismatched_runtime_values,
        }
    checks.append(
        ReleaseCheck(
            "runtime_registry_semantic_oracle",
            all(
                not details["missing"] and not details["mismatched"]
                for details in runtime_registry_details.values()
            ),
            "official v5/v6 constants are exposed through the runtime semantic value registries",
            runtime_registry_details,
        )
    )
    checks.append(
        ReleaseCheck(
            "signature_readiness_floor",
            v5_summary["signature_ready_ratio"] >= min_v5_signature_ready_ratio
            and v6_summary["signature_ready_ratio"] >= min_v6_signature_ready_ratio,
            "machine-readable signature coverage meets the 4.0 frontend floor",
            {
                "v5": v5_summary,
                "v6": v6_summary,
                "min_v5": min_v5_signature_ready_ratio,
                "min_v6": min_v6_signature_ready_ratio,
            },
        )
    )

    smoke_source = '//@version=6\nindicator("release contract smoke")\nplot(close)\n'
    smoke_result = parse_code(
        smoke_source, ParseOptions(version=6, source_name="release_contract_smoke.pine")
    )
    inspect_payload = build_inspect_payload(
        smoke_result,
        source_path="release_contract_smoke.pine",
        include_openpine_contract=True,
        include_semantic_snapshot=True,
    )
    contract_report = validate_contract_payload(inspect_payload).to_dict()
    checks.append(
        ReleaseCheck(
            "public_contract_smoke",
            smoke_result.ok and bool(contract_report.get("ok")),
            "inspect and embedded OpenPine contracts satisfy the structural contract validator",
            {
                "parse_ok": smoke_result.ok,
                "contract_report": contract_report,
            },
        )
    )

    architecture = architecture_budget_report(root_path / "pine2ast", max_lines=700).to_dict()
    # Keep packaged release manifests deterministic and free of local absolute paths.
    architecture["path"] = "pine2ast"
    checks.append(
        ReleaseCheck(
            "architecture_budget",
            bool(architecture.get("ok")),
            "Python modules stay under the 4.0 architecture budget",
            architecture,
        )
    )

    distribution = build_distribution_manifest(root_path).to_dict()
    # Keep packaged release manifests deterministic and free of local absolute paths.
    distribution["root"] = "."
    checks.append(
        ReleaseCheck(
            "distribution_hygiene",
            bool(distribution.get("ok")),
            "source-archive file selection excludes caches and includes required release files",
            distribution,
        )
    )

    oracle_payload: dict[str, Any] | None = None
    oracle_path = (
        Path(oracle_manifest)
        if oracle_manifest
        else root_path / "tests" / "oracle" / "frontend_oracle_manifest.json"
    )
    if oracle_path.exists():
        oracle_report = run_oracle_cases(load_oracle_manifest(oracle_path)).to_dict()
        oracle_payload = oracle_report
        checks.append(
            ReleaseCheck(
                "frontend_oracle",
                bool(oracle_report.get("ok")),
                "bundled frontend oracle manifest passes",
                {
                    "path": str(
                        oracle_path.relative_to(root_path)
                        if oracle_path.is_relative_to(root_path)
                        else oracle_path
                    ),
                    "case_count": oracle_report.get("case_count"),
                    "failure_count": oracle_report.get("failure_count"),
                },
            )
        )

    return ReleaseManifest(
        schema_version="pine2ast.release_manifest.v1",
        package_version=__version__,
        release_line=RELEASE_LINE,
        ast_contract=AST_CONTRACT_VERSION,
        openpine_contract=OPENPINE_CONTRACT_VERSION,
        runtime_contract_profile=RUNTIME_CONTRACT_PROFILE,
        docs=docs,
        checks=tuple(checks),
        signature_coverage=signature_reports,
        release_features={"summary": release_summary, "errors": list(release_errors)},
        compatibility=compatibility,
        oracle=oracle_payload,
    )


def release_manifest_json(root: str | Path = ".", *, indent: int = 2, **kwargs: Any) -> str:
    return json.dumps(
        build_release_manifest(root, **kwargs).to_dict(), ensure_ascii=False, indent=indent
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pine2ast.release")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument(
        "--relaxed-docs", action="store_true", help="Allow additional non-legacy docs"
    )
    parser.add_argument("--min-v5-signature-ready-ratio", type=float, default=1.0)
    parser.add_argument("--min-v6-signature-ready-ratio", type=float, default=1.0)
    parser.add_argument("--oracle-manifest")
    args = parser.parse_args(argv)
    manifest = build_release_manifest(
        args.root,
        strict_docs=not args.relaxed_docs,
        min_v5_signature_ready_ratio=args.min_v5_signature_ready_ratio,
        min_v6_signature_ready_ratio=args.min_v6_signature_ready_ratio,
        oracle_manifest=args.oracle_manifest,
    )
    payload = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2)
    if args.json_path:
        Path(args.json_path).write_text(payload + "\n", encoding="utf-8")
        print(args.json_path)
    else:
        print(payload)
    return 0 if manifest.ok else 1


__all__ = [
    "AST_CONTRACT_VERSION",
    "CANONICAL_DOCS",
    "OPENPINE_CONTRACT_VERSION",
    "RELEASE_LINE",
    "RELEASE_VERSION",
    "RUNTIME_CONTRACT_PROFILE",
    "SEMANTIC_SNAPSHOT_CONTRACT_VERSION",
    "ReleaseCheck",
    "ReleaseManifest",
    "build_release_manifest",
    "release_manifest_json",
]


if __name__ == "__main__":
    raise SystemExit(main())
