from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.ast.nodes import CallExpr
from pine2ast.ast.walk import iter_nodes
from pine2ast.semantic.type_infer import callee_name

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class CollectionValidationPass:
    """Validate array/matrix/map function and method signatures.

    Release 4.0 moves generic collection checks behind an explicit pass boundary so
    the frontend can continue extracting analyzer internals into reusable passes
    without changing the AST contract.
    """

    name = "collection_validation"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        for node in iter_nodes(program):
            if isinstance(node, CallExpr):
                self.analyzer._validate_collection_mutation_call(callee_name(node.callee), node)
