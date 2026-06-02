from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pine2ast.ast.nodes import (
    EnumDeclaration,
    EnumMember,
    FieldDeclaration,
    FunctionDeclaration,
    ImportDeclaration,
    MethodDeclaration,
    Parameter,
    TypeDeclaration,
)
from pine2ast.ast.types import TypeRef
from pine2ast.lexer.token import TokenKind

from pine2ast.parser.base import BaseParser, _TYPE_QUALIFIERS, join_span


class DeclarationsMixin(BaseParser):
    if TYPE_CHECKING:

        def parse_expression(self, min_prec: int = 0) -> Any: ...
        def parse_function_body(self) -> Any: ...

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
        return ImportDeclaration(
            join_span(start.span, self._previous().span), path, owner, library, version, alias
        )

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
            fields.append(
                FieldDeclaration(
                    join_span(type_ref.span, field_name.span), field_name.text, type_ref, default
                )
            )
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
        return FunctionDeclaration(
            join_span(name.span, body.span), name.text, params, body, exported
        )

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
        return MethodDeclaration(
            join_span(start.span, body.span),
            name.text,
            receiver_type,
            receiver_name,
            params,
            body,
            exported,
        )

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
            type_ref = TypeRef(name, args, join_span(start.span, end.span))
        else:
            type_ref = TypeRef(name, args, start.span)
        if self._match(TokenKind.LBRACKET):
            end = self._expect(TokenKind.RBRACKET)
            return TypeRef("array", [type_ref], join_span(type_ref.span, end.span))
        return type_ref
