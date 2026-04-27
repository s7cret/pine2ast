from __future__ import annotations

from dataclasses import dataclass

from pine2ast.ast.nodes import (
    Argument,
    BinaryExpr,
    Block,
    BreakStatement,
    CallExpr,
    ConditionalExpr,
    ContinueStatement,
    DeclarationStatement,
    ElseIfBranch,
    EnumDeclaration,
    EnumMember,
    ExpressionStatement,
    FieldDeclaration,
    ForInStructure,
    ForInTarget,
    ForRangeStructure,
    FunctionDeclaration,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    IfStructure,
    ImportDeclaration,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    Parameter,
    Program,
    Reassignment,
    SwitchCase,
    SwitchStructure,
    TupleDeclaration,
    TupleExpr,
    TupleTarget,
    TypeDeclaration,
    UnaryExpr,
    VarDeclaration,
    WhileStructure,
)
from pine2ast.ast.types import TypeRef
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.annotations import Annotation, AnnotationKind
from pine2ast.lexer.token import SourceSpan, Token, TokenKind
from pine2ast.parser.precedence import PRECEDENCE

_ASSIGN_KINDS = {
    TokenKind.COLONEQ: ":=",
    TokenKind.PLUSEQ: "+=",
    TokenKind.MINUSEQ: "-=",
    TokenKind.STAREQ: "*=",
    TokenKind.SLASHEQ: "/=",
    TokenKind.PERCENTEQ: "%=",
}
_TYPE_QUALIFIERS = {TokenKind.CONST: "const", TokenKind.SIMPLE: "simple", TokenKind.SERIES: "series"}
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
    return SourceSpan(a.start_offset, b.end_offset, a.start_line, a.start_col, b.end_line, b.end_col)


