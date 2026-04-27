from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class ScopeSymbolPass:
    """Visit statements and maintain scopes/symbols using the legacy stable walker."""

    name = "scope_symbols"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        for item in program.items:
            self.analyzer._visit_statement(item)
