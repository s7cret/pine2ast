"""Declaration-bound user-function families; SignatureResolver owns type matching.

Ordinary functions retain their original names and node IDs in the AST. Only
semantic symbol storage is per declaration; no source rewrite or runtime dispatch
is involved. All candidates share bounded inference work within one analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pine2ast.ast.nodes import CallExpr, FunctionDeclaration, Identifier, Program
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.node_index import NodeIndex
from pine2ast.semantic.parameter_qualifiers import parameter_qualifier
from pine2ast.semantic.signatures import SignatureIssue, SignatureResolution, SignatureResolver
from pine2ast.semantic.type_helpers import type_ref_name
from pine2ast.semantic.symbols import SymbolKind

MAX_FUNCTION_WORK = 262144
MAX_FUNCTION_CACHE = 4096


@dataclass(frozen=True, slots=True)
class FunctionCandidate:
    declaration: FunctionDeclaration
    declaration_id: str
    symbol_key: str

    @property
    def symbol_id(self) -> str:
        return f"user:function:{self.declaration.name}:{self.declaration_id}"


@dataclass(frozen=True, slots=True)
class FunctionSelection:
    resolution: SignatureResolution
    candidate: FunctionCandidate | None

    @property
    def user_selected(self) -> bool:
        return self.resolution.ok and self.candidate is not None


class FunctionCandidates:
    def __init__(self, analyzer: Any, program: Program) -> None:
        self.analyzer = analyzer
        self.index = NodeIndex.build(program)
        self.visibility = getattr(analyzer, "_method_visibility", None)
        groups: dict[str, list[FunctionDeclaration]] = {}
        for node in program.items:
            if isinstance(node, FunctionDeclaration):
                groups.setdefault(node.name, []).append(node)
        candidates = []
        for name, nodes in groups.items():
            for node in nodes:
                identity = self.index.id_for(node)
                key = name if len(nodes) == 1 else f"{name}#{identity}"
                candidates.append(FunctionCandidate(node, identity, key))
        self.candidates = tuple(candidates)
        self.by_node = MappingProxyType({id(c.declaration): c for c in candidates})
        self.by_symbol = MappingProxyType({c.symbol_id: c for c in candidates})
        self.by_name = MappingProxyType(
            {
                name: tuple(self.by_node[id(node)] for node in nodes)
                for name, nodes in groups.items()
            }
        )
        self.resolver = SignatureResolver(version_context=analyzer.version_context)
        self.spent = 0
        self.active: set[int] = set()
        self.cache: dict[tuple, FunctionSelection] = {}

    def duplicate_candidates(self) -> tuple[FunctionCandidate, ...]:
        """Optional/name/return-only differences do not create valid overloads."""
        duplicates = []
        for family in self.by_name.values():
            seen = {}
            untyped = set()
            for candidate in family:
                node = candidate.declaration
                origin = self.visibility.origin(node) if self.visibility is not None else None
                required = tuple(p for p in node.parameters if p.default_value is None)
                shape = tuple(
                    (
                        type_ref_name(p.type_ref) if p.type_ref else "any",
                        parameter_qualifier(p, self.analyzer.model) or "series",
                    )
                    for p in required
                )
                bucket = (origin, len(required))
                previous = seen.setdefault(bucket, set())
                has_any = any(t == "any" for t, _ in shape)
                # Optional/name/return changes cannot distinguish declarations;
                # equal-arity untyped definitions can match the same call. Use
                # indexed shapes rather than an O(n**2) pairwise family scan.
                if previous and (shape in previous or has_any or bucket in untyped):
                    duplicates.append(candidate)
                previous.add(shape)
                if has_any:
                    untyped.add(bucket)
        return tuple(duplicates)

    def entry(self, candidate: FunctionCandidate, *, symbols=None, qualifiers: bool = True) -> dict:
        node = candidate.declaration
        symbol = (symbols if symbols is not None else self.analyzer.model.symbols).get(
            candidate.symbol_key
        )
        return dict(
            name=node.name,
            symbol_id=candidate.symbol_id,
            overload_id=candidate.symbol_id + "#signature",
            parameters=[
                dict(
                    name=p.name,
                    type=type_ref_name(p.type_ref) if p.type_ref else "any",
                    qualifier_max=(parameter_qualifier(p, self.analyzer.model) or "series")
                    if qualifiers
                    else "series",
                    required=p.default_value is None,
                )
                for p in node.parameters
            ],
            returns=getattr(symbol, "type", None) or "unknown",
            return_qualifier=getattr(symbol, "qualifier", None) or "series",
        )

    def _failure(self, call: CallExpr, code: str, message: str) -> FunctionSelection:
        issue = SignatureIssue(Severity.ERROR, code, message, call.span)
        name = call.callee.name if isinstance(call.callee, Identifier) else call.callee.member
        resolution = SignatureResolution(name, "function", {}, (), {}, (), issues=(issue,))
        return FunctionSelection(resolution, None)

    def resolve(self, call: CallExpr, engine: Any, *, qualifiers: bool = True) -> FunctionSelection | None:
        namespace_owner = (
            self.visibility.function_owner(call) if self.visibility is not None else None
        )
        if not isinstance(call.callee, Identifier) and namespace_owner is None:
            return None
        name = call.callee.name if isinstance(call.callee, Identifier) else call.callee.member
        family = self.by_name.get(name)
        if not family or (len(family) == 1 and namespace_owner is None):
            return None
        symbol = (engine.symbols or {}).get(name)
        if (
            namespace_owner is None
            and symbol is not None
            and symbol.kind is not SymbolKind.FUNCTION
        ):
            return None
        if id(call) in self.active:
            return self._failure(
                call, codes.UNSUPPORTED_FEATURE, "Function candidate inference cycle."
            )
        self.active.add(id(call))
        try:
            candidates = family
            if len(family) > 1 and self.visibility is None:
                candidates = tuple(
                    c
                    for c in candidates
                    if c.declaration.span.start_offset <= call.span.start_offset
                )
            if self.visibility is not None and hasattr(self.visibility, "allows_function"):
                candidates = tuple(
                    c for c in candidates if self.visibility.allows_function(call, c.declaration)
                )
            if not candidates:
                return self._failure(
                    call, codes.UNKNOWN_CALL, "No user-function overload is visible at this call."
                )
            self.spent += 1 + len(call.arguments)
            if self.spent > MAX_FUNCTION_WORK:
                return self._failure(
                    call,
                    codes.UNSUPPORTED_FEATURE,
                    "Function candidate inference work limit exceeded.",
                )
            actual = tuple(
                (engine.infer_type(a.value), engine.infer_qualifier(a.value))
                for a in call.arguments
            )
            entries = [
                self.entry(c, symbols=engine.symbols, qualifiers=qualifiers) for c in candidates
            ]
            shape = tuple(
                (
                    e["symbol_id"],
                    e["returns"],
                    e["return_qualifier"],
                    tuple(
                        (p["name"], p["type"], p["qualifier_max"], p["required"])
                        for p in e["parameters"]
                    ),
                )
                for e in entries
            )
            key = (id(call), qualifiers, actual, shape)
            if key in self.cache:
                return self.cache[key]
            self.spent += sum(1 + len(e["parameters"]) + len(call.arguments) for e in entries)
            if self.spent > MAX_FUNCTION_WORK or len(self.cache) >= MAX_FUNCTION_CACHE:
                return self._failure(
                    call,
                    codes.UNSUPPORTED_FEATURE,
                    "Function candidate inference work limit exceeded.",
                )
            evidence = {id(a): value for a, value in zip(call.arguments, actual)}
            resolution = self.resolver.resolve_candidates(
                name,
                entries,
                call.arguments,
                call.span,
                kind="function",
                validate_types=True,
                validate_qualifiers=qualifiers,
                infer_arg_type=lambda a: evidence[id(a)][0],
                infer_arg_qualifier=lambda a: evidence[id(a)][1],
            )
            selected = FunctionSelection(
                resolution, self.by_symbol.get(str(resolution.entry.get("symbol_id")))
            )
            self.cache[key] = selected
            return selected
        finally:
            self.active.remove(id(call))
