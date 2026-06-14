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


class AnalyzerCollectionValidationMixin:
    """Focused semantic validation mixin extracted for Pine2AST 4.0."""

    def _collection_value_type(
        self, collection_type: str | None, *, key: bool = False
    ) -> str | None:
        if not collection_type:
            return None
        base, args = self._generic_type_parts(collection_type)
        if base in {"array", "matrix"} and args:
            return args[0]
        if base == "map" and len(args) >= 2:
            return args[0] if key else args[1]
        return None

    def _diag_collection_value(
        self, name: str, expected: str | None, actual: str, span: SourceSpan, value: Expression
    ) -> None:
        if expected and not self._is_assignable_type(expected, actual):
            self._diag(
                Severity.ERROR,
                codes.COLLECTION_ELEMENT_TYPE,
                f"Collection mutation {name} expects element/value type {expected}, got {actual}.",
                span,
            )
        self._validate_bool_cannot_be_na(expected, value)

    def _validate_collection_mutation_call(self, name: str, expr: CallExpr) -> None:
        """Validate collection function/method forms with receiver-specialized signatures.

        The bundled builtin registry intentionally keeps some generic collection
        entries broad or pending. Release 4.0 owns these checks here so array/matrix/map
        method forms (``xs.get(i)``, ``m.contains(k)``, ``mx.set(r,c,v)``) receive
        the same type diagnostics as function forms.
        """

        resolution = resolve_collection_call(expr, engine=self.inference)
        if resolution is None:
            return
        for issue in resolution.issues:
            self._diag(issue.severity, issue.code, issue.message, issue.span)
        for binding in resolution.bindings:
            if binding.parameter is not None:
                self._validate_bool_cannot_be_na(
                    binding.parameter.type_name, binding.argument.value
                )

    def _validate_generic_constructor_call(self, name: str, expr: CallExpr) -> None:
        # array.new<float>(size, initial), matrix.new<float>(rows, cols, initial), map.new<string,float>()
        if not isinstance(expr.callee, GenericInstantiationExpr) or not expr.callee.type_args:
            return
        base = callee_name(expr.callee.base)
        type_args = [self._type_ref_name(t) for t in expr.callee.type_args]
        expected_arity = generic_constructor_expected_arity(base)
        if expected_arity is not None and len(type_args) != expected_arity:
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Generic constructor {base}<...>() expects {expected_arity} type argument(s), got {len(type_args)}.",
                expr.callee.span,
            )
        if base == "array.new" and len(expr.arguments) >= 2 and len(type_args) >= 1:
            expected = type_args[0]
            actual = infer_type(expr.arguments[1].value, self.model.symbols)
            self._diag_collection_value(
                name,
                expected,
                actual,
                expr.arguments[1].span,
                expr.arguments[1].value,
            )
        elif base == "matrix.new" and len(expr.arguments) >= 3 and len(type_args) >= 1:
            expected = type_args[0]
            actual = infer_type(expr.arguments[2].value, self.model.symbols)
            self._diag_collection_value(
                name,
                expected,
                actual,
                expr.arguments[2].span,
                expr.arguments[2].value,
            )
        elif base == "map.new" and len(type_args) >= 1:
            key_type = type_args[0]
            if not is_valid_map_key_type(key_type, enum_types=self._enum_members.keys()):
                self._diag(
                    Severity.ERROR,
                    codes.COLLECTION_ELEMENT_TYPE,
                    f"Map key type must be a value or enum type, got {key_type}.",
                    expr.callee.type_args[0].span if expr.callee.type_args else expr.callee.span,
                )
