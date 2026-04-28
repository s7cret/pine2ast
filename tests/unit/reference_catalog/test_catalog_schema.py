from __future__ import annotations

import pytest

from pine2ast.reference_catalog import ReferenceCatalogError, load_catalog, validate_catalog_payload


def test_catalog_schema_validates_bundled_catalog() -> None:
    validate_catalog_payload(load_catalog())


def test_catalog_rejects_duplicate_ids() -> None:
    payload = load_catalog()
    first = dict(payload["entries"][0])
    payload["entries"] = [first, dict(first)]

    with pytest.raises(ReferenceCatalogError, match="duplicate catalog ids"):
        validate_catalog_payload(payload)


def test_catalog_entries_have_required_status_fields() -> None:
    payload = load_catalog()
    entry = dict(payload["entries"][0])
    del entry["golden_status"]
    payload["entries"] = [entry]

    with pytest.raises(ReferenceCatalogError, match="missing fields"):
        validate_catalog_payload(payload)
