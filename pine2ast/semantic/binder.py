from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Callable, Iterable, Mapping

from pine2ast.ast.base import ASTNode, Declaration, Expression, Statement
from pine2ast.ast.nodes import (
    BinaryExpr,
    Block,
    CallExpr,
    ConditionalExpr,
    EnumDeclaration,
    EnumMember,
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
from pine2ast.semantic.inference import PineInferenceEngine, registry_entry_for_call
from pine2ast.semantic.node_index import NodeIndex
from pine2ast.semantic.signatures import SignatureResolver
from pine2ast.policy import SemanticPolicy
from pine2ast.semantic.type_helpers import generic_type_parts, is_assignable_type, type_ref_name
from pine2ast.semantic.type_infer import callee_name
from pine2ast.semantic.values import expression_can_be_na
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
        self._coercions: dict[int, list[CoercionFact]] = {}
        self._declarations: dict[str, ASTNode] = {}

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
        self._propagate_user_statefulness(program)
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
        if isinstance(node, MethodDeclaration) and node.receiver_type is not None:
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

        if entry is not None:
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

        collection_resolution = resolve_collection_call(call, engine=self.engine)
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

        resolution = self.signatures.resolve_builtin(
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
            str(resolution.overload_id or f"{symbol_id}#canonical")
            if status == "RESOLVED"
            else None
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
        stateful = self._is_intrinsically_stateful(lookup_name, entry)
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
            receiver_base, _ = generic_type_parts(receiver_type or "")
            method_key = f"{receiver_base}.{call.callee.member}" if receiver_base else ""
            declaration = self._declarations.get(method_key) or self._declarations.get(
                call.callee.member
            )
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
                getattr(self.model.symbols.get(declaration.name), "type", None) or "unknown"
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
                    "required": field.default_value is None,
                }
                for field in declaration.fields
            ]
            return (
                raw_name,
                {
                    "name": raw_name,
                    "symbol_id": f"user:type:{declaration.name}:{self.index.id_for(declaration)}",
                    "parameters": parameters,
                    "returns": declaration.name,
                    "overload_id": f"user:type:{declaration.name}:{self.index.id_for(declaration)}#constructor",
                },
                call_form,
                receiver_type,
            )
        return None

    @staticmethod
    def _parameter_entry(parameter: Parameter) -> dict[str, Any]:
        return {
            "name": parameter.name,
            "type": type_ref_name(parameter.type_ref) if parameter.type_ref else "any",
            "qualifier_max": parameter.explicit_qualifier or "series",
            "required": parameter.default_value is None,
        }

    @staticmethod
    def _synthetic_symbol_id(call_form: str, name: str) -> str:
        return f"{call_form.lower()}:{name}"

    @staticmethod
    def _is_intrinsically_stateful(name: str, entry: Mapping[str, Any]) -> bool:
        if bool(entry.get("stateful")) or bool(entry.get("side_effect")):
            return True
        return name.startswith(("ta.", "request.", "strategy.", "alert"))

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
            item.name: item
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
                    if binding.stateful or binding.callee in stateful_names:
                        stateful_names.add(name)
                        changed = True
                        break
        for object_id, binding in list(self._call_bindings.items()):
            if binding.callee in stateful_names and not binding.stateful:
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

    def _const_value(self, node: Expression) -> Any | None:
        known, value = self._evaluate_const(node)
        return value if known else None

    def _evaluate_const(self, node: Expression) -> tuple[bool, Any]:
        if isinstance(node, Literal):
            return True, node.value
        if isinstance(node, UnaryExpr):
            known, value = self._evaluate_const(node.operand)
            if not known:
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
            lk, left = self._evaluate_const(node.left)
            rk, right = self._evaluate_const(node.right)
            if not (lk and rk):
                return False, None
            try:
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
            known, condition = self._evaluate_const(node.condition)
            if known:
                return self._evaluate_const(node.if_true if condition else node.if_false)
        if isinstance(node, CallExpr):
            name = callee_name(node.callee)
            values: list[Any] = []
            for argument in node.arguments:
                known, value = self._evaluate_const(argument.value)
                if not known:
                    return False, None
                values.append(value)
            try:
                if name == "int" and len(values) == 1:
                    return True, int(values[0])
                if name == "float" and len(values) == 1:
                    return True, float(values[0])
                if name == "bool" and len(values) == 1:
                    return True, bool(values[0])
                if name == "string" and len(values) == 1:
                    return True, str(values[0])
                pure: dict[str, Callable[..., object]] = {
                    "math.abs": abs,
                    "math.ceil": math.ceil,
                    "math.floor": math.floor,
                    "math.sqrt": math.sqrt,
                    "math.round": round,
                    "math.min": min,
                    "math.max": max,
                }
                if name in pure:
                    return True, pure[name](*values)
            except (ArithmeticError, TypeError, ValueError, OverflowError):
                return False, None
        return False, None

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
