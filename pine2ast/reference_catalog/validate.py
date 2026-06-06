from __future__ import annotations

import json
from collections import Counter
from collections import defaultdict
from importlib.resources import files
from typing import Any

from pine2ast.reference_catalog.loader import load_catalog, load_parity_matrix
from pine2ast.reference_catalog.schema import (
    CATALOG_KIND_OFFICIAL_CATEGORY,
    MATRIX_OWNER_FIELD,
    MATRIX_REQUIRED_ITEM_FIELDS,
    REQUIRED_ENTRY_FIELDS,
    STATUS_FIELDS,
    VALID_KINDS,
    VALID_PRIORITIES,
    VALID_STATUSES,
)


class ReferenceCatalogError(ValueError):
    """Raised when the Pine reference catalog or parity matrix is invalid."""


def _load_official_index_payload(pine_version: int) -> dict[str, Any]:
    resource = f"official_pine_v{pine_version}_reference_index.json"
    path = files("pine2ast.reference_catalog").joinpath(resource)
    return json.loads(path.read_text(encoding="utf-8"))


def _official_categories(index: dict[str, Any]) -> dict[str, set[str]]:
    if index.get("schema_version") != "pain.official_pine_reference_index.v1":
        raise ReferenceCatalogError("official reference index schema mismatch")
    categories = index.get("categories")
    if not isinstance(categories, dict):
        raise ReferenceCatalogError("official reference index categories must be an object")
    return {
        str(category): {str(item) for item in items}
        for category, items in categories.items()
        if isinstance(items, list)
    }


def _catalog_identity(entry: dict[str, Any]) -> tuple[str, str] | None:
    item_id = entry.get("id")
    category = CATALOG_KIND_OFFICIAL_CATEGORY.get(str(entry.get("kind")))
    if not isinstance(item_id, str) or category is None:
        return None
    return category, item_id


def _matrix_identity(item: dict[str, Any]) -> tuple[str, str] | None:
    item_id = item.get("id")
    category = item.get("official_category")
    if not isinstance(item_id, str) or not isinstance(category, str):
        return None
    return category, item_id


def official_matrix_coverage_payload(
    matrix: dict[str, Any], official_index: dict[str, Any] | None = None
) -> dict[str, Any]:
    pine_version = int(matrix.get("pine_version", 6))
    index = (
        official_index if official_index is not None else _load_official_index_payload(pine_version)
    )
    official_by_category = _official_categories(index)
    tracked_by_category: dict[str, set[str]] = defaultdict(set)
    for item in matrix.get("items", []):
        if not isinstance(item, dict):
            continue
        identity = _matrix_identity(item)
        if identity is None:
            continue
        category, item_id = identity
        tracked_by_category[category].add(item_id)

    missing_by_category = {
        category: sorted(official_ids - tracked_by_category.get(category, set()))
        for category, official_ids in sorted(official_by_category.items())
    }
    extra_matrix_by_category = {
        category: sorted(tracked_ids - official_by_category.get(category, set()))
        for category, tracked_ids in sorted(tracked_by_category.items())
        if tracked_ids - official_by_category.get(category, set())
    }
    official_count = sum(len(items) for items in official_by_category.values())
    missing_count = sum(len(items) for items in missing_by_category.values())
    tracked_count = official_count - missing_count
    return {
        "schema_version": "pain.official_parity_matrix_coverage.v1",
        "pine_version": pine_version,
        "summary": {
            "official_reference_count": official_count,
            "matrix_tracked_official_count": tracked_count,
            "missing_official_count": missing_count,
            "coverage_ratio": None if official_count == 0 else tracked_count / official_count,
        },
        "missing_by_category": missing_by_category,
        "extra_matrix_by_category": extra_matrix_by_category,
    }


def _fail(errors: list[str]) -> None:
    if errors:
        raise ReferenceCatalogError("\n".join(errors))


def validate_catalog_payload(payload: dict[str, Any]) -> None:
    errors: list[str] = []
    if payload.get("schema_version") != "pain.pine_reference_catalog.v1":
        errors.append("catalog schema_version must be pain.pine_reference_catalog.v1")
    if payload.get("pine_version") != 6:
        errors.append("catalog pine_version must be 6")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("catalog entries must be a non-empty array")
        _fail(errors)
        return

    ids: list[str] = []
    for idx, entry in enumerate(entries):
        path = f"entries[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{path} must be an object")
            continue
        missing = REQUIRED_ENTRY_FIELDS - set(entry)
        if missing:
            errors.append(f"{path} missing fields: {sorted(missing)}")
        extra_statuses = [
            field for field in STATUS_FIELDS if entry.get(field) not in VALID_STATUSES
        ]
        if extra_statuses:
            errors.append(f"{path} invalid status fields: {extra_statuses}")
        if entry.get("kind") not in VALID_KINDS:
            errors.append(f"{path}.kind invalid: {entry.get('kind')!r}")
        if entry.get("priority") not in VALID_PRIORITIES:
            errors.append(f"{path}.priority invalid: {entry.get('priority')!r}")
        if entry.get("pine_version") != 6:
            errors.append(f"{path}.pine_version must be 6")
        if not isinstance(entry.get("id"), str) or not entry.get("id"):
            errors.append(f"{path}.id must be non-empty string")
        else:
            ids.append(entry["id"])
        for field in ("stateful", "requires_history", "side_effect"):
            if not isinstance(entry.get(field), bool):
                errors.append(f"{path}.{field} must be boolean")
        if not isinstance(entry.get("signatures"), list):
            errors.append(f"{path}.signatures must be an array")
        if not isinstance(entry.get("known_edge_cases"), list):
            errors.append(f"{path}.known_edge_cases must be an array")

    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate catalog ids: {duplicates}")
    _fail(errors)


