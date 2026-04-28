from __future__ import annotations

from collections import Counter
from typing import Any

from pine2ast.reference_catalog.loader import load_catalog, load_parity_matrix
from pine2ast.reference_catalog.schema import (
    REQUIRED_ENTRY_FIELDS,
    STATUS_FIELDS,
    VALID_KINDS,
    VALID_PRIORITIES,
    VALID_STATUSES,
)


class ReferenceCatalogError(ValueError):
    """Raised when the Pine reference catalog or parity matrix is invalid."""


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
        extra_statuses = [field for field in STATUS_FIELDS if entry.get(field) not in VALID_STATUSES]
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


def validate_matrix_payload(matrix: dict[str, Any], catalog: dict[str, Any]) -> None:
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
    catalog_by_id = {entry["id"]: entry for entry in catalog_entries if isinstance(entry, dict) and "id" in entry}
    matrix_ids: list[str] = []
    for idx, item in enumerate(items):
        path = f"items[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or item_id not in catalog_by_id:
            errors.append(f"{path}.id not found in catalog: {item_id!r}")
            continue
        matrix_ids.append(item_id)
        entry = catalog_by_id[item_id]
        for field in ("priority", *STATUS_FIELDS):
            if item.get(field) != entry.get(field):
                errors.append(f"{path}.{field} differs from catalog for {item_id}")
    missing = sorted(set(catalog_by_id) - set(matrix_ids))
    extra_duplicates = sorted(item for item, count in Counter(matrix_ids).items() if count > 1)
    if missing:
        errors.append(f"matrix missing catalog ids: {missing[:20]}{'...' if len(missing) > 20 else ''}")
    if extra_duplicates:
        errors.append(f"matrix duplicate ids: {extra_duplicates}")
    _fail(errors)


def validate_catalog(path: str | None = None) -> None:
    validate_catalog_payload(load_catalog(path))


def validate_matrix(catalog_path: str | None = None, matrix_path: str | None = None) -> None:
    catalog = load_catalog(catalog_path)
    validate_catalog_payload(catalog)
    validate_matrix_payload(load_parity_matrix(matrix_path), catalog)
