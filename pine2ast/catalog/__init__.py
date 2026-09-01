from pine2ast.catalog.coverage import (
    INTERNAL_EXPECTED_NAMESPACE_MEMBERS,
    KNOWN_DEFERRED_NAMESPACE_MEMBERS,
    KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS,
    OFFICIAL_UNMAPPED_NAMESPACE_MEMBERS,
    CatalogCoverageReport,
    catalog_coverage_report,
)
from pine2ast.catalog.model import (
    CatalogError,
    CatalogIdentity,
    CatalogIntegrityError,
    CatalogSchemaError,
    CatalogStatus,
    DeltaOperation,
    SymbolKind,
)
from pine2ast.catalog.repository import CatalogRepository, clear_catalog_cache
from pine2ast.catalog.schema import validate_catalog_pack


def load_catalog_view(pine_version: int) -> dict:
    """Return an isolated mutable catalog projection for public callers."""
    return CatalogRepository.default().view(pine_version)


def load_catalog_readonly_view(pine_version: int):
    """Return the cached immutable catalog projection used by frontend internals."""
    return CatalogRepository.default().readonly_view(pine_version)


__all__ = [
    "INTERNAL_EXPECTED_NAMESPACE_MEMBERS",
    "KNOWN_DEFERRED_NAMESPACE_MEMBERS",
    "KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS",
    "OFFICIAL_UNMAPPED_NAMESPACE_MEMBERS",
    "CatalogCoverageReport",
    "CatalogError",
    "CatalogIdentity",
    "CatalogIntegrityError",
    "CatalogRepository",
    "CatalogSchemaError",
    "CatalogStatus",
    "DeltaOperation",
    "SymbolKind",
    "catalog_coverage_report",
    "clear_catalog_cache",
    "load_catalog_view",
    "load_catalog_readonly_view",
    "validate_catalog_pack",
]
