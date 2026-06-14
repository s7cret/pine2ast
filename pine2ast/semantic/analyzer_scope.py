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


class AnalyzerScopeMixin:
    """Implementation mixin split out of :mod:`pine2ast.semantic.analyzer`."""

    def _visit_callee(self, expr: Expression) -> None:
        # Validate the root of a call without treating every member segment as a standalone variable.
        if isinstance(expr, Identifier):
            if self._resolve(expr.name) is None and not expr.name.startswith("<"):
                self._diag(
                    Severity.ERROR,
                    codes.UNDECLARED_VARIABLE,
                    f"Use of undeclared function {expr.name}.",
                    expr.span,
                )
            return
        if isinstance(expr, GenericInstantiationExpr):
            self._visit_callee(expr.base)
            return
        if isinstance(expr, MemberAccessExpr):
            if isinstance(expr.object, Identifier):
                root = expr.object.name
                if self._resolve(root) is None and root not in self._external_aliases:
                    if self._is_v6_only_namespace_root(root):
                        self._diag(
                            Severity.WARNING,
                            codes.V6_ONLY_BUILTIN,
                            f"Namespace {root} is not available in Pine v5; it was added in v6.",
                            expr.object.span,
                        )
                    else:
                        self._diag(
                            Severity.ERROR,
                            codes.UNDECLARED_VARIABLE,
                            f"Use of undeclared namespace/object {root}.",
                            expr.object.span,
                        )
            else:
                self._visit_expr(expr.object)

    def _resolve_assignable(self, expr: Expression) -> Symbol | None:
        if isinstance(expr, Identifier):
            return self._resolve(expr.name)
        if isinstance(expr, MemberAccessExpr):
            root = self._member_root(expr)
            sym = self._resolve(root) if root else None
            if sym is None and root in self._external_aliases:
                return Symbol(
                    -1,
                    root,
                    SymbolKind.IMPORT_ALIAS,
                    expr.span,
                    "external",
                    None,
                    self.scope_stack[-1].id,
                )
            return sym
        return None

    def _member_root(self, expr: Expression) -> str | None:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccessExpr):
            return self._member_root(expr.object)
        return None

    def _assignable_name(self, expr: Expression) -> str | None:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccessExpr):
            root = self._member_root(expr)
            return root + ".<member>" if root else None
        return None

    def _define(
        self,
        name: str,
        kind: SymbolKind,
        span: SourceSpan,
        typ: str | None,
        qualifier: str | None,
        *,
        allow_existing: bool = False,
    ) -> Symbol | None:
        scope = self.scope_stack[-1]
        if name in scope.symbols and not allow_existing:
            # Allow user variables to shadow builtin namespaces/objects
            # (e.g. `text` is both a namespace and a common variable name)
            # but NOT import aliases (import ... as math should error)
            existing = self.model.symbols.get(name)
            if (
                existing is not None
                and existing.kind == SymbolKind.BUILTIN
                and kind == SymbolKind.VARIABLE
            ):
                pass  # shadow allowed
            else:
                self._diag(
                    Severity.ERROR,
                    codes.REDECLARATION,
                    f"Symbol {name} is already declared in this scope.",
                    span,
                )
                return None
        previous = self.model.symbols.get(name)
        sym = Symbol(self.next_symbol_id, name, kind, span, typ, qualifier, scope.id)
        self.next_symbol_id += 1
        scope.symbols[name] = sym.id
        if previous is not None and previous.id != sym.id:
            self._symbol_history.setdefault(name, []).append(previous)
        self.model.symbols[name] = sym
        return sym

    def _resolve(self, name: str | None) -> Symbol | None:
        if not name:
            return None
        for scope in reversed(self.scope_stack):
            if name in scope.symbols:
                sid = scope.symbols[name]
                for sym in self.model.symbols.values():
                    if sym.id == sid:
                        return sym
        resolved = self.model.symbols.get(name)
        if resolved is None:
            return None
        kind = self._scope_kind(resolved.scope_id)
        if kind in {ScopeKind.GLOBAL, ScopeKind.TYPE_DECL, ScopeKind.ENUM_DECL}:
            return resolved
        if resolved.kind in {
            SymbolKind.BUILTIN,
            SymbolKind.TYPE,
            SymbolKind.ENUM,
            SymbolKind.ENUM_MEMBER,
            SymbolKind.IMPORT_ALIAS,
            SymbolKind.FUNCTION,
            SymbolKind.METHOD,
        }:
            return resolved
        return None

    def _push_scope(
        self,
        kind: ScopeKind,
        *,
        non_na_symbols: set[str] | None = None,
        non_na_paths: set[str] | None = None,
    ) -> Scope:
        parent_id = self.scope_stack[-1].id if self.scope_stack else None
        scope = Scope(len(self.model.scopes) + 1, kind, parent_id)
        paths = set(non_na_paths or set()) | set(non_na_symbols or set())
        if paths:
            scope.non_na_symbols.update({path for path in paths if "." not in path})
            self.model.non_na_scopes[scope.id] = set(scope.non_na_symbols)
            self.model.non_na_paths[scope.id] = set(paths)
        self.model.scopes.append(scope)
        self.scope_stack.append(scope)
        return scope

    def _pop_scope(self) -> None:
        scope = self.scope_stack.pop()
        # Keep exported/global and qualified type/member symbols visible, but make local-only
        # variables disappear after their block/function scope. When a local declaration shadows
        # an outer symbol with the same name, restore the outer symbol instead of leaving the
        # shadow in the public SemanticModel.symbols view.
        for name, sid in list(scope.symbols.items()):
            current = self.model.symbols.get(name)
            if current is None or current.id != sid:
                continue
            keep = scope.kind is ScopeKind.GLOBAL or (
                scope.kind is ScopeKind.TYPE_DECL and "." in name
            )
            if keep:
                continue
            history = self._symbol_history.get(name)
            if history:
                self.model.symbols[name] = history.pop()
                if not history:
                    self._symbol_history.pop(name, None)

    def _has_diag(self, code: str, span: SourceSpan) -> bool:
        return any(
            diag.code == code
            and diag.span.start_offset == span.start_offset
            and diag.span.end_offset == span.end_offset
            for diag in self.model.diagnostics
        )

    def _diag(self, severity: Severity, code: str, message: str, span: SourceSpan) -> None:
        if len(self.model.diagnostics) < self.max_diagnostics:
            self.model.diagnostics.append(Diagnostic(severity, code, message, span))
