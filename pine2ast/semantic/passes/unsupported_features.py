from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class UnsupportedFeatureExtractionPass:
    """Phase boundary for runtime-contract unsupported feature extraction.

    Existing parser/semantic diagnostics are intentionally kept stable. Downstream
    runtime-contract consumers use `pine2ast.runtime_contract.unsupported_features_for_program()`
    to obtain explicit markers without changing golden diagnostics.
    """

    name = "unsupported_feature_extraction"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        return None
