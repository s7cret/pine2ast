from __future__ import annotations

import re
from dataclasses import dataclass

from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.annotations import parse_annotation
from pine2ast.lexer.token import KEYWORDS, SourceSpan, Token, TokenKind

_LONG_OPS: list[tuple[str, TokenKind]] = [
    ("=>", TokenKind.FAT_ARROW),
    (":=", TokenKind.COLONEQ),
    ("<=", TokenKind.LTE),
    (">=", TokenKind.GTE),
    ("==", TokenKind.EQEQ),
    ("!=", TokenKind.NEQ),
    ("+=", TokenKind.PLUSEQ),
    ("-=", TokenKind.MINUSEQ),
    ("*=", TokenKind.STAREQ),
    ("/=", TokenKind.SLASHEQ),
    ("%=", TokenKind.PERCENTEQ),
]

_SINGLE_OPS: dict[str, TokenKind] = {
    "+": TokenKind.PLUS,
    "-": TokenKind.MINUS,
    "*": TokenKind.STAR,
    "/": TokenKind.SLASH,
    "%": TokenKind.PERCENT,
    "<": TokenKind.LT,
    ">": TokenKind.GT,
    "=": TokenKind.EQ,
    "?": TokenKind.QUESTION,
    ":": TokenKind.COLON,
    ".": TokenKind.DOT,
    ",": TokenKind.COMMA,
    "(": TokenKind.LPAREN,
    ")": TokenKind.RPAREN,
    "[": TokenKind.LBRACKET,
    "]": TokenKind.RBRACKET,
}

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?")


@dataclass(slots=True)
class LexerResult:
    tokens: list[Token]
    diagnostics: list[Diagnostic]


