from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.ast.nodes import BreakStatement, ContinueStatement
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes

if TYPE_CHECKING:
    from pine2ast.semantic.analyzer import SemanticAnalyzer


def validate_loop_control_statement(
    analyzer: SemanticAnalyzer, node: BreakStatement | ContinueStatement
) -> None:
    """Validate that loop-control statements appear inside a loop body."""
    if analyzer.loop_depth > 0:
        return
    keyword = "break" if isinstance(node, BreakStatement) else "continue"
    analyzer._diag(
        Severity.ERROR,
        codes.BREAK_CONTINUE_OUTSIDE_LOOP,
        f"{keyword} is allowed only inside loops.",
        node.span,
    )
