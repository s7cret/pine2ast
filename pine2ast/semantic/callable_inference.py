from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pine2ast.ast.base import ASTNode, Expression
from pine2ast.ast.nodes import (
    Block,
    CallExpr,
    ExpressionStatement,
    FunctionDeclaration,
    MethodDeclaration,
    Parameter,
    Program,
    Reassignment,
    TupleDeclaration,
    VarDeclaration,
)
from pine2ast.ast.walk import iter_nodes
from pine2ast.semantic.type_helpers import type_ref_name
from pine2ast.semantic.type_model import merge_type_names
from pine2ast.semantic.type_infer import callee_name


@dataclass(frozen=True, slots=True)
class CallableInferenceSummary:
    iterations: int
    parameter_updates: int
    variable_updates: int
    callable_updates: int
    parameter_types: dict[str, dict[str, str]]
    return_types: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "parameter_updates": self.parameter_updates,
            "variable_updates": self.variable_updates,
            "callable_updates": self.callable_updates,
            "parameter_types": {
                name: dict(values) for name, values in self.parameter_types.items()
            },
            "return_types": dict(self.return_types),
        }


class CallableInferenceEngine:
    """Infer unannotated Pine UDF signatures without runtime execution.

    Inference is monotonic: an ``unknown`` fact may become concrete and numeric
    ``int``/``float`` disagreements widen to ``float``.  A concrete incompatible
    fact is never silently replaced. The pass converges over call-site constraints,
    local declarations, and callable return expressions.
    """

    def __init__(self, analyzer: Any) -> None:
        self.analyzer = analyzer
        self.model = analyzer.model
        self.engine = analyzer.inference
        self.policy = analyzer.policy
        self.declarations: dict[str, FunctionDeclaration | MethodDeclaration] = {}
        self.calls: dict[str, list[CallExpr]] = {}
        self.parameter_updates = 0
        self.variable_updates = 0
        self.callable_updates = 0

    def run(self, program: Program) -> CallableInferenceSummary:
        for node in iter_nodes(program):
            if isinstance(node, (FunctionDeclaration, MethodDeclaration)):
                self.declarations[node.name] = node
            elif isinstance(node, CallExpr):
                name = self._user_call_name(node)
                if name is not None:
                    self.calls.setdefault(name, []).append(node)

        iterations = 0
        for iterations in range(1, 17):
            changed = False
            changed |= self._infer_parameters()
            changed |= self._infer_declarations(program)
            changed |= self._infer_callable_returns()
            self.engine.collect_program_facts(program, self.model)
            if not changed:
                break
        parameter_types: dict[str, dict[str, str]] = {}
        return_types: dict[str, str] = {}
        for name, declaration in self.declarations.items():
            parameter_types[name] = {}
            for parameter in declaration.parameters:
                symbol = self._symbol(parameter.name, parameter)
                parameter_types[name][parameter.name] = str(
                    getattr(symbol, "type", None) or "unknown"
                )
            symbol = self._symbol(name, declaration)
            return_types[name] = str(getattr(symbol, "type", None) or "unknown")
        return CallableInferenceSummary(
            iterations=iterations,
            parameter_updates=self.parameter_updates,
            variable_updates=self.variable_updates,
            callable_updates=self.callable_updates,
            parameter_types=parameter_types,
            return_types=return_types,
        )

    def _infer_parameters(self) -> bool:
        changed = False
        for name, declaration in self.declarations.items():
            calls = self.calls.get(name, ())
            for index, parameter in enumerate(declaration.parameters):
                explicit = type_ref_name(parameter.type_ref) if parameter.type_ref else None
                inferred = explicit or self._merge(
                    self.engine.infer_type(argument.value)
                    for call in calls
                    for argument in [self._argument_for(call, parameter, index)]
                    if argument is not None
                )
                qualifier = parameter.explicit_qualifier or self._merge_qualifiers(
                    self.engine.infer_qualifier(argument.value)
                    for call in calls
                    for argument in [self._argument_for(call, parameter, index)]
                    if argument is not None
                )
                symbol = self._symbol(parameter.name, parameter)
                if symbol is not None:
                    if inferred and inferred != "unknown":
                        changed |= self._update_type(symbol, inferred, "parameter")
                    if qualifier and symbol.qualifier != qualifier:
                        symbol.qualifier = qualifier
                        changed = True
                        self.parameter_updates += 1
        return changed

    def _infer_declarations(self, program: Program) -> bool:
        changed = False
        for node in iter_nodes(program):
            if isinstance(node, VarDeclaration):
                inferred = self.engine.infer_type(node.initializer)
                qualifier = self.engine.infer_qualifier(node.initializer)
                symbol = self._symbol(node.name, node)
                if symbol is not None and inferred != "unknown":
                    changed |= self._update_type(symbol, inferred, "variable")
                    if symbol.qualifier in {None, "series"} and qualifier:
                        symbol.qualifier = qualifier if qualifier != "const" else symbol.qualifier
                self.model.node_types[id(node.initializer)] = inferred
                self.model.node_qualifiers[id(node.initializer)] = qualifier
            elif isinstance(node, TupleDeclaration):
                # Tuple targets are already arity-checked by the stable analyzer.
                self.model.node_types[id(node.initializer)] = self.engine.infer_type(
                    node.initializer
                )
                self.model.node_qualifiers[id(node.initializer)] = self.engine.infer_qualifier(
                    node.initializer
                )
        return changed

    def _infer_callable_returns(self) -> bool:
        changed = False
        for declaration in self.declarations.values():
            inferred = self._return_type(declaration.body)
            if inferred == "unknown":
                continue
            symbol = self._symbol(declaration.name, declaration)
            if symbol is not None:
                changed |= self._update_type(symbol, inferred, "callable")
        return changed

    def _return_type(self, body: Block | Expression) -> str:
        if isinstance(body, Expression):
            return self.engine.infer_type(body)
        if not body.statements:
            return "void"
        last = body.statements[-1]
        if isinstance(last, VarDeclaration):
            return self.engine.infer_type(last.initializer)
        if isinstance(last, ExpressionStatement):
            return self.engine.infer_type(last.expression)
        if isinstance(last, Reassignment):
            return self.engine.infer_type(last.value)
        if isinstance(last, Expression):
            return self.engine.infer_type(last)
        return "void"

    @staticmethod
    def _argument_for(call: CallExpr, parameter: Parameter, index: int):
        named = next((item for item in call.arguments if item.name == parameter.name), None)
        if named is not None:
            return named
        positional = [item for item in call.arguments if item.name is None]
        return positional[index] if index < len(positional) else None

    def _user_call_name(self, call: CallExpr) -> str | None:
        name = callee_name(call.callee)
        if name in self.declarations:
            return name
        if "." in name:
            suffix = name.rsplit(".", 1)[-1]
            if suffix in self.declarations and isinstance(
                self.declarations[suffix], MethodDeclaration
            ):
                return suffix
        return None

    def _symbol(self, name: str, declaration: ASTNode):
        candidates = []
        current = self.model.symbols.get(name)
        if current is not None:
            candidates.append(current)
        candidates.extend(self.analyzer._symbol_history.get(name, ()))
        exact = [item for item in candidates if item.declared_at == declaration.span]
        if exact:
            return exact[-1]
        return current

    def _update_type(self, symbol, inferred: str, category: str) -> bool:
        merged = self._merge((symbol.type or "unknown", inferred))
        if merged == "unknown" or symbol.type == merged:
            return False
        if symbol.type not in {None, "unknown", "function", "method"} and merged != symbol.type:
            # Only numeric widening is permitted after a concrete fact exists.
            if {symbol.type, merged} != {"int", "float"}:
                return False
        symbol.type = merged
        if category == "parameter":
            self.parameter_updates += 1
        elif category == "callable":
            self.callable_updates += 1
        else:
            self.variable_updates += 1
        return True

    @staticmethod
    def _merge(values: Iterable[str | None]) -> str:
        normalized = [str(item) for item in values if item and item not in {"unknown", "any", "na"}]
        if not normalized:
            return "unknown"
        return merge_type_names(normalized)

    def _merge_qualifiers(self, values: Iterable[str | None]) -> str | None:
        names = [item for item in values if item in self.policy.qualifier_order]
        if not names:
            return None
        return max(names, key=self.policy.qualifier_rank)


__all__ = ["CallableInferenceEngine", "CallableInferenceSummary"]
