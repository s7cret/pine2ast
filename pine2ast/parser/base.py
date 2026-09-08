from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from pine2ast.versioning import PineVersionContext
from pine2ast.policy import SyntaxPolicy

from pine2ast.ast.nodes import (
    CallExpr,
    DeclarationStatement,
    Identifier,
    MemberAccessExpr,
    Program,
)
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.annotations import Annotation
from pine2ast.lexer.token import SourceSpan, Token, TokenKind

AssignmentOperator = Literal[":=", "+=", "-=", "*=", "/=", "%="]
ScriptType = Literal["indicator", "strategy", "library"]

_ASSIGN_KINDS: dict[TokenKind, AssignmentOperator] = {
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
        def parse_type_decl(
            self, *, exported: bool = False, pending_annotations: list | None = None
        ) -> Any: ...
        def parse_enum_decl(
            self, *, exported: bool = False, pending_annotations: list | None = None
        ) -> Any: ...
        def parse_method_decl(
            self, *, exported: bool = False, pending_annotations: list | None = None
        ) -> Any: ...
        def parse_function_decl(
            self, *, exported: bool = False, pending_annotations: list | None = None
        ) -> Any: ...
        def parse_var_decl(
            self,
            *,
            is_exported: bool = False,
            pending_annotations: list | None = None,
            consume_separator: bool = True,
        ) -> Any: ...
        def parse_statement(self, *, pending_annotations: list | None = None) -> Any: ...

    def __init__(
        self,
        tokens: list[Token],
        *,
        version_context: PineVersionContext,
        syntax_policy: SyntaxPolicy,
        max_diagnostics: int = 200,
    ) -> None:
        syntax_policy.validate_context(version_context)
        self.tokens = tokens
        self.i = 0
        self.version_context = version_context
        self.syntax_policy = syntax_policy
        self.max_diagnostics = max_diagnostics
        self.diagnostics: list[Diagnostic] = []

    def parse(self) -> ParserResult:
        # The version was resolved before lexing. Parser only consumes the exact
        # annotation token so it can remain in the AST for provenance.
        leading = self._consume_version_annotation()
        annotations = [leading] if leading is not None else []
        if leading is not None:
            try:
                annotated = int(leading.value) if leading.value is not None else None
            except ValueError:
                annotated = None
            if annotated != self.version_context.pine_version:
                raise RuntimeError("resolved Pine version and parser annotation diverged")
        self._skip_newlines()
        declaration = None
        items = []
        # Consume leading imports before looking for the declaration. The
        # parser keeps recovery deterministic even for a version where imports
        # are unavailable, but the syntax-policy diagnostic remains blocking.
        while self._at(TokenKind.IMPORT):
            self._require_syntax("imports", self._peek().span)
            imported = self.parse_import()
            if imported is not None:
                items.append(imported)
            self._skip_newlines()
        if self._looks_like_declaration_statement():
            expr = self.parse_expression()
            if isinstance(expr, CallExpr):
                name = self._callee_name(expr.callee)
                declaration = DeclarationStatement(
                    expr.span, self._declaration_script_type(name), expr
                )
            self._consume_statement_separator()
        while not self._at(TokenKind.EOF):
            self._skip_newlines()
            pending_annotations = self._consume_annotations()
            if self._at(TokenKind.EOF):
                break
            item = self.parse_top_level_item(pending_annotations=pending_annotations)
            if item is not None:
                items.append(item)
            else:
                self._recover_to_line_end()
        end_span = self._peek().span
        start_span = (
            annotations[0].span if annotations else (declaration.span if declaration else end_span)
        )
        program = Program(
            join_span(start_span, end_span),
            self.version_context,
            annotations,
            declaration,
            items,
            [],
        )
        from pine2ast.ast.nodes import MethodDeclaration
        from pine2ast.ast.visitors import walk

        if any(
            isinstance(node, MethodDeclaration) and node.receiver_explicit_qualifier is not None
            for node in walk(program)
        ):
            program.schema_version = "2.1"
        return ParserResult(program, self.diagnostics)

    def parse_top_level_item(self, *, pending_annotations: list | None = None):
        pending = pending_annotations or []
        exported = self._match(TokenKind.EXPORT)
        if self._at(TokenKind.IMPORT):
            if not self._require_syntax("imports", self._peek().span):
                return None
            return self.parse_import(exported=exported)
        if self._at(TokenKind.TYPE):
            if not self._require_syntax("udt_declarations", self._peek().span):
                return None
            return self.parse_type_decl(exported=exported, pending_annotations=pending)
        if self._at(TokenKind.ENUM):
            if not self._require_syntax("enum_declarations", self._peek().span):
                return None
            return self.parse_enum_decl(exported=exported, pending_annotations=pending)
        if self._at(TokenKind.METHOD):
            if not self._require_syntax("method_declarations", self._peek().span):
                return None
            return self.parse_method_decl(exported=exported, pending_annotations=pending)
        if self._looks_like_declaration_statement():
            expr = self.parse_expression()
            self._consume_statement_separator()
            if isinstance(expr, CallExpr):
                name = self._callee_name(expr.callee)
                return DeclarationStatement(expr.span, self._declaration_script_type(name), expr)
        if self._looks_like_function_decl():
            self._require_syntax("user_functions", self._peek().span)
            return self.parse_function_decl(exported=exported, pending_annotations=pending)
        if exported:
            return self.parse_var_decl(is_exported=True, pending_annotations=pending)
        return self.parse_statement(pending_annotations=pending)

    def _require_syntax(self, capability: str, span: SourceSpan) -> bool:
        if self.syntax_policy.capability(capability):
            return True
        self._diag(
            Severity.ERROR,
            codes.SYNTAX_POLICY_VIOLATION,
            (
                f"Syntax capability {capability} is not available in Pine v"
                f"{self.version_context.pine_version}; rule="
                f"{self.syntax_policy.rule_id(capability)}."
            ),
            span,
        )
        return False

    @staticmethod
    def _declaration_script_type(spelling: str) -> ScriptType:
        # ``study`` is the historical indicator declaration spelling through
        # Pine v4. The AST exposes the semantic script kind while the CallExpr
        # retains the exact source spelling for provenance and migration tools.
        normalized = "indicator" if spelling == "study" else spelling
        if normalized not in {"indicator", "strategy", "library"}:
            raise RuntimeError(f"unsupported declaration spelling: {spelling!r}")
        return cast(ScriptType, normalized)

    def _looks_like_declaration_statement(self) -> bool:
        if not self._at(TokenKind.IDENTIFIER) or self._peek(1).kind is not TokenKind.LPAREN:
            return False
        return self._peek().text in self.syntax_policy.declaration_spellings

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

    def _consume_version_annotation(self) -> Annotation | None:
        """Consume at most one VERSION annotation, leaving any following
        annotations untouched so they can be attached to their target
        declaration by the main loop.
        """
        # Allow leading newlines before the version
        while self._at(TokenKind.NEWLINE):
            self._advance()
        if not self._at(TokenKind.VERSION_ANNOTATION):
            return None
        tok = self._advance()
        if isinstance(tok.value, Annotation):
            return tok.value
        return None

    def _skip_newlines(self) -> None:
        while self._at(TokenKind.NEWLINE):
            self._advance()

    def _consume_optional_newline(self) -> None:
        if self._at(TokenKind.NEWLINE):
            self._advance()

    def _consume_statement_separator(self) -> None:
        if self._at(TokenKind.COMMA) and self.syntax_policy.capability("comma_statement_separator"):
            self._advance()
        if self._at(TokenKind.NEWLINE):
            self._advance()

    def _recover_to_line_end(self) -> None:
        boundaries = {TokenKind.NEWLINE, TokenKind.DEDENT, TokenKind.EOF}
        if self.syntax_policy.capability("comma_statement_separator"):
            boundaries.add(TokenKind.COMMA)
        while self._peek().kind not in boundaries:
            self._advance()
        self._consume_statement_separator()

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
