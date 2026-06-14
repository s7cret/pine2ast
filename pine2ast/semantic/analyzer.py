from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional, TypeAlias

from pine2ast.ast.base import ASTNode, Expression, Statement
from pine2ast.ast.types import TypeRef
from pine2ast.ast.nodes import (
    BinaryExpr,
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
from pine2ast.lexer.token import SourceSpan
from pine2ast.language_profiles import PineLanguageProfile, pine_language_profile
from pine2ast.semantic.builtin_registry import (
    load_builtin_registry,
)
from pine2ast.semantic.model import SemanticModel
from pine2ast.semantic.qualifier_infer import infer_qualifier
from pine2ast.semantic.scopes import Scope, ScopeKind
from pine2ast.semantic.symbols import Symbol, SymbolKind
from pine2ast.semantic.type_infer import infer_type
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
from pine2ast.semantic.passes.loop_control import validate_loop_control_statement
from pine2ast.semantic.pipeline import AnalyzerPassPipeline, PassResult
from pine2ast.semantic.analyzer_statements import AnalyzerStatementMixin
from pine2ast.semantic.analyzer_expressions import AnalyzerExpressionMixin
from pine2ast.semantic.analyzer_validation import AnalyzerValidationMixin
from pine2ast.semantic.analyzer_scope import AnalyzerScopeMixin

StatementHandler: TypeAlias = Callable[["SemanticAnalyzer", Any], None]
ExpressionHandler: TypeAlias = Callable[["SemanticAnalyzer", Any], None]


class SemanticAnalyzer(
    AnalyzerStatementMixin,
    AnalyzerExpressionMixin,
    AnalyzerValidationMixin,
    AnalyzerScopeMixin,
):
    def __init__(
        self,
        *,
        max_diagnostics: int = 200,
        strict_builtin_namespaces: bool = False,
        pine_version: int = 6,
        loop_max_iterations: int = 100_000,
        language_profile: PineLanguageProfile | None = None,
    ) -> None:
        # pine_version is normalized at construction time so all
        # downstream lookups (registry, method receivers, qualifier
        # checks) see a stable value. v5 loads the v5 subset of the
        # registry; v6 loads the full v6 set.
        normalized_version = 5 if pine_version == 5 else 6
        self.language_profile = language_profile or pine_language_profile(normalized_version)
        self.pine_version = self.language_profile.version
        self.registry = load_builtin_registry(pine_version=self.pine_version)
        self.model = SemanticModel()
        self.inference = PineInferenceEngine(
            symbols=self.model.symbols,
            pine_version=self.pine_version,
            registry=self.registry,
        )
        self.max_diagnostics = max_diagnostics
        self.strict_builtin_namespaces = strict_builtin_namespaces
        self.loop_max_iterations = loop_max_iterations
        self.scope_stack: list[Scope] = []
        self.next_symbol_id = 1
        self.loop_depth = 0
        # P2.1: parallel to loop_depth, this tracks the static
        # iteration bound of each enclosing for-range so a nested
        # for-range can cheaply check the product.
        # None = bound is not a literal (input/series/etc.).
        self._static_loop_bounds: list[Optional[int]] = []
        self.local_depth = 0
        self.function_depth = 0
        self._predeclared_nodes: set[int] = set()
        self._function_params: dict[str, list[Parameter]] = {}
        self._user_method_params: dict[str, list[Parameter]] = {}
        self._method_receivers: dict[str, str | set[str]] = {}
        self._builtin_method_params: dict[str, dict[str, list[Parameter]]] = {}
        self._external_aliases: set[str] = set()
        self._udt_fields: dict[str, list[FieldDeclaration]] = {}
        self._enum_members: dict[str, set[str]] = {}
        self._symbol_history: dict[str, list[Symbol]] = {}
        self._script_type: str | None = None
        self._reassigned_names: set[str] = set()
        self.pass_results: tuple[PassResult, ...] = ()

    def analyze(self, program: Program) -> SemanticModel:
        if program.version is not None and program.version != self.pine_version:
            # The Pine version annotation in the source overrides the
            # constructor default. Reload the registry to match — this
            # is what allows v5 scripts to be parsed with the v5 subset
            # of the builtin catalog, even if the caller passed
            # pine_version=6 to ParseOptions.
            normalized = 5 if program.version == 5 else 6
            self.language_profile = pine_language_profile(
                normalized,
                strict=self.language_profile.strict,
                compatibility_mode=self.language_profile.compatibility_mode,
            )
            self.pine_version = self.language_profile.version
            self.registry = load_builtin_registry(pine_version=self.pine_version)
            self.inference = PineInferenceEngine(
                symbols=self.model.symbols,
                pine_version=self.pine_version,
                registry=self.registry,
            )
        self._reassigned_names = self._collect_reassigned_names(program)
        self._push_scope(ScopeKind.GLOBAL)
        pipeline = AnalyzerPassPipeline(
            (
                DeclarationIndexPass(self),
                ScopeSymbolPass(self),
                TypeInferencePass(self),
                QualifierInferencePass(self),
                BuiltinValidationPass(self),
                CollectionValidationPass(self),
                StaticValidationPass(self),
                StrategyContextValidationPass(self),
                UnsupportedFeatureExtractionPass(self),
                DeclarationCardinalityPass(self),
            )
        )
        self.pass_results = pipeline.run(
            program, diagnostics_count=lambda: len(self.model.diagnostics)
        )
        self.model.pass_results = self.pass_results
        self._pop_scope()
        return self.model

    def _infer_type(self, expr: Expression | None) -> str:
        return self.inference.infer_type(expr)

    def _infer_qualifier(self, expr: Expression | None) -> str:
        return self.inference.infer_qualifier(expr)

    def _infer_value(self, expr: Expression | None):
        return self.inference.infer_value(expr)

    def _registry_entry_for_call(self, callee: Expression) -> tuple[str, dict | None]:
        return registry_entry_for_call(callee, self.registry)

    def _collect_reassigned_names(self, node: ASTNode) -> set[str]:
        names: set[str] = set()

        def visit(value: object) -> None:
            if isinstance(value, Reassignment):
                root = self._assignment_root(value.target)
                if root:
                    names.add(root)
            if isinstance(value, ASTNode):
                for attr in getattr(value, "__dataclass_fields__", ()):
                    visit(getattr(value, attr))
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(node)
        return names

    def _assignment_root(self, target: Expression) -> str | None:
        if isinstance(target, Identifier):
            return target.name
        if isinstance(target, MemberAccessExpr):
            return self._assignment_root(target.object)
        return None

    def _predeclare_globals(self, items: list[Statement]) -> None:
        for item in items:
            if isinstance(item, FunctionDeclaration):
                return_shape = self._body_return_shape(item.body) or "function"
                if (
                    self._define(item.name, SymbolKind.FUNCTION, item.span, return_shape, None)
                    is not None
                ):
                    self._predeclared_nodes.add(id(item))
                    self._function_params[item.name] = item.parameters
            elif isinstance(item, MethodDeclaration):
                return_shape = self._body_return_shape(item.body) or "method"
                if (
                    self._define(item.name, SymbolKind.METHOD, item.span, return_shape, None)
                    is not None
                ):
                    self._predeclared_nodes.add(id(item))
                    self._function_params[item.name] = item.parameters
                    self._user_method_params[item.name] = item.parameters
                    if item.receiver_type is not None:
                        self._method_receivers[item.name] = item.receiver_type.name
            elif isinstance(item, TypeDeclaration):
                if self._define(item.name, SymbolKind.TYPE, item.span, "type", None) is not None:
                    self._predeclared_nodes.add(id(item))
            elif isinstance(item, EnumDeclaration):
                if self._define(item.name, SymbolKind.ENUM, item.span, "enum", None) is not None:
                    self._predeclared_nodes.add(id(item))
                members: set[str] = set()
                for m in item.members:
                    if m.name in members:
                        continue
                    members.add(m.name)
                    self._define(
                        f"{item.name}.{m.name}",
                        SymbolKind.ENUM_MEMBER,
                        m.span,
                        item.name,
                        "const",
                        allow_existing=True,
                    )
                self._enum_members[item.name] = members
            elif isinstance(item, ImportDeclaration):
                alias = item.alias or item.library or item.owner or item.path
                if (
                    self._define(alias, SymbolKind.IMPORT_ALIAS, item.span, "external", None)
                    is not None
                ):
                    self._external_aliases.add(alias)
                    self._predeclared_nodes.add(id(item))

    def _register_builtins(self) -> None:
        zero = SourceSpan.zero()
        for ns in self.registry.get("namespaces", {}):
            self._define(ns, SymbolKind.BUILTIN, zero, None, None, allow_existing=True)
        for name in self.registry.get("types", {}):
            self._define(name, SymbolKind.TYPE, zero, "type", None, allow_existing=True)
        for name, meta in self.registry.get("variables", {}).items():
            self._define(
                name,
                SymbolKind.BUILTIN,
                zero,
                meta.get("type"),
                meta.get("qualifier"),
                allow_existing=True,
            )
        for name in self.registry.get("functions", {}):
            root = name.split(".", 1)[0]
            self._define(root, SymbolKind.BUILTIN, zero, None, None, allow_existing=True)
        # Register builtin methods from the methods section
        # Keys are "type.method" but _method_receivers uses just "method"
        for qualified_name, meta in self.registry.get("methods", {}).items():
            receiver_type = meta.get("receiver_type")
            # Extract just the method name (after last dot)
            short_name = (
                qualified_name.rsplit(".", 1)[-1] if "." in qualified_name else qualified_name
            )
            if receiver_type:
                if short_name in self._method_receivers:
                    existing = self._method_receivers[short_name]
                    if isinstance(existing, set):
                        existing.add(receiver_type)
                    else:
                        self._method_receivers[short_name] = {existing, receiver_type}
                else:
                    self._method_receivers[short_name] = receiver_type
            # Entries with _signature_pending=True are registration-only:
            # they tell the analyzer that the method exists for this receiver
            # (used in _validate_method_call receiver check) but lack full
            # parameters/returns. Do NOT register them in _builtin_method_params
            # because that would override the per-receiver inference rules
            # (e.g. array.get returns T, matrix.get returns T) with empty params.
            if meta.get("_signature_pending"):
                continue
            params = []
            for p in meta.get("parameters", []):
                type_ref = (
                    TypeRef(span=zero, name=p.get("type", "unknown")) if p.get("type") else None
                )
                params.append(
                    Parameter(
                        span=zero,
                        name=p.get("name", ""),
                        type_ref=type_ref,
                        explicit_qualifier=p.get("qualifier_max"),
                    )
                )
            # Store in _builtin_method_params keyed by (method, receiver_type)
            if short_name not in self._builtin_method_params:
                self._builtin_method_params[short_name] = {}
            self._builtin_method_params[short_name][receiver_type] = params
            # Also store in _function_params for backward compatibility (last wins)
            if short_name not in self._function_params:
                self._function_params[short_name] = params

    def _visit_statement(self, node: Statement | ASTNode) -> None:
        # Fast path: check by exact type first.
        handlers = _STATEMENT_HANDLERS
        handler = handlers.get(type(node))
        if handler is not None:
            handler(self, node)
            return
        # Slightly slower path: structural check for mixed-type groups.
        if isinstance(
            node, (IfStructure, SwitchStructure, ForRangeStructure, ForInStructure, WhileStructure)
        ):
            self._visit_structure(node)
            return
        if isinstance(node, (BreakStatement, ContinueStatement)):
            validate_loop_control_statement(self, node)
            return
        if hasattr(node, "expression"):
            self._visit_expr(node.expression)  # type: ignore[attr-defined]

    # -------------------------------------------------------------------------
    # Statement-kind handlers -- registered in _STATEMENT_HANDLERS dict.
    # Each receives (self, node).
    # -------------------------------------------------------------------------

    def _visit_expr(self, expr: Expression) -> None:
        self.model.node_types[id(expr)] = infer_type(expr, self.model.symbols)
        self.model.node_qualifiers[id(expr)] = infer_qualifier(expr, self.model.symbols)
        handler = _EXPR_HANDLERS.get(type(expr))
        if handler is not None:
            handler(self, expr)
            return
        # Structural group: control-flow expressions
        if isinstance(
            expr, (IfStructure, SwitchStructure, ForRangeStructure, ForInStructure, WhileStructure)
        ):
            self._visit_structure(expr)

    # -------------------------------------------------------------------------
    # Expression-kind handlers -- registered in _EXPR_HANDLERS dict.
    # Each receives (self, expr) and runs after node type/qualifier are set.
    # -------------------------------------------------------------------------

    # Type and qualifier validation for builtin calls is centralized
    # in SignatureResolver so CLI, OpenPine contract generation, and
    # future semantic passes share one binding/diagnostic path.

    # If there is no shadowed symbol to restore, keep the local symbol in
    # SemanticModel.symbols for compatibility/introspection. Name resolution
    # below deliberately ignores out-of-scope local symbols, so this does not
    # leak locals into later semantic checks.


# ------------------------------------------------------------------
# Dispatch table for _visit_statement.  Populated by class body at
# module level so unbound references to SemanticAnalyzer._s_xxx resolve.
# ------------------------------------------------------------------
_STATEMENT_HANDLERS: dict[type, StatementHandler] = {
    DeclarationStatement: SemanticAnalyzer._s_declaration_statement,
    VarDeclaration: SemanticAnalyzer._s_var_declaration,
    TupleDeclaration: SemanticAnalyzer._s_tuple_declaration,
    Reassignment: SemanticAnalyzer._s_reassignment,
    FunctionDeclaration: SemanticAnalyzer._s_function_declaration,
    MethodDeclaration: SemanticAnalyzer._s_method_declaration,
    TypeDeclaration: SemanticAnalyzer._s_type_declaration,
    EnumDeclaration: SemanticAnalyzer._s_enum_declaration,
    ImportDeclaration: SemanticAnalyzer._s_import_declaration,
}

# ------------------------------------------------------------------
# Dispatch table for _visit_expr.  Uses exact type as key for speed.
# ------------------------------------------------------------------
_EXPR_HANDLERS: dict[type, ExpressionHandler] = {
    Identifier: SemanticAnalyzer._e_identifier,
    Literal: SemanticAnalyzer._e_literal,
    TupleExpr: SemanticAnalyzer._e_tuple_expr,
    UnaryExpr: SemanticAnalyzer._e_unary_expr,
    BinaryExpr: SemanticAnalyzer._e_binary_expr,
    ConditionalExpr: SemanticAnalyzer._e_conditional_expr,
    MemberAccessExpr: SemanticAnalyzer._e_member_access_expr,
    GenericInstantiationExpr: SemanticAnalyzer._e_generic_instantiation_expr,
    CallExpr: SemanticAnalyzer._e_call_expr,
    HistoryRefExpr: SemanticAnalyzer._e_history_ref_expr,
}
