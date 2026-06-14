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


class AnalyzerExpressionMixin:
    """Implementation mixin split out of :mod:`pine2ast.semantic.analyzer`."""

    def _expr_path(self, expr: Expression) -> str | None:
        if isinstance(expr, Identifier):
            return expr.name
        if isinstance(expr, MemberAccessExpr):
            root = self._expr_path(expr.object)
            return f"{root}.{expr.member}" if root else None
        return None

    def _na_call_path(self, expr: Expression) -> str | None:
        if (
            isinstance(expr, CallExpr)
            and callee_name(expr.callee) == "na"
            and len(expr.arguments) == 1
        ):
            return self._expr_path(expr.arguments[0].value)
        return None

    def _non_na_paths_from_condition(self, expr: Expression, *, truthy: bool = True) -> set[str]:
        """Return source paths known to be non-na in the requested branch.

        v2.11 extends the v2.10 `if not na(x)` metadata with:
        - conjunction guards: `if not na(x) and x > 0`;
        - member paths: `if not na(obj.field)`;
        - else-branch narrowing: `if na(x) ... else ...`.

        These facts remain scope-local and report-only. They do not rewrite AST or
        leak into sibling/global scopes.
        """
        if isinstance(expr, UnaryExpr) and expr.op == "not":
            return self._non_na_paths_from_condition(expr.operand, truthy=not truthy)
        na_path = self._na_call_path(expr)
        if na_path:
            return set() if truthy else {na_path}
        if isinstance(expr, BinaryExpr) and expr.op == "and" and truthy:
            return self._non_na_paths_from_condition(
                expr.left, truthy=True
            ) | self._non_na_paths_from_condition(expr.right, truthy=True)
        return set()

    def _non_na_narrowing_from_condition(
        self, expr: Expression, *, truthy: bool = True
    ) -> set[str]:
        # Backward-compatible symbol-only view for existing callers/tests.
        return {
            path
            for path in self._non_na_paths_from_condition(expr, truthy=truthy)
            if "." not in path
        }

    def _validate_narrowing_condition(self, expr: Expression) -> None:
        """Report `na()` guards that cannot produce a stable flow fact.

        Flow-sensitive narrowing is intentionally path-based. `na(x)` and
        `na(obj.field)` are stable, but `na(1)`, `na(close + open)`, or other
        computed expressions cannot be represented as scope-local facts. Keeping
        this as INFO makes it visible to hardening reports without breaking real
        scripts that use `na()` as a pure boolean predicate.
        """
        if isinstance(expr, UnaryExpr) and expr.op == "not":
            self._validate_narrowing_condition(expr.operand)
            return
        if isinstance(expr, BinaryExpr) and expr.op in {"and", "or"}:
            self._validate_narrowing_condition(expr.left)
            self._validate_narrowing_condition(expr.right)
            return
        if (
            isinstance(expr, CallExpr)
            and callee_name(expr.callee) == "na"
            and len(expr.arguments) == 1
        ):
            if self._expr_path(expr.arguments[0].value) is None:
                self._diag(
                    Severity.INFO,
                    codes.UNSTABLE_NA_NARROWING,
                    "na() guard does not reference a stable symbol/member path, so no non-na narrowing fact is recorded.",
                    expr.arguments[0].span,
                )

    def _visit_structure(self, node: Statement) -> None:
        if isinstance(node, IfStructure):
            self._check_bool(node.condition)
            self._validate_narrowing_condition(node.condition)
            then_paths = self._non_na_paths_from_condition(node.condition, truthy=True)
            self._visit_block(
                node.then_block,
                non_na_symbols={path for path in then_paths if "." not in path},
                non_na_paths=then_paths,
            )
            for br in node.else_if_branches:
                self._check_bool(br.condition)
                self._validate_narrowing_condition(br.condition)
                branch_paths = self._non_na_paths_from_condition(br.condition, truthy=True)
                self._visit_block(
                    br.block,
                    non_na_symbols={path for path in branch_paths if "." not in path},
                    non_na_paths=branch_paths,
                )
            if node.else_block:
                else_paths = self._non_na_paths_from_condition(node.condition, truthy=False)
                self._visit_block(
                    node.else_block,
                    non_na_symbols={path for path in else_paths if "." not in path},
                    non_na_paths=else_paths,
                )
        elif isinstance(node, ForRangeStructure):
            self._visit_expr(node.start)
            self._visit_expr(node.end)
            if node.step:
                self._visit_expr(node.step)
            for label, expr in (("start", node.start), ("end", node.end), ("step", node.step)):
                if expr is not None:
                    typ = infer_type(expr, self.model.symbols)
                    if typ not in {"int", "unknown"}:
                        self._diag(
                            Severity.ERROR,
                            codes.LOOP_RANGE_TYPE,
                            f"for range {label} expression must be int-like, got {typ}.",
                            expr.span,
                        )
            # P2.1: static DoS guard. When both start and end are
            # int literals (or negations of int literals), compute
            # the absolute iteration count. If it exceeds the
            # configured ceiling, fail with LOOP_ITERATION_OVERFLOW
            # before the runtime has to deal with a 10^9 iteration
            # loop. Negative step is allowed; the static check
            # covers both directions.
            static_bound = _static_int_bound(node.start, node.end, node.step)
            if static_bound is not None and static_bound > self.loop_max_iterations:
                self._diag(
                    Severity.ERROR,
                    codes.LOOP_ITERATION_OVERFLOW,
                    (
                        f"for-range has static iteration bound {static_bound} "
                        f"> loop_max_iterations={self.loop_max_iterations}. "
                        "Reduce the literal bound or raise ParseOptions.loop_max_iterations."
                    ),
                    node.span,
                )
            # P2.1: nested-loop explosion. If we're inside another
            # for-range and THIS one is static-bounded, the product
            # could explode. We warn (not error) because the runtime
            # max_loops will cut it off anyway, but a flag in CI is
            # cheaper than a 100MB stack trace.
            if self.loop_depth >= 1 and static_bound is not None:
                # Look at the nearest enclosing for-range with a
                # known static bound. We only need one parent to
                # detect a product > 10^8 — deeper chains are
                # necessarily larger still.
                parent_static: Optional[int] = None
                for bound in reversed(self._static_loop_bounds):
                    if bound is not None:
                        parent_static = bound
                        break
                if parent_static is not None:
                    product = parent_static * static_bound
                    if product > 100_000_000:
                        self._diag(
                            Severity.WARNING,
                            codes.NESTED_LOOP_EXPLOSION,
                            (
                                f"Nested static-bounded loops: "
                                f"{parent_static} * {static_bound} = {product} "
                                f"iterations. The runtime will cap at 100,000."
                            ),
                            node.span,
                        )
            self.loop_depth += 1
            self.local_depth += 1
            self._push_scope(ScopeKind.LOOP)
            self._define(node.variable, SymbolKind.VARIABLE, node.span, "int", "series")
            self._static_loop_bounds.append(static_bound)
            for st in node.body.statements:
                self._visit_statement(st)
            self._static_loop_bounds.pop()
            self._pop_scope()
            self.local_depth -= 1
            self.loop_depth -= 1
        elif isinstance(node, WhileStructure):
            self._check_bool(node.condition)
            self._validate_narrowing_condition(node.condition)
            # P2.1: literal-true `while` loops are almost always a
            # bug. We warn (not error) so an intentional
            # `while bar_index < some_runtime_cap` style is still
            # allowed, but a `while true do ... end` typo is flagged.
            if _is_literal_true(node.condition):
                self._diag(
                    Severity.WARNING,
                    codes.INFINITE_WHILE_LITERAL,
                    "while loop condition is the literal `true`; "
                    "this loop has no static exit. Ensure a runtime "
                    "break condition is reachable.",
                    node.condition.span,
                )
            self.loop_depth += 1
            self._visit_block(node.body, kind=ScopeKind.LOOP)
            self.loop_depth -= 1
        elif isinstance(node, ForInStructure):
            self._validate_for_in_target(node)
            self._visit_expr(node.iterable)
            iterable_type = infer_type(node.iterable, self.model.symbols)
            target_types = self._for_in_target_types(iterable_type, len(node.target.names))
            self.loop_depth += 1
            self.local_depth += 1
            self._push_scope(ScopeKind.LOOP)
            for index, name in enumerate(node.target.names):
                if name == "_":
                    continue
                typ = target_types[index] if index < len(target_types) else "unknown"
                self._define(name, SymbolKind.VARIABLE, node.target.span, typ, "series")
            for st in node.body.statements:
                self._visit_statement(st)
            self._pop_scope()
            self.local_depth -= 1
            self.loop_depth -= 1
        elif isinstance(node, SwitchStructure):
            switch_type = None
            if node.expression:
                self._visit_expr(node.expression)
                switch_type = infer_type(node.expression, self.model.symbols)
            for case in node.cases:
                if case.condition:
                    if node.expression is None:
                        self._check_bool(case.condition)
                    else:
                        self._visit_expr(case.condition)
                        case_type = infer_type(case.condition, self.model.symbols)
                        if not (
                            self._is_assignable_type(switch_type, case_type)
                            or self._is_assignable_type(case_type, switch_type)
                        ):
                            self._diag(
                                Severity.ERROR,
                                codes.SWITCH_CASE_TYPE,
                                f"switch case type {case_type} is not comparable with switch expression type {switch_type}.",
                                case.condition.span,
                            )
                self._visit_body(case.body)

    def _e_identifier(self, expr: Identifier) -> None:
        if self._resolve(expr.name) is None and not expr.name.startswith("<"):
            self._diag(
                Severity.ERROR,
                codes.UNDECLARED_VARIABLE,
                f"Use of undeclared variable {expr.name}.",
                expr.span,
            )

    def _e_literal(self, expr: Literal) -> None:
        pass  # no-op: type already recorded above

    def _e_tuple_expr(self, expr: TupleExpr) -> None:
        for item in expr.elements:
            self._visit_expr(item)

    def _e_unary_expr(self, expr: UnaryExpr) -> None:
        self._visit_expr(expr.operand)
        if expr.op == "not":
            operand_type = infer_type(expr.operand, self.model.symbols)
            if operand_type not in {"bool", "unknown"}:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Unary not requires bool operand, got {operand_type}.",
                    expr.span,
                )

    def _e_binary_expr(self, expr: BinaryExpr) -> None:
        self._visit_expr(expr.left)
        self._visit_expr(expr.right)
        self._validate_binary_expr(expr)

    def _e_conditional_expr(self, expr: ConditionalExpr) -> None:
        self._check_bool(expr.condition)
        self._validate_narrowing_condition(expr.condition)
        self._visit_expr(expr.if_true)
        self._visit_expr(expr.if_false)
        true_type = infer_type(expr.if_true, self.model.symbols)
        false_type = infer_type(expr.if_false, self.model.symbols)
        if not (
            true_type in {None, "unknown", "na"}
            or false_type in {None, "unknown", "na"}
            or self._is_assignable_type(true_type, false_type)
            or self._is_assignable_type(false_type, true_type)
        ):
            self._diag(
                Severity.ERROR,
                codes.BRANCH_TYPE_MISMATCH,
                f"Ternary branches must have compatible types, got {true_type} and {false_type}.",
                expr.span,
            )

    def _e_member_access_expr(self, expr: MemberAccessExpr) -> None:
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
        self._validate_strategy_namespace_usage(callee_name(expr), expr.span, is_call=False)
        self._validate_unknown_builtin_namespace_value(expr)
        self._validate_member_access(expr)

    def _e_generic_instantiation_expr(self, expr: GenericInstantiationExpr) -> None:
        self._visit_expr(expr.base)

    def _e_call_expr(self, expr: CallExpr) -> None:
        name = callee_name(expr.callee)
        lookup_name, entry = self._registry_entry_for_call(expr.callee)
        self._visit_callee(expr.callee)
        if entry and entry.get("forbidden_in_local_blocks") and self.local_depth > 0:
            self._diag(
                Severity.ERROR,
                codes.BUILTIN_FORBIDDEN_LOCAL,
                f"{name}() is forbidden in local blocks in Pine.",
                expr.span,
            )
        self._validate_strategy_call_script_type(name, expr)
        self._validate_strategy_namespace_usage(name, expr.span, is_call=True)
        self._validate_known_deferred_or_unsupported_builtin(name, entry, expr)
        self._validate_unknown_builtin_namespace_member(name, entry, expr)
        if (
            name.startswith("request.")
            and entry is None
            and not self._is_known_deferred_or_unsupported_builtin(name)
        ):
            self._diag(
                Severity.ERROR,
                codes.REQUEST_SIGNATURE,
                f"Unknown request.* builtin {name}.",
                expr.span,
            )
        self._validate_builtin_call(lookup_name if entry is not None else name, entry, expr)
        self._validate_generic_constructor_call(name, expr)
        if entry is None:
            self._validate_udt_constructor_call(expr)
            self._validate_method_call(expr)
            self._validate_user_function_call(name, expr)
            self._validate_member_call_target(name, expr)
        seen_named: set[str] = set()
        named_seen = False
        for arg in expr.arguments:
            if arg.name:
                named_seen = True
                if arg.name in seen_named:
                    self._diag(
                        Severity.ERROR,
                        codes.DUPLICATE_NAMED_ARGUMENT,
                        f"Duplicate named argument {arg.name}.",
                        arg.span,
                    )
                seen_named.add(arg.name)
                if (
                    name.startswith("strategy.")
                    and arg.name == "when"
                    and entry is None
                    and self.pine_version >= 6
                ):
                    self._diag(
                        Severity.ERROR,
                        codes.STRATEGY_WHEN_REMOVED,
                        "strategy.*(..., when=...) is not valid in Pine v6.",
                        arg.span,
                    )
            elif named_seen:
                self._diag(
                    Severity.ERROR,
                    codes.POSITIONAL_AFTER_NAMED,
                    "Positional argument after named argument.",
                    arg.span,
                )
            self._visit_expr(arg.value)

    def _e_history_ref_expr(self, expr: HistoryRefExpr) -> None:
        if isinstance(expr.base, Literal):
            self._diag(
                Severity.ERROR,
                codes.HISTORY_ON_LITERAL,
                "History reference cannot be applied to a literal.",
                expr.span,
            )
        if isinstance(expr.base, HistoryRefExpr):
            self._diag(
                Severity.ERROR,
                codes.REPEATED_HISTORY,
                "Repeated history reference x[1][2] is not allowed.",
                expr.span,
            )
        if isinstance(expr.base, Identifier):
            sym = self._resolve(expr.base.name)
            if sym is not None and self._scope_kind(sym.scope_id) not in {
                ScopeKind.GLOBAL,
                None,
            }:
                self._diag(
                    Severity.WARNING,
                    codes.HISTORY_LOCAL_SCOPE,
                    "History reference to a value declared in a local scope can be unsafe in Pine.",
                    expr.span,
                )
        offset_type = infer_type(expr.offset, self.model.symbols)
        if offset_type not in {"int", "unknown"}:
            self._diag(
                Severity.ERROR,
                codes.HISTORY_OFFSET_NOT_INTEGER,
                "History reference offset must be integer-like.",
                expr.offset.span,
            )
        if self._is_static_negative_history_offset(expr.offset):
            self._diag(
                Severity.ERROR,
                codes.HISTORY_NEGATIVE_OFFSET,
                "History reference offset cannot be negative in Pine.",
                expr.offset.span,
            )
        self._visit_expr(expr.base)
        self._visit_expr(expr.offset)

    def _check_bool(self, expr: Expression) -> None:
        self._visit_expr(expr)
        if not self._uses_v6_bool_rules():
            return
        typ = infer_type(expr, self.model.symbols)
        if isinstance(expr, Literal) and expr.literal_type == "na":
            self._diag(
                Severity.ERROR,
                codes.NA_IN_BOOL_CONTEXT,
                "na is not allowed in bool context in Pine v6.",
                expr.span,
            )
        elif typ != "bool" and typ != "unknown":
            self._diag(
                Severity.ERROR,
                codes.NON_BOOL_CONDITION,
                "Non-bool expression used as condition in Pine v6.",
                expr.span,
            )

    def _validate_for_in_target(self, node: ForInStructure) -> None:
        non_blank = [name for name in node.target.names if name != "_"]
        seen: set[str] = set()
        for name in non_blank:
            if name in seen:
                self._diag(
                    Severity.ERROR,
                    codes.REDECLARATION,
                    f"Duplicate for-in target {name}.",
                    node.target.span,
                )
                break
            seen.add(name)
        if len(node.target.names) not in {1, 2}:
            self._diag(
                Severity.ERROR,
                codes.FOR_IN_TARGET_ARITY,
                "for-in destructuring supports one value target or [index, value].",
                node.target.span,
            )

    def _is_static_negative_history_offset(self, expr: Expression) -> bool:
        return (
            isinstance(expr, UnaryExpr)
            and expr.op == "-"
            and isinstance(expr.operand, Literal)
            and expr.operand.literal_type == "int"
        )
