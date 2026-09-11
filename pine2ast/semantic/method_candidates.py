"""One source-anchored inventory and signature selection owner for methods."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pine2ast.ast.nodes import (
    CallExpr,
    FunctionDeclaration,
    Identifier,
    MemberAccessExpr,
    MethodDeclaration,
    Program,
    TypeDeclaration,
)
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.collection_signatures import resolve_collection_call
from pine2ast.semantic.node_index import NodeIndex
from pine2ast.semantic.parameter_qualifiers import parameter_qualifier
from pine2ast.semantic.signatures import (
    ReceiverArgumentEvidence,
    SignatureIssue,
    SignatureResolution,
    SignatureResolver,
)
from pine2ast.semantic.type_helpers import generic_type_parts, is_reference_type, type_ref_name
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
        self.visibility = getattr(analyzer, "_method_visibility", None)
        self.index = NodeIndex.build(program)
        self.udts = frozenset(n.name for n in self.index.nodes if isinstance(n, TypeDeclaration))
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
                self.visibility.origin(node) if self.visibility is not None else None,
                receiver,
                node.name,
                self.receiver_qualifier(node, for_binding=True),
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
        names: dict[str, list[MethodCandidate]] = {}
        for candidate in candidates:
            names.setdefault(candidate.declaration.name, []).append(candidate)
            groups.setdefault((candidate.receiver_type, candidate.declaration.name), []).append(
                candidate
            )
        self.by_receiver_name = MappingProxyType(
            {key: tuple(group) for key, group in groups.items()}
        )
        self.by_node = MappingProxyType({id(c.declaration): c for c in candidates})
        self.by_symbol = MappingProxyType({c.symbol_id: c for c in candidates})
        self.by_name = MappingProxyType({name: tuple(group) for name, group in names.items()})
        self.function_names = frozenset(
            n.name for n in program.items if isinstance(n, FunctionDeclaration)
        )
        self.names = frozenset(self.by_name)
        self.duplicates = tuple(duplicates)
        self.resolver = SignatureResolver(version_context=analyzer.version_context)
        self.spent = 0
        self.active: set[int] = set()
        self.cache: dict[tuple[Any, ...], MethodSelection] = {}

    def receiver_qualifier(self, node: MethodDeclaration, *, for_binding: bool = False) -> str:
        """References stay series; v6 explicitly ignores their qualifier keyword.

        The v5 simple-reference *admission* exception is not independently
        established. Preserve that bounded rejection profile, without letting
        its source annotation fabricate a simple reference inside a method.
        """
        dtype = type_ref_name(node.receiver_type)
        reference = dtype in self.udts or is_reference_type(dtype)
        if reference and (not for_binding or self.analyzer.version_context.pine_version == 6):
            return "series"
        return node.receiver_explicit_qualifier or "series"

    def entry(self, candidate: MethodCandidate, *, symbols: Any = None) -> dict[str, Any]:
        node = candidate.declaration
        symbol = (symbols if symbols is not None else self.analyzer.model.symbols).get(
            candidate.symbol_key
        )
        entry = dict(
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
        if node.receiver_explicit_qualifier is not None:
            entry["__receiver_parameter"] = dict(
                name=node.receiver_name,
                type=candidate.receiver_type,
                qualifier_max=self.receiver_qualifier(node, for_binding=True),
                required=True,
            )
            entry["return_qualifier"] = getattr(symbol, "qualifier", None) or "series"
        if id(node) in getattr(self.analyzer, "_projected_exported_functions", ()):
            entry["return_qualifier"] = getattr(symbol, "qualifier", None) or "series"
        return entry

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
        explicit = isinstance(call.callee, Identifier)
        namespace_owner = None
        if isinstance(call.callee, MemberAccessExpr) and self.visibility is not None:
            namespace_owner = self.visibility.explicit_owner(call)
            explicit = namespace_owner is not None
        name = call.callee.name if isinstance(call.callee, Identifier) else (
            call.callee.member if isinstance(call.callee, MemberAccessExpr) else None
        )
        if name not in self.names:
            return None
        # Ordinary functions/builtins keep their existing owner. A method's
        # function notation is not a spelling-based replacement for a function.
        if explicit and namespace_owner is None and name in self.function_names:
            return None
        if callee_name(call.callee) in engine.registry.get("functions", {}):
            return None
        if id(call) in self.active:
            return self._limit(call, "unknown")
        self.active.add(id(call))
        try:
            receiver = "unknown" if explicit else engine.infer_type(call.callee.object)
            candidates = self.by_name[name] if explicit else self.by_receiver_name.get((receiver, name), ())
            if not candidates:
                return None
            all_candidates = candidates
            if self.visibility is not None:
                candidates = tuple(c for c in candidates if self.visibility.allows(call, c.declaration))
            self.spent += 1 + len(call.arguments)
            if self.spent > MAX_METHOD_WORK:
                return self._limit(call, receiver)
            entries = [
                self.entry(
                    c,
                    symbols=(
                        engine.symbols
                        if c.declaration.receiver_explicit_qualifier is not None
                        else None
                    ),
                )
                for c in candidates
            ]
            receiver_evidence = None
            if explicit:
                for entry, candidate in zip(entries, candidates):
                    # SignatureResolver owns binding/coercions/qualifiers for
                    # every argument, including an explicitly supplied receiver.
                    entry.pop("__receiver_parameter", None)
                    entry["parameters"] = [{
                        "name": candidate.declaration.receiver_name,
                        "type": candidate.receiver_type,
                        "qualifier_max": self.receiver_qualifier(candidate.declaration, for_binding=True),
                        "required": True,
                    }, *entry["parameters"]]
            elif any(c.declaration.receiver_explicit_qualifier is not None for c in candidates):
                value = engine.infer_value(call.callee.object)
                receiver_evidence = ReceiverArgumentEvidence(
                    self.index.id_for(call.callee.object),
                    call.callee.object.span,
                    receiver,
                    value.qualifier,
                    value.can_be_na,
                )
            base, _ = generic_type_parts(receiver)
            builtin = None if explicit else engine.registry.get("methods", {}).get(f"{base}.{name}")
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
            if not entries and all_candidates:
                issue = SignatureIssue(Severity.ERROR, codes.UNKNOWN_CALL,
                    "No imported or local method is visible for this receiver.", call.span)
                resolution = SignatureResolution(callee_name(call.callee), "method", {}, (), {}, (), issues=(issue,))
                return MethodSelection(receiver, resolution, None)
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
                    row.get("return_qualifier"),
                    tuple(sorted((row.get("__receiver_parameter") or {}).items())),
                    tuple(
                        (p.get("name"), p.get("type"), p.get("qualifier_max"), p.get("required"))
                        for p in row.get("parameters", [])
                    ),
                )
                for row in entries
            )
            key = (id(call), explicit, receiver, receiver_evidence, actual, shape)
            if key in self.cache:
                return self.cache[key]
            cost = sum(
                1
                + len(row.get("parameters", []))
                + len(call.arguments)
                + int("__receiver_parameter" in row)
                for row in entries
            )
            self.spent += cost
            if self.spent > MAX_METHOD_WORK or len(self.cache) >= MAX_METHOD_CACHE:
                return self._limit(call, receiver)
            # Selection consumes the original source arguments once. Distinct
            # declaration IDs are never deduplicated merely by callable shape.
            resolution = self.resolver.resolve_candidates(
                name,
                entries,
                call.arguments,
                call.span,
                kind="method",
                validate_types=True,
                validate_qualifiers=True,
                infer_arg_type=lambda a: actual_by_argument[id(a)][0],
                infer_arg_qualifier=lambda a: actual_by_argument[id(a)][1],
                receiver=receiver_evidence,
            )
            chosen = self.by_symbol.get(str(resolution.entry.get("symbol_id")))
            selected = MethodSelection(
                chosen.receiver_type if explicit and chosen is not None else receiver,
                resolution, chosen,
            )
            self.cache[key] = selected
            return selected
        finally:
            self.active.remove(id(call))
