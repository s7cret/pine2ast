"""Pre-validation simple/series results of typed v5/v6 functions.

Declaration bounds are already fixed. Result facts may narrow from series to
simple once, so chains terminate after at most one change per function. This
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
from pine2ast.semantic.type_helpers import type_ref_name


class CallableResultQualifierInference:
    def __init__(self, analyzer: Any, program: Program) -> None:
        self.analyzer = analyzer
        self.declarations = {
            n.name: n
            for n in program.items
            if isinstance(n, FunctionDeclaration)
            and n.parameters
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
        remaining = set(self.declarations)
        while remaining:
            changed: set[str] = set()
            for name in sorted(remaining):
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
                # Const/input results need an exported-result floor preserved by
                # library projection; they retain the prior conservative result.
                if result == "simple":
                    symbols[name].qualifier = result
                    result_type = self.types.get(id(returned), "unknown")
                    if result_type not in {"unknown", "any", "function", "method"}:
                        symbols[name].type = result_type
                    changed.add(name)
            if not changed:
                break
            remaining -= changed
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
            SemanticModel(symbols=symbols, node_qualifiers=self.values, node_types=self.types)
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
            if dtype in self.udts or node.name in self.analyzer._reassigned_names:
                qualifier = "series"
            symbols[node.name] = Symbol(
                -1, node.name, SymbolKind.VARIABLE, node.span, dtype, qualifier, -1
            )
            return
        if isinstance(node, (ForRangeStructure, ForInStructure)):
            local = dict(symbols)
            names = [node.variable] if isinstance(node, ForRangeStructure) else node.target.names
            for name in names:
                local[name] = Symbol(-1, name, SymbolKind.VARIABLE, node.span, "int", "series", -1)
            for child in iter_child_nodes(node):
                self._walk(child, local if child is node.body else symbols)
        else:
            for child in iter_child_nodes(node):
                self._walk(child, symbols)
        if isinstance(node, Expression):
            engine = self._engine(symbols)
            self.values[id(node)] = engine.infer_qualifier(node)
            self.types[id(node)] = engine.infer_type(node)


def infer_callable_result_qualifiers(analyzer: Any, program: Program) -> None:
    CallableResultQualifierInference(analyzer, program).run()
