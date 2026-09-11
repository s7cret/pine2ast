"""Structural contract shared by the semantic-analyzer mixins.

The analyzer is deliberately split into focused mixins.  A mixin cannot inherit
from :class:`SemanticAnalyzer` without creating an import cycle, so this
protocol records the state and cross-mixin operations each fragment may use.
It gives MyPy a real composition boundary instead of suppressing errors at the
file level.
"""

from __future__ import annotations

from typing import Any, Protocol

from pine2ast.ast.base import ASTNode, Expression, Statement
from pine2ast.ast.nodes import (
    Block,
    CallExpr,
    FieldDeclaration,
    MemberAccessExpr,
    Parameter,
    Program,
)
from pine2ast.ast.types import TypeRef
from pine2ast.diagnostics import Severity
from pine2ast.lexer.token import SourceSpan
from pine2ast.policy import SemanticPolicy
from pine2ast.semantic.inference import PineInferenceEngine
from pine2ast.semantic.model import SemanticModel
from pine2ast.semantic.pipeline import PassResult
from pine2ast.semantic.scopes import Scope, ScopeKind
from pine2ast.semantic.symbols import Symbol, SymbolKind
from pine2ast.versioning import PineVersionContext


class AnalyzerMixinHost(Protocol):
    """State and operations available to every semantic analyzer mixin."""

    version_context: PineVersionContext
    registry: dict[str, Any]
    policy: SemanticPolicy
    model: SemanticModel
    inference: PineInferenceEngine
    max_diagnostics: int
    strict_builtin_namespaces: bool
    loop_max_iterations: int
    scope_stack: list[Scope]
    next_symbol_id: int
    loop_depth: int
    _static_loop_bounds: list[int | None]
    local_depth: int
    function_depth: int
    _predeclared_nodes: set[int]
    _function_params: dict[str, list[Parameter]]
    _user_method_params: dict[tuple[str, str], list[Parameter]]
    _method_receivers: dict[str, str | set[str]]
    _builtin_method_params: dict[str, dict[str, list[Parameter]]]
    _external_aliases: set[str]
    _udt_fields: dict[str, list[FieldDeclaration]]
    _enum_members: dict[str, set[str]]
    _symbol_history: dict[str, list[Symbol]]
    _script_type: str | None
    _reassigned_names: set[str]
    _reassigned_declarations: frozenset[int]
    pass_results: tuple[PassResult, ...]

    def analyze(self, program: Program) -> SemanticModel: ...

    def _infer_type(self, expr: Expression | None) -> str: ...

    def _infer_qualifier(self, expr: Expression | None) -> str: ...

    def _infer_value(self, expr: Expression | None) -> Any: ...

    def _registry_entry_for_call(self, callee: Expression) -> tuple[str, dict[str, Any] | None]: ...

    def _collect_reassigned_names(self, node: ASTNode) -> set[str]: ...

    def _is_reassigned_declaration(self, node: Any) -> bool: ...

    def _assignment_root(self, target: Expression) -> str | None: ...

    def _predeclare_globals(self, items: list[Statement]) -> None: ...

    def _register_builtins(self) -> None: ...

    def _visit_statement(self, node: Statement | ASTNode) -> None: ...

    def _visit_expr(self, expr: Expression) -> None: ...

    def _visit_body(self, body: Block | Expression) -> None: ...

    def _visit_block(
        self,
        block: Block,
        *,
        kind: ScopeKind = ScopeKind.LOCAL_BLOCK,
        non_na_symbols: set[str] | None = None,
        non_na_paths: set[str] | None = None,
    ) -> None: ...

    def _visit_callee(self, expr: Expression) -> None: ...

    def _resolve_assignable(self, expr: Expression) -> Symbol | None: ...

    def _member_root(self, expr: Expression) -> str | None: ...

    def _assignable_name(self, expr: Expression) -> str | None: ...

    def _define(
        self,
        name: str,
        kind: SymbolKind,
        span: SourceSpan,
        typ: str | None,
        qualifier: str | None,
        *,
        allow_existing: bool = False,
    ) -> Symbol | None: ...

    def _resolve(self, name: str | None) -> Symbol | None: ...

    def _push_scope(
        self,
        kind: ScopeKind,
        *,
        non_na_symbols: set[str] | None = None,
        non_na_paths: set[str] | None = None,
    ) -> Scope: ...

    def _pop_scope(self) -> None: ...

    def _has_diag(self, code: str, span: SourceSpan) -> bool: ...

    def _diag(
        self,
        severity: Severity,
        code: str,
        message: str,
        span: SourceSpan,
    ) -> None: ...

    def _qualifier_rank(self, qualifier: str | None) -> int: ...

    def _validate_qualifier_assignment(
        self,
        expected_max: str | None,
        actual: str | None,
        span: SourceSpan,
        context: str,
    ) -> None: ...

    def _validate_binary_expr(self, expr: Any) -> None: ...

    def _type_ref_name(self, type_ref: TypeRef | None) -> str: ...

    def _for_in_target_types(self, iterable_type: str, target_count: int) -> list[str]: ...

    def _split_type_args(self, inner: str) -> list[str]: ...

    def _validate_type_ref(self, type_ref: TypeRef | None) -> None: ...

    def _tuple_element_types(self, typ: str) -> list[str]: ...

    def _generic_type_parts(self, typ: str | None) -> tuple[str | None, list[str]]: ...

    def _is_assignable_type(self, expected: str | None, actual: str | None) -> bool: ...

    def _uses_v6_bool_rules(self) -> bool: ...

    def _is_bool_target_type(self, typ: str | None) -> bool: ...

    def _expr_can_be_na(self, expr: Expression) -> bool: ...

    def _validate_bool_cannot_be_na(self, expected: str | None, expr: Expression) -> None: ...

    def _validate_argument_type(
        self, callee: str, arg: Any, param: dict[str, Any] | None
    ) -> None: ...

    def _strategy_constant_members(self) -> set[str]: ...

    def _strategy_state_members(self) -> set[str]: ...

    def _validate_strategy_namespace_usage(
        self, name: str, span: SourceSpan, *, is_call: bool
    ) -> None: ...

    def _builtin_namespace_root(self, name: str) -> str | None: ...

    def _is_known_deferred_or_unsupported_builtin(self, name: str) -> bool: ...

    def _validate_known_deferred_or_unsupported_builtin(
        self, name: str, entry: dict[str, Any] | None, expr: CallExpr
    ) -> None: ...

    def _validate_unknown_builtin_namespace_member(
        self, name: str, entry: dict[str, Any] | None, expr: CallExpr
    ) -> None: ...

    def _validate_unknown_builtin_namespace_value(self, expr: MemberAccessExpr) -> None: ...

    def _registry_exposes_value_or_namespace(self, name: str) -> bool: ...

    def _exists_in_v6_registry(self, name: str, *, kind: str) -> bool: ...

    def _is_v6_only_namespace_root(self, root: str) -> bool: ...

    def _validate_strategy_call_script_type(self, name: str, expr: CallExpr) -> None: ...

    def _validate_udt_constructor_call(self, expr: CallExpr) -> None: ...

    def _is_builtin_namespace_root(self, expr: Expression) -> bool: ...

    def _is_external_alias_root(self, expr: Expression) -> bool: ...

    def _is_collection_method(self, receiver_type: str | None, member: str) -> bool: ...

    def _validate_member_call_target(self, name: str, expr: CallExpr) -> None: ...

    def _validate_method_call(self, expr: CallExpr) -> None: ...

    def _validate_user_function_call(self, name: str, expr: CallExpr) -> None: ...

    def _validate_param_call(
        self,
        name: str,
        params: list[Parameter],
        args: list[Any],
        span: SourceSpan,
        *,
        kind: str,
    ) -> None: ...

    def _validate_builtin_call(
        self, name: str, entry: dict[str, Any] | None, expr: CallExpr
    ) -> None: ...

    def _param_removed_in_current_version(self, param: dict[str, Any]) -> bool: ...

    def _validate_argument_qualifier(
        self, callee: str, arg: Any, param: dict[str, Any] | None
    ) -> None: ...

    def _collection_value_type(
        self, collection_type: str | None, *, key: bool = False
    ) -> str | None: ...

    def _diag_collection_value(
        self,
        name: str,
        expected: str | None,
        actual: str,
        span: SourceSpan,
        value: Expression,
    ) -> None: ...

    def _validate_collection_mutation_call(self, name: str, expr: CallExpr) -> None: ...

    def _validate_generic_constructor_call(self, name: str, expr: CallExpr) -> None: ...

    def _member_owner_type(self, expr: MemberAccessExpr) -> str | None: ...

    def _member_field_type(self, expr: MemberAccessExpr) -> str | None: ...

    def _validate_member_access(self, expr: MemberAccessExpr) -> None: ...

    def _scope_kind(self, scope_id: int | None) -> ScopeKind | None: ...
