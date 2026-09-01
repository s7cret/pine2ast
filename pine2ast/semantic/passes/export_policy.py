from __future__ import annotations

from typing import Protocol

from pine2ast.ast.base import ASTNode
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan


class ExportPolicyAnalyzer(Protocol):
    """Minimal analyzer surface needed by the export-policy pass."""

    _script_type: str | None

    def _diag(
        self,
        severity: Severity,
        code: str,
        message: str,
        span: SourceSpan,
    ) -> None: ...


def validate_export_policy(analyzer: ExportPolicyAnalyzer, node: ASTNode) -> None:
    """Validate that exported declarations only appear in library scripts."""
    if getattr(node, "is_exported", False) and analyzer._script_type != "library":
        analyzer._diag(
            Severity.ERROR,
            codes.EXPORT_NOT_LIBRARY,
            "export declarations are allowed only in library() scripts.",
            node.span,
        )
