from __future__ import annotations

from dataclasses import dataclass

from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan, Token, TokenKind

_CONTINUATION_END = {
    TokenKind.PLUS,
    TokenKind.MINUS,
    TokenKind.STAR,
    TokenKind.SLASH,
    TokenKind.PERCENT,
    TokenKind.LT,
    TokenKind.LTE,
    TokenKind.GT,
    TokenKind.GTE,
    TokenKind.EQEQ,
    TokenKind.NEQ,
    TokenKind.AND,
    TokenKind.OR,
    TokenKind.QUESTION,
    TokenKind.COLON,
    TokenKind.COMMA,
    TokenKind.EQ,
    TokenKind.COLONEQ,
    TokenKind.PLUSEQ,
    TokenKind.MINUSEQ,
    TokenKind.STAREQ,
    TokenKind.SLASHEQ,
    TokenKind.PERCENTEQ,
}
_OPEN = {TokenKind.LPAREN, TokenKind.LBRACKET}
_CLOSE = {TokenKind.RPAREN, TokenKind.RBRACKET}


@dataclass(slots=True)
class LayoutResult:
    tokens: list[Token]
    diagnostics: list[Diagnostic]


class LayoutProcessor:
    """Turns physical NEWLINE tokens into logical NEWLINE/INDENT/DEDENT tokens.

    The implementation intentionally keeps layout as a separate layer. It treats Pine-style
    offside blocks as indentation multiples of 4 at logical line starts, and treats non-block
    indentation after continuation operators as line wrapping.
    """

    def process(self, tokens: list[Token]) -> LayoutResult:
        lines: list[list[Token]] = []
        cur: list[Token] = []
        eof = tokens[-1]
        for tok in tokens:
            if tok.kind is TokenKind.EOF:
                eof = tok
                break
            if tok.kind is TokenKind.NEWLINE:
                lines.append(cur)
                cur = []
            else:
                cur.append(tok)
        if cur:
            lines.append(cur)

        out: list[Token] = []
        diagnostics: list[Diagnostic] = []
        indent_stack = [0]
        depth = 0
        prev_last: Token | None = None
        previous_line_was_logical = False

        nonempty_lines = [line for line in lines if line]
        for idx, line in enumerate(nonempty_lines):
            first = line[0]
            indent = max(0, first.span.start_col - 1)
            continuation = depth > 0 or (prev_last is not None and prev_last.kind in _CONTINUATION_END)
            if not continuation and indent % 4 != 0 and indent not in indent_stack:
                continuation = True

            if not continuation:
                if previous_line_was_logical:
                    out.append(self._layout_token(TokenKind.NEWLINE, prev_last.span if prev_last else first.span))
                self._apply_indent(indent, indent_stack, out, diagnostics, first.span)
                previous_line_was_logical = True

            out.extend(line)
            depth = self._depth_after_line(line, depth)
            prev_last = self._last_significant(line) or prev_last

            next_line = nonempty_lines[idx + 1] if idx + 1 < len(nonempty_lines) else None
            if next_line is None:
                continue
            next_indent = max(0, next_line[0].span.start_col - 1)
            next_continuation = depth > 0 or (prev_last is not None and prev_last.kind in _CONTINUATION_END)
            if not next_continuation and next_indent % 4 != 0 and next_indent not in indent_stack:
                next_continuation = True
            if continuation or next_continuation:
                # no logical newline between wrapped physical lines
                pass

        if previous_line_was_logical and prev_last is not None:
            out.append(self._layout_token(TokenKind.NEWLINE, prev_last.span))
        while len(indent_stack) > 1:
            indent_stack.pop()
            out.append(self._layout_token(TokenKind.DEDENT, eof.span))
        out.append(eof)
        return LayoutResult(out, diagnostics)

    def _apply_indent(
        self,
        indent: int,
        indent_stack: list[int],
        out: list[Token],
        diagnostics: list[Diagnostic],
        span: SourceSpan,
    ) -> None:
        current = indent_stack[-1]
        if indent > current:
            indent_stack.append(indent)
            out.append(self._layout_token(TokenKind.INDENT, span))
            return
        if indent < current:
            while len(indent_stack) > 1 and indent < indent_stack[-1]:
                indent_stack.pop()
                out.append(self._layout_token(TokenKind.DEDENT, span))
            if indent_stack[-1] != indent:
                diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        codes.BAD_INDENTATION,
                        "Indentation does not match any active block level.",
                        span,
                    )
                )

    def _depth_after_line(self, line: list[Token], initial: int) -> int:
        depth = initial
        for tok in line:
            if tok.kind in _OPEN:
                depth += 1
            elif tok.kind in _CLOSE:
                depth = max(0, depth - 1)
        return depth

    def _last_significant(self, line: list[Token]) -> Token | None:
        for tok in reversed(line):
            if tok.kind not in {TokenKind.ANNOTATION, TokenKind.VERSION_ANNOTATION}:
                return tok
        return None

    def _layout_token(self, kind: TokenKind, span: SourceSpan) -> Token:
        return Token(kind, "", None, span)
