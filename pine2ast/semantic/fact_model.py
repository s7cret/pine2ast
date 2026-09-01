from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

FactClassification = Literal[
    "PROGRAM",
    "DECLARATION",
    "STATEMENT",
    "EXPRESSION",
    "STRUCTURAL",
]


@dataclass(frozen=True, slots=True)
class TypeFact:
    base: str
    qualifier: str | None
    nullable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "qualifier": self.qualifier,
            "nullable": self.nullable,
        }


@dataclass(frozen=True, slots=True)
class CoercionFact:
    source_type: str
    target_type: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "source_type": self.source_type,
            "target_type": self.target_type,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ArgumentBindingFact:
    argument_node_id: str
    parameter_name: str | None
    parameter_index: int | None
    binding: str
    actual_type: str | None
    actual_qualifier: str | None
    expected_type: str | None = None
    max_qualifier: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "argument_node_id": self.argument_node_id,
            "parameter_name": self.parameter_name,
            "parameter_index": self.parameter_index,
            "binding": self.binding,
            "actual_type": self.actual_type,
            "actual_qualifier": self.actual_qualifier,
            "expected_type": self.expected_type,
            "max_qualifier": self.max_qualifier,
        }


@dataclass(frozen=True, slots=True)
class DefaultBindingFact:
    parameter_name: str
    parameter_index: int
    expected_type: str | None
    max_qualifier: str | None
    default_known: bool
    default_value: Any | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "parameter_index": self.parameter_index,
            "binding": "defaulted",
            "expected_type": self.expected_type,
            "max_qualifier": self.max_qualifier,
            "default_known": self.default_known,
            "default_value": self.default_value,
        }


@dataclass(frozen=True, slots=True)
class CallBindingFact:
    node_id: str
    callee: str
    symbol_id: str
    resolution_status: str
    overload_id: str | None
    call_form: str
    receiver_type: str | None
    return_type: str
    stateful: bool
    arguments: tuple[ArgumentBindingFact, ...] = ()
    defaults_applied: tuple[DefaultBindingFact, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "callee": self.callee,
            "symbol_id": self.symbol_id,
            "resolution_status": self.resolution_status,
            "overload_id": self.overload_id,
            "call_form": self.call_form,
            "receiver_type": self.receiver_type,
            "return_type": self.return_type,
            "stateful": self.stateful,
            "arguments": [item.to_dict() for item in self.arguments],
            "defaults_applied": [item.to_dict() for item in self.defaults_applied],
        }


@dataclass(frozen=True, slots=True)
class SemanticFact:
    node_id: str
    kind: str
    classification: FactClassification
    span: dict[str, int]
    scope_id: str
    resolved_type: TypeFact | None
    symbol_id: str | None = None
    overload_id: str | None = None
    declaration_target: str | None = None
    call_form: str | None = None
    receiver_type: str | None = None
    coercions: tuple[CoercionFact, ...] = ()
    const_value: Any | None = None
    semantic_rule_ids: tuple[str, ...] = ()
    stateful_call: bool = False
    diagnostic_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "node_kind": self.kind,
            "classification": self.classification,
            "span": dict(self.span),
            "scope_id": self.scope_id,
            "resolved_type": self.resolved_type.to_dict() if self.resolved_type else None,
            "symbol_id": self.symbol_id,
            "overload_id": self.overload_id,
            "declaration_target": self.declaration_target,
            "call_form": self.call_form,
            "receiver_type": self.receiver_type,
            "coercions": [item.to_dict() for item in self.coercions],
            "const_value": self.const_value,
            "semantic_rule_ids": list(self.semantic_rule_ids),
            "stateful_call": self.stateful_call,
            "diagnostic_refs": list(self.diagnostic_refs),
        }


@dataclass(frozen=True, slots=True)
class SemanticCoverage:
    total_nodes: int
    fact_nodes: int
    expression_nodes: int
    typed_expression_nodes: int
    call_nodes: int
    resolved_call_nodes: int
    unresolved_calls: tuple[str, ...] = ()
    missing_fact_nodes: tuple[str, ...] = ()

    @property
    def facts_ratio(self) -> float:
        return 1.0 if self.total_nodes == 0 else self.fact_nodes / self.total_nodes

    @property
    def expression_type_ratio(self) -> float:
        return (
            1.0
            if self.expression_nodes == 0
            else self.typed_expression_nodes / self.expression_nodes
        )

    @property
    def call_resolution_ratio(self) -> float:
        return 1.0 if self.call_nodes == 0 else self.resolved_call_nodes / self.call_nodes

    @property
    def ok(self) -> bool:
        return (
            self.facts_ratio == 1.0
            and self.expression_type_ratio == 1.0
            and self.call_resolution_ratio == 1.0
            and not self.missing_fact_nodes
            and not self.unresolved_calls
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "total_nodes": self.total_nodes,
            "fact_nodes": self.fact_nodes,
            "facts_ratio": self.facts_ratio,
            "expression_nodes": self.expression_nodes,
            "typed_expression_nodes": self.typed_expression_nodes,
            "expression_type_ratio": self.expression_type_ratio,
            "call_nodes": self.call_nodes,
            "resolved_call_nodes": self.resolved_call_nodes,
            "call_resolution_ratio": self.call_resolution_ratio,
            "unresolved_calls": list(self.unresolved_calls),
            "missing_fact_nodes": list(self.missing_fact_nodes),
        }


@dataclass(frozen=True, slots=True)
class SemanticFactsBundle:
    facts: tuple[SemanticFact, ...]
    calls: tuple[CallBindingFact, ...]
    diagnostics: tuple[dict[str, Any], ...]
    coverage: SemanticCoverage
    artifact: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ArgumentBindingFact",
    "CallBindingFact",
    "CoercionFact",
    "SemanticCoverage",
    "SemanticFact",
    "SemanticFactsBundle",
    "TypeFact",
]
