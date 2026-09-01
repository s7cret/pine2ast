from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.semantic.callable_inference import CallableInferenceEngine

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class CallableInferencePass:
    name = "callable_inference"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        self.analyzer.model.callable_inference = CallableInferenceEngine(self.analyzer).run(program)


__all__ = ["CallableInferencePass"]
