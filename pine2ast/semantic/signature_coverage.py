"""Version-aware builtin/signature coverage reporting.

The registry parity gate answers "is the official name present?".  This module
adds the next Release 4.0 question: "does the frontend have enough machine-readable
signature metadata to validate calls or expose OpenPine contracts?"  It is a
reporting layer, not a hard compatibility claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from pine2ast.semantic.builtin_registry import load_builtin_registry
from pine2ast.semantic.collection_signatures import collection_function_names

_REFERENCE_INDEX_FILES = {
    5: "official_pine_v5_reference_index.json",
    6: "official_pine_v6_reference_index.json",
}

_SIGNATURE_CATEGORIES = (
    "functions",
    "methods",
    "variables",
    "constants",
    "types",
    "operators",
    "keywords",
    "annotations",
)


@dataclass(frozen=True, slots=True)
class CategorySignatureCoverage:
    category: str
    official_count: int
    registry_count: int
    implemented_count: int
    missing: tuple[str, ...] = field(default_factory=tuple)
    registry_extra: tuple[str, ...] = field(default_factory=tuple)
    signature_ready_count: int = 0
    signature_pending: tuple[str, ...] = field(default_factory=tuple)

    @property
    def name_coverage_ratio(self) -> float:
        return 1.0 if self.official_count == 0 else self.implemented_count / self.official_count

    @property
    def signature_ready_ratio(self) -> float:
        return (
            1.0
            if self.implemented_count == 0
            else self.signature_ready_count / self.implemented_count
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "official_count": self.official_count,
            "registry_count": self.registry_count,
            "implemented_count": self.implemented_count,
            "name_coverage_ratio": round(self.name_coverage_ratio, 6),
            "signature_ready_count": self.signature_ready_count,
            "signature_ready_ratio": round(self.signature_ready_ratio, 6),
            "missing_count": len(self.missing),
            "missing": list(self.missing),
            "registry_extra_count": len(self.registry_extra),
            "registry_extra": list(self.registry_extra),
            "signature_pending_count": len(self.signature_pending),
            "signature_pending": list(self.signature_pending),
        }


@dataclass(frozen=True, slots=True)
class SignatureCoverageReport:
    schema_version: str
    pine_version: int
    categories: tuple[CategorySignatureCoverage, ...]
    reference_source: dict[str, Any]

    @property
    def ok(self) -> bool:
        return all(not category.missing for category in self.categories)

    @property
    def summary(self) -> dict[str, Any]:
        official = sum(category.official_count for category in self.categories)
        implemented = sum(category.implemented_count for category in self.categories)
        signature_ready = sum(category.signature_ready_count for category in self.categories)
        pending = sum(len(category.signature_pending) for category in self.categories)
        return {
            "official_count": official,
            "implemented_count": implemented,
            "missing_count": sum(len(category.missing) for category in self.categories),
            "registry_extra_count": sum(
                len(category.registry_extra) for category in self.categories
            ),
            "signature_ready_count": signature_ready,
            "signature_pending_count": pending,
            "name_coverage_ratio": round(1.0 if official == 0 else implemented / official, 6),
            "signature_ready_ratio": round(
                1.0 if implemented == 0 else signature_ready / implemented, 6
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pine_version": self.pine_version,
            "ok": self.ok,
            "summary": self.summary,
            "reference_source": self.reference_source,
            "categories": {category.category: category.to_dict() for category in self.categories},
        }


def _reference_root() -> Path:
    return Path(__file__).resolve().parent.parent / "reference_catalog"


def load_official_reference_index(pine_version: int) -> dict[str, Any]:
    version = 5 if pine_version == 5 else 6
    path = _reference_root() / _REFERENCE_INDEX_FILES[version]
    return json.loads(path.read_text(encoding="utf-8"))


def _registry_names(registry: Mapping[str, Any], category: str) -> set[str]:
    values = registry.get(category, {})
    if isinstance(values, Mapping):
        return {str(name) for name in values}
    if isinstance(values, (list, tuple, set)):
        return {str(name) for name in values}
    return set()


def _official_names(index: Mapping[str, Any], category: str) -> set[str]:
    values = (index.get("categories") or {}).get(category, [])
    return {str(name) for name in values}


def _entry_signature_ready(category: str, name: str, entry: Any) -> bool:
    if category in {"variables", "constants"}:
        return isinstance(entry, Mapping) and bool(entry.get("type") or entry.get("qualifier"))
    if category == "types":
        return isinstance(entry, Mapping)
    if category in {"operators", "keywords", "annotations"}:
        return True
    if category == "methods":
        if name in collection_function_names():
            return True
        return isinstance(entry, Mapping) and not entry.get("_signature_pending")
    if category == "functions":
        if name in collection_function_names():
            return True
        if not isinstance(entry, Mapping):
            return False
        if entry.get("_signature_pending"):
            return False
        return bool(
            "parameters" in entry
            or entry.get("overloads")
            or entry.get("signatures")
            or entry.get("allow_extra_positional")
        )
    return isinstance(entry, Mapping)


def _registry_entry(registry: Mapping[str, Any], category: str, name: str) -> Any:
    values = registry.get(category, {})
    return values.get(name) if isinstance(values, Mapping) else None


def build_signature_coverage_report(pine_version: int = 6) -> SignatureCoverageReport:
    version = 5 if pine_version == 5 else 6
    registry = load_builtin_registry(pine_version=version)
    official = load_official_reference_index(version)
    category_reports: list[CategorySignatureCoverage] = []
    for category in _SIGNATURE_CATEGORIES:
        official_names = _official_names(official, category)
        registry_names = _registry_names(registry, category)
        implemented = official_names & registry_names
        signature_pending = tuple(
            sorted(
                name
                for name in implemented
                if not _entry_signature_ready(
                    category, name, _registry_entry(registry, category, name)
                )
            )
        )
        category_reports.append(
            CategorySignatureCoverage(
                category=category,
                official_count=len(official_names),
                registry_count=len(registry_names),
                implemented_count=len(implemented),
                missing=tuple(sorted(official_names - registry_names)),
                registry_extra=tuple(sorted(registry_names - official_names)),
                signature_ready_count=len(implemented) - len(signature_pending),
                signature_pending=signature_pending,
            )
        )
    return SignatureCoverageReport(
        schema_version="pine2ast.signature_coverage.v1",
        pine_version=version,
        categories=tuple(category_reports),
        reference_source=dict(official.get("source") or {}),
    )


def signature_coverage_json(pine_version: int = 6, *, indent: int = 2) -> str:
    return json.dumps(
        build_signature_coverage_report(pine_version).to_dict(), ensure_ascii=False, indent=indent
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m pine2ast.semantic.signature_coverage")
    parser.add_argument("--version", type=int, choices=(5, 6), default=6)
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--fail-on-missing", action="store_true")
    parser.add_argument(
        "--fail-under-signature-ready-ratio",
        type=float,
        default=None,
        help="Fail if overall machine-readable signature coverage is below this ratio.",
    )
    args = parser.parse_args(argv)
    output = signature_coverage_json(args.version)
    if args.json_path:
        Path(args.json_path).write_text(output, encoding="utf-8")
        print(args.json_path)
    else:
        print(output)
    report = build_signature_coverage_report(args.version)
    if args.fail_on_missing and not report.ok:
        return 1
    if (
        args.fail_under_signature_ready_ratio is not None
        and report.summary["signature_ready_ratio"] < args.fail_under_signature_ready_ratio
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
