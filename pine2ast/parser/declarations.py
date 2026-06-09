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
from pine2ast.lexer.annotations import Annotation, AnnotationKind
from pine2ast.lexer.token import TokenKind

from pine2ast.parser.base import BaseParser, _TYPE_QUALIFIERS, join_span


def _split_annotations(annotations: list[Annotation]) -> tuple[list[Annotation], list[Annotation]]:
    """Split a flat annotation list into (function_level, param_or_field_or_returns).

    Function-level kinds: FUNCTION, RETURNS, TYPE, ENUM, VARIABLE, DESCRIPTION.
    Param/field-level kinds: PARAM, FIELD. Kept separate so the parser can
    route them to the right AST node based on the `name` attribute.
    """
    function_kinds = {
        AnnotationKind.FUNCTION,
        AnnotationKind.RETURNS,
        AnnotationKind.TYPE,
        AnnotationKind.ENUM,
        AnnotationKind.VARIABLE,
        AnnotationKind.DESCRIPTION,
    }
    func_level: list[Annotation] = []
    routed: list[Annotation] = []
    for a in annotations:
        if a.kind in function_kinds:
            func_level.append(a)
        else:
            routed.append(a)
    return func_level, routed


def _attach_documentation(
    documentation: list[Annotation], routed: list[Annotation]
) -> None:
    """Append any PARAM/FIELD annotations to documentation (caller chooses target)."""
    for a in routed:
        documentation.append(a)


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

    def parse_type_decl(
        self, *, exported: bool = False, pending_annotations: list | None = None
    ) -> TypeDeclaration:
        start = self._expect(TokenKind.TYPE)
        name = self._expect(TokenKind.IDENTIFIER).text
        self._expect(TokenKind.NEWLINE)
        self._expect(TokenKind.INDENT)
        fields: list[FieldDeclaration] = []
        # Route PARAM-style annotations to fields by name; TYPE/FIELD/... go to declaration.
        func_level, routed = _split_annotations(pending_annotations or [])
        doc_annotations: list[Annotation] = list(func_level)
        for f_ann in routed:
            doc_annotations.append(f_ann)
        # Build name -> [annotations] for field lookup
        field_ann_by_name: dict[str, list[Annotation]] = {}
        for a in routed:
            if a.kind == AnnotationKind.FIELD:
                field_ann_by_name.setdefault(a.name, []).append(a)
        # Now allow per-field //@field annotation as well, consumed before each field
        while not self._at(TokenKind.DEDENT, TokenKind.EOF):
            self._skip_newlines()
            if self._at(TokenKind.DEDENT, TokenKind.EOF):
                break
            # Consume per-field pending annotations right before each field
            field_pending = self._consume_annotations()
            for a in field_pending:
                if a.kind == AnnotationKind.FIELD:
                    field_ann_by_name.setdefault(a.name, []).append(a)
            type_ref = self.parse_type_ref()
            field_name = self._expect(TokenKind.IDENTIFIER)
            default = None
            if self._match(TokenKind.EQ):
                default = self.parse_expression()
            self._consume_optional_newline()
            field_doc = field_ann_by_name.get(field_name.text, [])
            fields.append(
                FieldDeclaration(
                    join_span(type_ref.span, field_name.span),
                    field_name.text,
                    type_ref,
                    default,
                    list(field_doc),
                )
            )
        end = self._expect(TokenKind.DEDENT)
        return TypeDeclaration(
            join_span(start.span, end.span),
            name,
            fields,
            exported,
            documentation=doc_annotations,
        )

    def parse_enum_decl(
        self, *, exported: bool = False, pending_annotations: list | None = None
    ) -> EnumDeclaration:
        start = self._expect(TokenKind.ENUM)
        name = self._expect(TokenKind.IDENTIFIER).text
        self._expect(TokenKind.NEWLINE)
        self._expect(TokenKind.INDENT)
        members: list[EnumMember] = []
        func_level, routed = _split_annotations(pending_annotations or [])
        doc_annotations: list[Annotation] = list(func_level)
        for a in routed:
            doc_annotations.append(a)
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
        return EnumDeclaration(
            join_span(start.span, end.span),
            name,
            members,
            exported,
            documentation=doc_annotations,
        )

    def parse_function_decl(
        self, *, exported: bool = False, pending_annotations: list | None = None
    ) -> FunctionDeclaration:
        name = self._expect(TokenKind.IDENTIFIER)
        self._expect(TokenKind.LPAREN)
        params, _ = self.parse_params()
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.FAT_ARROW)
        body = self.parse_function_body()
        func_level, routed = _split_annotations(pending_annotations or [])
        doc_annotations: list[Annotation] = list(func_level)
        param_ann_by_name: dict[str, list[Annotation]] = {}
        for a in routed:
            if a.kind == AnnotationKind.PARAM:
                param_ann_by_name.setdefault(a.name, []).append(a)
            else:
                doc_annotations.append(a)
        # Attach per-param documentation
        for p in params:
            p.documentation = list(param_ann_by_name.get(p.name, []))
        return FunctionDeclaration(
            join_span(name.span, body.span),
            name.text,
            params,
            body,
            exported,
            documentation=doc_annotations,
        )

    def parse_method_decl(
        self, *, exported: bool = False, pending_annotations: list | None = None
    ) -> MethodDeclaration:
        start = self._expect(TokenKind.METHOD)
        name = self._expect(TokenKind.IDENTIFIER)
        self._expect(TokenKind.LPAREN)
        receiver_type = None
        receiver_name = None
        # Method signature: METHOD NAME ( [RECEIVER_TYPE RECEIVER_NAME [, PARAMS] ] ) => BODY
        # Receiver is the first parameter (required), followed by optional additional params.
        if not self._at(TokenKind.RPAREN):
            receiver_type = self.parse_type_ref()
            receiver_tok = self._expect(TokenKind.IDENTIFIER)
            receiver_name = receiver_tok.text
        if self._match(TokenKind.COMMA):
            params, _ = self.parse_params()
        else:
            params = []
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.FAT_ARROW)
        body = self.parse_function_body()
        func_level, routed = _split_annotations(pending_annotations or [])
        doc_annotations: list[Annotation] = list(func_level)
        param_ann_by_name: dict[str, list[Annotation]] = {}
        for a in routed:
            if a.kind == AnnotationKind.PARAM:
                param_ann_by_name.setdefault(a.name, []).append(a)
            else:
                doc_annotations.append(a)
        for p in params:
            p.documentation = list(param_ann_by_name.get(p.name, []))
        return MethodDeclaration(
            join_span(start.span, body.span),
            name.text,
            receiver_type,
            receiver_name,
            params,
            body,
            exported,
            documentation=doc_annotations,
        )

    def parse_params(
        self, *, until_rparen: bool = True
    ) -> tuple[list[Parameter], dict[str, list[Annotation]]]:
        """Parse a parameter list.

        Returns (params, param_ann_by_name). The caller is responsible for
        attaching per-param documentation onto each Parameter after the full
        list of pending_annotations is known (parse_function_decl /
        parse_method_decl do this in one place to avoid double-routing).
        """
        params: list[Parameter] = []
        param_ann_by_name: dict[str, list[Annotation]] = {}
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
        return params, param_ann_by_name

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
