"""One source-anchored inventory and signature selection owner for methods."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pine2ast.ast.nodes import CallExpr, MemberAccessExpr, MethodDeclaration, Program
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.collection_signatures import resolve_collection_call
from pine2ast.semantic.node_index import NodeIndex
from pine2ast.semantic.parameter_qualifiers import parameter_qualifier
from pine2ast.semantic.signatures import SignatureIssue, SignatureResolution, SignatureResolver
from pine2ast.semantic.type_helpers import generic_type_parts, type_ref_name
from pine2ast.semantic.type_infer import callee_name

MAX_METHOD_WORK = 262144
MAX_METHOD_CACHE = 4096


@dataclass(frozen=True, slots=True)
class MethodCandidate:
    declaration: MethodDeclaration
    declaration_id: str
    receiver_type: str
    symbol_key: str

    @property
    def symbol_id(self) -> str:
        return f"user:method:{self.declaration.name}:{self.declaration_id}"


@dataclass(frozen=True, slots=True)
class MethodSelection:
    receiver_type: str
    resolution: SignatureResolution
    candidate: MethodCandidate | None

    @property
    def user_selected(self) -> bool:
        return self.resolution.ok and self.candidate is not None


class MethodCandidates:
    """No type rules or overload scoring live here: SignatureResolver owns both.

    The declaration index is bound to one actual Program. Candidate entries and
    failed bindings consume one shared work budget. Cache keys include admitted
    argument types/qualifiers and the evolving declaration return facts.
    """

    def __init__(self, analyzer: Any, program: Program) -> None:
        self.analyzer = analyzer
        self.index = NodeIndex.build(program)
        declarations = [n for n in self.index.nodes if isinstance(n, MethodDeclaration)]
        counts: dict[tuple[str, str], int] = {}
        for node in declarations:
            receiver_key = (type_ref_name(node.receiver_type), node.name)
            counts[receiver_key] = counts.get(receiver_key, 0) + 1
        candidates = []
        seen: set[tuple[Any, ...]] = set()
        duplicates = []
        for node in declarations:
            receiver = type_ref_name(node.receiver_type)
            identity = self.index.id_for(node)
            key = f"{receiver}.{node.name}"
            if counts[(receiver, node.name)] > 1:
                key += f"#{identity}"
            candidate = MethodCandidate(node, identity, receiver, key)
            candidates.append(candidate)
            # Names/default-only differences cannot make a required signature
            # unique; preserve exact qualifier/type distinctions.
            signature = (
                receiver,
                node.name,
                tuple(
                    (
                        type_ref_name(p.type_ref) if p.type_ref else "any",
                        p.explicit_qualifier or "series",
                    )
                    for p in node.parameters
                    if p.default_value is None
                ),
            )
            if signature in seen:
                duplicates.append(candidate)
            seen.add(signature)
        self.candidates = tuple(candidates)
        groups: dict[tuple[str, str], list[MethodCandidate]] = {}
        for candidate in candidates:
            groups.setdefault((candidate.receiver_type, candidate.declaration.name), []).append(
                candidate
            )
        self.by_receiver_name = MappingProxyType(
            {key: tuple(group) for key, group in groups.items()}
        )
        self.by_node = MappingProxyType({id(c.declaration): c for c in candidates})
        self.by_symbol = MappingProxyType({c.symbol_id: c for c in candidates})
        self.names = frozenset(c.declaration.name for c in candidates)
        self.duplicates = tuple(duplicates)
        self.resolver = SignatureResolver(version_context=analyzer.version_context)
        self.spent = 0
        self.active: set[int] = set()
        self.cache: dict[tuple[Any, ...], MethodSelection] = {}

    def entry(self, candidate: MethodCandidate) -> dict[str, Any]:
        node = candidate.declaration
        symbol = self.analyzer.model.symbols.get(candidate.symbol_key)
        return dict(
            name=node.name,
            symbol_id=candidate.symbol_id,
            overload_id=candidate.symbol_id + "#signature",
            receiver_type=candidate.receiver_type,
            parameters=[
                dict(
                    name=p.name,
                    type=type_ref_name(p.type_ref) if p.type_ref else "any",
                    qualifier_max=parameter_qualifier(p, self.analyzer.model) or "series",
                    required=p.default_value is None,
                )
                for p in node.parameters
            ],
            returns=getattr(symbol, "type", None) or "unknown",
        )

    def _limit(self, call: CallExpr, receiver: str) -> MethodSelection:
        issue = SignatureIssue(
            Severity.ERROR,
            codes.UNSUPPORTED_FEATURE,
            "Method candidate inference work limit exceeded.",
            call.span,
        )
        resolution = SignatureResolution(
            callee_name(call.callee), "method", {}, (), {}, (), issues=(issue,)
        )
        return MethodSelection(receiver, resolution, None)

    def resolve(self, call: CallExpr, engine: Any) -> MethodSelection | None:
        if not isinstance(call.callee, MemberAccessExpr) or call.callee.member not in self.names:
            return None
        if callee_name(call.callee) in engine.registry.get("functions", {}):
            return None
        if id(call) in self.active:
            return self._limit(call, "unknown")
        self.active.add(id(call))
        try:
            receiver = engine.infer_type(call.callee.object)
            candidates = self.by_receiver_name.get((receiver, call.callee.member), ())
            if not candidates:
                return None
            self.spent += 1 + len(call.arguments)
            if self.spent > MAX_METHOD_WORK:
                return self._limit(call, receiver)
            entries = [self.entry(c) for c in candidates]
            base, _ = generic_type_parts(receiver)
            builtin = engine.registry.get("methods", {}).get(f"{base}.{call.callee.member}")
            if isinstance(builtin, dict):
                builtin = dict(builtin)
                collection = resolve_collection_call(call, engine=engine)
                if collection is not None:
                    builtin["parameters"] = [
                        dict(
                            name=p.name,
                            type=p.type_name or "unknown",
                            required=p.required,
                            qualifier_max="series",
                        )
                        for p in collection.parameters
                    ]
                    builtin["returns"] = collection.return_type or builtin.get("returns")
                entries.extend(self.resolver.candidate_entries(builtin))
            actual = tuple(
                (engine.infer_type(a.value), engine.infer_qualifier(a.value))
                for a in call.arguments
            )
            actual_by_argument = {
                id(argument): value for argument, value in zip(call.arguments, actual)
            }
            shape = tuple(
                (
                    row.get("symbol_id"),
                    row.get("returns"),
                    tuple(
                        (p.get("name"), p.get("type"), p.get("qualifier_max"), p.get("required"))
                        for p in row.get("parameters", [])
                    ),
                )
                for row in entries
            )
            key = (id(call), receiver, actual, shape)
            if key in self.cache:
                return self.cache[key]
            cost = sum(1 + len(row.get("parameters", [])) + len(call.arguments) for row in entries)
            self.spent += cost
            if self.spent > MAX_METHOD_WORK or len(self.cache) >= MAX_METHOD_CACHE:
                return self._limit(call, receiver)
            # Selection consumes the original source arguments once. Distinct
            # declaration IDs are never deduplicated merely by callable shape.
            resolution = self.resolver.resolve_candidates(
                call.callee.member,
                entries,
                call.arguments,
                call.span,
                kind="method",
                validate_types=True,
                validate_qualifiers=True,
                infer_arg_type=lambda a: actual_by_argument[id(a)][0],
                infer_arg_qualifier=lambda a: actual_by_argument[id(a)][1],
            )
            chosen = self.by_symbol.get(str(resolution.entry.get("symbol_id")))
            selected = MethodSelection(receiver, resolution, chosen)
            self.cache[key] = selected
            return selected
        finally:
            self.active.remove(id(call))
