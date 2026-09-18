"""Stage 2.10 coordinated language publication.

One published contract binds pine2ast, ast2python and pinelib. A local green
run that disagrees with this lock is not a publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import pine2ast
from pine2ast.catalog.repository import CatalogRepository

LOCK_PATH = Path(__file__).with_name("stage2_10_language_publication.json")


class LanguagePublicationError(Exception):
    """Published language identity does not match the installed packages."""


def load_language_publication(path: Path | None = None) -> dict[str, Any]:
    payload = json.loads((path or LOCK_PATH).read_text(encoding="utf-8"))
    if payload.get("schema_id") != "openpine.stage2_10_language_publication.v1":
        raise LanguagePublicationError("unsupported language publication schema")
    return payload


def catalog_hashes() -> dict[str, str]:
    repo = CatalogRepository.default()
    return {str(version): repo.identity(version).catalog_hash for version in range(1, 7)}


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def observe_language_publication(
    *,
    ast2python_version: str | None = None,
    pinelib_version: str | None = None,
    compiler_target_hash: str | None = None,
    compiler_target_name: str | None = None,
    compiler_target_version: str | None = None,
    runtime_target_file_hash: str | None = None,
) -> dict[str, Any]:
    """Observe the installed language surface. Missing compiler/runtime fields stay None."""
    return {
        "packages": {
            "pine2ast": pine2ast.__version__,
            "ast2python": ast2python_version,
            "pinelib": pinelib_version,
        },
        "catalog_hashes": catalog_hashes(),
        "compiler_target_hash": compiler_target_hash,
        "compiler_target_name": compiler_target_name,
        "compiler_target_version": compiler_target_version,
        "runtime_target_file_hash": runtime_target_file_hash,
    }


def _mismatch(label: str, expected: object, actual: object) -> LanguagePublicationError:
    return LanguagePublicationError(
        f"{label} mismatch: published {expected!r}, installed {actual!r}"
    )


PRIMARY_STAGE2_CRITERIA = (
    "versioned_catalog",
    "stateful_language_matrix",
    "imports",
    "independent_builtin_expected",
)
MANDATORY_STAGE2_GATES = (
    "python_3.11",
    "python_3.13",
    "sandbox",
    "protected_workers",
    "stage1_corpus",
    "architecture",
    "frontend",
    "package_builds",
    "test_inventory",
)


def _verify_full_acceptance(
    published: Mapping[str, Any], evidence_root: Path | None = None
) -> None:
    """A package publication is never a substitute for the full-stage run receipts."""
    residuals = published.get("residuals")
    if not isinstance(residuals, list):
        raise LanguagePublicationError("full acceptance requires a structured residual register")
    if any(
        not isinstance(row, Mapping)
        or row.get("status") != "resolved"
        or not row.get("evidence_hash")
        for row in residuals
    ):
        raise LanguagePublicationError("full acceptance has unresolved residual blockers")
    criteria = published.get("criteria", {})
    if any(criteria.get(key) != "accepted" for key in PRIMARY_STAGE2_CRITERIA):
        raise LanguagePublicationError(
            "full acceptance requires all four accepted primary criteria"
        )
    source_hash = published.get("source_lock_hash")
    if (
        not isinstance(source_hash, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", source_hash) is None
    ):
        raise LanguagePublicationError("full acceptance lacks an exact coordinated source lock")
    receipts = published.get("mandatory_gate_receipts", {})
    for name in MANDATORY_STAGE2_GATES:
        receipt = receipts.get(name) if isinstance(receipts, Mapping) else None
        if (
            not isinstance(receipt, Mapping)
            or receipt.get("status") != "passed"
            or receipt.get("source_lock_hash") != source_hash
            or not receipt.get("artifact_hash")
            or any(receipt.get(key) != 0 for key in ("failures", "errors", "skipped"))
        ):
            raise LanguagePublicationError(
                f"full acceptance lacks clean exact-tree receipt: {name}"
            )
        if evidence_root is None:
            raise LanguagePublicationError("full acceptance requires the actual evidence directory")
        root = evidence_root.resolve()
        relative = receipt.get("artifact_path")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise LanguagePublicationError(f"unsafe receipt path: {name}")
        candidate = root / relative
        if (
            candidate.is_symlink()
            or not candidate.resolve().is_relative_to(root)
            or not candidate.is_file()
        ):
            raise LanguagePublicationError(f"missing or unsafe receipt file: {name}")
        if file_sha256(candidate) != receipt["artifact_hash"]:
            raise LanguagePublicationError(f"receipt file hash mismatch: {name}")
        try:
            actual = json.loads(candidate.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise LanguagePublicationError(f"invalid receipt file: {name}") from exc
        for key in ("status", "source_lock_hash", "failures", "errors", "skipped"):
            if not isinstance(actual, Mapping) or actual.get(key) != receipt.get(key):
                raise LanguagePublicationError(f"receipt content mismatch: {name}.{key}")


def verify_language_publication(
    lock: Mapping[str, Any] | None = None,
    observation: Mapping[str, Any] | None = None,
    *,
    mode: str = "local",
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Check observed identities; coordinated mode requires every component.

    Local verification explicitly reports incomplete observations. Neither mode
    attests test execution; full-stage acceptance additionally needs sealed receipts.
    """
    if mode not in {"local", "coordinated"}:
        raise LanguagePublicationError("unknown publication verification mode")
    published = load_language_publication() if lock is None else lock
    observed = observe_language_publication() if observation is None else observation
    if published.get("schema_id") != "openpine.stage2_10_language_publication.v1":
        raise LanguagePublicationError("unsupported language publication schema")
    packages = observed.get("packages", {})
    if published.get("packages", {}).get("pine2ast") != packages.get("pine2ast"):
        raise _mismatch(
            "pine2ast version",
            published.get("packages", {}).get("pine2ast"),
            packages.get("pine2ast"),
        )
    missing = []
    for field in ("ast2python", "pinelib"):
        actual = packages.get(field)
        if actual is None:
            missing.append(f"packages.{field}")
        elif published.get("packages", {}).get(field) != actual:
            raise _mismatch(f"{field} version", published.get("packages", {}).get(field), actual)
    if published.get("catalog_hashes") != observed.get("catalog_hashes"):
        raise _mismatch(
            "catalog hashes", published.get("catalog_hashes"), observed.get("catalog_hashes")
        )
    for field in (
        "compiler_target_hash",
        "compiler_target_name",
        "compiler_target_version",
        "runtime_target_file_hash",
    ):
        actual = observed.get(field)
        if actual is None:
            missing.append(field)
        elif published.get(field) != actual:
            raise _mismatch(field, published.get(field), actual)
    if mode == "coordinated" and missing:
        raise LanguagePublicationError(
            "coordinated publication lacks observations: " + ", ".join(missing)
        )
    if published.get("full_stage2_accepted") is True:
        _verify_full_acceptance(published, evidence_root)
        if missing:
            raise LanguagePublicationError(
                "full acceptance requires complete coordinated observations"
            )
    return {
        "status": "published" if mode == "coordinated" else "verified_local",
        "publication": published["publication"],
        "mode": mode,
        "observation_complete": not missing,
        "missing_observations": missing,
        "full_stage2_accepted": published.get("full_stage2_accepted") is True,
    }
