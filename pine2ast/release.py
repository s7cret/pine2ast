"""Pine2AST frontend release evidence.

This module reports only Pine2AST-owned concerns: package identity, version-pack
integrity, AST/frontend contracts, and static-semantic coverage. Runtime, codegen,
broker, and live-readiness belong to downstream repositories.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pine2ast._version import __version__
from pine2ast.catalog import CatalogRepository
from pine2ast.distribution import build_distribution_manifest

AST_CONTRACT = "pine.ast.v2"
FRONTEND_CONTRACT = "pine.frontend.v3"
SEMANTIC_FACTS_CONTRACT = "pine.semantic_facts.v1"


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    schema_version: str
    package_version: str
    contracts: dict[str, str]
    catalog_versions: tuple[dict[str, Any], ...]
    distribution: dict[str, Any]
    static_coverage: dict[str, Any]

    @property
    def ok(self) -> bool:
        return (
            bool(self.distribution.get("ok"))
            and all(
                row.get("catalog_hash", "").startswith("sha256:") for row in self.catalog_versions
            )
            and bool(self.static_coverage.get("ok", True))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "package_version": self.package_version,
            "contracts": dict(self.contracts),
            "catalog_versions": [dict(row) for row in self.catalog_versions],
            "distribution": dict(self.distribution),
            "static_coverage": dict(self.static_coverage),
        }


def build_release_manifest(
    root: str | Path = ".",
    *,
    min_v5_signature_ready_ratio: float = 1.0,
    min_v6_signature_ready_ratio: float = 1.0,
    **_: Any,
) -> ReleaseManifest:
    if not 0.0 <= min_v5_signature_ready_ratio <= 1.0:
        raise ValueError("min_v5_signature_ready_ratio must be in [0, 1]")
    if not 0.0 <= min_v6_signature_ready_ratio <= 1.0:
        raise ValueError("min_v6_signature_ready_ratio must be in [0, 1]")
    repository = CatalogRepository.default()
    catalog_rows = tuple(
        {
            "pine_version": version,
            "status": repository.identity(version).status.value,
            "spec_snapshot_ref": repository.identity(version).spec_snapshot_ref,
            "catalog_hash": repository.identity(version).catalog_hash,
        }
        for version in range(1, 7)
    )
    try:
        from pine2ast.semantic.coverage import static_semantic_release_coverage

        coverage = static_semantic_release_coverage(
            min_v5=min_v5_signature_ready_ratio,
            min_v6=min_v6_signature_ready_ratio,
        )
    except ImportError:
        coverage = {"ok": True, "status": "stage2_catalog_only"}
    return ReleaseManifest(
        schema_version="pine2ast.release_manifest.v2",
        package_version=__version__,
        contracts={
            "ast": AST_CONTRACT,
            "frontend": FRONTEND_CONTRACT,
            "semantic_facts": SEMANTIC_FACTS_CONTRACT,
        },
        catalog_versions=catalog_rows,
        distribution=build_distribution_manifest(root).to_dict(),
        static_coverage=coverage,
    )


def release_manifest_json(root: str | Path = ".", *, indent: int = 2, **kwargs: Any) -> str:
    return json.dumps(
        build_release_manifest(root, **kwargs).to_dict(), ensure_ascii=False, indent=indent
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pine2ast.release")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    payload = release_manifest_json(args.root)
    if args.json:
        Path(args.json).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if json.loads(payload)["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = [
    "AST_CONTRACT",
    "FRONTEND_CONTRACT",
    "SEMANTIC_FACTS_CONTRACT",
    "ReleaseManifest",
    "build_release_manifest",
    "release_manifest_json",
]
