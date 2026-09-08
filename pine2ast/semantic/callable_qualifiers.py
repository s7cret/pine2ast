"""Pre-validation result qualifiers of typed v5/v6 functions.

Declaration bounds are already fixed. Result facts may descend the four-level
qualifier lattice at most three times, so dependency cycles are bounded. This
does not specialize untyped functions by callsite or weaken mutable/reference
values. The shared expression inference owner evaluates all expression rules.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pine2ast.ast.base import ASTNode, Expression
from pine2ast.ast.nodes import (
    Block,
    ForInStructure,
    ForRangeStructure,
    FunctionDeclaration,
    Program,
    TypeDeclaration,
    VarDeclaration,
)
from pine2ast.ast.walk import iter_child_nodes
from pine2ast.semantic.inference import PineInferenceEngine
from pine2ast.semantic.model import SemanticModel
from pine2ast.semantic.parameter_qualifiers import parameter_qualifier
from pine2ast.semantic.symbols import Symbol, SymbolKind
from pine2ast.semantic.type_helpers import for_in_target_types, type_ref_name
from pine2ast.semantic.type_model import QUALIFIER_ORDER


class CallableResultQualifierInference:
    def __init__(self, analyzer: Any, program: Program) -> None:
        self.analyzer = analyzer
        self.declarations = {
            n.name: n
            for n in program.items
            if isinstance(n, FunctionDeclaration)
            and all(p.type_ref is not None for p in n.parameters)
        }
        self.udts = {n.name for n in program.items if isinstance(n, TypeDeclaration)}
        self.values: dict[int, str] = {}
        self.types: dict[int, str] = {}

    def run(self) -> None:
        if self.analyzer.version_context.pine_version < 5:
            return
        # Copies prevent preliminary values from escaping into the real model.
        symbols = {name: replace(symbol) for name, symbol in self.analyzer.model.symbols.items()}
        while True:
            changed: set[str] = set()
            for name in sorted(self.declarations):
                node = self.declarations[name]
                local = dict(symbols)
                self.values = {}
                self.types = {}
                for p in node.parameters:
                    dtype = type_ref_name(p.type_ref)
                    qualifier = parameter_qualifier(p, self.analyzer.model) or "series"
                    if dtype in self.udts:
                        qualifier = "series"
                    local[p.name] = Symbol(
                        -1, p.name, SymbolKind.VARIABLE, p.span, dtype, qualifier, -1
                    )
                self._walk(node.body, local)
                returned = self.analyzer._body_return_expr(node.body)
                result = self.values.get(id(returned), "series")
                if node.is_exported or id(node) in getattr(
                    self.analyzer, "_projected_exported_functions", ()
                ):
                    result = max(result, "simple", key=QUALIFIER_ORDER.__getitem__)
                current = symbols[name].qualifier or "series"
                if QUALIFIER_ORDER[result] < QUALIFIER_ORDER[current]:
                    symbols[name].qualifier = result
                    result_type = self.types.get(id(returned), "unknown")
                    if result_type not in {"unknown", "any", "function", "method"}:
                        symbols[name].type = result_type
                    changed.add(name)
            if not changed:
                break
        for name in self.declarations:
            self.analyzer.model.symbols[name].qualifier = symbols[name].qualifier or "series"
            self.analyzer.model.symbols[name].type = symbols[name].type

    def _engine(self, symbols: dict[str, Symbol]) -> PineInferenceEngine:
        engine = PineInferenceEngine(
            version_context=self.analyzer.version_context,
            symbols=symbols,
            registry=self.analyzer.registry,
            policy=self.analyzer.policy,
        )
        engine.bind_model(
            SemanticModel(
                symbols=symbols,
                node_qualifiers=self.values,
                node_types=self.types,
                callable_context=self.analyzer.model.callable_context,
                method_candidates=self.analyzer.model.method_candidates,
            )
        )
        return engine

    def _walk(self, node: ASTNode, symbols: dict[str, Symbol]) -> None:
        if isinstance(node, Block):
            local = dict(symbols)
            for statement in node.statements:
                self._walk(statement, local)
            return
        if isinstance(node, VarDeclaration):
            self._walk(node.initializer, symbols)
            engine = self._engine(symbols)
            dtype = (
                type_ref_name(node.type_ref)
                if node.type_ref
                else engine.infer_type(node.initializer)
            )
            qualifier = node.explicit_qualifier or engine.infer_qualifier(node.initializer)
            if dtype in self.udts or self._is_reassigned(node):
                qualifier = "series"
            symbols[node.name] = Symbol(
                -1, node.name, SymbolKind.VARIABLE, node.span, dtype, qualifier, -1
            )
            return
        if isinstance(node, (ForRangeStructure, ForInStructure)):
            local = dict(symbols)
            names = [node.variable] if isinstance(node, ForRangeStructure) else node.target.names
            types = (
                ["int"]
                if isinstance(node, ForRangeStructure)
                else for_in_target_types(
                    self._engine(symbols).infer_type(node.iterable), len(names)
                )
            )
            for name, dtype in zip(names, types):
                local[name] = Symbol(-1, name, SymbolKind.VARIABLE, node.span, dtype, "series", -1)
            for child in iter_child_nodes(node):
                self._walk(child, local if child is node.body else symbols)
        else:
            for child in iter_child_nodes(node):
                self._walk(child, symbols)
        if isinstance(node, Expression):
            engine = self._engine(symbols)
            self.values[id(node)] = engine.infer_qualifier(node)
            self.types[id(node)] = engine.infer_type(node)

    def _is_reassigned(self, node: VarDeclaration) -> bool:
        return node.name in self.analyzer._reassigned_names


def infer_callable_result_qualifiers(analyzer: Any, program: Program) -> None:
    if analyzer.version_context.pine_version >= 5:
        from pine2ast.semantic.callable_context import CallableContext

        analyzer.model.callable_context = CallableContext(analyzer, program)
        analyzer.inference.bind_model(analyzer.model)
    CallableResultQualifierInference(analyzer, program).run()
    if analyzer.model.callable_context is not None:
        analyzer.model.callable_context.publish_fixed_results()
