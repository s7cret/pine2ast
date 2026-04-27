from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class DeclarationIndexPass:
    """Index builtins and global declarations before body validation."""

    name = "declaration_index"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        self.analyzer._register_builtins()
        if program.declaration is None:
            self.analyzer._diag(
                Severity.ERROR,
                codes.MISSING_DECLARATION,
                "Program has no indicator/strategy/library declaration statement.",
                program.span,
            )
        else:
            self.analyzer._analyze_declaration_statement(program.declaration)
        self.analyzer._predeclare_globals(program.items)
