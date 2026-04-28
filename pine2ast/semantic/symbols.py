from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pine2ast.lexer.token import SourceSpan


class SymbolKind(str, Enum):
    VARIABLE = "VARIABLE"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    TYPE = "TYPE"
    ENUM = "ENUM"
    ENUM_MEMBER = "ENUM_MEMBER"
    FIELD = "FIELD"
    IMPORT_ALIAS = "IMPORT_ALIAS"
    BUILTIN = "BUILTIN"


@dataclass(slots=True)
class Symbol:
    id: int
    name: str
    kind: SymbolKind
    declared_at: SourceSpan
    type: str | None
    qualifier: str | None
    scope_id: int
