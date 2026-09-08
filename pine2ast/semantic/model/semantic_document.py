from __future__ import annotations

from dataclasses import dataclass, field

from pine2ast.diagnostics import Diagnostic
from pine2ast.semantic.scopes import Scope
from typing import Any

from pine2ast.semantic.symbols import Symbol
from pine2ast.versioning import PineVersionContext


@dataclass(slots=True)
class SemanticModel:
    version_context: PineVersionContext | None = None
    symbols: dict[str, Symbol] = field(default_factory=dict)
    scopes: list[Scope] = field(default_factory=list)
    node_types: dict[int, str] = field(default_factory=dict)
    node_qualifiers: dict[int, str] = field(default_factory=dict)
    # Declaration bounds inferred from typed v5/v6 function bodies. AST source
    # qualifiers remain untouched; validation and consumer facts share this map.
    parameter_qualifiers: dict[int, str] = field(default_factory=dict)
    non_na_scopes: dict[int, set[str]] = field(default_factory=dict)
    # Scope-local flow facts for `not na(x)`, `not na(obj.field)`, and `if na(x) ... else`.
    # Values are stable source-level paths, not object references, so reports remain JSON-safe.
    non_na_paths: dict[int, set[str]] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    pass_results: tuple[Any, ...] = ()
    callable_inference: Any | None = None
    semantic_facts: Any | None = None
    # Rebuilt producer-only call specialization; never serialized as trusted input.
    callable_context: Any | None = None
    # Producer-owned source declaration inventory; not serialized authority.
    method_candidates: Any | None = None
