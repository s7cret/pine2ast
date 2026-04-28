from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class StrategyContextValidationPass:
    """Strategy-only namespace/state validation phase boundary."""

    name = "strategy_context_validation"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        return None