class Lexer:
    def __init__(self, text: str, *, source_name: str = "<memory>") -> None:
        self.text = text
        self.source_name = source_name
        self.i = 0
        self.line = 1
        self.col = 1
        self.diagnostics: list[Diagnostic] = []

    def lex(self) -> LexerResult:
        tokens: list[Token] = []
        while not self._eof():
            ch = self._peek()
            if ch in " \t\f":
                self._advance()
                continue
            if ch == "\n":
                tokens.append(self._simple_token(TokenKind.NEWLINE, "\n", None))
                self._advance_newline()
                continue
            if ch == "/" and self._peek(1) == "/":
                token = self._lex_comment_or_annotation()
                if token is not None:
                    tokens.append(token)
                continue
            if ch in ('"', "'"):
                tokens.append(self._lex_string())
                continue
            if ch == "#":
                m = _HEX_RE.match(self.text, self.i)
                if m:
                    raw = m.group(0)
                    tokens.append(self._token(TokenKind.COLOR, raw, raw))
                    self._advance_text(raw)
                    continue
            if ch.isdigit() or (ch == "." and self._peek(1).isdigit()):
                tokens.append(self._lex_number())
                continue
            if ch.isalpha() or ch == "_":
                tokens.append(self._lex_identifier())
                continue
            matched = False
            for raw, kind in _LONG_OPS:
                if self.text.startswith(raw, self.i):
                    tokens.append(self._token(kind, raw, None))
                    self._advance_text(raw)
                    matched = True
                    break
            if matched:
                continue
            if ch in _SINGLE_OPS:
                tokens.append(self._simple_token(_SINGLE_OPS[ch], ch, None))
                self._advance()
                continue
            span = self._span_here(1)
            self.diagnostics.append(
                Diagnostic(Severity.ERROR, codes.UNKNOWN_TOKEN, f"Unknown token {ch!r}.", span)
            )
            self._advance()
        eof_span = SourceSpan(self.i, self.i, self.line, self.col, self.line, self.col)
        tokens.append(Token(TokenKind.EOF, "", None, eof_span))
        return LexerResult(tokens, self.diagnostics)

    def _lex_comment_or_annotation(self) -> Token | None:
        start_i, start_line, start_col = self.i, self.line, self.col
        while not self._eof() and self._peek() != "\n":
            self._advance()
        raw = self.text[start_i : self.i]
        span = SourceSpan(start_i, self.i, start_line, start_col, self.line, self.col)
        if raw.startswith("//@") or raw.startswith("//#region") or raw.startswith("//#endregion"):
            ann = parse_annotation(raw, span)
            kind = TokenKind.VERSION_ANNOTATION if ann.name == "version" else TokenKind.ANNOTATION
            return Token(kind, raw, ann, span)
        return None

    def _lex_number(self) -> Token:
        start_i, start_line, start_col = self.i, self.line, self.col
        saw_dot = False
        saw_exp = False
        if self._peek() == ".":
            saw_dot = True
            self._advance()
            while self._peek().isdigit():
                self._advance()
        else:
            while self._peek().isdigit():
                self._advance()
            if self._peek() == ".":
                saw_dot = True
                self._advance()
                while self._peek().isdigit():
                    self._advance()
        if self._peek() in "eE":
            nxt = self._peek(1)
            nxt2 = self._peek(2)
            if nxt.isdigit() or (nxt in "+-" and nxt2.isdigit()):
                saw_exp = True
                self._advance()
                if self._peek() in "+-":
                    self._advance()
                while self._peek().isdigit():
                    self._advance()
        raw = self.text[start_i : self.i]
        span = SourceSpan(start_i, self.i, start_line, start_col, self.line, self.col)
        if saw_dot or saw_exp:
            return Token(TokenKind.FLOAT, raw, float(raw), span)
        return Token(TokenKind.INTEGER, raw, int(raw), span)

    def _lex_identifier(self) -> Token:
        m = _IDENT_RE.match(self.text, self.i)
        assert m is not None
        raw = m.group(0)
        start_i, start_line, start_col = self.i, self.line, self.col
        self._advance_text(raw)
        span = SourceSpan(start_i, self.i, start_line, start_col, self.line, self.col)
        if raw == "true":
            return Token(TokenKind.BOOL, raw, True, span)
        if raw == "false":
            return Token(TokenKind.BOOL, raw, False, span)
        if raw == "na":
            return Token(TokenKind.NA, raw, None, span)
        return Token(KEYWORDS.get(raw, TokenKind.IDENTIFIER), raw, None, span)

    def _lex_string(self) -> Token:
        quote = self._peek()
        start_i, start_line, start_col = self.i, self.line, self.col
        triple = self.text.startswith(quote * 3, self.i)
        delim = quote * (3 if triple else 1)
        self._advance_text(delim)
        value_chars: list[str] = []
        while not self._eof():
            if self.text.startswith(delim, self.i):
                self._advance_text(delim)
                raw = self.text[start_i : self.i]
                span = SourceSpan(start_i, self.i, start_line, start_col, self.line, self.col)
                return Token(TokenKind.STRING, raw, "".join(value_chars), span)
            ch = self._peek()
            if ch == "\n" and not triple:
                break
            if ch == "\\":
                self._advance()
                esc = self._peek()
                mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}
                value_chars.append(mapping.get(esc, esc))
                if not self._eof():
                    self._advance()
                continue
            value_chars.append(ch)
            if ch == "\n":
                self._advance_newline()
            else:
                self._advance()
        span = SourceSpan(start_i, self.i, start_line, start_col, self.line, self.col)
        self.diagnostics.append(
            Diagnostic(
                Severity.FATAL, codes.UNTERMINATED_STRING, "Unterminated string literal.", span
            )
        )
        return Token(TokenKind.STRING, self.text[start_i : self.i], "".join(value_chars), span)

    def _token(self, kind: TokenKind, text: str, value: object | None) -> Token:
        return Token(kind, text, value, self._span_here(len(text)))

    def _simple_token(self, kind: TokenKind, text: str, value: object | None) -> Token:
        return Token(kind, text, value, self._span_here(len(text)))

    def _span_here(self, length: int) -> SourceSpan:
        return SourceSpan(
            self.i, self.i + length, self.line, self.col, self.line, self.col + length
        )

    def _peek(self, n: int = 0) -> str:
        idx = self.i + n
        if idx >= len(self.text):
            return "\0"
        return self.text[idx]

    def _eof(self) -> bool:
        return self.i >= len(self.text)

    def _advance(self) -> None:
        self.i += 1
        self.col += 1

    def _advance_newline(self) -> None:
        self.i += 1
        self.line += 1
        self.col = 1

    def _advance_text(self, raw: str) -> None:
        for ch in raw:
            if ch == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.i += 1
