"""Machine-readable OpenPine frontend contract inventory.

This is intentionally a compact structural schema, not a full JSON Schema for
all nested payload rows.  Downstream packages can use it as a cheap compatibility
preflight before accepting an ``openpine.frontend.v1`` payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

FRONTEND_CONTRACT = "openpine.frontend.v1"
FRONTEND_SCHEMA_CONTRACT = "openpine.frontend.schema.v1"
SCHEMA_VERSION = 1

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


@dataclass(frozen=True, slots=True)
class ContractSchemaIssue:
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message}


def openpine_contract_schema() -> dict[str, Any]:
    """Return the public OpenPine frontend contract inventory."""

    return {
        "schema_version": SCHEMA_VERSION,
        "contract": FRONTEND_SCHEMA_CONTRACT,
        "frontend_contract": FRONTEND_CONTRACT,
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
    """Validate the stable outer shape of an ``openpine.frontend.v1`` payload."""

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
    if payload.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            ContractSchemaIssue(
                "schema_version",
                f"expected {SCHEMA_VERSION}, got {payload.get('schema_version')!r}",
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
        "schema_version": SCHEMA_VERSION,
        "contract": FRONTEND_SCHEMA_CONTRACT,
        "ok": not issues,
        "issue_count": len(issues),
        "issues": [issue.to_dict() for issue in issues],
    }


__all__ = [
    "FRONTEND_CONTRACT",
    "FRONTEND_SCHEMA_CONTRACT",
    "SCHEMA_VERSION",
    "SECTION_CONTRACTS",
    "TOP_LEVEL_REQUIRED",
    "ContractSchemaIssue",
    "openpine_contract_schema",
    "validate_openpine_contract_payload",
    "validate_openpine_contract_payload_dict",
]
