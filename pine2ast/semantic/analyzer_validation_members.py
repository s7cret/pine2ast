from __future__ import annotations

# mypy: ignore-errors

# ruff: noqa: F401,F403,F405

from collections.abc import Callable
from typing import Any, Optional, TypeAlias

from pine2ast.ast.base import ASTNode, Expression, Statement
from pine2ast.ast.types import TypeRef
from pine2ast.ast.nodes import (
    BinaryExpr,
    Block,
    BreakStatement,
    CallExpr,
    ConditionalExpr,
    ContinueStatement,
    DeclarationStatement,
    EnumDeclaration,
    ForInStructure,
    ForRangeStructure,
    FunctionDeclaration,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    IfStructure,
    ImportDeclaration,
    Literal,
    MemberAccessExpr,
    MethodDeclaration,
    Program,
    Reassignment,
    SwitchStructure,
    TupleDeclaration,
    TupleExpr,
    TypeDeclaration,
    FieldDeclaration,
    Parameter,
    UnaryExpr,
    VarDeclaration,
    WhileStructure,
)
from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.semantic.builtin_registry import (
    KNOWN_DEFERRED_NAMESPACE_MEMBERS,
    KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS,
    load_builtin_registry,
)
from pine2ast.semantic.model import SemanticModel
from pine2ast.semantic.type_helpers import (
    for_in_target_types,
    generic_type_parts,
    is_assignable_type,
    is_valid_map_key_type,
    split_type_args,
    tuple_element_types,
    type_ref_name,
)
from pine2ast.semantic.qualifier_infer import infer_qualifier
from pine2ast.semantic.qualifier_validation import qualifier_rank
from pine2ast.semantic.scopes import Scope, ScopeKind
from pine2ast.semantic.symbols import Symbol, SymbolKind
from pine2ast.semantic.type_infer import callee_name, infer_type
from pine2ast.semantic.signatures import SignatureResolver
from pine2ast.semantic.collection_signatures import (
    generic_constructor_expected_arity,
    is_collection_method,
    resolve_collection_call,
)
from pine2ast.semantic.inference import PineInferenceEngine, registry_entry_for_call
from pine2ast.semantic.passes import (
    BuiltinValidationPass,
    CollectionValidationPass,
    DeclarationCardinalityPass,
    DeclarationIndexPass,
    QualifierInferencePass,
    ScopeSymbolPass,
    StaticValidationPass,
    StrategyContextValidationPass,
    TypeInferencePass,
    UnsupportedFeatureExtractionPass,
)
from pine2ast.semantic.passes.export_policy import validate_export_policy
from pine2ast.semantic.passes.loop_control import validate_loop_control_statement
from pine2ast.semantic.passes.loop_dos import (
    _is_literal_true,
    _static_int_bound,
)
from pine2ast.semantic.pipeline import AnalyzerPassPipeline, PassResult


class AnalyzerMemberValidationMixin:
    """Focused semantic validation mixin extracted for Pine2AST 4.0."""

    def _member_owner_type(self, expr: MemberAccessExpr) -> str | None:
        if isinstance(expr.object, Identifier):
            sym = self._resolve(expr.object.name)
            return sym.type if sym is not None else None
        if isinstance(expr.object, MemberAccessExpr):
            return infer_type(expr.object, self.model.symbols)
        return None

    def _member_field_type(self, expr: MemberAccessExpr) -> str | None:
        owner_type = self._member_owner_type(expr)
        if not owner_type:
            return None
        sym = self._resolve(f"{owner_type}.{expr.member}")
        return sym.type if sym is not None else None

    def _validate_member_access(self, expr: MemberAccessExpr) -> None:
        if isinstance(expr.object, Identifier):
            owner_sym = self._resolve(expr.object.name)
            if owner_sym is not None and owner_sym.kind is SymbolKind.ENUM:
                if f"{expr.object.name}.{expr.member}" not in self.model.symbols:
                    self._diag(
                        Severity.ERROR,
                        codes.UNKNOWN_FIELD,
                        f"Unknown enum member {expr.member} for enum {expr.object.name}.",
                        expr.span,
                    )
                return
        owner_type = self._member_owner_type(expr)
        if owner_type not in self._udt_fields:
            return
        if self._member_field_type(expr) is None:
            self._diag(
                Severity.ERROR,
                codes.UNKNOWN_FIELD,
                f"Unknown field {expr.member} for type {owner_type}.",
                expr.span,
            )

    def _scope_kind(self, scope_id: int | None) -> ScopeKind | None:
        if scope_id is None:
            return None
        for scope in self.model.scopes:
            if scope.id == scope_id:
                return scope.kind
        return None
