from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pine2ast.ast.nodes import (
    CallExpr,
    DeclarationStatement,
    Identifier,
    MemberAccessExpr,
    Program,
)
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.annotations import Annotation, AnnotationKind
from pine2ast.lexer.token import SourceSpan, Token, TokenKind

_ASSIGN_KINDS = {
    TokenKind.COLONEQ: ":=",
    TokenKind.PLUSEQ: "+=",
    TokenKind.MINUSEQ: "-=",
    TokenKind.STAREQ: "*=",
    TokenKind.SLASHEQ: "/=",
    TokenKind.PERCENTEQ: "%=",
}
_TYPE_QUALIFIERS = {
    TokenKind.CONST: "const",
    TokenKind.SIMPLE: "simple",
    TokenKind.SERIES: "series",
}
_DECL_MODES = {TokenKind.VAR: "var", TokenKind.VARIP: "varip"}
_LITERAL_KINDS = {
    TokenKind.INTEGER: "int",
    TokenKind.FLOAT: "float",
    TokenKind.BOOL: "bool",
    TokenKind.STRING: "string",
    TokenKind.COLOR: "color",
    TokenKind.NA: "na",
}


@dataclass(slots=True)
class ParserResult:
    program: Program | None
    diagnostics: list[Diagnostic]


def join_span(a: SourceSpan, b: SourceSpan) -> SourceSpan:
    return SourceSpan(
        a.start_offset, b.end_offset, a.start_line, a.start_col, b.end_line, b.end_col
    )


