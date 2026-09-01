from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CatalogStatus(str, Enum):
    """Declared completeness of one immutable version pack."""

    HISTORICAL_STATIC_SNAPSHOT = "HISTORICAL_STATIC_SNAPSHOT"
    STATIC_COMPLETE = "STATIC_COMPLETE"


class SymbolKind(str, Enum):
    ANNOTATION = "annotation"
    KEYWORD = "keyword"
    OPERATOR = "operator"
    DECLARATION = "declaration"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    CONSTANT = "constant"
    TYPE = "type"
    NAMESPACE = "namespace"
    ENUM_VALUE = "enum_value"
    PARAMETER = "parameter"


class DeltaOperation(str, Enum):
    ADD = "ADD"
    PATCH = "PATCH"
    REMOVE = "REMOVE"
    RENAME = "RENAME"


@dataclass(frozen=True, slots=True)
class CatalogIdentity:
    pine_version: int
    status: CatalogStatus
    spec_snapshot_ref: str
    catalog_hash: str


class CatalogError(ValueError):
    pass


class CatalogIntegrityError(CatalogError):
    pass


class CatalogSchemaError(CatalogError):
    pass


CatalogView = dict[str, Any]

__all__ = [
    "CatalogError",
    "CatalogIdentity",
    "CatalogIntegrityError",
    "CatalogSchemaError",
    "CatalogStatus",
    "CatalogView",
    "DeltaOperation",
    "SymbolKind",
]
