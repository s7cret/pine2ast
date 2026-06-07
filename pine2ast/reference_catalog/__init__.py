from __future__ import annotations

from pine2ast.reference_catalog.export_markdown import catalog_markdown, export_catalog_markdown
from pine2ast.reference_catalog.loader import load_catalog, load_entries, load_parity_matrix
from pine2ast.reference_catalog.official_reference import (
    OfficialReferenceError,
    fetch_official_reference_index,
    load_official_reference_index,
    official_reference_diff_payload,
    official_reference_gate_payload,
)
from pine2ast.reference_catalog.schema import CatalogEntry
from pine2ast.reference_catalog.validate import (
    ReferenceCatalogError,
    validate_catalog,
    validate_catalog_payload,
    validate_matrix,
    validate_matrix_payload,
)

__all__ = [
    "CatalogEntry",
    "OfficialReferenceError",
    "ReferenceCatalogError",
    "catalog_markdown",
    "export_catalog_markdown",
    "fetch_official_reference_index",
    "load_catalog",
    "load_entries",
    "load_official_reference_index",
    "load_parity_matrix",
    "official_reference_diff_payload",
    "official_reference_gate_payload",
    "validate_catalog",
    "validate_catalog_payload",
    "validate_matrix",
    "validate_matrix_payload",
]
