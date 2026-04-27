from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal as TypingLiteral, cast

from pine2ast.ast.nodes import (
    Argument,
    BinaryExpr,
    CallExpr,
    ConditionalExpr,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    Literal,
    MemberAccessExpr,
    TupleExpr,
    UnaryExpr,
)
from pine2ast.ast.types import TypeRef
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import TokenKind
from pine2ast.parser.precedence import PRECEDENCE

from pine2ast.parser.base import BaseParser, _LITERAL_KINDS, join_span


class ExpressionsMixin(BaseParser):
    if TYPE_CHECKING:

        def parse_if(self) -> Any: ...
        def parse_switch(self) -> Any: ...
        def parse_for(self) -> Any: ...
        def parse_while(self) -> Any: ...
        def parse_type_ref(self) -> Any: ...

    def parse_expression(self, min_prec: int = 0):
        left = self.parse_prefix()
        while True:
            kind = self._peek().kind
            prec = PRECEDENCE.get(kind)
            if prec is not None and prec >= min_prec:
                op = self._advance()
                right = self.parse_expression(prec + 1)
                left = BinaryExpr(join_span(left.span, right.span), op.text, left, right)
                continue
            if min_prec <= 5 and self._match(TokenKind.QUESTION):
                true_expr = self.parse_expression()
                self._expect(TokenKind.COLON)
                false_expr = self.parse_expression(5)
                left = ConditionalExpr(
                    join_span(left.span, false_expr.span), left, true_expr, false_expr
                )
                continue
            break
        return left

    def parse_prefix(self):
        if self._peek().kind in {TokenKind.PLUS, TokenKind.MINUS, TokenKind.NOT}:
            op = self._advance()
            expr = self.parse_expression(70)
            return UnaryExpr(join_span(op.span, expr.span), op.text, expr)
        expr = self.parse_primary()
        return self.parse_postfix(expr)

    def parse_primary(self):
        tok = self._peek()
        if tok.kind in _LITERAL_KINDS:
            self._advance()
            return Literal(
                tok.span,
                tok.value,
                cast(
                    TypingLiteral["int", "float", "bool", "string", "color", "na"],
                    _LITERAL_KINDS[tok.kind],
                ),
            )
        if tok.kind is TokenKind.IDENTIFIER:
            self._advance()
            return Identifier(tok.span, tok.text)
        if tok.kind is TokenKind.LBRACKET:
            return self.parse_tuple_expr()
        if tok.kind is TokenKind.IF:
            return self.parse_if()
        if tok.kind is TokenKind.SWITCH:
            return self.parse_switch()
        if tok.kind is TokenKind.FOR:
            return self.parse_for()
        if tok.kind is TokenKind.WHILE:
            return self.parse_while()
        if self._match(TokenKind.LPAREN):
            expr = self.parse_expression()
            end = self._expect_closing(TokenKind.RPAREN)
            expr.span = join_span(tok.span, end.span)  # type: ignore[misc]
            return expr
        self._diag(
            Severity.ERROR,
            codes.SYNTAX_ERROR,
            f"Expected expression, got {tok.kind.value}.",
            tok.span,
        )
        self._advance()
        return Identifier(tok.span, "<error>")

    def parse_postfix(self, expr):
        while True:
            if self._match(TokenKind.DOT):
                member = self._expect_member_name()
                expr = MemberAccessExpr(join_span(expr.span, member.span), expr, member.text)
                continue
            if self._at(TokenKind.LT) and self._looks_like_template_suffix():
                self._advance()
                type_args: list[TypeRef] = []
                while not self._at(TokenKind.GT, TokenKind.EOF):
                    type_args.append(self.parse_type_ref())
                    if not self._match(TokenKind.COMMA):
                        break
                    if self._at(TokenKind.GT):
                        break
                end = self._expect(TokenKind.GT)
                expr = GenericInstantiationExpr(join_span(expr.span, end.span), expr, type_args)
                continue
            if self._match(TokenKind.LPAREN):
                args: list[Argument] = []
                while not self._at(TokenKind.RPAREN, TokenKind.EOF):
                    if self._at(TokenKind.IDENTIFIER) and self._peek(1).kind is TokenKind.EQ:
                        name = self._advance().text
                        eq = self._advance()
                        value = self.parse_expression()
                        args.append(Argument(join_span(eq.span, value.span), name, value))
                    else:
                        value = self.parse_expression()
                        args.append(Argument(value.span, None, value))
                    if not self._match(TokenKind.COMMA):
                        break
                    if self._at(TokenKind.RPAREN):
                        break
                end = self._expect_closing(TokenKind.RPAREN)
                expr = CallExpr(join_span(expr.span, end.span), expr, args)
                continue
            if self._match(TokenKind.LBRACKET):
                offset = self.parse_expression()
                end = self._expect_closing(TokenKind.RBRACKET)
                expr = HistoryRefExpr(join_span(expr.span, end.span), expr, offset)
                continue
            break
        return expr

    def parse_tuple_expr(self) -> TupleExpr:
        start = self._expect(TokenKind.LBRACKET)
        elements = []
        while not self._at(TokenKind.RBRACKET, TokenKind.EOF):
            elements.append(self.parse_expression())
            if not self._match(TokenKind.COMMA):
                break
            if self._at(TokenKind.RBRACKET):
                break
        end = self._expect_closing(TokenKind.RBRACKET)
        return TupleExpr(join_span(start.span, end.span), elements)
