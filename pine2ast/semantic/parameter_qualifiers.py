"""Body constraints for typed v5/v6 function parameters, before body validation.

This computes declaration bounds, not callsite value qualifiers. Edges describe
which caller parameters supply a callee parameter. A worklist propagates the
simple requirement once per eligible parameter, including cyclic call graphs.
Normal SignatureResolver owns argument association and overload/type selection;
normal semantic validation still reports incompatible bodies, defaults and calls.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from pine2ast.ast.base import ASTNode, Expression
from pine2ast.ast.nodes import (
    Block,
    CallExpr,
    EnumDeclaration,
    ForInStructure,
    ForRangeStructure,
    FunctionDeclaration,
    Identifier,
    IfStructure,
    Parameter,
    Program,
    Reassignment,
    SwitchStructure,
    TypeDeclaration,
    VarDeclaration,
)
from pine2ast.ast.walk import iter_child_nodes
from pine2ast.semantic.control_values import structural_qualifier_sources
from pine2ast.semantic.inference import PineInferenceEngine, registry_entry_for_call
from pine2ast.semantic.signatures import SignatureResolver
from pine2ast.semantic.symbols import Symbol, SymbolKind
from pine2ast.semantic.type_helpers import type_ref_name
from pine2ast.semantic.type_infer import callee_name
from pine2ast.semantic.type_model import is_reference_type_name


def parameter_qualifier(parameter: Parameter, model: Any) -> str | None:
    """One effective-bound lookup for validation and consumer facts."""
    return parameter.explicit_qualifier or model.parameter_qualifiers.get(id(parameter))


class ParameterQualifierInference:
    def __init__(self, analyzer: Any, program: Program) -> None:
        self.analyzer = analyzer
        self.program = program
        self.declarations = {
            node.name: node for node in program.items if isinstance(node, FunctionDeclaration)
        }
        self.enums = {node.name for node in program.items if isinstance(node, EnumDeclaration)}
        self.udts = {node.name for node in program.items if isinstance(node, TypeDeclaration)}
        self.bounds: dict[int, str] = {}
        self.eligible: set[int] = set()
        self.edges: dict[int, set[int]] = defaultdict(set)
        self.required: set[int] = set()
        self.origins: dict[int, frozenset[int]] = {}
        self.resolver = SignatureResolver(version_context=analyzer.version_context)

    def run(self) -> dict[int, str]:
        if self.analyzer.version_context.pine_version < 5:
            return {}
        for declaration in self.declarations.values():
            for parameter in declaration.parameters:
                if parameter.type_ref is None:
                    continue
                dtype = type_ref_name(parameter.type_ref)
                self.bounds[id(parameter)] = parameter.explicit_qualifier or "series"
                if (
                    parameter.explicit_qualifier is None
                    and dtype not in self.udts
                    and not is_reference_type_name(dtype, enum_types=self.enums)
                ):
                    self.eligible.add(id(parameter))
        for declaration in self.declarations.values():
            symbols = dict(self.analyzer.model.symbols)
            origins: dict[str, frozenset[int]] = {}
            for parameter in declaration.parameters:
                symbols[parameter.name] = self._symbol(
                    parameter,
                    type_ref_name(parameter.type_ref) if parameter.type_ref else "unknown",
                    self.bounds.get(id(parameter), parameter.explicit_qualifier),
                )
                origins[parameter.name] = (
                    frozenset({id(parameter)}) if id(parameter) in self.eligible else frozenset()
                )
            self._walk(declaration.body, symbols, origins)

        pending = deque(sorted(self.required))
        visited: set[int] = set()
        while pending:
            parameter_id = pending.popleft()
            if parameter_id in visited:
                continue
            visited.add(parameter_id)
            if parameter_id in self.eligible:
                self.bounds[parameter_id] = "simple"
                pending.extend(sorted(self.edges.get(parameter_id, set()) - visited))
        return self.bounds

    @staticmethod
    def _symbol(node: Parameter | VarDeclaration, dtype: str, qualifier: str | None) -> Symbol:
        return Symbol(-1, node.name, SymbolKind.VARIABLE, node.span, dtype, qualifier, -1)

    def _engine(self, symbols: dict[str, Symbol]) -> PineInferenceEngine:
        return PineInferenceEngine(
            version_context=self.analyzer.version_context,
            symbols=symbols,
            registry=self.analyzer.registry,
            policy=self.analyzer.policy,
        )

    def _walk(
        self, node: ASTNode, symbols: dict[str, Symbol], origins: dict[str, frozenset[int]]
    ) -> None:
        if isinstance(node, Identifier):
            self.origins[id(node)] = origins.get(node.name, frozenset())
            return
        if isinstance(node, Block):
            local_symbols, local_origins = dict(symbols), dict(origins)
            for statement in node.statements:
                self._walk(statement, local_symbols, local_origins)
            return
        if isinstance(node, VarDeclaration):
            self._walk(node.initializer, symbols, origins)
            engine = self._engine(symbols)
            dtype = (
                type_ref_name(node.type_ref)
                if node.type_ref
                else engine.infer_type(node.initializer)
            )
            symbols[node.name] = self._symbol(
                node, dtype, node.explicit_qualifier or engine.infer_qualifier(node.initializer)
            )
            origins[node.name] = self.origins.get(id(node.initializer), frozenset())
            return
        if isinstance(node, ForRangeStructure):
            for expression in (node.start, node.end, node.step):
                if expression is not None:
                    self._walk(expression, symbols, origins)
            local_symbols, local_origins = dict(symbols), dict(origins)
            local_symbols[node.variable] = Symbol(
                -1, node.variable, SymbolKind.VARIABLE, node.span, "int", "series", -1
            )
            local_origins[node.variable] = frozenset()
            self._walk(node.body, local_symbols, local_origins)
            return
        if isinstance(node, ForInStructure):
            self._walk(node.iterable, symbols, origins)
            local_symbols, local_origins = dict(symbols), dict(origins)
            for name in node.target.names:
                local_symbols[name] = Symbol(
                    -1, name, SymbolKind.VARIABLE, node.span, "unknown", "series", -1
                )
                local_origins[name] = frozenset()
            self._walk(node.body, local_symbols, local_origins)
            return
        for child in iter_child_nodes(node):
            self._walk(child, symbols, origins)
        if isinstance(node, Reassignment) and isinstance(node.target, Identifier):
            origins[node.target.name] = origins.get(
                node.target.name, frozenset()
            ) | self.origins.get(id(node.value), frozenset())
        if isinstance(node, Expression):
            children: list[ASTNode]
            if isinstance(node, (IfStructure, SwitchStructure)):
                children = list(structural_qualifier_sources(node))
            else:
                children = list(iter_child_nodes(node))
            self.origins[id(node)] = frozenset().union(
                *(self.origins.get(id(child), frozenset()) for child in children)
            )
        # Argument wrapper nodes carry their expression's dependency evidence.
        elif not isinstance(node, (FunctionDeclaration, TypeDeclaration, EnumDeclaration)):
            self.origins[id(node)] = frozenset().union(
                *(self.origins.get(id(child), frozenset()) for child in iter_child_nodes(node))
            )
        if isinstance(node, CallExpr):
            self._call(node, symbols)

    def _call(self, call: CallExpr, symbols: dict[str, Symbol]) -> None:
        name = callee_name(call.callee)
        entry: dict[str, Any] | None
        declaration = self.declarations.get(name)
        if (
            declaration is not None
            and getattr(symbols.get(name), "kind", None) is not SymbolKind.FUNCTION
        ):
            return
        if declaration is not None:
            entry = {
                "symbol_id": "user:function:" + name,
                "parameters": [
                    {
                        "name": p.name,
                        "type": type_ref_name(p.type_ref) if p.type_ref else "any",
                        "required": p.default_value is None,
                    }
                    for p in declaration.parameters
                ],
            }
        else:
            name, entry = registry_entry_for_call(call.callee, self.analyzer.registry)
        if not entry:
            return
        engine = self._engine(symbols)
        resolution = self.resolver.resolve_builtin(
            name,
            entry,
            call.arguments,
            call.span,
            validate_types=True,
            infer_arg_type=lambda argument: engine.infer_type(argument.value),
        )
        if not resolution.ok:
            return
        parameters = {p.name: p for p in declaration.parameters} if declaration else {}
        for argument in resolution.resolved_arguments:
            if argument.argument is None or argument.parameter is None:
                continue
            dependencies = self.origins.get(id(argument.argument.value), frozenset())
            parameter = parameters.get(str(argument.parameter.get("name")))
            if parameter is not None:
                if parameter.explicit_qualifier in {"simple", "input", "const"}:
                    self.required.update(dependencies)
                elif id(parameter) in self.eligible:
                    self.edges[id(parameter)].update(dependencies)
            elif argument.parameter.get("qualifier_max") in {"simple", "input", "const"}:
                self.required.update(dependencies)


def infer_parameter_qualifiers(analyzer: Any, program: Program) -> dict[int, str]:
    return ParameterQualifierInference(analyzer, program).run()
