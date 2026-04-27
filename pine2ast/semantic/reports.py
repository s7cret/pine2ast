from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pine2ast.semantic.analyzer import SemanticModel


@dataclass(slots=True)
class SemanticReport:
    schema_version: int
    symbol_count: int
    scope_count: int
    by_kind: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    by_qualifier: dict[str, int] = field(default_factory=dict)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    scopes: list[dict[str, Any]] = field(default_factory=list)
    narrowing_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "symbol_count": self.symbol_count,
            "scope_count": self.scope_count,
            "by_kind": dict(sorted(self.by_kind.items())),
            "by_type": dict(sorted(self.by_type.items())),
            "by_qualifier": dict(sorted(self.by_qualifier.items())),
            "symbols": self.symbols,
            "scopes": self.scopes,
            "narrowing_count": self.narrowing_count,
        }


def semantic_report(model: SemanticModel | None, *, include_builtins: bool = False) -> SemanticReport:
    if model is None:
        return SemanticReport(schema_version=2, symbol_count=0, scope_count=0)
    by_kind: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_qualifier: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for sym in sorted(model.symbols.values(), key=lambda s: (s.scope_id, s.name, s.id)):
        kind = getattr(sym.kind, "value", str(sym.kind))
        if not include_builtins and kind == "BUILTIN":
            continue
        typ = sym.type or "unknown"
        qualifier = sym.qualifier or "none"
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_type[typ] = by_type.get(typ, 0) + 1
        by_qualifier[qualifier] = by_qualifier.get(qualifier, 0) + 1
        rows.append(
            {
                "id": sym.id,
                "name": sym.name,
                "kind": kind,
                "type": sym.type,
                "qualifier": sym.qualifier,
                "scope_id": sym.scope_id,
                "span": sym.declared_at.to_dict(),
            }
        )
    scopes = []
    narrowing_count = 0
    for scope in model.scopes:
        non_na_symbols = sorted(scope.non_na_symbols)
        non_na_paths = sorted(model.non_na_paths.get(scope.id, set(non_na_symbols)))
        narrowing_count += len(non_na_paths)
        scopes.append(
            {
                "id": scope.id,
                "kind": getattr(scope.kind, "value", str(scope.kind)),
                "parent_id": scope.parent_id,
                "symbol_count": len(scope.symbols),
                "non_na_symbols": non_na_symbols,
                "non_na_paths": non_na_paths,
            }
        )
    return SemanticReport(
        schema_version=2,
        symbol_count=len(rows),
        scope_count=len(model.scopes),
        by_kind=by_kind,
        by_type=by_type,
        by_qualifier=by_qualifier,
        symbols=rows,
        scopes=scopes,
        narrowing_count=narrowing_count,
    )
