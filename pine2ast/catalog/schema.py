from __future__ import annotations

import re
from typing import Any

from pine2ast.catalog.hashing import verify_hash
from pine2ast.catalog.model import CatalogSchemaError, CatalogStatus

_SECTION_NAMES = (
    "annotations",
    "keywords",
    "operators",
    "declarations",
    "functions",
    "methods",
    "variables",
    "constants",
    "types",
    "namespaces",
    "enum_values",
)
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def validate_catalog_pack(pack: dict[str, Any]) -> None:
    if pack.get("schema_id") != "pine.catalog.pack.v1":
        raise CatalogSchemaError("catalog pack schema_id must be pine.catalog.pack.v1")
    if pack.get("schema_version") != "1.0.0":
        raise CatalogSchemaError("unsupported catalog pack schema_version")
    version = pack.get("pine_version")
    if type(version) is not int or version not in {1, 2, 3, 4, 5, 6}:
        raise CatalogSchemaError("catalog pack pine_version must be an integer 1..6")
    try:
        CatalogStatus(str(pack.get("status")))
    except ValueError as exc:
        raise CatalogSchemaError("invalid catalog pack status") from exc
    for key in ("spec_snapshot_ref", "source_manifest_hash", "catalog_hash", "content_hash"):
        value = pack.get(key)
        if key == "spec_snapshot_ref":
            if not isinstance(value, str) or not value:
                raise CatalogSchemaError("spec_snapshot_ref is required")
        elif not isinstance(value, str) or not _HASH_RE.fullmatch(value):
            raise CatalogSchemaError(f"{key} must be sha256:<64 lowercase hex>")
    rules = pack.get("rules")
    if not isinstance(rules, dict):
        raise CatalogSchemaError("rules must be an object")
    sections = pack.get("sections")
    if not isinstance(sections, dict) or set(sections) != set(_SECTION_NAMES):
        raise CatalogSchemaError("catalog pack must contain the complete section set")
    for section_name, section in sections.items():
        if not isinstance(section, dict):
            raise CatalogSchemaError(f"section {section_name} must be an object")
        for name, definition in section.items():
            if not isinstance(name, str) or not name:
                raise CatalogSchemaError(f"section {section_name} contains invalid name")
            if not isinstance(definition, dict):
                raise CatalogSchemaError(f"definition {section_name}.{name} must be an object")
            symbol_id = definition.get("symbol_id")
            if not isinstance(symbol_id, str) or not symbol_id.startswith("pine:"):
                raise CatalogSchemaError(f"definition {section_name}.{name} has invalid symbol_id")
            if definition.get("name") != name:
                raise CatalogSchemaError(f"definition {section_name}.{name} name mismatch")
    if not verify_hash(pack):
        raise CatalogSchemaError("catalog pack content_hash is invalid")
    body = {
        key: value for key, value in pack.items() if key not in {"content_hash", "catalog_hash"}
    }
    from pine2ast.catalog.hashing import sha256_id

    if pack["catalog_hash"] != sha256_id(body):
        raise CatalogSchemaError("catalog_hash does not match canonical pack body")


def section_names() -> tuple[str, ...]:
    return _SECTION_NAMES


__all__ = ["section_names", "validate_catalog_pack"]
