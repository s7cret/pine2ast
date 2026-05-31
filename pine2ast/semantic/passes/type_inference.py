from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class TypeInferencePass:
    """Type inference phase boundary.

    Type facts are currently produced during the stable statement/expression walk;
    this explicit boundary documents the phase without changing diagnostics.
    """

    name = "type_inference"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        return None