def validate_matrix_payload(
    matrix: dict[str, Any],
    catalog: dict[str, Any],
    official_index: dict[str, Any] | None = None,
) -> None:
    errors: list[str] = []
    if matrix.get("schema_version") != "pain.parity_matrix.v1":
        errors.append("matrix schema_version must be pain.parity_matrix.v1")
    if matrix.get("pine_version") != 6:
        errors.append("matrix pine_version must be 6")
    items = matrix.get("items")
    if not isinstance(items, list):
        errors.append("matrix items must be an array")
        _fail(errors)
        return

    catalog_entries = catalog.get("entries", [])
    catalog_by_id = {
        entry["id"]: entry for entry in catalog_entries if isinstance(entry, dict) and "id" in entry
    }
    catalog_identities = {
        identity
        for entry in catalog_entries
        if isinstance(entry, dict) and (identity := _catalog_identity(entry))
    }
    official_by_category: dict[str, set[str]] = {}
    pine_version = matrix.get("pine_version")
    if isinstance(pine_version, int):
        try:
            index = (
                official_index
                if official_index is not None
                else _load_official_index_payload(pine_version)
            )
            official_by_category = _official_categories(index)
        except (FileNotFoundError, ReferenceCatalogError) as exc:
            errors.append(str(exc))
    matrix_identities: list[tuple[str, str]] = []
    for idx, item in enumerate(items):
        path = f"items[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        missing = MATRIX_REQUIRED_ITEM_FIELDS - set(item)
        if missing:
            errors.append(f"{path} missing fields: {sorted(missing)}")
        for field in STATUS_FIELDS:
            if item.get(field) not in VALID_STATUSES:
                errors.append(f"{path}.{field} invalid: {item.get(field)!r}")
        if item.get("priority") not in VALID_PRIORITIES:
            errors.append(f"{path}.priority invalid: {item.get('priority')!r}")
        owner = item.get(MATRIX_OWNER_FIELD)
        if owner is not None and not isinstance(owner, str):
            errors.append(f"{path}.{MATRIX_OWNER_FIELD} must be string or null")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{path}.id must be non-empty string")
            continue
        official_category = item.get("official_category")
        if not isinstance(official_category, str) or not official_category:
            errors.append(f"{path}.official_category must be non-empty string")
            continue
        if official_category not in official_by_category:
            errors.append(
                f"{path}.official_category not found in official reference: {official_category!r}"
            )
        elif item_id not in official_by_category[official_category]:
            errors.append(
                f"{path}.id not found in official {official_category} reference: {item_id!r}"
            )
        identity = (official_category, item_id)
        matrix_identities.append(identity)
        entry = catalog_by_id.get(item_id)
        if entry is not None and identity == _catalog_identity(entry):
            for field in ("priority", MATRIX_OWNER_FIELD, *STATUS_FIELDS):
                if item.get(field) != entry.get(field):
                    errors.append(f"{path}.{field} differs from catalog for {item_id}")
    missing_catalog = sorted(catalog_identities - set(matrix_identities))
    extra_duplicates = sorted(
        item for item, count in Counter(matrix_identities).items() if count > 1
    )
    if missing_catalog:
        preview = [f"{category}:{item_id}" for category, item_id in missing_catalog[:20]]
        suffix = "..." if len(missing_catalog) > 20 else ""
        errors.append(f"matrix missing catalog ids: {preview}{suffix}")
    if extra_duplicates:
        errors.append(f"matrix duplicate official ids: {extra_duplicates}")
    _fail(errors)


def validate_catalog(path: str | None = None) -> None:
    validate_catalog_payload(load_catalog(path))


def validate_matrix(catalog_path: str | None = None, matrix_path: str | None = None) -> None:
    catalog = load_catalog(catalog_path)
    validate_catalog_payload(catalog)
    validate_matrix_payload(load_parity_matrix(matrix_path), catalog)
