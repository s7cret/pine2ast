from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.ast.nodes import DeclarationStatement
from pine2ast.ast.visitors import walk
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class DeclarationCardinalityPass:
    """Validate the single declaration-statement contract after semantic walking."""

    name = "declaration_cardinality"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        seen_decls = 1 if program.declaration else 0
        seen_decls += sum(
            1
            for node in walk(program)
            if isinstance(node, DeclarationStatement) and node is not program.declaration
        )
        if seen_decls > 1:
            self.analyzer._diag(
                Severity.ERROR,
                codes.MULTIPLE_DECLARATIONS,
                "Program has more than one declaration statement.",
                program.span,
            )
