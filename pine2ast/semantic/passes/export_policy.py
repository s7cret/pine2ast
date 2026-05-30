from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.ast.base import ASTNode
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes

if TYPE_CHECKING:
    from pine2ast.semantic.analyzer import SemanticAnalyzer


def validate_export_policy(analyzer: SemanticAnalyzer, node: ASTNode) -> None:
    """Validate that exported declarations only appear in library scripts."""
    if getattr(node, "is_exported", False) and analyzer._script_type != "library":
        analyzer._diag(
            Severity.ERROR,
            codes.EXPORT_NOT_LIBRARY,
            "export declarations are allowed only in library() scripts.",
            node.span,
        )
