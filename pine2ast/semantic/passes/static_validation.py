from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.semantic.static_validation import validate_static_semantics

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class StaticValidationPass:
    """Release 4.0 frontend semantic rules extracted from the legacy analyzer."""

    name = "static_validation"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        for issue in validate_static_semantics(
            program,
            semantic_model=self.analyzer.model,
            profile=self.analyzer.version_context,
        ):
            self.analyzer._diag(issue.severity, issue.code, issue.message, issue.span)
