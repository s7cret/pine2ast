from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Callable, Iterable, Mapping, cast

from pine2ast.ast.base import ASTNode, Declaration, Expression, Statement
from pine2ast.ast.nodes import (
    BinaryExpr,
    Block,
    CallExpr,
    ConditionalExpr,
    EnumDeclaration,
    EnumMember,
    ExpressionStatement,
    FieldDeclaration,
    ForInStructure,
    ForRangeStructure,
    FunctionDeclaration,
    GenericInstantiationExpr,
    Identifier,
    IfStructure,
    OnceStructure,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    Parameter,
    Program,
    Reassignment,
    TupleDeclaration,
    TupleTarget,
    TypeDeclaration,
    UnaryExpr,
    VarDeclaration,
    WhileStructure,
)
from pine2ast.ast.walk import iter_child_nodes
from pine2ast.catalog.hashing import seal_hash, sha256_id
from pine2ast.diagnostics import Diagnostic, Severity, codes
from pine2ast.semantic.fact_model import (
    ArgumentBindingFact,
    CallBindingFact,
    CoercionFact,
    DefaultBindingFact,
    SemanticCoverage,
    SemanticFact,
    FactClassification,
    SemanticFactsBundle,
    TypeFact,
)
from pine2ast.semantic.collection_signatures import resolve_collection_call
from pine2ast.semantic.constant_numbers import comparison_constant, round_constant
from pine2ast.semantic import constant_functions as const_functions
from pine2ast.semantic.inference import PineInferenceEngine, registry_entry_for_call
from pine2ast.semantic.node_index import NodeIndex
from pine2ast.semantic.signatures import SignatureResolver
from pine2ast.policy import SemanticPolicy
from pine2ast.semantic.type_helpers import generic_type_parts, is_assignable_type, type_ref_name
from pine2ast.semantic.type_infer import callee_name
from pine2ast.semantic.values import expression_can_be_na
from pine2ast.semantic.parameter_qualifiers import parameter_qualifier
from pine2ast.versioning import PineVersionContext


