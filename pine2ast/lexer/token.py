from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(slots=True, frozen=True)
class SourceSpan:
    start_offset: int
    end_offset: int
    start_line: int
    start_col: int
    end_line: int
    end_col: int

    @classmethod
    def zero(cls) -> "SourceSpan":
        return cls(0, 0, 1, 1, 1, 1)

    def to_dict(self) -> dict[str, int]:
        return {
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "start_line": self.start_line,
            "start_col": self.start_col,
            "end_line": self.end_line,
            "end_col": self.end_col,
        }


class TokenKind(str, Enum):
    EOF = "EOF"
    NEWLINE = "NEWLINE"
    INDENT = "INDENT"
    DEDENT = "DEDENT"
    IDENTIFIER = "IDENTIFIER"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    STRING = "STRING"
    BOOL = "BOOL"
    NA = "NA"
    COLOR = "COLOR"
    VERSION_ANNOTATION = "VERSION_ANNOTATION"
    ANNOTATION = "ANNOTATION"

    IF = "IF"
    ELSE = "ELSE"
    FOR = "FOR"
    TO = "TO"
    BY = "BY"
    IN = "IN"
    WHILE = "WHILE"
    SWITCH = "SWITCH"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"
    VAR = "VAR"
    VARIP = "VARIP"
    TYPE = "TYPE"
    ENUM = "ENUM"
    METHOD = "METHOD"
    EXPORT = "EXPORT"
    IMPORT = "IMPORT"
    AS = "AS"
    CONST = "CONST"
    SIMPLE = "SIMPLE"
    SERIES = "SERIES"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"

    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    SLASH = "SLASH"
    PERCENT = "PERCENT"
    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"
    EQEQ = "EQEQ"
    NEQ = "NEQ"
    EQ = "EQ"
    COLONEQ = "COLONEQ"
    PLUSEQ = "PLUSEQ"
    MINUSEQ = "MINUSEQ"
    STAREQ = "STAREQ"
    SLASHEQ = "SLASHEQ"
    PERCENTEQ = "PERCENTEQ"
    QUESTION = "QUESTION"
    COLON = "COLON"
    FAT_ARROW = "FAT_ARROW"
    DOT = "DOT"
    COMMA = "COMMA"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"


KEYWORDS: dict[str, TokenKind] = {
    "if": TokenKind.IF,
    "else": TokenKind.ELSE,
    "for": TokenKind.FOR,
    "to": TokenKind.TO,
    "by": TokenKind.BY,
    "in": TokenKind.IN,
    "while": TokenKind.WHILE,
    "switch": TokenKind.SWITCH,
    "break": TokenKind.BREAK,
    "continue": TokenKind.CONTINUE,
    "var": TokenKind.VAR,
    "varip": TokenKind.VARIP,
    "type": TokenKind.TYPE,
    "enum": TokenKind.ENUM,
    "method": TokenKind.METHOD,
    "export": TokenKind.EXPORT,
    "import": TokenKind.IMPORT,
    "as": TokenKind.AS,
    "const": TokenKind.CONST,
    "simple": TokenKind.SIMPLE,
    "series": TokenKind.SERIES,
    "and": TokenKind.AND,
    "or": TokenKind.OR,
    "not": TokenKind.NOT,
}


@dataclass(slots=True, frozen=True)
class Trivia:
    kind: str
    text: str
    span: SourceSpan

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "span": self.span.to_dict()}


@dataclass(slots=True, frozen=True)
class Token:
    kind: TokenKind
    text: str
    value: Any
    span: SourceSpan
    leading_trivia: tuple[Trivia, ...] = ()
    trailing_trivia: tuple[Trivia, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "text": self.text,
            "value": self.value,
            "span": self.span.to_dict(),
        }
