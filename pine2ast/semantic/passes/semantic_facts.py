from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.semantic.binder import SemanticFactBuilder

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class SemanticFactsPass:
    """Seal all resolved static semantics after validation passes complete."""

    name = "semantic_facts"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        self.analyzer.model.semantic_facts = SemanticFactBuilder(
            version_context=self.analyzer.version_context,
            catalog=self.analyzer.registry,
            policy=self.analyzer.policy,
            model=self.analyzer.model,
        ).build(program)


__all__ = ["SemanticFactsPass"]
