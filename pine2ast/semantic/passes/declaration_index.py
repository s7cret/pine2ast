from __future__ import annotations

from typing import TYPE_CHECKING

from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.semantic.parameter_qualifiers import infer_parameter_qualifiers
from pine2ast.semantic.callable_qualifiers import infer_callable_result_qualifiers

if TYPE_CHECKING:
    from pine2ast.ast.nodes import Program
    from pine2ast.semantic.analyzer import SemanticAnalyzer


class DeclarationIndexPass:
    """Index builtins and global declarations before body validation."""

    name = "declaration_index"

    def __init__(self, analyzer: SemanticAnalyzer) -> None:
        self.analyzer = analyzer

    def run(self, program: Program) -> None:
        self.analyzer._register_builtins()
        if self.analyzer.version_context.pine_version >= 5:
            from pine2ast.ast.nodes import MethodDeclaration
            from pine2ast.semantic.function_candidates import FunctionCandidates

            self.analyzer.model.function_candidates = FunctionCandidates(self.analyzer, program)
            self.analyzer.inference.bind_model(self.analyzer.model)
            from pine2ast.semantic.method_candidates import MethodCandidates

            if any(isinstance(node, MethodDeclaration) for node in program.items):
                owner = MethodCandidates(self.analyzer, program)
                self.analyzer.model.method_candidates = owner
                self.analyzer.inference.bind_model(self.analyzer.model)
                for candidate in owner.duplicates:
                    self.analyzer._diag(
                        Severity.ERROR,
                        codes.REDECLARATION,
                        "Method overload repeats the same required qualified parameter types.",
                        candidate.declaration.span,
                    )
        if program.declaration is None:
            self.analyzer._diag(
                Severity.ERROR,
                codes.MISSING_DECLARATION,
                "Program has no indicator/strategy/library declaration statement.",
                program.span,
            )
        else:
            self.analyzer._analyze_declaration_statement(program.declaration)
        self.analyzer._predeclare_globals(program.items)
        self.analyzer.model.parameter_qualifiers = infer_parameter_qualifiers(
            self.analyzer, program
        )
        owner = self.analyzer.model.function_candidates
        if owner is not None:
            for candidate in owner.duplicate_candidates():
                self.analyzer._diag(Severity.ERROR, codes.REDECLARATION,
                    "Function overload repeats or cannot distinguish required qualified parameter types.",
                    candidate.declaration.span)
        infer_callable_result_qualifiers(self.analyzer, program)
