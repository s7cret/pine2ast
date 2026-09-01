"""Structural preflight for pine2ast-owned frontend extractor metadata.

Catalog validation for ``openpine.frontend.v2`` lives in ``artifact.py`` and
uses ``openpine_contracts.validate_payload``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pine2ast.frontend.ids import (
    FRONTEND_CONTRACT,
    SECTION_CONTRACTS,
    TOP_LEVEL_REQUIRED,
)


@dataclass(frozen=True, slots=True)
class ContractSchemaIssue:
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


def openpine_contract_schema() -> dict[str, Any]:
    """Return the owned envelope schema plus extractor section inventory.

    The frontend envelope is intentionally additive: downstream consumers may
    ignore sections they do not understand, while the producer-owned identity,
    source, diagnostics, and version context remain mandatory.  Keeping this
    schema beside the validator avoids an undeclared dependency on a global
    schema registry and makes the CLI output deterministic from the installed
    wheel alone.
    """

    catalog: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": FRONTEND_CONTRACT,
        "title": "Pine2AST frontend contract envelope",
        "type": "object",
        "required": list(TOP_LEVEL_REQUIRED),
        "properties": {
            "schema_version": {"const": 1},
            "contract": {"const": FRONTEND_CONTRACT},
            "producer": {
                "type": "object",
                "required": ["name", "version"],
                "properties": {
                    "name": {"const": "pine2ast"},
                    "version": {"type": "string", "minLength": 1},
                },
                "additionalProperties": True,
            },
            "source": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string", "minLength": 1}},
                "additionalProperties": True,
            },
            "ok": {"type": "boolean"},
            "diagnostics": {"type": "array"},
            "version_context": {"type": "object"},
        },
        "additionalProperties": True,
    }
    return {
        "schema_id": FRONTEND_CONTRACT,
        "frontend_contract": FRONTEND_CONTRACT,
        "catalog_schema": catalog,
        "top_level_required": list(TOP_LEVEL_REQUIRED),
        "section_contracts": dict(SECTION_CONTRACTS),
        "compatibility": {
            "additive_sections_allowed": True,
            "unknown_top_level_keys_allowed": True,
            "section_absence_allowed_when_parse_failed": True,
        },
    }


def validate_openpine_contract_payload(
    payload: Mapping[str, Any],
) -> tuple[ContractSchemaIssue, ...]:
    """Validate the extractor-metadata envelope (not the catalog v2 artifact)."""

    issues: list[ContractSchemaIssue] = []
    for key in TOP_LEVEL_REQUIRED:
        if key not in payload:
            issues.append(ContractSchemaIssue(key, "required top-level key is missing"))
    if payload.get("contract") != FRONTEND_CONTRACT:
        issues.append(
            ContractSchemaIssue(
                "contract",
                f"expected {FRONTEND_CONTRACT}, got {payload.get('contract')!r}",
            )
        )
    if payload.get("schema_version") != 1:
        issues.append(
            ContractSchemaIssue(
                "schema_version",
                f"expected 1, got {payload.get('schema_version')!r}",
            )
        )
    producer = payload.get("producer")
    if not isinstance(producer, Mapping):
        issues.append(ContractSchemaIssue("producer", "producer must be an object"))
    elif producer.get("name") != "pine2ast" or not producer.get("version"):
        issues.append(
            ContractSchemaIssue(
                "producer",
                "producer must include name='pine2ast' and a non-empty version",
            )
        )
    source = payload.get("source")
    if not isinstance(source, Mapping):
        issues.append(ContractSchemaIssue("source", "source must be an object"))
    elif not source.get("name"):
        issues.append(ContractSchemaIssue("source.name", "source.name must be present"))
    if not isinstance(payload.get("diagnostics"), list):
        issues.append(ContractSchemaIssue("diagnostics", "diagnostics must be a list"))

    for section, expected_contract in SECTION_CONTRACTS.items():
        value = payload.get(section)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            issues.append(ContractSchemaIssue(section, "section must be an object when present"))
            continue
        actual_contract = value.get("contract")
        if actual_contract != expected_contract:
            issues.append(
                ContractSchemaIssue(
                    f"{section}.contract",
                    f"expected {expected_contract}, got {actual_contract!r}",
                )
            )
    return tuple(issues)


def validate_openpine_contract_payload_dict(payload: Mapping[str, Any]) -> dict[str, Any]:
    issues = validate_openpine_contract_payload(payload)
    return {
        "schema_id": FRONTEND_CONTRACT,
        "ok": not issues,
        "issue_count": len(issues),
        "issues": [issue.to_dict() for issue in issues],
    }


__all__ = [
    "ContractSchemaIssue",
    "openpine_contract_schema",
    "validate_openpine_contract_payload",
    "validate_openpine_contract_payload_dict",
]
