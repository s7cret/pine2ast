from __future__ import annotations

from pine2ast.parser.base import ParserResult
from pine2ast.parser.declarations import DeclarationsMixin
from pine2ast.parser.expressions import ExpressionsMixin
from pine2ast.parser.statements import StatementsMixin


class Parser(DeclarationsMixin, StatementsMixin, ExpressionsMixin):
    """Pine Script parser facade.

    Parser behavior is implemented by focused mixins in this package; this class
    intentionally preserves the historic public import path.
    """


__all__ = ["Parser", "ParserResult"]
