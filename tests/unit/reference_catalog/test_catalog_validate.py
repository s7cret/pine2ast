from __future__ import annotations

import pytest

from pine2ast.reference_catalog import (
    ReferenceCatalogError,
    catalog_markdown,
    load_parity_matrix,
    validate_catalog,
    validate_matrix,
)
from pine2ast.reference_catalog.validate import (
    official_matrix_coverage_payload,
    validate_matrix_payload,
)


def test_bundled_catalog_and_matrix_validate() -> None:
    validate_catalog()
    validate_matrix()


def test_catalog_markdown_exports_status_table() -> None:
    text = catalog_markdown()

    assert "# Pine v6 Reference Catalog" in text
    assert "`ta.ema`" in text
    assert "`strategy.entry`" in text
    assert (
        "| ID | Official | Kind | Owner | Parser | Semantic | Codegen | Runtime | Golden |" in text
    )
    assert "full TradingView compatibility" in text


def test_matrix_requires_explicit_owner_and_status_fields() -> None:
    official_index = {
        "schema_version": "pain.official_pine_reference_index.v1",
        "pine_version": 6,
        "categories": {"functions": ["ta.ema"]},
    }
    matrix = {
        "schema_version": "pain.parity_matrix.v1",
        "pine_version": 6,
        "items": [
            {
                "id": "ta.ema",
                "official_category": "functions",
                "priority": "P0",
                "parser_status": "NOT_STARTED",
                "semantic_status": "NOT_STARTED",
                "codegen_status": "NOT_STARTED",
                "runtime_status": "NOT_STARTED",
                "golden_status": "NOT_A_STATUS",
            }
        ],
    }

    with pytest.raises(ReferenceCatalogError, match="missing fields"):
        validate_matrix_payload(matrix, {"entries": []}, official_index)


def test_matrix_identity_includes_official_category() -> None:
    official_index = {
        "schema_version": "pain.official_pine_reference_index.v1",
        "pine_version": 6,
        "categories": {
            "functions": ["array.avg"],
            "methods": ["array.avg"],
        },
    }
    catalog_entry = {
        "id": "array.avg",
        "kind": "function",
        "priority": "P0",
        "runtime_owner": "pinelib.collections",
        "parser_status": "IMPLEMENTED_UNVERIFIED",
        "semantic_status": "IMPLEMENTED_UNVERIFIED",
        "codegen_status": "IMPLEMENTED_UNVERIFIED",
        "runtime_status": "IMPLEMENTED_UNVERIFIED",
        "golden_status": "NOT_STARTED",
    }
    matrix = {
        "schema_version": "pain.parity_matrix.v1",
        "pine_version": 6,
        "items": [
            {
                "id": "array.avg",
                "official_category": "functions",
                "priority": "P0",
                "runtime_owner": "pinelib.collections",
                "parser_status": "IMPLEMENTED_UNVERIFIED",
                "semantic_status": "IMPLEMENTED_UNVERIFIED",
                "codegen_status": "IMPLEMENTED_UNVERIFIED",
                "runtime_status": "IMPLEMENTED_UNVERIFIED",
                "golden_status": "NOT_STARTED",
            },
            {
                "id": "array.avg",
                "official_category": "methods",
                "priority": "P1",
                "runtime_owner": None,
                "parser_status": "NOT_STARTED",
                "semantic_status": "NOT_STARTED",
                "codegen_status": "NOT_STARTED",
                "runtime_status": "NOT_STARTED",
                "golden_status": "NOT_STARTED",
            },
        ],
    }

    validate_matrix_payload(matrix, {"entries": [catalog_entry]}, official_index)


def test_official_matrix_coverage_reports_missing_ids_by_category() -> None:
    official_index = {
        "schema_version": "pain.official_pine_reference_index.v1",
        "pine_version": 6,
        "categories": {
            "functions": ["array.avg", "ta.ema"],
            "methods": ["array.avg"],
            "variables": ["close"],
        },
    }
    matrix = {
        "schema_version": "pain.parity_matrix.v1",
        "pine_version": 6,
        "items": [
            {
                "id": "array.avg",
                "official_category": "functions",
            }
        ],
    }

    payload = official_matrix_coverage_payload(matrix, official_index)

    assert payload["summary"]["official_reference_count"] == 4
    assert payload["summary"]["matrix_tracked_official_count"] == 1
    assert payload["missing_by_category"]["functions"] == ["ta.ema"]
    assert payload["missing_by_category"]["methods"] == ["array.avg"]
    assert payload["missing_by_category"]["variables"] == ["close"]


def test_bundled_matrix_reports_untracked_official_snapshot_ids() -> None:
    payload = official_matrix_coverage_payload(load_parity_matrix())

    assert payload["summary"]["official_reference_count"] > len(load_parity_matrix()["items"])
    assert payload["summary"]["missing_official_count"] > 0
    assert "alert" in payload["missing_by_category"]["functions"]
