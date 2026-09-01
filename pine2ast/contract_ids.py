"""Canonical public contract identifiers shared across package layers.

This module intentionally has no imports from parser, semantic, or frontend
packages so identifiers can be referenced without creating initialization
cycles.
"""

from __future__ import annotations

FRONTEND_CONTRACT = "pine.frontend.v3"
SUPPORT_PROFILE_CONTRACT = "pine.support_profile.v3"
AST_CATALOG_CONTRACT = "pine.ast.v2"
SOURCE_MANIFEST_CONTRACT = "pine.source_manifest.v1"
SEMANTIC_FACTS_CONTRACT = "pine.semantic_facts.v1"
CATALOG_SCHEMA_VERSION = "3.0.0"

SECTION_CONTRACTS: dict[str, str] = {
    "static_validation": "pine.static_validation.v2",
    "requests": "pine.requests.v2",
    "strategy": "pine.strategy_static.v2",
    "types": "pine.types.v2",
    "methods": "pine.methods.v2",
    "collections": "pine.collections.v2",
    "callables": "pine.callables.v2",
    "control_flow": "pine.control_flow.v2",
}

TOP_LEVEL_REQUIRED = (
    "schema_version",
    "contract",
    "producer",
    "source",
    "ok",
    "diagnostics",
    "version_context",
)

__all__ = [
    "AST_CATALOG_CONTRACT",
    "CATALOG_SCHEMA_VERSION",
    "FRONTEND_CONTRACT",
    "SOURCE_MANIFEST_CONTRACT",
    "SEMANTIC_FACTS_CONTRACT",
    "SECTION_CONTRACTS",
    "SUPPORT_PROFILE_CONTRACT",
    "TOP_LEVEL_REQUIRED",
]
