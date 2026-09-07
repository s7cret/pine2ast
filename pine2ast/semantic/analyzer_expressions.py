from __future__ import annotations


from typing import Optional

from pine2ast.ast.base import ASTNode, Expression, Statement
from pine2ast.ast.nodes import (
    BinaryExpr,
    CallExpr,
    ConditionalExpr,
    ForInStructure,
    ForRangeStructure,
    GenericInstantiationExpr,
    HistoryRefExpr,
    Identifier,
    IfStructure,
    OnceStructure,
    Literal,
    MemberAccessExpr,
    SwitchStructure,
    TupleExpr,
    UnaryExpr,
    WhileStructure,
)
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.semantic.scopes import ScopeKind
from pine2ast.semantic.symbols import SymbolKind
from pine2ast.semantic.type_infer import callee_name, request_expression_argument
from pine2ast.semantic.passes.loop_dos import (
    _is_literal_true,
    _static_int_bound,
)
from pine2ast.semantic.analyzer_contract import AnalyzerMixinHost


class AnalyzerExpressionMixin(AnalyzerMixinHost):
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
        if isinstance(node, OnceStructure):
            self._check_bool(node.condition)
            self._visit_block(node.body)
        elif isinstance(node, IfStructure):
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
                    typ = self._infer_type(expr)
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
            iterable_type = self._infer_type(node.iterable)
            if iterable_type.startswith("map<") and len(node.target.names) != 2:
                self._diag(Severity.ERROR, codes.FOR_IN_TARGET_ARITY,
                           "Map iteration requires [key, value] targets.", node.target.span)
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
                switch_type = self._infer_type(node.expression)
            for case in node.cases:
                if case.condition:
                    if node.expression is None:
                        self._check_bool(case.condition)
                    else:
                        self._visit_expr(case.condition)
                        case_type = self._infer_type(case.condition)
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
            operand_type = self._infer_type(expr.operand)
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
        true_type = self._infer_type(expr.if_true)
        false_type = self._infer_type(expr.if_false)
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
        for type_arg in expr.type_args:
            self._validate_type_ref(type_arg)

    def _identifier_names(self, expr: Expression) -> set[str]:
        names: set[str] = set()

        def visit(node: ASTNode) -> None:
            if isinstance(node, Identifier):
                names.add(node.name)
            for field_name in getattr(node, "__dataclass_fields__", ()):  # stable AST walk
                value = getattr(node, field_name)
                if isinstance(value, ASTNode):
                    visit(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, ASTNode):
                            visit(item)

        visit(expr)
        return names

    def _validate_security_expression(self, name: str, expr: CallExpr) -> None:
        if name not in {"security", "request.security"}:
            return
        expression = request_expression_argument(expr)
        if expression is None or not self.policy.forbids_mutable_security_expression:
            return
        mutable = sorted(self._identifier_names(expression) & self._reassigned_names)
        if mutable:
            self._diag(
                Severity.ERROR,
                codes.MUTABLE_SECURITY_ARGUMENT,
                (
                    f"Pine v{self.version_context.pine_version} forbids mutable "
                    f"variables in security() expressions: {', '.join(mutable)}."
                ),
                expression.span,
            )

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
        self._validate_security_expression(name, expr)
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
                    and self.version_context.pine_version >= 6
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
        if self.version_context.pine_version < 5 and self._infer_type(expr.base).startswith(
            "array<"
        ):
            self._diag(
                Severity.ERROR,
                codes.VERSION_FEATURE_UNAVAILABLE,
                "Array instance history requires Pine v5 or later; scalar element-result history remains available.",
                expr.span,
            )
        if self.version_context.pine_version >= 6 and isinstance(expr.base, Literal):
            self._diag(
                Severity.ERROR,
                codes.HISTORY_ON_LITERAL,
                "History reference cannot be applied to a literal.",
                expr.span,
            )
        if (
            self.version_context.pine_version >= 6
            and isinstance(expr.base, MemberAccessExpr)
            and self._infer_type(expr.base.object) in self._udt_fields
        ):
            self._diag(
                Severity.ERROR,
                codes.HISTORY_ON_UDT_FIELD,
                "In Pine v6, reference the UDT object's history before accessing its field.",
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
        offset_type = self._infer_type(expr.offset)
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
        typ = self._infer_type(expr)
        if self.policy.numeric_condition_allowed:
            return
        if isinstance(expr, Literal) and expr.literal_type == "na":
            self._diag(
                Severity.ERROR,
                codes.NA_IN_BOOL_CONTEXT,
                (f"na is not allowed in a condition in Pine v{self.version_context.pine_version}."),
                expr.span,
            )
        elif typ not in {"bool", "unknown"}:
            self._diag(
                Severity.ERROR,
                codes.NON_BOOL_CONDITION,
                (
                    f"Non-bool expression used as a condition in Pine v"
                    f"{self.version_context.pine_version}."
                ),
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
