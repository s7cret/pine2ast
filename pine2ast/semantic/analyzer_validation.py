from __future__ import annotations

from pine2ast.semantic.analyzer_validation_builtins import AnalyzerBuiltinValidationMixin
from pine2ast.semantic.analyzer_validation_calls import AnalyzerCallValidationMixin
from pine2ast.semantic.analyzer_validation_collections import AnalyzerCollectionValidationMixin
from pine2ast.semantic.analyzer_validation_members import AnalyzerMemberValidationMixin
from pine2ast.semantic.analyzer_validation_types import AnalyzerTypeValidationMixin


class AnalyzerValidationMixin(
    AnalyzerBuiltinValidationMixin,
    AnalyzerTypeValidationMixin,
    AnalyzerCollectionValidationMixin,
    AnalyzerCallValidationMixin,
    AnalyzerMemberValidationMixin,
):
    """Compatibility facade for focused semantic validation mixins."""


__all__ = ["AnalyzerValidationMixin"]
