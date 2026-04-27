from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ScopeKind(str, Enum):
    GLOBAL = "GLOBAL"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    LOCAL_BLOCK = "LOCAL_BLOCK"
    LOOP = "LOOP"
    TYPE_DECL = "TYPE_DECL"
    ENUM_DECL = "ENUM_DECL"


@dataclass(slots=True)
class Scope:
    id: int
    kind: ScopeKind
    parent_id: int | None
    symbols: dict[str, int] = field(default_factory=dict)
    non_na_symbols: set[str] = field(default_factory=set)
