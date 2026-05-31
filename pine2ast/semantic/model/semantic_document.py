from __future__ import annotations

from dataclasses import dataclass, field

from pine2ast.diagnostics import Diagnostic
from pine2ast.semantic.scopes import Scope
from pine2ast.semantic.symbols import Symbol


@dataclass(slots=True)
class SemanticModel:
    symbols: dict[str, Symbol] = field(default_factory=dict)
    scopes: list[Scope] = field(default_factory=list)
    node_types: dict[int, str] = field(default_factory=dict)
    node_qualifiers: dict[int, str] = field(default_factory=dict)
    non_na_scopes: dict[int, set[str]] = field(default_factory=dict)
    # Scope-local flow facts for `not na(x)`, `not na(obj.field)`, and `if na(x) ... else`.
    # Values are stable source-level paths, not object references, so reports remain JSON-safe.
    non_na_paths: dict[int, set[str]] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
