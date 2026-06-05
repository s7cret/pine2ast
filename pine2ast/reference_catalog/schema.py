from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

CatalogStatus = Literal[
    "NOT_STARTED",
    "PARTIAL",
    "IMPLEMENTED_UNVERIFIED",
    "DONE_VERIFIED",
    "UNSUPPORTED_DIAGNOSTIC",
    "UNSUPPORTED_SILENT_RISK",
    "BLOCKED_BY_TV_EXPORT",
    "BLOCKED_BY_DOC_AMBIGUITY",
    "DEPRECATED_NOT_SUPPORTED",
]

VALID_STATUSES: set[str] = {
    "NOT_STARTED",
    "PARTIAL",
    "IMPLEMENTED_UNVERIFIED",
    "DONE_VERIFIED",
    "UNSUPPORTED_DIAGNOSTIC",
    "UNSUPPORTED_SILENT_RISK",
    "BLOCKED_BY_TV_EXPORT",
    "BLOCKED_BY_DOC_AMBIGUITY",
    "DEPRECATED_NOT_SUPPORTED",
}

VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_KINDS = {"declaration", "function", "method", "type", "variable", "visual"}
REQUIRED_ENTRY_FIELDS = {
    "id",
    "kind",
    "namespace",
    "name",
    "pine_version",
    "priority",
    "signatures",
    "stateful",
    "requires_history",
    "side_effect",
    "method_receiver",
    "function_equivalent",
    "runtime_owner",
    "parser_status",
    "semantic_status",
    "codegen_status",
    "runtime_status",
    "golden_status",
    "known_edge_cases",
}
STATUS_FIELDS = (
    "parser_status",
    "semantic_status",
    "codegen_status",
    "runtime_status",
    "golden_status",
)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: str
    kind: str
    namespace: str | None
    name: str
    pine_version: int
    priority: str
    signatures: list[dict[str, Any]]
    stateful: bool
    requires_history: bool
    side_effect: bool
    method_receiver: str | None
    function_equivalent: str | None
    runtime_owner: str | None
    parser_status: str
    semantic_status: str
    codegen_status: str
    runtime_status: str
    golden_status: str
    known_edge_cases: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogEntry":
        return cls(
            id=str(data["id"]),
            kind=str(data["kind"]),
            namespace=data["namespace"] if data["namespace"] is None else str(data["namespace"]),
            name=str(data["name"]),
            pine_version=int(data["pine_version"]),
            priority=str(data["priority"]),
            signatures=list(data["signatures"]),
            stateful=bool(data["stateful"]),
            requires_history=bool(data["requires_history"]),
            side_effect=bool(data["side_effect"]),
            method_receiver=(
                data["method_receiver"]
                if data["method_receiver"] is None
                else str(data["method_receiver"])
            ),
            function_equivalent=(
                data["function_equivalent"]
                if data["function_equivalent"] is None
                else str(data["function_equivalent"])
            ),
            runtime_owner=(
                data["runtime_owner"]
                if data["runtime_owner"] is None
                else str(data["runtime_owner"])
            ),
            parser_status=str(data["parser_status"]),
            semantic_status=str(data["semantic_status"]),
            codegen_status=str(data["codegen_status"]),
            runtime_status=str(data["runtime_status"]),
            golden_status=str(data["golden_status"]),
            known_edge_cases=[str(item) for item in data["known_edge_cases"]],
        )