class Parser:
    def __init__(self, tokens: list[Token], *, strict_v6: bool = True, max_diagnostics: int = 200) -> None:
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
        start_span = annotations[0].span if annotations else (declaration.span if declaration else end_span)
        program = Program(join_span(start_span, end_span), version, annotations, declaration, items, [])
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

    def parse_import(self, *, exported: bool = False) -> ImportDeclaration:
        start = self._expect(TokenKind.IMPORT)
        parts: list[str] = []
        while self._at(TokenKind.IDENTIFIER, TokenKind.INTEGER) or self._at(TokenKind.SLASH):
            tok = self._advance()
            parts.append(tok.text)
        alias = None
        if self._match(TokenKind.AS):
            alias = self._expect(TokenKind.IDENTIFIER).text
        self._consume_optional_newline()
        path = "".join(parts)
        split = path.split("/")
        owner = split[0] if len(split) >= 1 else None
        library = split[1] if len(split) >= 2 else None
        version = split[2] if len(split) >= 3 else None
        return ImportDeclaration(join_span(start.span, self._previous().span), path, owner, library, version, alias)

    def parse_type_decl(self, *, exported: bool = False) -> TypeDeclaration:
        start = self._expect(TokenKind.TYPE)
        name = self._expect(TokenKind.IDENTIFIER).text
        self._expect(TokenKind.NEWLINE)
        self._expect(TokenKind.INDENT)
        fields: list[FieldDeclaration] = []
        while not self._at(TokenKind.DEDENT, TokenKind.EOF):
            self._skip_newlines()
            if self._at(TokenKind.DEDENT, TokenKind.EOF):
                break
            type_ref = self.parse_type_ref()
            field_name = self._expect(TokenKind.IDENTIFIER)
            default = None
            if self._match(TokenKind.EQ):
                default = self.parse_expression()
            self._consume_optional_newline()
            fields.append(FieldDeclaration(join_span(type_ref.span, field_name.span), field_name.text, type_ref, default))
        end = self._expect(TokenKind.DEDENT)
        return TypeDeclaration(join_span(start.span, end.span), name, fields, exported)

    def parse_enum_decl(self, *, exported: bool = False) -> EnumDeclaration:
        start = self._expect(TokenKind.ENUM)
        name = self._expect(TokenKind.IDENTIFIER).text
        self._expect(TokenKind.NEWLINE)
        self._expect(TokenKind.INDENT)
        members: list[EnumMember] = []
        while not self._at(TokenKind.DEDENT, TokenKind.EOF):
            self._skip_newlines()
            if self._at(TokenKind.DEDENT, TokenKind.EOF):
                break
            member = self._expect(TokenKind.IDENTIFIER)
            title = None
            if self._at(TokenKind.STRING):
                title = self._advance().value
            self._consume_optional_newline()
            members.append(EnumMember(member.span, member.text, title))
        end = self._expect(TokenKind.DEDENT)
        return EnumDeclaration(join_span(start.span, end.span), name, members, exported)

    def parse_function_decl(self, *, exported: bool = False) -> FunctionDeclaration:
        name = self._expect(TokenKind.IDENTIFIER)
        self._expect(TokenKind.LPAREN)
        params = self.parse_params()
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.FAT_ARROW)
        body = self.parse_function_body()
        return FunctionDeclaration(join_span(name.span, body.span), name.text, params, body, exported)

    def parse_method_decl(self, *, exported: bool = False) -> MethodDeclaration:
        start = self._expect(TokenKind.METHOD)
        name = self._expect(TokenKind.IDENTIFIER)
        self._expect(TokenKind.LPAREN)
        receiver_type = None
        receiver_name = None
        params: list[Parameter] = []
        if not self._at(TokenKind.RPAREN):
            receiver_type = self.parse_type_ref()
            receiver_tok = self._expect(TokenKind.IDENTIFIER)
            receiver_name = receiver_tok.text
            if self._match(TokenKind.COMMA):
                params = self.parse_params(until_rparen=True)
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.FAT_ARROW)
        body = self.parse_function_body()
        return MethodDeclaration(join_span(start.span, body.span), name.text, receiver_type, receiver_name, params, exported)

    def parse_params(self, *, until_rparen: bool = True) -> list[Parameter]:
        params: list[Parameter] = []
        while not self._at(TokenKind.RPAREN, TokenKind.EOF):
            qualifier = None
            if self._peek().kind in _TYPE_QUALIFIERS:
                qualifier = _TYPE_QUALIFIERS[self._advance().kind]
            type_ref = None
            if self._looks_like_type_annotation(self.i):
                type_ref = self.parse_type_ref()
            name = self._expect(TokenKind.IDENTIFIER)
            default = None
            if self._match(TokenKind.EQ):
                default = self.parse_expression()
            params.append(Parameter(name.span, name.text, type_ref, qualifier, default))
            if not self._match(TokenKind.COMMA):
                break
            if self._at(TokenKind.RPAREN):
                break
        return params

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
            tok = self._advance(); self._consume_optional_newline(); return BreakStatement(tok.span)
        if self._at(TokenKind.CONTINUE):
            tok = self._advance(); self._consume_optional_newline(); return ContinueStatement(tok.span)
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
            self._diag(Severity.ERROR, codes.SYNTAX_ERROR, f"Unexpected token {self._peek().kind.value} after expression statement.", self._peek().span)
            self._recover_to_line_end()
        else:
            self._consume_optional_newline()
        return ExpressionStatement(expr.span, expr)

    def parse_var_decl(self, *, is_exported: bool = False) -> VarDeclaration:
        start_tok = self._peek()
        mode = None
        qualifier = None
        if self._peek().kind in _DECL_MODES:
            mode = _DECL_MODES[self._advance().kind]
        if self._peek().kind in _TYPE_QUALIFIERS:
            qualifier = _TYPE_QUALIFIERS[self._advance().kind]
        type_ref = None
        if self._looks_like_type_annotation(self.i):
            type_ref = self.parse_type_ref()
        name = self._expect(TokenKind.IDENTIFIER)
        self._expect(TokenKind.EQ)
        initializer = self.parse_expression()
        self._consume_optional_newline()
        return VarDeclaration(join_span(start_tok.span, initializer.span), name.text, mode, qualifier, type_ref, initializer, is_exported)

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
            else_tok = self._advance(); self._advance()
            econd = self.parse_expression()
            eblock = self.parse_required_block()
            else_if.append(ElseIfBranch(join_span(else_tok.span, eblock.span), econd, eblock))
        if self._match(TokenKind.ELSE):
            else_block = self.parse_required_block()
        return IfStructure(join_span(start.span, (else_block or then_block).span), cond, then_block, else_if, else_block)

    def parse_required_block(self) -> Block:
        self._expect(TokenKind.NEWLINE)
        self._expect(TokenKind.INDENT)
        return self.parse_block_after_indent()

    def parse_switch(self) -> SwitchStructure:
        start = self._expect(TokenKind.SWITCH)
        expr = None
        if not self._at(TokenKind.NEWLINE):
            expr = self.parse_expression()
        self._expect(TokenKind.NEWLINE); self._expect(TokenKind.INDENT)
        cases: list[SwitchCase] = []
        while not self._at(TokenKind.DEDENT, TokenKind.EOF):
            self._skip_newlines()
            if self._at(TokenKind.DEDENT, TokenKind.EOF): break
            cond = None
            case_start = self._peek().span
            if not self._at(TokenKind.FAT_ARROW):
                cond = self.parse_expression()
            self._expect(TokenKind.FAT_ARROW)
            if self._match(TokenKind.NEWLINE):
                self._expect(TokenKind.INDENT)
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
                    self._diag(Severity.ERROR, codes.SYNTAX_ERROR, f"Expected for-in target identifier, got {self._peek().kind.value}.", self._peek().span)
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
            begin = self.parse_expression(); self._expect(TokenKind.TO); end_expr = self.parse_expression()
            step = self.parse_expression() if self._match(TokenKind.BY) else None
            body = self.parse_required_block()
            return ForRangeStructure(join_span(start.span, body.span), name.text, begin, end_expr, step, body)
        self._expect(TokenKind.IN)
        iterable = self.parse_expression()
        body = self.parse_required_block()
        return ForInStructure(join_span(start.span, body.span), ForInTarget(name.span, [name.text]), iterable, body)

    def parse_while(self) -> WhileStructure:
        start = self._expect(TokenKind.WHILE)
        cond = self.parse_expression()
        body = self.parse_required_block()
        return WhileStructure(join_span(start.span, body.span), cond, body)

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
                left = ConditionalExpr(join_span(left.span, false_expr.span), left, true_expr, false_expr)
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
            return Literal(tok.span, tok.value, _LITERAL_KINDS[tok.kind])
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
            end = self._expect(TokenKind.RPAREN)
            expr.span = join_span(tok.span, end.span)  # type: ignore[misc]
            return expr
        self._diag(Severity.ERROR, codes.SYNTAX_ERROR, f"Expected expression, got {tok.kind.value}.", tok.span)
        self._advance()
        return Identifier(tok.span, "<error>")

    def parse_postfix(self, expr):
        while True:
            if self._match(TokenKind.DOT):
                member = self._expect_member_name()
                expr = MemberAccessExpr(join_span(expr.span, member.span), expr, member.text)
                continue
            if self._at(TokenKind.LT) and self._looks_like_template_suffix():
                lt = self._advance()
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
                end = self._expect(TokenKind.RPAREN)
                expr = CallExpr(join_span(expr.span, end.span), expr, args)
                continue
            if self._match(TokenKind.LBRACKET):
                offset = self.parse_expression()
                end = self._expect(TokenKind.RBRACKET)
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
        end = self._expect(TokenKind.RBRACKET)
        return TupleExpr(join_span(start.span, end.span), elements)

    def parse_type_ref(self) -> TypeRef:
        start = self._expect(TokenKind.IDENTIFIER)
        name = start.text
        while self._match(TokenKind.DOT):
            name += "." + self._expect(TokenKind.IDENTIFIER).text
        args: list[TypeRef] = []
        if self._match(TokenKind.LT):
            while not self._at(TokenKind.GT, TokenKind.EOF):
                args.append(self.parse_type_ref())
                if not self._match(TokenKind.COMMA):
                    break
                if self._at(TokenKind.GT):
                    break
            end = self._expect(TokenKind.GT)
            return TypeRef(name, args, join_span(start.span, end.span))
        return TypeRef(name, args, start.span)

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
            if k is TokenKind.LPAREN: depth += 1
            elif k is TokenKind.RPAREN:
                depth -= 1
                if depth == 0:
                    return j + 1 < len(self.tokens) and self.tokens[j + 1].kind is TokenKind.FAT_ARROW
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
        while self.tokens[j].kind is TokenKind.DOT and self.tokens[j + 1].kind is TokenKind.IDENTIFIER:
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
        return self.tokens[j].kind is TokenKind.GT and self.tokens[j + 1].kind in {TokenKind.LPAREN, TokenKind.DOT}

    def _looks_like_tuple_decl(self) -> bool:
        j = self.i + 1
        saw_comma = False
        while j < len(self.tokens) and self.tokens[j].kind is not TokenKind.RBRACKET:
            if self.tokens[j].kind is TokenKind.COMMA: saw_comma = True
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
                self._advance(); continue
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
            TokenKind.EOF, TokenKind.NEWLINE, TokenKind.INDENT, TokenKind.DEDENT,
            TokenKind.LPAREN, TokenKind.RPAREN, TokenKind.LBRACKET, TokenKind.RBRACKET,
            TokenKind.COMMA, TokenKind.DOT, TokenKind.EQ, TokenKind.FAT_ARROW,
        }
        tok = self._peek()
        if tok.kind not in disallowed:
            return self._advance()
        self._diag(Severity.ERROR, codes.SYNTAX_ERROR, f"Expected member name after '.', got {tok.kind.value}.", tok.span)
        if tok.kind is not TokenKind.EOF:
            self._advance()
        return tok

    def _expect(self, kind: TokenKind) -> Token:
        if self._at(kind):
            return self._advance()
        tok = self._peek()
        self._diag(Severity.ERROR, codes.SYNTAX_ERROR, f"Expected {kind.value}, got {tok.kind.value}.", tok.span)
        # Recovery: consume one unexpected token so callers inside loops cannot stall forever.
        if tok.kind is not TokenKind.EOF:
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