class BaseParser:
    if TYPE_CHECKING:

        def parse_expression(self, min_prec: int = 0) -> Any: ...
        def parse_import(self, *, exported: bool = False) -> Any: ...
        def parse_type_decl(self, *, exported: bool = False) -> Any: ...
        def parse_enum_decl(self, *, exported: bool = False) -> Any: ...
        def parse_method_decl(self, *, exported: bool = False) -> Any: ...
        def parse_function_decl(self, *, exported: bool = False) -> Any: ...
        def parse_var_decl(self, *, is_exported: bool = False) -> Any: ...
        def parse_statement(self) -> Any: ...

    def __init__(
        self, tokens: list[Token], *, strict_v6: bool = True, max_diagnostics: int = 200
    ) -> None:
        self.tokens = tokens
        self.i = 0
        self.strict_v6 = strict_v6
        self.max_diagnostics = max_diagnostics
        self.diagnostics: list[Diagnostic] = []

    def parse(self) -> ParserResult:
        annotations = self._consume_annotations()
        version = self._extract_version(annotations)
        if version != 6:
            span = annotations[0].span if annotations else self._peek().span
            if version is None:
                self._diag(
                    Severity.ERROR if self.strict_v6 else Severity.WARNING,
                    codes.MISSING_VERSION_6 if self.strict_v6 else codes.VERSION_ASSUMED,
                    "Missing //@version=6 annotation.",
                    span,
                )
                if not self.strict_v6:
                    version = 6
            elif version == 5:
                self._diag(
                    Severity.WARNING,
                    codes.UNSUPPORTED_VERSION,
                    "Pine version 5 is parsed in v6 compatibility mode.",
                    span,
                )
            else:
                self._diag(
                    Severity.ERROR if self.strict_v6 else Severity.WARNING,
                    codes.UNSUPPORTED_VERSION,
                    f"Unsupported Pine version {version}; this parser targets v6.",
                    span,
                )
        self._skip_newlines()
        declaration = None
        items = []
        if self._looks_like_declaration_statement():
            expr = self.parse_expression()
            if isinstance(expr, CallExpr):
                name = self._callee_name(expr.callee)
                declaration = DeclarationStatement(expr.span, name, expr)  # type: ignore[arg-type]
            self._consume_optional_newline()
        while not self._at(TokenKind.EOF):
            self._skip_newlines()
            self._consume_annotations()
            if self._at(TokenKind.EOF):
                break
            item = self.parse_top_level_item()
            if item is not None:
                items.append(item)
            else:
                self._recover_to_line_end()
        end_span = self._peek().span
        start_span = (
            annotations[0].span if annotations else (declaration.span if declaration else end_span)
        )
        program = Program(
            join_span(start_span, end_span), version, annotations, declaration, items, []
        )
        return ParserResult(program, self.diagnostics)

    def parse_top_level_item(self):
        exported = self._match(TokenKind.EXPORT)
        if self._at(TokenKind.IMPORT):
            return self.parse_import(exported=exported)
        if self._at(TokenKind.TYPE):
            return self.parse_type_decl(exported=exported)
        if self._at(TokenKind.ENUM):
            return self.parse_enum_decl(exported=exported)
        if self._at(TokenKind.METHOD):
            return self.parse_method_decl(exported=exported)
        if self._looks_like_declaration_statement():
            expr = self.parse_expression()
            self._consume_optional_newline()
            if isinstance(expr, CallExpr):
                return DeclarationStatement(expr.span, self._callee_name(expr.callee), expr)  # type: ignore[arg-type]
        if self._looks_like_function_decl():
            return self.parse_function_decl(exported=exported)
        if exported:
            return self.parse_var_decl(is_exported=True)
        return self.parse_statement()

    def _looks_like_declaration_statement(self) -> bool:
        if not self._at(TokenKind.IDENTIFIER) or self._peek(1).kind is not TokenKind.LPAREN:
            return False
        return self._peek().text in {"indicator", "strategy", "library"}

    def _looks_like_function_decl(self) -> bool:
        if not (self._at(TokenKind.IDENTIFIER) and self._peek(1).kind is TokenKind.LPAREN):
            return False
        depth = 0
        j = self.i
        while j < len(self.tokens):
            k = self.tokens[j].kind
            if k is TokenKind.LPAREN:
                depth += 1
            elif k is TokenKind.RPAREN:
                depth -= 1
                if depth == 0:
                    return (
                        j + 1 < len(self.tokens) and self.tokens[j + 1].kind is TokenKind.FAT_ARROW
                    )
            elif k in {TokenKind.NEWLINE, TokenKind.EOF}:
                return False
            j += 1
        return False

    def _looks_like_var_decl(self) -> bool:
        j = self.i
        if self.tokens[j].kind in _DECL_MODES:
            j += 1
        if self.tokens[j].kind in _TYPE_QUALIFIERS:
            j += 1
        if self.tokens[j].kind is TokenKind.IDENTIFIER and self.tokens[j + 1].kind is TokenKind.EQ:
            return True
        if self._looks_like_type_annotation(j):
            end = self._scan_type_ref(j)
            return (
                end is not None
                and self.tokens[end].kind is TokenKind.IDENTIFIER
                and self.tokens[end + 1].kind is TokenKind.EQ
            )
        return False

    def _looks_like_type_annotation(self, start: int) -> bool:
        end = self._scan_type_ref(start)
        return (
            end is not None
            and self.tokens[end].kind is TokenKind.IDENTIFIER
            and self.tokens[end + 1].kind in {TokenKind.EQ, TokenKind.COMMA, TokenKind.RPAREN}
        )

    def _scan_type_ref(self, start: int) -> int | None:
        j = start
        if self.tokens[j].kind is not TokenKind.IDENTIFIER:
            return None
        j += 1
        while (
            self.tokens[j].kind is TokenKind.DOT and self.tokens[j + 1].kind is TokenKind.IDENTIFIER
        ):
            j += 2
        if self.tokens[j].kind is TokenKind.LT:
            j += 1
            if self.tokens[j].kind is TokenKind.GT:
                return None
            while True:
                nested_end = self._scan_type_ref(j)
                if nested_end is None:
                    return None
                j = nested_end
                if self.tokens[j].kind is TokenKind.COMMA:
                    j += 1
                    continue
                if self.tokens[j].kind is TokenKind.GT:
                    j += 1
                    break
                return None
        if (
            self.tokens[j].kind is TokenKind.LBRACKET
            and self.tokens[j + 1].kind is TokenKind.RBRACKET
        ):
            j += 2
        return j

    def _looks_like_template_suffix(self) -> bool:
        if self.tokens[self.i].kind is not TokenKind.LT:
            return False
        j = self.i + 1
        nested_end = self._scan_type_ref(j)
        if nested_end is None:
            return False
        j = nested_end
        while self.tokens[j].kind is TokenKind.COMMA:
            nested_end = self._scan_type_ref(j + 1)
            if nested_end is None:
                return False
            j = nested_end
        return self.tokens[j].kind is TokenKind.GT and self.tokens[j + 1].kind in {
            TokenKind.LPAREN,
            TokenKind.DOT,
        }

    def _looks_like_tuple_decl(self) -> bool:
        j = self.i + 1
        saw_comma = False
        while j < len(self.tokens) and self.tokens[j].kind is not TokenKind.RBRACKET:
            if self.tokens[j].kind is TokenKind.COMMA:
                saw_comma = True
            j += 1
        return saw_comma and j + 1 < len(self.tokens) and self.tokens[j + 1].kind is TokenKind.EQ

    def _callee_name(self, expr) -> str:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccessExpr):
            return self._callee_name(expr.object) + "." + expr.member
        return "<expr>"

    def _extract_version(self, annotations: list[Annotation]) -> int | None:
        for ann in annotations:
            if ann.kind is AnnotationKind.VERSION and ann.value is not None:
                try:
                    return int(ann.value)
                except ValueError:
                    return None
        return None

    def _consume_annotations(self) -> list[Annotation]:
        annotations: list[Annotation] = []
        while self._at(TokenKind.VERSION_ANNOTATION, TokenKind.ANNOTATION, TokenKind.NEWLINE):
            if self._at(TokenKind.NEWLINE):
                self._advance()
                continue
            tok = self._advance()
            if isinstance(tok.value, Annotation):
                annotations.append(tok.value)
        return annotations

    def _skip_newlines(self) -> None:
        while self._at(TokenKind.NEWLINE):
            self._advance()

    def _consume_optional_newline(self) -> None:
        if self._at(TokenKind.NEWLINE):
            self._advance()

    def _recover_to_line_end(self) -> None:
        while not self._at(TokenKind.NEWLINE, TokenKind.DEDENT, TokenKind.EOF):
            self._advance()
        self._consume_optional_newline()

    def _match(self, *kinds: TokenKind) -> bool:
        if self._at(*kinds):
            self._advance()
            return True
        return False

    def _expect_member_name(self) -> Token:
        # Pine allows member/namespace names after a dot that can lex as keywords, e.g. input.enum().
        disallowed = {
            TokenKind.EOF,
            TokenKind.NEWLINE,
            TokenKind.INDENT,
            TokenKind.DEDENT,
            TokenKind.LPAREN,
            TokenKind.RPAREN,
            TokenKind.LBRACKET,
            TokenKind.RBRACKET,
            TokenKind.COMMA,
            TokenKind.DOT,
            TokenKind.EQ,
            TokenKind.FAT_ARROW,
        }
        tok = self._peek()
        if tok.kind not in disallowed:
            return self._advance()
        self._diag(
            Severity.ERROR,
            codes.SYNTAX_ERROR,
            f"Expected member name after '.', got {tok.kind.value}.",
            tok.span,
        )
        if tok.kind is not TokenKind.EOF:
            self._advance()
        return tok

    def _expect(self, kind: TokenKind) -> Token:
        if self._at(kind):
            return self._advance()
        tok = self._peek()
        self._diag(
            Severity.ERROR,
            codes.SYNTAX_ERROR,
            f"Expected {kind.value}, got {tok.kind.value}.",
            tok.span,
        )
        # Recovery: consume one unexpected token so callers inside loops cannot stall forever.
        if tok.kind is not TokenKind.EOF:
            self._advance()
        return tok

    def _expect_closing(self, kind: TokenKind) -> Token:
        if self._at(kind):
            return self._advance()
        tok = self._peek()
        self._diag(
            Severity.ERROR,
            codes.SYNTAX_ERROR,
            f"Expected {kind.value}, got {tok.kind.value}.",
            tok.span,
        )
        # Missing delimiters are usually followed by a statement boundary.  Keep synchronizing
        # tokens in place so the outer statement/block parser can recover subsequent statements.
        if tok.kind not in {TokenKind.NEWLINE, TokenKind.DEDENT, TokenKind.EOF}:
            self._advance()
        return tok

    def _at(self, *kinds: TokenKind) -> bool:
        return self._peek().kind in kinds

    def _peek(self, n: int = 0) -> Token:
        idx = min(self.i + n, len(self.tokens) - 1)
        return self.tokens[idx]

    def _previous(self) -> Token:
        return self.tokens[max(0, self.i - 1)]

    def _advance(self) -> Token:
        tok = self._peek()
        if tok.kind is not TokenKind.EOF:
            self.i += 1
        return tok

    def _diag(self, severity: Severity, code: str, message: str, span: SourceSpan) -> None:
        if len(self.diagnostics) < self.max_diagnostics:
            self.diagnostics.append(Diagnostic(severity, code, message, span))
