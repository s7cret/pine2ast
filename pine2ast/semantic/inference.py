"""Shared Pine type/qualifier inference facade.

This module is the Release 4.0.2 bridge between the legacy semantic analyzer and
newer contract/signature layers. It intentionally keeps the public facts string
compatible with the existing semantic model while centralizing three pieces of
logic that were previously duplicated:

* version-aware builtin/generic call lookup;
* expression type + qualifier inference;
* collection-specialized argument/return facts for downstream OpenPine metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pine2ast.ast.base import ASTNode, Expression
from pine2ast.ast.walk import iter_nodes
from pine2ast.ast.nodes import BinaryExpr, CallExpr, GenericInstantiationExpr, MemberAccessExpr
from pine2ast.semantic.builtin_registry import load_builtin_registry
from pine2ast.semantic.model import SemanticModel
from pine2ast.semantic.qualifier_infer import infer_qualifier as legacy_infer_qualifier
from pine2ast.semantic.symbols import SymbolKind
from pine2ast.semantic.type_infer import callee_name, infer_type as legacy_infer_type
from pine2ast.semantic.type_model import (
    COLLECTION_TYPE_BASES,
    PineType,
    is_reference_type_name,
    parse_type_string,
    strip_series_type,
)
from pine2ast.semantic.values import SemanticValue, expression_can_be_na

_GENERIC_REGISTRY_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "array.new": ("array.new<type>",),
    "matrix.new": ("matrix.new<type>",),
    "map.new": ("map.new<type,type>",),
}


@dataclass(frozen=True, slots=True)
class InferredNodeFact:
    """JSON-safe expression fact produced by :class:`PineInferenceEngine`."""

    node_id: int
    kind: str
    type_name: str
    qualifier: str
    can_be_na: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "type": self.type_name,
            "qualifier": self.qualifier,
            "can_be_na": self.can_be_na,
        }


def call_lookup_name(callee: Expression, registry: Mapping[str, Any] | None = None) -> str:
    """Return the registry lookup name for a call callee.

    The parser preserves user-written generic type arguments, e.g.
    ``map.new<Key, float>``. The bundled registry stores many generic builtins as
    placeholder signatures such as ``map.new<type,type>``. This helper maps the
    concrete syntax back to the best registry key without altering the source AST.
    """

    raw = callee_name(callee)
    functions = (registry or {}).get("functions", {}) if registry is not None else {}
    if raw in functions:
        return raw
    if isinstance(callee, GenericInstantiationExpr):
        base = callee_name(callee.base)
        if base in functions:
            return base
        for placeholder in _GENERIC_REGISTRY_PLACEHOLDERS.get(base, ()):  # exact generic shape
            if placeholder in functions:
                return placeholder
        # Specific registry snapshots sometimes contain concrete primitive
        # signatures only (array.new<float>, matrix.new<int>, ...). If the raw
        # concrete name is absent, prefer the normalized base for diagnostics and
        # for downstream collection specialization.
        return base
    return raw


def registry_entry_for_call(
    callee: Expression,
    registry: Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    lookup_name = call_lookup_name(callee, registry)
    entry = registry.get("functions", {}).get(lookup_name)
    return lookup_name, entry


def normalize_return_type(type_name: str | None) -> str:
    """Remove qualifier wrappers from registry return type strings."""

    typ = parse_type_string(type_name)
    unwrapped = strip_series_type(typ)
    return unwrapped.to_string()


def _symbol_kind_value(symbol: Any | None) -> str | None:
    kind = getattr(symbol, "kind", None)
    return getattr(kind, "value", kind)


class PineInferenceEngine:
    """Version-aware Pine expression inference facade.

    The engine deliberately delegates the broad expression grammar to the legacy
    inference helpers, but it owns version-aware registry lookup and post-facts
    that are required by signatures/contracts: reference types are ``series``,
    enum members retain their enum type, and generic builtin calls use normalized
    registry keys.
    """

    def __init__(
        self,
        *,
        symbols: Mapping[str, Any] | None = None,
        pine_version: int = 6,
        registry: Mapping[str, Any] | None = None,
    ) -> None:
        self.symbols = symbols
        self.pine_version = 5 if pine_version == 5 else 6
        self.registry = registry or load_builtin_registry(pine_version=self.pine_version)

    @classmethod
    def from_analyzer(cls, analyzer: Any) -> "PineInferenceEngine":
        return cls(
            symbols=getattr(getattr(analyzer, "model", None), "symbols", None),
            pine_version=getattr(analyzer, "pine_version", 6),
            registry=getattr(analyzer, "registry", None),
        )

    def bind_model(self, model: SemanticModel) -> None:
        self.symbols = model.symbols

    def infer_type(self, expr: Expression | None) -> str:
        if expr is None:
            return "unknown"
        if isinstance(expr, MemberAccessExpr):
            symbol_type = self._symbol_type(callee_name(expr))
            if symbol_type:
                return symbol_type
        if isinstance(expr, BinaryExpr):
            specialized = self._binary_return_type(expr)
            if specialized:
                return specialized
        legacy = legacy_infer_type(expr, self.symbols)
        if isinstance(expr, CallExpr):
            specialized = self._call_return_type(expr, legacy)
            if specialized:
                return specialized
        return legacy

    def infer_qualifier(self, expr: Expression | None) -> str:
        if expr is None:
            return "series"
        if isinstance(expr, MemberAccessExpr):
            qualifier = self._symbol_qualifier(callee_name(expr))
            if qualifier:
                return qualifier
        qualifier = legacy_infer_qualifier(expr, self.symbols)
        typ = self.infer_type(expr)
        if _type_is_reference_like(typ):
            return "series"
        if isinstance(expr, CallExpr):
            ret = self._registry_return(expr)
            if ret and _type_is_reference_like(ret):
                return "series"
            if ret and _return_is_series_qualified(ret):
                return "series"
        return qualifier

    def infer_value(self, expr: Expression | None) -> SemanticValue:
        return SemanticValue(
            type_name=self.infer_type(expr),
            qualifier=self.infer_qualifier(expr),
            can_be_na=expression_can_be_na(expr),
        )

    def collect_program_facts(
        self, program: ASTNode, model: SemanticModel
    ) -> tuple[InferredNodeFact, ...]:
        """Populate ``model.node_types``/``node_qualifiers`` for every expression.

        The legacy analyzer already fills these maps during its validation walk.
        This pass is intentionally idempotent and may be run afterwards to make
        type/qualifier inference a real pipeline phase without changing AST JSON.
        """

        self.bind_model(model)
        facts: list[InferredNodeFact] = []
        for node in iter_nodes(program):
            if isinstance(node, Expression):
                value = self.infer_value(node)
                model.node_types[id(node)] = value.type_name
                model.node_qualifiers[id(node)] = value.qualifier
                facts.append(
                    InferredNodeFact(
                        node_id=id(node),
                        kind=getattr(node, "kind", type(node).__name__),
                        type_name=value.type_name,
                        qualifier=value.qualifier,
                        can_be_na=value.can_be_na,
                    )
                )
        return tuple(facts)

    def _binary_return_type(self, expr: BinaryExpr) -> str | None:
        # Pine v6 changed the compile-time result of const-int division: a
        # division between two const int values can produce a fractional value,
        # so downstream type checks should see float rather than int. Keep v5
        # compatibility untouched.
        if expr.op != "/" or self.pine_version < 6:
            return None
        left_type = self.infer_type(expr.left)
        right_type = self.infer_type(expr.right)
        if left_type == right_type == "int" and {
            self.infer_qualifier(expr.left),
            self.infer_qualifier(expr.right),
        } <= {"const"}:
            return "float"
        return None

    def _call_return_type(self, expr: CallExpr, legacy: str) -> str | None:
        # Collection method/function forms are receiver-specialized by the Release 4.0
        # signature layer. Prefer those facts because broad registry entries
        # often say only "unknown" for generic methods such as array.slice(),
        # matrix.row(), or map.keys().
        specialized = self._collection_call_return(expr)
        if specialized and specialized != "unknown":
            return specialized
        # Preserve richer shape-sensitive legacy results next: generic
        # constructors, UDT constructors, request.security expression shape,
        # tuples, etc.
        if legacy not in {"unknown", "any"}:
            return legacy
        ret = self._registry_return(expr)
        return normalize_return_type(ret) if ret else specialized

    def _collection_call_return(self, expr: CallExpr) -> str | None:
        from pine2ast.semantic.collection_signatures import resolve_collection_call

        resolution = resolve_collection_call(expr, engine=self)
        return resolution.return_type if resolution is not None else None

    def _registry_return(self, expr: CallExpr) -> str | None:
        _, entry = registry_entry_for_call(expr.callee, self.registry)
        if not entry:
            return None
        return entry.get("returns")

    def _symbol_type(self, name: str) -> str | None:
        if not self.symbols:
            return None
        symbol = self.symbols.get(name)
        if symbol is None:
            return None
        typ = getattr(symbol, "type", None)
        if typ and typ not in {"function", "method", "enum", "type"}:
            return typ
        if _symbol_kind_value(symbol) in {SymbolKind.ENUM_MEMBER.value, "ENUM_MEMBER"} and typ:
            return typ
        return None

    def _symbol_qualifier(self, name: str) -> str | None:
        if not self.symbols:
            return None
        symbol = self.symbols.get(name)
        if symbol is None:
            return None
        qualifier = getattr(symbol, "qualifier", None)
        return qualifier if qualifier in {"const", "input", "simple", "series"} else None


def _return_is_series_qualified(type_name: str | None) -> bool:
    if not type_name:
        return False
    typ = parse_type_string(type_name)
    return typ.base == "series" and bool(typ.args)


def _type_is_reference_like(type_name: str | None) -> bool:
    if not type_name:
        return False
    typ = strip_series_type(PineType.parse(type_name))
    if typ.base in COLLECTION_TYPE_BASES:
        return True
    return is_reference_type_name(typ.to_string())


__all__ = [
    "InferredNodeFact",
    "PineInferenceEngine",
    "call_lookup_name",
    "normalize_return_type",
    "registry_entry_for_call",
]
