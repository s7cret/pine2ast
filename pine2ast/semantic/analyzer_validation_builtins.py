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


class AnalyzerBuiltinValidationMixin:
    """Focused semantic validation mixin extracted for Pine2AST 4.0."""

    def _strategy_constant_members(self) -> set[str]:
        return {
            "strategy.long",
            "strategy.short",
            "strategy.cash",
            "strategy.percent_of_equity",
            "strategy.commission.percent",
        }

    def _strategy_state_members(self) -> set[str]:
        return {
            "strategy.account_currency",
            "strategy.avg_losing_trade",
            "strategy.avg_losing_trade_percent",
            "strategy.avg_trade",
            "strategy.avg_trade_percent",
            "strategy.avg_winning_trade",
            "strategy.avg_winning_trade_percent",
            "strategy.closedtrades",
            "strategy.equity",
            "strategy.eventrades",
            "strategy.grossloss_percent",
            "strategy.grossprofit_percent",
            "strategy.losstrades",
            "strategy.margin_liquidation_price",
            "strategy.max_contracts_held_all",
            "strategy.max_contracts_held_long",
            "strategy.max_contracts_held_short",
            "strategy.max_drawdown",
            "strategy.max_drawdown_percent",
            "strategy.max_runup",
            "strategy.max_runup_percent",
            "strategy.netprofit",
            "strategy.netprofit_percent",
            "strategy.openprofit",
            "strategy.openprofit_percent",
            "strategy.opentrades",
            "strategy.position_entry_name",
            "strategy.position_avg_price",
            "strategy.position_size",
            "strategy.wintrades",
        }

    def _validate_strategy_namespace_usage(
        self, name: str, span: SourceSpan, *, is_call: bool
    ) -> None:
        if not name.startswith("strategy."):
            return
        if name in self._strategy_constant_members():
            return
        is_state_member = name in self._strategy_state_members()
        is_readonly_trade_member = name.startswith("strategy.closedtrades.") or name.startswith(
            "strategy.opentrades."
        )
        if (is_state_member or is_readonly_trade_member) and self._script_type not in {
            None,
            "strategy",
        }:
            self._diag(
                Severity.ERROR,
                codes.STRATEGY_STATE_WRONG_SCRIPT_TYPE,
                f"{name} is available only in strategy() scripts; strategy constants remain allowed in libraries.",
                span,
            )

    def _builtin_namespace_root(self, name: str) -> str | None:
        if "." not in name:
            return None
        root = name.split(".", 1)[0]
        sym = self._resolve(root)
        if sym is not None and sym.kind is SymbolKind.BUILTIN:
            return root
        return None

    def _is_known_deferred_or_unsupported_builtin(self, name: str) -> bool:
        if "." not in name:
            return False
        namespace, member = name.split(".", 1)
        return member in KNOWN_DEFERRED_NAMESPACE_MEMBERS.get(
            namespace, set()
        ) or member in KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS.get(namespace, set())

    def _validate_known_deferred_or_unsupported_builtin(
        self, name: str, entry: dict | None, expr: CallExpr
    ) -> None:
        if entry is not None and entry.get("unsupported"):
            self._diag(
                Severity.ERROR,
                entry.get("unsupported_diagnostic_code") or codes.UNSUPPORTED_FEATURE,
                f"Builtin {name} is intentionally unsupported by this parser/semantic layer.",
                expr.span,
            )
            return
        if entry is not None or "." not in name:
            return
        namespace, member = name.split(".", 1)
        if member in KNOWN_DEFERRED_NAMESPACE_MEMBERS.get(namespace, set()):
            self._diag(
                Severity.INFO,
                codes.UNSUPPORTED_FEATURE,
                f"Builtin {name} is deliberately deferred in the v4.x registry snapshot.",
                expr.span,
            )
        if member in KNOWN_UNSUPPORTED_NAMESPACE_MEMBERS.get(namespace, set()):
            self._diag(
                Severity.ERROR,
                codes.UNSUPPORTED_FEATURE,
                f"Builtin {name} is intentionally unsupported by this parser/semantic layer.",
                expr.span,
            )

    def _validate_unknown_builtin_namespace_member(
        self, name: str, entry: dict | None, expr: CallExpr
    ) -> None:
        if entry is not None or name.startswith("<"):
            return
        if (
            isinstance(expr.callee, MemberAccessExpr)
            and expr.callee.member in self._method_receivers
        ):
            return
        root = self._builtin_namespace_root(name)
        if (
            root is None
            or root in self._external_aliases
            or self._is_known_deferred_or_unsupported_builtin(name)
        ):
            return
        # Registry coverage is intentionally incomplete, so unknown members from known namespaces
        # are surfaced as INFO instead of ERROR. `request.*` remains an ERROR in the dedicated
        # request validator below because that namespace affects data access semantics.
        if root == "request":
            return
        # v5→v6 migration: if this name exists in the v6 registry but not
        # the current (v5) one, emit a migration warning instead of an
        # unknown-builtin error. The script can still be parsed; the
        # v5→v6 migration would need to remove or replace the call.
        if self.pine_version == 5 and self._exists_in_v6_registry(name, kind="function"):
            self._diag(
                Severity.WARNING,
                codes.V6_ONLY_BUILTIN,
                f"Builtin {name} is not available in Pine v5; it was added in v6. "
                "This call will fail in v5 backends.",
                expr.span,
            )
            return
        severity = Severity.ERROR if self.strict_builtin_namespaces else Severity.INFO
        self._diag(
            severity,
            codes.UNKNOWN_BUILTIN_MEMBER,
            f"Builtin namespace member {name} is not present in the current registry snapshot.",
            expr.span,
        )

    def _validate_unknown_builtin_namespace_value(self, expr: MemberAccessExpr) -> None:
        name = callee_name(expr)
        if "." not in name:
            return
        root = self._builtin_namespace_root(name)
        if (
            root is None
            or root in self._external_aliases
            or self._is_known_deferred_or_unsupported_builtin(name)
        ):
            return
        if self._registry_exposes_value_or_namespace(name):
            return
        # v5→v6 migration: same logic as for function calls — if the
        # name is a v6-only constant/variable, emit a warning.
        if self.pine_version == 5 and self._exists_in_v6_registry(name, kind="variable"):
            self._diag(
                Severity.WARNING,
                codes.V6_ONLY_BUILTIN,
                f"Builtin {name} is not available in Pine v5; it was added in v6.",
                expr.span,
            )
            return
        self._diag(
            Severity.ERROR,
            codes.UNKNOWN_BUILTIN_MEMBER,
            f"Builtin namespace member {name} is not present in the current registry snapshot.",
            expr.span,
        )

    def _registry_exposes_value_or_namespace(self, name: str) -> bool:
        """Return whether the runtime registry can resolve ``name`` as a value path.

        Constants must be mirrored into ``variables`` to become typed semantic values.
        A nested prefix such as ``strategy.direction`` is also a valid namespace
        when the registry exposes ``strategy.direction.long`` and peers.
        """
        sections = ("variables", "functions", "namespaces")
        if any(name in self.registry.get(section, {}) for section in sections):
            return True
        prefix = name + "."
        return any(
            candidate.startswith(prefix)
            for section in sections
            for candidate in self.registry.get(section, {})
        )

    def _exists_in_v6_registry(self, name: str, *, kind: str) -> bool:
        """True if `name` exists as a function/variable in the v6 registry.

        Used to drive v5→v6 migration diagnostics: when a v5 script
        references a v6-only builtin, we want to emit V6_ONLY_BUILTIN
        (warning) instead of UNKNOWN_BUILTIN_MEMBER (error).
        """
        v6 = load_builtin_registry(pine_version=6)
        sections = ("functions",) if kind == "function" else ("variables", "constants")
        return any(name in v6.get(section, {}) for section in sections)

    def _is_v6_only_namespace_root(self, root: str) -> bool:
        """True if `root` is a v6-only namespace/variable/function prefix.

        In v5 mode, when the analyzer encounters an undeclared root like
        ``footprint`` (which has functions like ``footprint.buy_volume``
        in v6 but not in v5), we want to emit V6_ONLY_BUILTIN warning
        instead of UNDECLARED_VARIABLE error. This helper centralizes the
        detection: we check the v6 registry for any function or variable
        whose name starts with ``root + "."``.
        """
        if self.pine_version != 5:
            return False
        v6 = load_builtin_registry(pine_version=6)
        prefix = root + "."
        for section in ("functions", "variables", "constants"):
            for name in v6.get(section, {}):
                if name.startswith(prefix):
                    return True
        return False

    def _validate_strategy_call_script_type(self, name: str, expr: CallExpr) -> None:
        strategy_order_calls = {
            "strategy.entry",
            "strategy.exit",
            "strategy.close",
            "strategy.close_all",
            "strategy.order",
            "strategy.cancel",
            "strategy.cancel_all",
            "strategy.risk.allow_entry_in",
            "strategy.risk.max_drawdown",
            "strategy.risk.max_intraday_loss",
            "strategy.risk.max_cons_loss_days",
            "strategy.risk.max_intraday_filled_orders",
            "strategy.risk.max_position_size",
        }
        if name in strategy_order_calls and self._script_type not in {None, "strategy"}:
            self._diag(
                Severity.ERROR,
                codes.STRATEGY_CALL_WRONG_SCRIPT_TYPE,
                f"{name}() is allowed only in strategy() scripts.",
                expr.span,
            )