class SemanticFactBuilder:
    """Create deterministic, version-bound static facts for Ast2Python.

    The builder never chooses a Pine version. It accepts the exact context already
    admitted by the parser and refuses mismatches with the AST or catalog.
    """

    def __init__(
        self,
        *,
        version_context: PineVersionContext,
        catalog: Mapping[str, Any],
        policy: SemanticPolicy,
        model: Any,
    ) -> None:
        self.version_context = version_context
        policy.validate_context(version_context)
        self.catalog = catalog
        # Structural parents of active qualified names need type evidence even
        # when a pinned catalog omits the intermediate namespace (v5 direction).
        # This does not import names from another version or overwrite a symbol.
        self._namespace_prefixes = {
            ".".join(parts[:i])
            for section in ("variables", "constants", "functions", "methods")
            for name in catalog.get(section, {})
            for parts in [name.split(".")]
            for i in range(1, len(parts))
        }
        self.policy = policy
        self.model = model
        self.engine = PineInferenceEngine(
            version_context=version_context,
            symbols=model.symbols,
            registry=catalog,
            policy=policy,
        )
        self.engine.bind_model(model)
        self.signatures = SignatureResolver(version_context=version_context)
        self.index: NodeIndex | None = None
        self._scopes: dict[int, str] = {}
        self._call_bindings: dict[int, CallBindingFact] = {}
        self._constant_varargs: dict[int, tuple[str, str | None, frozenset[tuple[int, str]]]] = {}
        self._coercions: dict[int, list[CoercionFact]] = {}
        self._declarations: dict[str, ASTNode] = {}
        self._constant_functions: dict[str, FunctionDeclaration] = {}
        self._constant_roots: set[int] = set()
        self._constant_work = const_functions.ConstantWork()
        self._constant_global_scopes: dict[str, dict[str, VarDeclaration]] = {}

    def build(self, program: Program) -> SemanticFactsBundle:
        if program.version_context != self.version_context:
            raise ValueError("Program and SemanticAnalyzer version contexts differ")
        if str(self.catalog.get("pine_version")) != str(self.version_context.pine_version):
            raise ValueError("catalog Pine version does not match PineVersionContext")
        if self.catalog.get("catalog_hash") != self.version_context.catalog_hash:
            raise ValueError("catalog hash does not match PineVersionContext")

        self.index = NodeIndex.build(program)
        self._index_declarations(program)
        self._assign_scopes(program, "scope:global")
        self._resolve_calls(program)
        from pine2ast.semantic.call_graph import reject_recursive_calls
        reject_recursive_calls(program, self.index, self._call_bindings, self._append_diagnostic)
        self._propagate_user_statefulness(program)
        self._index_constant_functions()
        self._collect_version_coercions(program)

        diagnostic_rows = self._diagnostic_rows()
        facts = tuple(self._fact_for(node, diagnostic_rows) for node in self.index.nodes)
        calls = tuple(
            self._call_bindings[id(node)]
            for node in self.index.nodes
            if id(node) in self._call_bindings
        )
        coverage = self._coverage(facts, calls)
        artifact_body = {
            "schema_id": "pine.semantic_facts.v1",
            "schema_version": "1.0.0",
            "version_context": self.version_context.to_dict(),
            "version_context_ref": sha256_id(self.version_context.to_dict()),
            "catalog_hash": self.version_context.catalog_hash,
            "facts": [item.to_dict() for item in facts],
            "calls": [item.to_dict() for item in calls],
            "diagnostics": list(diagnostic_rows),
            "coverage": coverage.to_dict(),
        }
        artifact = seal_hash(artifact_body)
        return SemanticFactsBundle(
            facts=facts,
            calls=calls,
            diagnostics=tuple(diagnostic_rows),
            coverage=coverage,
            artifact=artifact,
        )

    def _declaration_key(self, node: ASTNode) -> str:
        if isinstance(node, FunctionDeclaration):
            owner = self.model.function_candidates
            candidate = owner.by_node.get(id(node)) if owner is not None else None
            if candidate is not None:
                return candidate.symbol_key
        if isinstance(node, MethodDeclaration) and node.receiver_type is not None:
            owner = self.model.method_candidates
            candidate = owner.by_node.get(id(node)) if owner is not None else None
            if candidate is not None:
                return candidate.symbol_key
            return f"{type_ref_name(node.receiver_type)}.{node.name}"
        return getattr(node, "name", "")

    def _index_declarations(self, program: Program) -> None:
        for node in self.index.nodes if self.index else ():
            if isinstance(node, (FunctionDeclaration, MethodDeclaration, TypeDeclaration)):
                self._declarations[self._declaration_key(node)] = node

    def _assign_scopes(self, node: ASTNode, scope_id: str) -> None:
        assert self.index is not None
        self._scopes[id(node)] = scope_id
        nested = scope_id
        if isinstance(node, FunctionDeclaration):
            nested = f"scope:function:{self.index.id_for(node)}"
        elif isinstance(node, MethodDeclaration):
            nested = f"scope:method:{self.index.id_for(node)}"
        elif isinstance(node, TypeDeclaration):
            nested = f"scope:type:{self.index.id_for(node)}"
        elif isinstance(node, EnumDeclaration):
            nested = f"scope:enum:{self.index.id_for(node)}"
        elif isinstance(node, (ForRangeStructure, ForInStructure, WhileStructure)):
            nested = f"scope:loop:{self.index.id_for(node)}"

        for child in iter_child_nodes(node):
            child_scope = nested
            if isinstance(child, Block) and nested == scope_id:
                child_scope = f"scope:block:{self.index.id_for(child)}"
            self._assign_scopes(child, child_scope)

    def _resolve_calls(self, program: Program) -> None:
        assert self.index is not None
        for node in self.index.nodes:
            if not isinstance(node, CallExpr):
                continue
            binding = self._resolve_call(node)
            if binding is not None:
                self._call_bindings[id(node)] = binding

    def _resolve_call(self, call: CallExpr) -> CallBindingFact | None:
        assert self.index is not None
        raw_name = callee_name(call.callee)
        lookup_name, entry = registry_entry_for_call(call.callee, self.catalog)
        call_form = "FUNCTION"
        receiver_type: str | None = None
        owner = self.model.method_candidates
        selection = owner.resolve(call, self.engine) if owner is not None else None

        functions = self.model.function_candidates
        function_selection = functions.resolve(call, self.engine) if functions is not None else None
        if function_selection is not None:
            selection = function_selection
            entry = selection.resolution.entry
            lookup_name = raw_name
            call_form = "USER_FUNCTION"
        elif selection is not None:
            entry = selection.resolution.entry
            receiver_type = selection.receiver_type
            lookup_name = str(entry.get("name") or raw_name)
            call_form = "USER_METHOD" if selection.candidate is not None else "METHOD"
        elif entry is not None:
            call_form = "NAMESPACE_FUNCTION" if "." in lookup_name else "FUNCTION"
        elif isinstance(call.callee, MemberAccessExpr):
            receiver_type = self.engine.infer_type(call.callee.object)
            receiver_base, _ = generic_type_parts(receiver_type)
            method_name = f"{receiver_base}.{call.callee.member}" if receiver_base else ""
            method_entry = self.catalog.get("methods", {}).get(method_name)
            if isinstance(method_entry, dict):
                lookup_name, entry = method_name, method_entry
                call_form = "METHOD"

        if entry is None:
            synthetic = self._user_callable_entry(call, raw_name, receiver_type)
            if synthetic is not None:
                lookup_name, entry, call_form, receiver_type = synthetic

        if entry is None:
            self._append_diagnostic(
                Diagnostic(
                    Severity.ERROR,
                    codes.UNKNOWN_CALL,
                    f"Call {raw_name} cannot be resolved in Pine v{self.version_context.pine_version}.",
                    call.span,
                )
            )
            return None

        collection_resolution = (
            resolve_collection_call(call, engine=self.engine) if selection is None else None
        )
        if collection_resolution is not None:
            entry = dict(entry)
            entry["parameters"] = [
                {
                    "name": parameter.name,
                    "type": parameter.type_name or "unknown",
                    "required": parameter.required,
                    "qualifier_max": "series",
                }
                for parameter in collection_resolution.parameters
            ]
            if collection_resolution.return_type:
                entry["returns"] = collection_resolution.return_type

        resolution = (
            selection.resolution
            if selection is not None
            else self.signatures.resolve_builtin(
                lookup_name,
                dict(entry),
                call.arguments,
                call.span,
                kind=call_form.lower(),
                symbols=self.model.symbols,
                validate_types=True,
                validate_qualifiers=True,
                infer_arg_type=lambda argument: self.engine.infer_type(argument.value),
                infer_arg_qualifier=lambda argument: self.engine.infer_qualifier(argument.value),
            )
        )
        for issue in resolution.issues:
            self._append_diagnostic(
                Diagnostic(issue.severity, issue.code, issue.message, issue.span)
            )

        symbol_id = str(entry.get("symbol_id") or self._synthetic_symbol_id(call_form, lookup_name))
        status = (
            "RESOLVED"
            if resolution.ok
            else (
                "AMBIGUOUS"
                if any(item.code == codes.AMBIGUOUS_OVERLOAD for item in resolution.issues)
                else "INVALID"
            )
        )
        overload_id = (
            str(entry.get("overload_id") or resolution.overload_id or f"{symbol_id}#canonical")
            if status == "RESOLVED"
            else None
        )
        self._constant_varargs[id(call)] = (
            symbol_id,
            overload_id,
            frozenset(
                (index, str(parameter["name"]))
                for index, parameter in enumerate(resolution.active_parameters)
                if parameter.get("variadic") is True and parameter.get("name")
            ),
        )
        argument_facts: list[ArgumentBindingFact] = []
        for resolved in resolution.resolved_arguments:
            if resolved.argument is None:
                raise AssertionError("source argument binding has no AST argument")
            parameter_name = (
                str(resolved.parameter.get("name"))
                if resolved.parameter and resolved.parameter.get("name") is not None
                else None
            )
            argument_facts.append(
                ArgumentBindingFact(
                    argument_node_id=self.index.id_for(resolved.argument),
                    parameter_name=parameter_name,
                    parameter_index=resolved.parameter_index,
                    binding=resolved.binding,
                    actual_type=resolved.actual_type,
                    actual_qualifier=resolved.actual_qualifier,
                    expected_type=(
                        str(resolved.parameter.get("type") or resolved.parameter.get("value_type"))
                        if resolved.parameter
                        and (resolved.parameter.get("type") or resolved.parameter.get("value_type"))
                        else None
                    ),
                    max_qualifier=(
                        str(resolved.parameter.get("qualifier_max"))
                        if resolved.parameter and resolved.parameter.get("qualifier_max")
                        else None
                    ),
                )
            )
            expected = (
                str(resolved.parameter.get("type") or resolved.parameter.get("value_type"))
                if resolved.parameter
                and (resolved.parameter.get("type") or resolved.parameter.get("value_type"))
                else None
            )
            actual = resolved.actual_type
            if expected and actual and expected != actual and is_assignable_type(expected, actual):
                self._coercions.setdefault(id(resolved.argument.value), []).append(
                    CoercionFact(actual, expected, "call_argument")
                )

        inferred_return = self.engine.infer_type(call)
        return_type = str(
            inferred_return
            if inferred_return not in {"unknown", "any"}
            else (resolution.return_type or entry.get("returns") or "unknown")
        )
        stateful = self._is_intrinsically_stateful(lookup_name, resolution.entry)
        return CallBindingFact(
            node_id=self.index.id_for(call),
            callee=lookup_name,
            symbol_id=symbol_id,
            resolution_status=status,
            overload_id=overload_id,
            call_form=call_form,
            receiver_type=receiver_type,
            return_type=return_type,
            stateful=stateful,
            arguments=tuple(argument_facts),
            defaults_applied=tuple(
                DefaultBindingFact(
                    parameter_name=str(parameter["name"]),
                    parameter_index=int(parameter["parameter_index"]),
                    expected_type=(str(parameter["type"]) if parameter.get("type") else None),
                    max_qualifier=(
                        str(parameter["qualifier_max"]) if parameter.get("qualifier_max") else None
                    ),
                    default_known=("default" in parameter or "default_value" in parameter),
                    default_value=parameter.get("default", parameter.get("default_value")),
                )
                for parameter in resolution.defaulted_parameters
                if parameter.get("name") is not None
            ),
        )

    def _user_callable_entry(
        self,
        call: CallExpr,
        raw_name: str,
        receiver_type: str | None,
    ) -> tuple[str, dict[str, Any], str, str | None] | None:
        declaration = self._declarations.get(raw_name)
        call_form = "USER_FUNCTION"
        if declaration is None and isinstance(call.callee, MemberAccessExpr):
            method_key = f"{receiver_type}.{call.callee.member}" if receiver_type else ""
            declaration = self._declarations.get(method_key)
            if isinstance(declaration, MethodDeclaration):
                call_form = "USER_METHOD"
                raw_name = declaration.name
                receiver_type = self.engine.infer_type(call.callee.object)
        if (
            declaration is None
            and isinstance(call.callee, MemberAccessExpr)
            and call.callee.member == "new"
        ):
            if isinstance(call.callee.object, Identifier):
                declaration = self._declarations.get(call.callee.object.name)
                if isinstance(declaration, TypeDeclaration):
                    call_form = "UDT_CONSTRUCTOR"
                    raw_name = f"{declaration.name}.new"
        if (
            declaration is None
            and isinstance(call.callee, MemberAccessExpr)
            and call.callee.member == "copy"
        ):
            object_name = callee_name(call.callee.object)
            candidate = self._declarations.get(object_name) or self._declarations.get(
                receiver_type or ""
            )
            if isinstance(candidate, TypeDeclaration):
                declaration = candidate
                call_form = "UDT_COPY"
                raw_name = f"{declaration.name}.copy"
        if declaration is None:
            symbol = self.model.symbols.get(raw_name)
            if symbol is None:
                return None
            if getattr(symbol.kind, "value", symbol.kind) not in {"FUNCTION", "METHOD"}:
                return None
            parameters: list[dict[str, Any]] = []
            return (
                raw_name,
                {
                    "name": raw_name,
                    "symbol_id": f"user:{str(getattr(symbol.kind, 'value', symbol.kind)).lower()}:{raw_name}",
                    "parameters": parameters,
                    "returns": symbol.type or "unknown",
                },
                call_form,
                receiver_type,
            )

        assert self.index is not None
        if isinstance(declaration, (FunctionDeclaration, MethodDeclaration)):
            parameters = [self._parameter_entry(item) for item in declaration.parameters]
            symbol_kind = "method" if isinstance(declaration, MethodDeclaration) else "function"
            return_type = (
                getattr(self.model.symbols.get(self._declaration_key(declaration)), "type", None)
                or "unknown"
            )
            return (
                raw_name,
                {
                    "name": raw_name,
                    "symbol_id": f"user:{symbol_kind}:{declaration.name}:{self.index.id_for(declaration)}",
                    "parameters": parameters,
                    "returns": return_type,
                    "overload_id": f"user:{symbol_kind}:{declaration.name}:{self.index.id_for(declaration)}#signature",
                    "receiver_type": (
                        type_ref_name(declaration.receiver_type)
                        if isinstance(declaration, MethodDeclaration) and declaration.receiver_type
                        else None
                    ),
                },
                call_form,
                receiver_type,
            )
        if isinstance(declaration, TypeDeclaration):
            parameters = [
                {
                    "name": field.name,
                    "type": type_ref_name(field.type_ref),
                    "required": False,
                    "qualifier_max": "series",
                }
                for field in declaration.fields
            ]
            operation = "constructor"
            if call_form == "UDT_COPY":
                assert isinstance(call.callee, MemberAccessExpr)
                operation = "copy"
                parameters = []
                if callee_name(call.callee.object) == declaration.name:
                    parameters = [
                        {
                            "name": "object",
                            "type": declaration.name,
                            "required": True,
                            "qualifier_max": "series",
                        }
                    ]
            return (
                raw_name,
                {
                    "name": raw_name,
                    "symbol_id": f"user:type:{declaration.name}:{self.index.id_for(declaration)}",
                    "parameters": parameters,
                    "returns": declaration.name,
                    "overload_id": f"user:type:{declaration.name}:{self.index.id_for(declaration)}#{operation}",
                    "stateful": True,
                },
                call_form,
                receiver_type,
            )
        return None

    def _parameter_entry(self, parameter: Parameter) -> dict[str, Any]:
        return {
            "name": parameter.name,
            "type": type_ref_name(parameter.type_ref) if parameter.type_ref else "any",
            "qualifier_max": parameter_qualifier(parameter, self.model) or "series",
            "required": parameter.default_value is None,
        }

    @staticmethod
    def _synthetic_symbol_id(call_form: str, name: str) -> str:
        return f"{call_form.lower()}:{name}"

    @staticmethod
    def _is_intrinsically_stateful(name: str, entry: Mapping[str, Any]) -> bool:
        if bool(entry.get("side_effect")):
            return True
        if isinstance(entry.get("stateful"), bool):
            return bool(entry["stateful"])
        canonical = str(entry.get("symbol_id") or "").removeprefix("pine:function:")
        return (canonical or name).startswith(("ta.", "request.", "strategy.", "alert"))

    def _collect_version_coercions(self, program: Program) -> None:
        if not self.policy.allows_bool_to_number:
            return
        for node in self.index.nodes if self.index else ():
            if not isinstance(node, BinaryExpr) or node.op not in {"+", "-", "*", "/", "%"}:
                continue
            rows: list[CoercionFact] = []
            for operand in (node.left, node.right):
                if self.engine.infer_type(operand) == "bool":
                    rows.append(
                        CoercionFact(
                            source_type="bool",
                            target_type="int",
                            reason=self.policy.rule_id("bool_to_number"),
                        )
                    )
            if rows:
                self._coercions[id(node)] = rows

    def _propagate_user_statefulness(self, program: Program) -> None:
        assert self.index is not None
        declaration_for_call: dict[str, FunctionDeclaration | MethodDeclaration] = {
            f"user:{'method' if isinstance(item, MethodDeclaration) else 'function'}:{item.name}:{self.index.id_for(item)}": item
            for item in self._declarations.values()
            if isinstance(item, (FunctionDeclaration, MethodDeclaration))
        }
        stateful_names = {
            name
            for name, declaration in declaration_for_call.items()
            if any(
                isinstance(node, OnceStructure)
                or (isinstance(node, VarDeclaration) and node.mode in {"var", "varip"})
                for node in self._descendants(declaration.body)
            )
        }
        changed = True
        while changed:
            changed = False
            for name, declaration in declaration_for_call.items():
                if name in stateful_names:
                    continue
                descendant_ids = {id(node) for node in self._descendants(declaration.body)}
                for call_id, binding in self._call_bindings.items():
                    if call_id not in descendant_ids:
                        continue
                    if binding.stateful or binding.symbol_id in stateful_names:
                        stateful_names.add(name)
                        changed = True
                        break
        for object_id, binding in list(self._call_bindings.items()):
            if binding.symbol_id in stateful_names and not binding.stateful:
                self._call_bindings[object_id] = replace(binding, stateful=True)

    def _descendants(self, node: ASTNode) -> Iterable[ASTNode]:
        yield node
        for child in iter_child_nodes(node):
            yield from self._descendants(child)

    def _fact_for(
        self,
        node: ASTNode,
        diagnostics: tuple[dict[str, Any], ...],
    ) -> SemanticFact:
        assert self.index is not None
        node_id = self.index.id_for(node)
        classification = self._classification(node)
        type_fact: TypeFact | None = None
        symbol_id = self._symbol_id(node)
        if classification == "EXPRESSION" and isinstance(node, Expression):
            type_name = self.model.node_types.get(id(node)) or self.engine.infer_type(node)
            if not type_name or type_name == "unknown":
                type_name = self._symbol_type_hint(node) or "unknown"
            qualifier = self.model.node_qualifiers.get(id(node)) or self.engine.infer_qualifier(
                node
            )
            type_fact = TypeFact(
                base=type_name,
                qualifier=qualifier,
                nullable=expression_can_be_na(node),
            )
        call = self._call_bindings.get(id(node))
        is_callee = False
        if call is None and isinstance(node, Expression):
            parent = self.index.parent_for(node)
            if isinstance(parent, CallExpr) and parent.callee is node:
                call = self._call_bindings.get(id(parent))
                is_callee = call is not None
            elif isinstance(parent, GenericInstantiationExpr) and parent.base is node:
                outer = self.index.parent_for(parent)
                if isinstance(outer, CallExpr) and outer.callee is parent:
                    # The syntactic base of a checked generic callee is a function,
                    # not an unresolved value. Reuse the resolved call identity;
                    # unknown constructors still have no callable evidence.
                    call = self._call_bindings.get(id(outer))
                    is_callee = call is not None
        if call is not None:
            symbol_id = call.symbol_id
            if is_callee and type_fact is not None and type_fact.base == "unknown":
                type_fact = TypeFact(
                    base=("method" if call.call_form in {"METHOD", "USER_METHOD"} else "function"),
                    qualifier=type_fact.qualifier,
                    nullable=False,
                )
        return SemanticFact(
            node_id=node_id,
            kind=node.kind,
            classification=classification,
            span=node.span.to_dict(),
            scope_id=self._scopes.get(id(node), "scope:global"),
            resolved_type=type_fact,
            symbol_id=symbol_id,
            overload_id=call.overload_id if call else None,
            declaration_target=self._declaration_target(node),
            call_form=call.call_form if call else None,
            receiver_type=call.receiver_type if call else None,
            coercions=tuple(self._coercions.get(id(node), ())),
            const_value=self._const_value(node) if isinstance(node, Expression) else None,
            semantic_rule_ids=tuple(self._semantic_rule_ids(node, call)),
            stateful_call=bool(call and call.stateful),
            diagnostic_refs=tuple(self._diagnostic_refs(node, diagnostics)),
        )

    def _classification(self, node: ASTNode) -> FactClassification:
        if isinstance(node, Program):
            return "PROGRAM"
        if isinstance(node, Declaration):
            return "DECLARATION"
        if isinstance(node, (IfStructure, ForRangeStructure, ForInStructure, WhileStructure)):
            parent = self.index.parent_for(node) if self.index else None
            if isinstance(parent, (Program, Block)):
                return "STATEMENT"
            return "EXPRESSION"
        if isinstance(node, Statement):
            return "STATEMENT"
        if isinstance(node, Expression):
            return "EXPRESSION"
        return "STRUCTURAL"

    def _symbol_type_hint(self, node: ASTNode) -> str | None:
        name: str | None = None
        if isinstance(node, Identifier):
            name = node.name
        elif isinstance(node, MemberAccessExpr):
            name = callee_name(node)
        if not name:
            return None
        for section, type_name in (
            ("functions", "function"),
            ("methods", "method"),
            ("namespaces", "namespace"),
            ("types", "type"),
            ("constants", "constant"),
        ):
            entry = self.catalog.get(section, {}).get(name)
            if isinstance(entry, Mapping):
                if section == "constants" and isinstance(entry.get("type"), str):
                    return str(entry["type"])
                return type_name
        symbol = self.model.symbols.get(name)
        if symbol is not None:
            kind = str(getattr(symbol.kind, "value", symbol.kind)).lower()
            if kind in {"function", "method", "type", "enum", "builtin"}:
                return kind
            if symbol.type:
                return str(symbol.type)
        if name in self._namespace_prefixes:
            return "namespace"
        return None

    def _symbol_id(self, node: ASTNode) -> str | None:
        assert self.index is not None
        name: str | None = None
        sections: tuple[str, ...] = ()
        if isinstance(node, Identifier):
            name = node.name
            sections = ("variables", "constants", "types", "namespaces", "functions")
        elif isinstance(node, MemberAccessExpr):
            name = callee_name(node)
            sections = ("variables", "constants", "functions", "methods", "namespaces")
        if name:
            for section in sections:
                entry = self.catalog.get(section, {}).get(name)
                if isinstance(entry, Mapping) and entry.get("symbol_id"):
                    return str(entry["symbol_id"])
            symbol = self.model.symbols.get(name)
            if symbol is not None:
                return f"user:{str(getattr(symbol.kind, 'value', symbol.kind)).lower()}:{name}:scope:{symbol.scope_id}"
            if name in self._namespace_prefixes:
                return f"pine:namespace:{name}"
        if isinstance(node, FunctionDeclaration):
            return f"user:function:{node.name}:{self.index.id_for(node)}"
        if isinstance(node, MethodDeclaration):
            return f"user:method:{node.name}:{self.index.id_for(node)}"
        if isinstance(node, TypeDeclaration):
            return f"user:type:{node.name}:{self.index.id_for(node)}"
        if isinstance(node, EnumDeclaration):
            return f"user:enum:{node.name}:{self.index.id_for(node)}"
        if isinstance(node, (VarDeclaration, Parameter, FieldDeclaration, TupleTarget, EnumMember)):
            target = self._declaration_target(node)
            return f"user:{node.kind.lower()}:{target}:{self.index.id_for(node)}"
        return None

    @staticmethod
    def _declaration_target(node: ASTNode) -> str | None:
        if isinstance(
            node,
            (
                VarDeclaration,
                FunctionDeclaration,
                MethodDeclaration,
                TypeDeclaration,
                EnumDeclaration,
                Parameter,
                FieldDeclaration,
                TupleTarget,
                EnumMember,
            ),
        ):
            return node.name
        if isinstance(node, TupleDeclaration):
            return ",".join(item.name for item in node.targets)
        if isinstance(node, Reassignment):
            return callee_name(node.target)
        if isinstance(node, ForRangeStructure):
            return node.variable
        if isinstance(node, ForInStructure):
            return ",".join(node.target.names)
        return None

    def _semantic_rule_ids(self, node: ASTNode, call: CallBindingFact | None) -> list[str]:
        version = self.version_context.pine_version
        rules: list[str] = []
        if isinstance(node, BinaryExpr):
            operator_name = {
                "+": "add",
                "-": "subtract",
                "*": "multiply",
                "/": "division",
                "%": "remainder",
                "and": "logical_and",
                "or": "logical_or",
                "==": "equal",
                "!=": "not_equal",
                "<": "less",
                "<=": "less_equal",
                ">": "greater",
                ">=": "greater_equal",
            }.get(node.op, node.op)
            rules.append(f"operator.{operator_name}.v{version}")
            left = self.engine.infer_type(node.left)
            right = self.engine.infer_type(node.right)
            if (
                node.op == "/"
                and left == right == "int"
                and {
                    self.engine.infer_qualifier(node.left),
                    self.engine.infer_qualifier(node.right),
                }
                <= {"const"}
            ):
                rules.append(f"operator.division.const_int.v{version}")
            if node.op in {"and", "or"}:
                key = "logical_and" if node.op == "and" else "logical_or"
                rules.append(self.policy.rule_id(key))
        elif isinstance(node, UnaryExpr):
            rules.append(f"operator.unary.{node.op}.v{version}")
        elif isinstance(node, ConditionalExpr):
            rules.append(f"control.condition.v{version}")
            rules.append(self.policy.rule_id("ternary"))
        elif isinstance(node, OnceStructure):
            rules.append(f"control.once.v{version}")
        elif isinstance(node, (IfStructure, WhileStructure)):
            rules.append(f"control.condition.v{version}")
        elif isinstance(node, ForRangeStructure):
            rules.append(self.policy.rule_id("for_range_end"))
        elif isinstance(node, ForInStructure):
            rules.append(f"control.for_in.v{version}")
        if call is not None:
            rules.append(f"call.signature.v{version}")
            if call.callee.startswith("request."):
                rules.append(self.policy.rule_id("request_default"))
            if call.callee in {"security", "request.security"}:
                rules.append(self.policy.rule_id("security_lookahead_default"))
            if call.callee.startswith("strategy."):
                rules.append(f"strategy.static.{call.callee.removeprefix('strategy.')}.v{version}")
        return rules

    def _index_constant_functions(self) -> None:
        assert self.index is not None
        if self.version_context.pine_version not in (5, 6):
            return
        owner = self.model.callable_context
        reassigned = owner.reassigned_globals if owner is not None else None
        visible: dict[str, VarDeclaration] = {}
        program = self.index.nodes[0]
        assert isinstance(program, Program)
        for declaration in program.items:
            if isinstance(declaration, (FunctionDeclaration, VarDeclaration)):
                self._constant_global_scopes[self.index.id_for(declaration)] = dict(visible)
            if isinstance(declaration, VarDeclaration):
                if (
                    declaration.mode is None
                    and declaration.explicit_qualifier in (None, "const")
                    and reassigned is not None
                    and id(declaration) not in reassigned
                    and self.model.node_qualifiers.get(id(declaration.initializer)) == "const"
                    and self.model.node_types.get(id(declaration.initializer))
                    in {"int", "float", "bool"}
                ):
                    visible[declaration.name] = declaration
        for node in self.index.nodes:
            if isinstance(node, FunctionDeclaration):
                identity = f"user:function:{node.name}:{self.index.id_for(node)}"
                self._constant_functions[identity] = node
            binding = self._call_bindings.get(id(node))
            if binding is not None and binding.call_form == "USER_FUNCTION":
                current: ASTNode | None = node
                while current is not None:
                    if isinstance(current, Expression):
                        self._constant_roots.add(id(current))
                    current = self.index.parent_for(current)

    def _constant_function_for_call(
        self,
        node: CallExpr,
        binding: CallBindingFact,
        context: const_functions.ConstantContext | None = None,
    ) -> FunctionDeclaration | None:
        assert self.index is not None
        declaration = self._constant_functions.get(binding.symbol_id or "")
        proof = self._constant_call_proof(node, context)
        contextual = context is not None and (
            bool(context.proof_stack)
            or bool(context.frames and context.frames[-1].proof is not None)
        )
        qualifier = (
            proof.qualifier
            if contextual and proof is not None
            else self.model.node_qualifiers.get(id(node))
        )
        dtype = (
            proof.type_name
            if contextual and proof is not None
            else self.model.node_types.get(id(node))
        )
        if (
            self.version_context.pine_version not in (5, 6)
            or binding.resolution_status != "RESOLVED"
            or binding.call_form != "USER_FUNCTION"
            or binding.stateful
            or declaration is None
            or declaration.is_exported
            or binding.overload_id != f"{binding.symbol_id}#signature"
            or qualifier != "const"
            or dtype not in {"int", "float", "bool"}
            or proof is not None
            and (
                proof.symbol_id != binding.symbol_id
                or proof.qualifier != "const"
                or proof.call_id != self.index.id_for(node)
            )
        ):
            return None
        # This completed declaration fact is checked against its source span;
        # it is not a global value lookup or a lexical-variable resolver.
        symbol = self.model.symbols.get(declaration.name)
        if symbol is None or symbol.declared_at != declaration.span:
            return None
        if any(p.type_ref is None for p in declaration.parameters):
            if proof is None or proof.qualifier != "const":
                return None
        elif symbol.qualifier != "const":
            return None
        return declaration

    def _constant_call_proof(self, node: CallExpr, context: const_functions.ConstantContext | None):
        owner = self.model.callable_context
        if owner is None:
            return None
        parent = None
        if context is not None:
            if context.proof_stack:
                parent = context.proof_stack[-1]
            elif context.frames:
                parent = context.frames[-1].proof
        return (
            owner.from_parent(node, parent)
            if parent is not None
            else owner.infer_call(node, self.engine)
        )

    @staticmethod
    def _constant_argument_qualifier(
        node: Expression, original: str | None, context: const_functions.ConstantContext | None
    ) -> str | None:
        if context is None:
            return original
        proof = (
            context.proof_stack[-1]
            if context.proof_stack
            else (context.frames[-1].proof if context.frames else None)
        )
        return proof.node_qualifiers.get(id(node), original) if proof is not None else original

    def _constant_global_for(
        self, name: str, context: const_functions.ConstantContext
    ) -> VarDeclaration | None:
        scope = (
            context.scope_stack[-1]
            if context.scope_stack
            else (context.frames[-1].declaration_id if context.frames else None)
        )
        return self._constant_global_scopes.get(scope or "", {}).get(name)

    def _constant_global_is_pure(
        self, declaration: VarDeclaration, context: const_functions.ConstantContext
    ) -> bool:
        assert self.index is not None
        identity = self.index.id_for(declaration)
        if not context.charge() or identity in context.global_active:
            return False
        context.global_active.add(identity)
        context.scope_stack.append(identity)
        context.proof_stack.append(None)
        try:
            return self._constant_expression_is_pure(declaration.initializer, set(), context)
        finally:
            context.proof_stack.pop()
            context.scope_stack.pop()
            context.global_active.remove(identity)

    def _evaluate_constant_global(
        self, declaration: VarDeclaration, context: const_functions.ConstantContext
    ) -> tuple[bool, Any]:
        assert self.index is not None
        identity = self.index.id_for(declaration)
        if not context.charge() or identity in context.global_active:
            return False, None
        context.global_active.add(identity)
        context.scope_stack.append(identity)
        context.frames.append(const_functions.ConstantFrame(identity, {}))
        context.proof_stack.append(None)
        try:
            return self._evaluate_const(declaration.initializer, context)
        finally:
            context.proof_stack.pop()
            context.frames.pop()
            context.scope_stack.pop()
            context.global_active.remove(identity)

    def _constant_builtin(self, binding: CallBindingFact) -> bool:
        if binding.resolution_status != "RESOLVED" or binding.stateful:
            return False
        symbol = binding.symbol_id
        if symbol in {"pine:function:int", "pine:function:float"}:
            return binding.call_form == "FUNCTION" and binding.overload_id == f"{symbol}#canonical"
        if (
            symbol
            not in {
                "pine:function:math.round",
                "pine:function:math.abs",
                "pine:function:math.ceil",
                "pine:function:math.floor",
                "pine:function:math.sqrt",
                "pine:function:math.min",
                "pine:function:math.max",
            }
            or binding.call_form != "NAMESPACE_FUNCTION"
            or self.version_context.pine_version not in (5, 6)
        ):
            return False
        overloads = {f"{symbol}#canonical"}
        if symbol in {"pine:function:math.round", "pine:function:math.abs"}:
            overloads.add(f"{symbol}#overload:0")
        return binding.overload_id in overloads

    def _constant_expression_is_pure(
        self, expression: Expression, names: set[str], context: const_functions.ConstantContext
    ) -> bool:
        pending = [expression]
        while pending:
            node = pending.pop()
            if not context.charge():
                return False
            if isinstance(node, Literal):
                if not const_functions.supported_scalar(node.value):
                    return False
            elif isinstance(node, Identifier):
                if node.name not in names:
                    global_declaration = self._constant_global_for(node.name, context)
                    if global_declaration is None or not self._constant_global_is_pure(
                        global_declaration, context
                    ):
                        return False
            elif isinstance(node, UnaryExpr) and node.op in {"+", "-", "not"}:
                pending.append(node.operand)
            elif isinstance(node, BinaryExpr) and node.op in {
                "+",
                "-",
                "*",
                "/",
                "==",
                "!=",
                "<",
                "<=",
                ">",
                ">=",
                "and",
                "or",
            }:
                pending.extend((node.right, node.left))
            elif isinstance(node, ConditionalExpr):
                # Every guard and branch is inspected, including unselected code.
                pending.extend((node.if_false, node.if_true, node.condition))
            elif isinstance(node, CallExpr):
                binding = self._call_bindings.get(id(node))
                if binding is None:
                    return False
                if binding.call_form == "USER_FUNCTION":
                    declaration = self._constant_function_for_call(node, binding, context)
                    if declaration is None or not self._constant_function_is_pure(
                        declaration, context, self._constant_call_proof(node, context)
                    ):
                        return False
                elif not self._constant_builtin(binding):
                    return False
                for argument in node.arguments:
                    if not context.charge():
                        return False
                    pending.append(argument.value)
            else:
                return False
        return True

    def _constant_function_is_pure(
        self,
        declaration: FunctionDeclaration,
        context: const_functions.ConstantContext,
        proof=None,
    ) -> bool:
        assert self.index is not None
        identity = self.index.id_for(declaration)
        cache_identity = identity if proof is None else repr(proof.context_key)
        if not context.charge() or identity in context.purity_active:
            return False
        if cache_identity in context.work.purity:
            return context.work.purity[cache_identity]
        if (
            len(context.purity_active) >= const_functions.MAX_FUNCTION_DEPTH
            or not context.work.room()
        ):
            return False
        context.purity_active.add(identity)
        context.scope_stack.append(identity)
        context.proof_stack.append(proof)
        pure = False
        try:
            names: set[str] = set()
            for parameter in declaration.parameters:
                if not context.charge() or parameter.name in names:
                    return False
                names.add(parameter.name)
                if parameter.default_value is not None and not self._constant_expression_is_pure(
                    parameter.default_value, set(), context
                ):
                    return False
            body = declaration.body
            if isinstance(body, Expression):
                pure = self._constant_expression_is_pure(body, names, context)
                return pure
            if (
                not context.charge()
                or not body.statements
                or not isinstance(body.statements[-1], ExpressionStatement)
            ):
                return False
            for statement in body.statements:
                if not context.charge():
                    return False
                if isinstance(statement, VarDeclaration):
                    if (
                        statement.mode is not None
                        or statement.explicit_qualifier not in (None, "const")
                        or statement.name in names
                    ):
                        return False
                    if not self._constant_expression_is_pure(statement.initializer, names, context):
                        return False
                    names.add(statement.name)
                elif isinstance(statement, ExpressionStatement):
                    if not self._constant_expression_is_pure(statement.expression, names, context):
                        return False
                else:
                    return False
            pure = True
            return True
        finally:
            context.proof_stack.pop()
            context.scope_stack.pop()
            context.purity_active.remove(identity)
            if context.work.room():
                context.work.purity[cache_identity] = pure

    def _constant_user_arguments(
        self,
        node: CallExpr,
        binding: CallBindingFact,
        declaration: FunctionDeclaration,
        context: const_functions.ConstantContext,
    ) -> list[Any] | None:
        assert self.index is not None
        source = {self.index.id_for(argument): argument for argument in node.arguments}
        if tuple(source) != tuple(row.argument_node_id for row in binding.arguments):
            return None
        parameters = declaration.parameters
        values: dict[int, Any] = {}
        for row in binding.arguments:
            if not context.charge() or type(row.parameter_index) is not int:
                return None
            index = row.parameter_index
            if index < 0 or index >= len(parameters) or index in values:
                return None
            argument = source[row.argument_node_id]
            parameter = parameters[index]
            if (
                row.parameter_name != parameter.name
                or row.expected_type != self._parameter_entry(parameter)["type"]
                or self._constant_argument_qualifier(argument.value, row.actual_qualifier, context)
                != "const"
                or row.binding != ("named" if argument.name is not None else "positional")
                or argument.name is not None
                and argument.name != parameter.name
            ):
                return None
            known, value = self._evaluate_const(argument.value, context)
            if not known:
                return None
            values[index] = value
        for default in binding.defaults_applied:
            if not context.charge() or type(default.parameter_index) is not int:
                return None
            index = default.parameter_index
            if index < 0 or index >= len(parameters) or index in values:
                return None
            parameter = parameters[index]
            if (
                parameter.default_value is None
                or default.parameter_name != parameter.name
                or default.expected_type != self._parameter_entry(parameter)["type"]
            ):
                return None
            # Defaults belong to the declaration and cannot see a caller's locals.
            identity = self.index.id_for(declaration)
            context.frames.append(const_functions.ConstantFrame(identity, {}))
            context.scope_stack.append(identity)
            context.proof_stack.append(None)
            try:
                known, value = self._evaluate_const(parameter.default_value, context)
            finally:
                context.proof_stack.pop()
                context.scope_stack.pop()
                context.frames.pop()
            if (
                not known
                or default.default_known
                and (
                    type(default.default_value) is not type(value) or default.default_value != value
                )
            ):
                return None
            values[index] = value
        if set(values) != set(range(len(parameters))):
            return None
        return [values[index] for index in range(len(parameters))]

    def _evaluate_constant_function(
        self, node: CallExpr, binding: CallBindingFact, context: const_functions.ConstantContext
    ) -> tuple[bool, Any]:
        assert self.index is not None
        declaration = self._constant_function_for_call(node, binding, context)
        proof = self._constant_call_proof(node, context)
        if declaration is None or not self._constant_function_is_pure(declaration, context, proof):
            return False, None
        identity = self.index.id_for(declaration)
        if len(context.frames) >= const_functions.MAX_FUNCTION_DEPTH or any(
            frame.declaration_id == identity for frame in context.frames
        ):
            return False, None
        arguments = self._constant_user_arguments(node, binding, declaration, context)
        if arguments is None:
            return False, None
        key = (identity, tuple((type(value).__name__, value) for value in arguments))
        if key in context.work.results:
            return context.work.results[key]
        if not context.work.room():
            return False, None
        frame = const_functions.ConstantFrame(
            identity,
            {
                parameter.name: (self.index.id_for(parameter), value)
                for parameter, value in zip(declaration.parameters, arguments)
            },
            proof,
        )
        context.frames.append(frame)
        context.scope_stack.append(identity)
        context.proof_stack.append(proof)
        result: tuple[bool, Any] = (False, None)
        try:
            body = declaration.body
            if isinstance(body, Expression):
                result = self._evaluate_const(body, context)
            elif context.charge():
                for statement in body.statements:
                    if not context.charge():
                        result = False, None
                        break
                    if isinstance(statement, VarDeclaration):
                        known, value = self._evaluate_const(statement.initializer, context)
                        if not known:
                            result = False, None
                            break
                        frame.bindings[statement.name] = self.index.id_for(statement), value
                    elif isinstance(statement, ExpressionStatement):
                        result = self._evaluate_const(statement.expression, context)
                        if not result[0]:
                            break
                    else:
                        result = False, None
                        break
        finally:
            context.proof_stack.pop()
            context.scope_stack.pop()
            context.frames.pop()
        if context.work.room():
            context.work.results[key] = result
        return result

    def _const_value(self, node: Expression) -> Any | None:
        known, value = self._evaluate_const(node)
        return value if known else None

    def _evaluate_const(
        self, node: Expression, context: const_functions.ConstantContext | None = None
    ) -> tuple[bool, Any]:
        if context is None and id(node) in self._constant_roots:
            context = const_functions.ConstantContext(self._constant_work)
            if not self._constant_expression_is_pure(node, set(), context):
                return False, None
        if context is None:
            return self._admitted_numeric_result(node, self._evaluate_const_node(node, None))
        if not context.enter_expression():
            return False, None
        try:
            known, value = self._admitted_numeric_result(
                node, self._evaluate_const_node(node, context), context
            )
            return (
                (True, value)
                if known and const_functions.supported_scalar(value)
                else (False, None)
            )
        finally:
            context.expression_depth -= 1

    def _admitted_numeric_result(
        self,
        node: Expression,
        result: tuple[bool, Any],
        context: const_functions.ConstantContext | None = None,
    ) -> tuple[bool, Any]:
        """Consume the shared type owner's modern expression result, without resolving types."""
        known, value = result
        proof = (
            (
                context.proof_stack[-1]
                if context.proof_stack
                else (context.frames[-1].proof if context.frames else None)
            )
            if context is not None
            else None
        )
        dtype = (
            proof.node_types.get(id(node))
            if proof is not None
            else self.model.node_types.get(id(node))
        )
        if (
            self.version_context.pine_version in (5, 6)
            and known
            and type(value) is int
            and dtype == "float"
        ):
            try:
                value = float(value)
            except OverflowError:
                return False, None
        return known, value

    def _evaluate_const_node(
        self, node: Expression, context: const_functions.ConstantContext | None
    ) -> tuple[bool, Any]:
        if isinstance(node, Literal):
            return True, node.value
        if isinstance(node, Identifier) and context is not None:
            known, value = context.lookup(node.name)
            if known:
                return True, value
            declaration = self._constant_global_for(node.name, context)
            return (
                self._evaluate_constant_global(declaration, context)
                if declaration is not None
                else (False, None)
            )
        if isinstance(node, UnaryExpr):
            known, value = self._evaluate_const(node.operand, context)
            if not known:
                return False, None
            if context is not None and not (
                node.op in {"+", "-"}
                and const_functions.numeric(value)
                or node.op == "not"
                and type(value) is bool
            ):
                return False, None
            try:
                if node.op == "+":
                    return True, +value
                if node.op == "-":
                    return True, -value
                if node.op == "not":
                    return True, not bool(value)
            except (TypeError, ValueError):
                return False, None
        if isinstance(node, BinaryExpr):
            lk, left = self._evaluate_const(node.left, context)
            rk, right = self._evaluate_const(node.right, context)
            if not (lk and rk):
                return False, None
            if (
                self.version_context.pine_version == 6
                and node.op in {"==", "!=", "<", "<=", ">", ">="}
                and (left is None or right is None)
            ):
                return True, False
            if context is not None and not (
                node.op in {"+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">="}
                and const_functions.numeric(left)
                and const_functions.numeric(right)
                or node.op in {"==", "!=", "and", "or"}
                and type(left) is type(right) is bool
            ):
                return False, None
            try:
                if (
                    self.version_context.pine_version == 6
                    and node.op in {"==", "!=", "<", "<=", ">", ">="}
                    and const_functions.numeric(left)
                    and const_functions.numeric(right)
                ):
                    comparison = comparison_constant(left, right, node.op)
                    return (True, comparison) if comparison is not None else (False, None)
                if node.op == "+":
                    return True, left + right
                if node.op == "-":
                    return True, left - right
                if node.op == "*":
                    return True, left * right
                if node.op == "/":
                    if right == 0:
                        return False, None
                    if (
                        not self.policy.const_int_division_fractional
                        and isinstance(left, int)
                        and not isinstance(left, bool)
                        and isinstance(right, int)
                        and not isinstance(right, bool)
                    ):
                        return True, int(left / right)
                    return True, left / right
                if node.op == "%":
                    return True, left % right
                if node.op == "==":
                    return True, left == right
                if node.op == "!=":
                    return True, left != right
                if node.op == "<":
                    return True, left < right
                if node.op == "<=":
                    return True, left <= right
                if node.op == ">":
                    return True, left > right
                if node.op == ">=":
                    return True, left >= right
                if node.op == "and":
                    return True, bool(left) and bool(right)
                if node.op == "or":
                    return True, bool(left) or bool(right)
            except (ArithmeticError, TypeError, ValueError, OverflowError):
                return False, None
        if isinstance(node, ConditionalExpr):
            known, condition = self._evaluate_const(node.condition, context)
            if known and (context is None or type(condition) is bool):
                return self._evaluate_const(node.if_true if condition else node.if_false, context)
        if isinstance(node, CallExpr):
            binding = self._call_bindings.get(id(node))
            if context is not None and binding is not None and binding.call_form == "USER_FUNCTION":
                return self._evaluate_constant_function(node, binding, context)
            if (
                binding is None
                or binding.resolution_status != "RESOLVED"
                or binding.stateful
                or binding.call_form not in {"FUNCTION", "NAMESPACE_FUNCTION"}
            ):
                return False, None
            symbol = binding.symbol_id
            overloads = {f"{symbol}#canonical"}
            if symbol in {"pine:function:math.abs", "pine:function:math.round"}:
                overloads.add(f"{symbol}#overload:0")
            if binding.overload_id not in overloads:
                return False, None
            # Legacy unqualified math calls were not folded before this wave.
            # Exact producer resolution does not backport modern folding support.
            if symbol.startswith("pine:function:math.") and (
                self.version_context.pine_version not in (5, 6)
                or binding.call_form != "NAMESPACE_FUNCTION"
            ):
                return False, None
            values = self._bound_const_arguments(node, binding, context)
            if values is None:
                return False, None
            if context is not None and (
                not self._constant_builtin(binding)
                or not all(const_functions.numeric(value) for value in values)
            ):
                return False, None
            try:
                if symbol == "pine:function:math.round":
                    expected_names = (
                        ("number",)
                        if binding.overload_id == "pine:function:math.round#canonical"
                        else ("number", "precision")
                    )
                    names = tuple(
                        row.parameter_name
                        for row in sorted(
                            binding.arguments, key=lambda row: cast(int, row.parameter_index)
                        )
                    )
                    if names != expected_names or binding.defaults_applied:
                        return False, None
                    value = round_constant(*values)
                    return value is not None, value
                if symbol == "pine:function:int" and len(values) == 1:
                    return True, int(values[0])
                if symbol == "pine:function:float" and len(values) == 1:
                    return True, float(values[0])
                if symbol == "pine:function:bool" and len(values) == 1:
                    return True, bool(values[0])
                if symbol == "pine:function:string" and len(values) == 1:
                    return True, str(values[0])
                pure: dict[str, Callable[..., object]] = {
                    "pine:function:math.abs": abs,
                    "pine:function:math.ceil": math.ceil,
                    "pine:function:math.floor": math.floor,
                    "pine:function:math.sqrt": math.sqrt,
                    "pine:function:math.min": min,
                    "pine:function:math.max": max,
                }
                if symbol in pure:
                    return True, pure[symbol](*values)
            except (ArithmeticError, TypeError, ValueError, OverflowError):
                return False, None
        return False, None

    def _bound_const_arguments(
        self,
        node: CallExpr,
        binding: CallBindingFact,
        context: const_functions.ConstantContext | None = None,
    ) -> list[Any] | None:
        """Consume the already resolved parameter identities, including named order."""
        assert self.index is not None
        source = {self.index.id_for(argument): argument for argument in node.arguments}
        if tuple(source) != tuple(row.argument_node_id for row in binding.arguments):
            return None
        selected = self._constant_varargs.get(id(node))
        variadic_parameters = (
            selected[2]
            if selected is not None and selected[:2] == (binding.symbol_id, binding.overload_id)
            else frozenset()
        )
        values: dict[int, list[Any]] = {}
        consumed: set[str] = set()
        for row in binding.arguments:
            if context is not None and not context.charge():
                return None
            argument = source.get(row.argument_node_id)
            if (
                argument is None
                or row.argument_node_id in consumed
                or type(row.parameter_index) is not int
                or row.parameter_index < 0
                or not row.parameter_name
                or not row.expected_type
                or self._constant_argument_qualifier(argument.value, row.actual_qualifier, context)
                != "const"
                or row.binding not in {"named", "positional", "vararg"}
            ):
                return None
            declared_variadic = (row.parameter_index, row.parameter_name) in variadic_parameters
            expected_binding = (
                "named"
                if argument.name is not None
                else "vararg" if declared_variadic else "positional"
            )
            if row.binding != expected_binding or (
                argument.name is not None and argument.name != row.parameter_name
            ):
                return None
            if row.parameter_index in values and not (
                declared_variadic and row.binding == "vararg"
            ):
                return None
            known, value = self._evaluate_const(argument.value, context)
            if not known:
                return None
            values.setdefault(row.parameter_index, []).append(value)
            consumed.add(row.argument_node_id)
        for default in binding.defaults_applied:
            if context is not None and not context.charge():
                return None
            if (
                not default.default_known
                or type(default.parameter_index) is not int
                or default.parameter_index in values
                or default.parameter_index < 0
            ):
                return None
            values[default.parameter_index] = [default.default_value]
        if set(values) != set(range(len(values))):
            return None
        return [value for index in range(len(values)) for value in values[index]]

    def _diagnostic_rows(self) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for index, diagnostic in enumerate(self.model.diagnostics):
            rows.append({"diagnostic_id": f"d{index:08d}", **diagnostic.to_dict()})
        return tuple(rows)

    @staticmethod
    def _diagnostic_refs(node: ASTNode, diagnostics: tuple[dict[str, Any], ...]) -> list[str]:
        result: list[str] = []
        for row in diagnostics:
            span = row.get("span") or {}
            if (
                span.get("start_offset", -1) >= node.span.start_offset
                and span.get("end_offset", -1) <= node.span.end_offset
            ):
                result.append(str(row["diagnostic_id"]))
        return result

    def _coverage(
        self,
        facts: tuple[SemanticFact, ...],
        calls: tuple[CallBindingFact, ...],
    ) -> SemanticCoverage:
        assert self.index is not None
        fact_ids = {item.node_id for item in facts}
        expression_nodes = [
            node for node in self.index.nodes if self._classification(node) == "EXPRESSION"
        ]
        typed = [
            item
            for item in facts
            if item.classification == "EXPRESSION"
            and item.resolved_type is not None
            and item.resolved_type.base != "unknown"
        ]
        call_nodes = [node for node in self.index.nodes if isinstance(node, CallExpr)]
        resolved_calls = [item for item in calls if item.resolution_status == "RESOLVED"]
        call_ids = {item.node_id for item in resolved_calls}
        return SemanticCoverage(
            total_nodes=len(self.index.nodes),
            fact_nodes=len(facts),
            expression_nodes=len(expression_nodes),
            typed_expression_nodes=len(typed),
            call_nodes=len(call_nodes),
            resolved_call_nodes=len(resolved_calls),
            unresolved_calls=tuple(
                self.index.id_for(node)
                for node in call_nodes
                if self.index.id_for(node) not in call_ids
            ),
            missing_fact_nodes=tuple(
                self.index.id_for(node)
                for node in self.index.nodes
                if self.index.id_for(node) not in fact_ids
            ),
        )

    def _append_diagnostic(self, diagnostic: Diagnostic) -> None:
        key = (
            diagnostic.code,
            diagnostic.span.start_offset,
            diagnostic.span.end_offset,
            diagnostic.message,
        )
        existing = {
            (item.code, item.span.start_offset, item.span.end_offset, item.message)
            for item in self.model.diagnostics
        }
        if key not in existing:
            self.model.diagnostics.append(diagnostic)


__all__ = ["SemanticFactBuilder"]
