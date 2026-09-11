"""Bounded call-specific facts using the shared signature and body-inference owners."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from types import MappingProxyType
from typing import Any, Mapping

from pine2ast.ast.base import ASTNode
from pine2ast.ast.nodes import (
    CallExpr,
    FunctionDeclaration,
    Identifier,
    Program,
    TypeDeclaration,
    VarDeclaration,
)
from pine2ast.semantic.callable_qualifiers import CallableResultQualifierInference
from pine2ast.semantic.inference import PineInferenceEngine
from pine2ast.semantic.model import SemanticModel
from pine2ast.semantic.node_index import NodeIndex
from pine2ast.semantic.parameter_qualifiers import parameter_qualifier
from pine2ast.semantic.signatures import SignatureResolver
from pine2ast.semantic.symbols import Symbol, SymbolKind
from pine2ast.semantic.type_helpers import type_ref_name
from pine2ast.semantic.type_model import QUALIFIER_ORDER, is_reference_type_name

MAX_DEPTH = 64
MAX_ROOT_WORK = 4096
MAX_BUILDER_WORK = 262144
MAX_CACHE = 4096


class InferenceLimit(Exception):
    pass


@dataclass(frozen=True)
class QualifiedArgument:
    parameter_id: str
    parameter_index: int
    parameter_name: str
    argument_id: str | None
    type_name: str
    qualifier: str


@dataclass(frozen=True)
class CallContextProof:
    declaration_id: str
    symbol_id: str
    call_id: str
    type_name: str
    qualifier: str
    arguments: tuple[QualifiedArgument, ...]
    node_types: Mapping[int, str]
    node_qualifiers: Mapping[int, str]
    symbols: Mapping[str, tuple[Any, ...]]

    @property
    def context_key(self) -> tuple[Any, ...]:
        return (
            self.declaration_id,
            tuple(
                (a.parameter_id, a.parameter_index, a.type_name, a.qualifier)
                for a in self.arguments
            ),
        )


class ContextBodyWalk(CallableResultQualifierInference):
    """Reuse all existing body/control rules; only inject context and work limits."""

    def __init__(self, owner: CallableContext, *, global_scope: bool = False) -> None:
        super().__init__(owner.analyzer, owner.program)
        self.owner = owner
        self.global_scope = global_scope

    def _walk(self, node: ASTNode, symbols: dict[str, Symbol]) -> None:
        self.owner.charge()
        super()._walk(node, symbols)

    def _engine(self, symbols: dict[str, Symbol]) -> PineInferenceEngine:
        return self.owner.engine(symbols, self.types, self.values)

    def _is_reassigned(self, node: VarDeclaration) -> bool:
        if self.global_scope:
            return id(node) in self.owner.reassigned_globals
        return super()._is_reassigned(node)


class CallableContext:
    def __init__(self, analyzer: Any, program: Program) -> None:
        self.analyzer = analyzer
        self.program = program
        self.index = NodeIndex.build(program)
        self.reassigned_globals = self._global_reassignment_ids(program)
        self.declarations = {n.name: n for n in program.items if isinstance(n, FunctionDeclaration)}
        self.globals_before: dict[int, tuple[VarDeclaration, ...]] = {}
        visible: list[VarDeclaration] = []
        for node in program.items:
            if isinstance(node, (FunctionDeclaration, VarDeclaration)):
                self.globals_before[id(node)] = tuple(visible)
            if isinstance(node, VarDeclaration):
                visible.append(node)
        self.resolver = SignatureResolver(version_context=analyzer.version_context)
        self.active: list[int] = []
        self.root_spent: int | None = None
        self.spent = 0
        self.cache: dict[tuple[Any, ...], CallContextProof] = {}

    @staticmethod
    def _global_reassignment_ids(program: Program) -> frozenset[int]:
        """Use the same source-identity classification as ordinary validation."""
        from pine2ast.semantic.mutation_identity import reassigned_declarations

        global_ids = {id(n) for n in program.items if isinstance(n, VarDeclaration)}
        return reassigned_declarations(program) & global_ids

    def charge(self) -> None:
        if self.root_spent is None:
            return
        if self.root_spent >= MAX_ROOT_WORK or self.spent >= MAX_BUILDER_WORK:
            raise InferenceLimit
        self.root_spent += 1
        self.spent += 1

    def publish_fixed_results(self) -> None:
        # Typed declaration bounds are fixed independently of call arguments.
        # Untyped declarations intentionally retain their aggregate legacy fact.
        caller = self.engine(self.analyzer.model.symbols)
        for node in self.index.nodes:
            if not isinstance(node, CallExpr) or not isinstance(node.callee, Identifier):
                continue
            declaration = self.declarations.get(node.callee.name)
            if declaration is None or any(p.type_ref is None for p in declaration.parameters):
                continue
            proof = self.infer_call(node, caller)
            if proof is None:
                continue
            symbol = self.analyzer.model.symbols[declaration.name]
            if QUALIFIER_ORDER[proof.qualifier] < QUALIFIER_ORDER[symbol.qualifier or "series"]:
                symbol.qualifier = proof.qualifier
                if proof.type_name not in {"unknown", "any", "function", "method"}:
                    symbol.type = proof.type_name

    def engine(
        self,
        symbols: Mapping[str, Symbol],
        types: Mapping[int, str] | None = None,
        qualifiers: Mapping[int, str] | None = None,
    ) -> PineInferenceEngine:
        engine = PineInferenceEngine(
            version_context=self.analyzer.version_context,
            registry=self.analyzer.registry,
            policy=self.analyzer.policy,
        )
        engine.bind_model(
            SemanticModel(
                symbols=dict(symbols),
                node_types=dict(types or {}),
                node_qualifiers=dict(qualifiers or {}),
                callable_context=self,
                method_candidates=self.analyzer.model.method_candidates,
            )
        )
        return engine

    def globals_for(self, declaration: FunctionDeclaration | VarDeclaration) -> dict[str, Symbol]:
        # Values and locals from the model's flattened view are never imported.
        symbols = {
            name: replace(s)
            for name, s in self.analyzer.model.symbols.items()
            if s.kind is not SymbolKind.VARIABLE
        }
        walker = ContextBodyWalk(self, global_scope=True)
        for node in self.globals_before[id(declaration)]:
            walker._walk(node, symbols)
            if node.mode is not None:
                symbols[node.name].qualifier = "series"
        return symbols

    def from_parent(self, call: CallExpr, parent: CallContextProof) -> CallContextProof | None:
        return self.infer_call(
            call,
            self.engine(
                {name: Symbol(*snapshot) for name, snapshot in parent.symbols.items()},
                parent.node_types,
                parent.node_qualifiers,
            ),
        )

    def infer_call(self, call: CallExpr, caller: PineInferenceEngine) -> CallContextProof | None:
        if not isinstance(call.callee, Identifier):
            return None
        declaration = self.declarations.get(call.callee.name)
        symbol = (caller.symbols or {}).get(call.callee.name)
        if (
            declaration is None
            or symbol is None
            or symbol.kind is not SymbolKind.FUNCTION
            or symbol.declared_at != declaration.span
        ):
            return None
        root = self.root_spent is None
        if root:
            self.root_spent = 0
        try:
            return self._infer(call, declaration, caller)
        except InferenceLimit:
            return self._unknown(call, declaration)
        finally:
            if root:
                self.root_spent = None

    def _unknown(self, call: CallExpr, declaration: FunctionDeclaration) -> CallContextProof:
        identity = self.index.id_for(declaration)
        # Fixed typed declaration bounds are already established by the existing
        # non-contextual owner. Exhausting optional specialization cannot erase
        # those facts; untyped declarations have no such safe fallback.
        symbol = self.analyzer.model.symbols.get(declaration.name)
        fixed = symbol is not None and all(p.type_ref is not None for p in declaration.parameters)
        return CallContextProof(
            identity,
            f"user:function:{declaration.name}:{identity}",
            self.index.id_for(call),
            (symbol.type or "unknown") if fixed else "unknown",
            (symbol.qualifier or "series") if fixed else "series",
            (),
            MappingProxyType({}),
            MappingProxyType({}),
            MappingProxyType({}),
        )

    def _infer(
        self, call: CallExpr, declaration: FunctionDeclaration, caller: PineInferenceEngine
    ) -> CallContextProof:
        self.charge()
        if id(declaration) in self.active or len(self.active) >= MAX_DEPTH:
            return self._unknown(call, declaration)
        identity = self.index.id_for(declaration)
        symbol_id = f"user:function:{declaration.name}:{identity}"
        entry = dict(
            symbol_id=symbol_id,
            overload_id=symbol_id + "#signature",
            parameters=[
                dict(
                    name=p.name,
                    type=type_ref_name(p.type_ref) if p.type_ref else "any",
                    qualifier_max=parameter_qualifier(p, self.analyzer.model) or "series",
                    required=p.default_value is None,
                )
                for p in declaration.parameters
            ],
        )
        resolved = self.resolver.resolve_builtin(
            declaration.name,
            entry,
            call.arguments,
            call.span,
            validate_types=True,
            validate_qualifiers=True,
            infer_arg_type=lambda a: caller.infer_type(a.value),
            infer_arg_qualifier=lambda a: caller.infer_qualifier(a.value),
        )
        if not resolved.ok:
            return self._unknown(call, declaration)
        self.active.append(id(declaration))
        try:
            globals_ = self.globals_for(declaration)
            arguments: dict[int, QualifiedArgument] = {}
            for arg in resolved.resolved_arguments:
                self.charge()
                if (
                    arg.argument is None
                    or arg.parameter_index is None
                    or arg.parameter_index in arguments
                ):
                    return self._unknown(call, declaration)
                p = declaration.parameters[arg.parameter_index]
                arguments[arg.parameter_index] = QualifiedArgument(
                    self.index.id_for(p),
                    arg.parameter_index,
                    p.name,
                    self.index.id_for(arg.argument),
                    arg.actual_type or "unknown",
                    arg.actual_qualifier or "series",
                )
            default_engine = self.engine(globals_)
            for i, p in enumerate(declaration.parameters):
                if i not in arguments:
                    self.charge()
                    if p.default_value is None:
                        return self._unknown(call, declaration)
                    arguments[i] = QualifiedArgument(
                        self.index.id_for(p),
                        i,
                        p.name,
                        None,
                        default_engine.infer_type(p.default_value),
                        default_engine.infer_qualifier(p.default_value),
                    )
            ordered = tuple(arguments[i] for i in range(len(declaration.parameters)))
            key = (
                identity,
                tuple(
                    (a.parameter_id, a.parameter_index, a.type_name, a.qualifier) for a in ordered
                ),
            )
            if key in self.cache:
                return replace(self.cache[key], call_id=self.index.id_for(call), arguments=ordered)
            if len(self.cache) >= MAX_CACHE:
                return self._unknown(call, declaration)
            local = dict(globals_)
            for p, a in zip(declaration.parameters, ordered):
                dtype = type_ref_name(p.type_ref) if p.type_ref else a.type_name
                qualifier = (
                    (parameter_qualifier(p, self.analyzer.model) or "series")
                    if p.type_ref
                    else (p.explicit_qualifier or a.qualifier)
                )
                if is_reference_type_name(dtype) or dtype in {
                    n.name for n in self.program.items if isinstance(n, TypeDeclaration)
                }:
                    qualifier = "series"
                local[p.name] = Symbol(
                    -1, p.name, SymbolKind.VARIABLE, p.span, dtype, qualifier, -1
                )
            walker = ContextBodyWalk(self)
            walker._walk(declaration.body, local)
            returned = self.analyzer._body_return_expr(declaration.body)
            q = walker.values.get(id(returned), "series")
            dtype = walker.types.get(id(returned), "unknown")
            if (
                declaration.is_exported
                or id(declaration) in self.analyzer._projected_exported_functions
            ):
                q = max(q, "simple", key=QUALIFIER_ORDER.__getitem__)
            if is_reference_type_name(dtype):
                q = "series"
            proof = CallContextProof(
                identity,
                symbol_id,
                self.index.id_for(call),
                dtype,
                q,
                ordered,
                MappingProxyType(dict(walker.types)),
                MappingProxyType(dict(walker.values)),
                MappingProxyType(
                    {
                        name: tuple(getattr(s, f.name) for f in fields(Symbol))
                        for name, s in local.items()
                    }
                ),
            )
            self.cache[key] = proof
            return proof
        finally:
            self.active.pop()
