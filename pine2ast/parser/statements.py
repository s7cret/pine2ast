from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal as TypingLiteral, cast

from pine2ast.ast.nodes import (
    Block,
    BreakStatement,
    CallExpr,
    ContinueStatement,
    DeclarationStatement,
    ElseIfBranch,
    ExpressionStatement,
    ForInStructure,
    ForInTarget,
    ForRangeStructure,
    IfStructure,
    Reassignment,
    SwitchCase,
    SwitchStructure,
    TupleDeclaration,
    TupleTarget,
    VarDeclaration,
    WhileStructure,
)
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import Token, TokenKind

from pine2ast.parser.base import BaseParser, _ASSIGN_KINDS, _DECL_MODES, _TYPE_QUALIFIERS, join_span


class StatementsMixin(BaseParser):
    if TYPE_CHECKING:

        def parse_type_ref(self) -> Any: ...

    def parse_function_body(self):
        if self._match(TokenKind.NEWLINE):
            self._expect(TokenKind.INDENT)
            return self.parse_block_after_indent()
        return self.parse_inline_function_body()

    def parse_inline_function_body(self):
        return self.parse_inline_sequence_body()

    def parse_inline_sequence_body(self):
        statements = []
        start_span = self._peek().span
        while not self._at(TokenKind.NEWLINE, TokenKind.DEDENT, TokenKind.EOF):
            st = self.parse_inline_statement()
            statements.append(st)
            if not self._match(TokenKind.COMMA):
                break
            if self._at(TokenKind.NEWLINE, TokenKind.DEDENT, TokenKind.EOF):
                break
        self._consume_optional_newline()
        if len(statements) == 1 and isinstance(statements[0], ExpressionStatement):
            return statements[0].expression
        end_span = statements[-1].span if statements else start_span
        return Block(join_span(start_span, end_span), statements)

    def parse_inline_statement(self):
        if self._looks_like_var_decl():
            return self.parse_var_decl()
        expr = self.parse_expression()
        if self._peek().kind in _ASSIGN_KINDS:
            op_tok = self._advance()
            value = self.parse_expression()
            return Reassignment(join_span(expr.span, value.span), expr, _ASSIGN_KINDS[op_tok.kind], value)  # type: ignore[arg-type]
        return ExpressionStatement(expr.span, expr)

    def parse_block_after_indent(self) -> Block:
        statements = []
        start = self._previous().span
        while not self._at(TokenKind.DEDENT, TokenKind.EOF):
            self._skip_newlines()
            if self._at(TokenKind.DEDENT, TokenKind.EOF):
                break
            st = self.parse_statement()
            if st is not None:
                statements.append(st)
            else:
                self._recover_to_line_end()
        end = self._expect(TokenKind.DEDENT).span
        return Block(join_span(start, end), statements)

    def parse_statement(self):
        self._skip_newlines()
        if self._at(TokenKind.IF):
            return self.parse_if()
        if self._at(TokenKind.SWITCH):
            return self.parse_switch()
        if self._at(TokenKind.FOR):
            return self.parse_for()
        if self._at(TokenKind.WHILE):
            return self.parse_while()
        if self._at(TokenKind.BREAK):
            tok = self._advance()
            self._consume_optional_newline()
            return BreakStatement(tok.span)
        if self._at(TokenKind.CONTINUE):
            tok = self._advance()
            self._consume_optional_newline()
            return ContinueStatement(tok.span)
        if self._at(TokenKind.METHOD):
            return self.parse_method_decl(exported=False)
        if self._looks_like_function_decl():
            return self.parse_function_decl(exported=False)
        if self._looks_like_declaration_statement():
            expr = self.parse_expression()
            self._consume_optional_newline()
            if isinstance(expr, CallExpr):
                return DeclarationStatement(expr.span, self._callee_name(expr.callee), expr)  # type: ignore[arg-type]
        if self._at(TokenKind.LBRACKET) and self._looks_like_tuple_decl():
            return self.parse_tuple_decl()
        if self._looks_like_var_decl():
            return self.parse_var_decl()
        expr = self.parse_expression()
        if self._peek().kind in _ASSIGN_KINDS:
            op_tok = self._advance()
            value = self.parse_expression()
            self._consume_optional_newline()
            return Reassignment(join_span(expr.span, value.span), expr, _ASSIGN_KINDS[op_tok.kind], value)  # type: ignore[arg-type]
        if not self._at(TokenKind.NEWLINE, TokenKind.DEDENT, TokenKind.EOF):
            self._diag(
                Severity.ERROR,
                codes.SYNTAX_ERROR,
                f"Unexpected token {self._peek().kind.value} after expression statement.",
                self._peek().span,
            )
            self._recover_to_line_end()
        else:
            self._consume_optional_newline()
        return ExpressionStatement(expr.span, expr)

    def parse_var_decl(self, *, is_exported: bool = False) -> VarDeclaration:
        start_tok = self._peek()
        mode = None
        qualifier = None
        if self._peek().kind in _DECL_MODES:
            mode = cast(TypingLiteral["var", "varip"], _DECL_MODES[self._advance().kind])
        if self._peek().kind in _TYPE_QUALIFIERS:
            qualifier = cast(
                TypingLiteral["const", "simple", "series"], _TYPE_QUALIFIERS[self._advance().kind]
            )
        type_ref = None
        if self._looks_like_type_annotation(self.i):
            type_ref = self.parse_type_ref()
        name = self._expect(TokenKind.IDENTIFIER)
        self._expect(TokenKind.EQ)
        initializer = self.parse_expression()
        self._consume_optional_newline()
        return VarDeclaration(
            join_span(start_tok.span, initializer.span),
            name.text,
            mode,
            qualifier,
            type_ref,
            initializer,
            is_exported,
        )

    def parse_tuple_decl(self) -> TupleDeclaration:
        start = self._expect(TokenKind.LBRACKET)
        targets: list[TupleTarget] = []
        while not self._at(TokenKind.RBRACKET, TokenKind.EOF):
            target = self._expect(TokenKind.IDENTIFIER)
            targets.append(TupleTarget(target.span, target.text))
            if not self._match(TokenKind.COMMA):
                break
            if self._at(TokenKind.RBRACKET):
                break
        self._expect(TokenKind.RBRACKET)
        self._expect(TokenKind.EQ)
        init = self.parse_expression()
        self._consume_optional_newline()
        return TupleDeclaration(join_span(start.span, init.span), targets, init)

    def parse_if(self) -> IfStructure:
        start = self._expect(TokenKind.IF)
        cond = self.parse_expression()
        then_block = self.parse_required_block()
        else_if: list[ElseIfBranch] = []
        else_block = None
        while self._at(TokenKind.ELSE) and self._peek(1).kind is TokenKind.IF:
            else_tok = self._advance()
            self._advance()
            econd = self.parse_expression()
            eblock = self.parse_required_block()
            else_if.append(ElseIfBranch(join_span(else_tok.span, eblock.span), econd, eblock))
        if self._match(TokenKind.ELSE):
            else_block = self.parse_required_block()
        return IfStructure(
            join_span(start.span, (else_block or then_block).span),
            cond,
            then_block,
            else_if,
            else_block,
        )

    def parse_required_block(self) -> Block:
        newline = self._expect(TokenKind.NEWLINE)
        if not self._at(TokenKind.INDENT):
            tok = self._peek()
            self._diag(
                Severity.ERROR,
                codes.SYNTAX_ERROR,
                f"Expected {TokenKind.INDENT.value}, got {tok.kind.value}.",
                tok.span,
            )
            return Block(join_span(newline.span, newline.span), [])
        self._advance()
        return self.parse_block_after_indent()

    def parse_switch(self) -> SwitchStructure:
        start = self._expect(TokenKind.SWITCH)
        expr = None
        if not self._at(TokenKind.NEWLINE):
            expr = self.parse_expression()
        # Consume newline after switch header; if case arms are on the same logical
        # line (no INDENT emitted by layout), treat the first case arm as direct
        # continuation and skip the INDENT check for the first iteration only.
        self._expect(TokenKind.NEWLINE)
        if not self._at(TokenKind.INDENT):
            synthetic_indent = Token(TokenKind.INDENT, "", None, self._peek().span)
            self.tokens.insert(self.i, synthetic_indent)
        self._expect(TokenKind.INDENT)
        self._skip_newlines()  # consume blank lines / comments before first case
        cases: list[SwitchCase] = []
        while not self._at(TokenKind.DEDENT, TokenKind.EOF):
            self._skip_newlines()
            if self._at(TokenKind.DEDENT, TokenKind.EOF):
                break
            cond = None
            case_start = self._peek().span
            if not self._at(TokenKind.FAT_ARROW):
                cond = self.parse_expression()
            self._expect(TokenKind.FAT_ARROW)
            if self._match(TokenKind.NEWLINE):
                if self._at(TokenKind.INDENT):
                    self._advance()
                    body = self.parse_block_after_indent()
                else:
                    synthetic = Token(TokenKind.INDENT, "", None, self._peek().span)
                    self.tokens.insert(self.i, synthetic)
                    self._advance()
                    body = self.parse_block_after_indent()
            else:
                body = self.parse_inline_sequence_body()
            cases.append(SwitchCase(join_span(case_start, body.span), cond, body))
        end = self._expect(TokenKind.DEDENT)
        return SwitchStructure(join_span(start.span, end.span), expr, cases)

    def parse_for(self):
        start = self._expect(TokenKind.FOR)
        if self._match(TokenKind.LBRACKET):
            target_start = self._previous().span
            names: list[str] = []
            last_span = target_start
            # Recovery-friendly parsing: preserve every identifier inside the target list so
            # semantic analysis can still type what it can, but do not get stuck when the
            # Pine grammar is malformed (e.g. `for [a, b, c] in values`).
            while not self._at(TokenKind.RBRACKET, TokenKind.EOF):
                if self._at(TokenKind.IDENTIFIER):
                    tok = self._advance()
                    names.append(tok.text)
                    last_span = tok.span
                else:
                    self._diag(
                        Severity.ERROR,
                        codes.SYNTAX_ERROR,
                        f"Expected for-in target identifier, got {self._peek().kind.value}.",
                        self._peek().span,
                    )
                    self._advance()
                    continue
                if not self._match(TokenKind.COMMA):
                    break
                if self._at(TokenKind.RBRACKET):
                    break
            rbr = self._expect(TokenKind.RBRACKET)
            target_span = join_span(target_start, rbr.span if rbr else last_span)
            if len(names) not in {1, 2}:
                self._diag(
                    Severity.ERROR,
                    codes.FOR_IN_TARGET_ARITY,
                    "for-in destructuring supports one value target or [index, value].",
                    target_span,
                )
            target = ForInTarget(target_span, names or ["<error>"])
            self._expect(TokenKind.IN)
            iterable = self.parse_expression()
            body = self.parse_required_block()
            return ForInStructure(join_span(start.span, body.span), target, iterable, body)
        name = self._expect(TokenKind.IDENTIFIER)
        if self._match(TokenKind.EQ):
            begin = self.parse_expression()
            self._expect(TokenKind.TO)
            end_expr = self.parse_expression()
            step = self.parse_expression() if self._match(TokenKind.BY) else None
            body = self.parse_required_block()
            return ForRangeStructure(
                join_span(start.span, body.span), name.text, begin, end_expr, step, body
            )
        self._expect(TokenKind.IN)
        iterable = self.parse_expression()
        body = self.parse_required_block()
        return ForInStructure(
            join_span(start.span, body.span), ForInTarget(name.span, [name.text]), iterable, body
        )

    def parse_while(self) -> WhileStructure:
        start = self._expect(TokenKind.WHILE)
        cond = self.parse_expression()
        body = self.parse_required_block()
        return WhileStructure(join_span(start.span, body.span), cond, body)
