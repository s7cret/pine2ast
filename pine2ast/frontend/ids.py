"""Catalog IDs and pine2ast-owned extractor section labels.

Frontend/artifact IDs come from the installed ``openpine_contracts`` package.
Section labels below are pine2ast extractor metadata, not catalog schemas.
"""

from __future__ import annotations

from openpine_contracts import (
    Finality,
    RevisionState,
    SemanticProfile,
    SupportStatus,
    WarmupMode,
    get_schema,
    list_schema_ids,
    validate_payload,
)

FRONTEND_CONTRACT = "openpine.frontend.v2"
SUPPORT_PROFILE_CONTRACT = "openpine.support_profile.v2"
AST_CATALOG_CONTRACT = "pine.ast.v1"
STACK_ID = "openpine-5.0"
CATALOG_SCHEMA_VERSION = "2.0.0"

SECTION_CONTRACTS: dict[str, str] = {
    "static_validation": "openpine.static_validation.v1",
    "requests": "openpine.requests.v1",
    "strategy": "openpine.strategy.v1",
    "types": "openpine.types.v1",
    "methods": "openpine.methods.v1",
    "collections": "openpine.collections.v1",
    "callables": "openpine.callables.v1",
    "control_flow": "openpine.control_flow.v1",
}

TOP_LEVEL_REQUIRED = (
    "schema_version",
    "contract",
    "producer",
    "source",
    "ok",
    "diagnostics",
)


def assert_catalog_ids() -> None:
    ids = set(list_schema_ids())
    for schema_id in (FRONTEND_CONTRACT, SUPPORT_PROFILE_CONTRACT, AST_CATALOG_CONTRACT):
        if schema_id not in ids:
            raise RuntimeError(f"pinned openpine-contracts catalog is missing {schema_id}")


__all__ = [
    "AST_CATALOG_CONTRACT",
    "CATALOG_SCHEMA_VERSION",
    "FRONTEND_CONTRACT",
    "SECTION_CONTRACTS",
    "STACK_ID",
    "SUPPORT_PROFILE_CONTRACT",
    "TOP_LEVEL_REQUIRED",
    "Finality",
    "RevisionState",
    "SemanticProfile",
    "SupportStatus",
    "WarmupMode",
    "assert_catalog_ids",
    "get_schema",
    "list_schema_ids",
    "validate_payload",
]
