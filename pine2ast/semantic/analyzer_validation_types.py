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


class AnalyzerTypeValidationMixin:
    """Focused semantic validation mixin extracted for Pine2AST 4.0."""

    def _qualifier_rank(self, qualifier: str | None) -> int:
        return qualifier_rank(qualifier)

    def _validate_qualifier_assignment(
        self, expected_max: str | None, actual: str | None, span: SourceSpan, context: str
    ) -> None:
        if expected_max is None:
            return
        if self._qualifier_rank(actual) > self._qualifier_rank(expected_max):
            self._diag(
                Severity.ERROR,
                codes.QUALIFIER_MISMATCH,
                f"{context} requires {expected_max} or weaker qualifier, got {actual or 'unknown'}.",
                span,
            )

    def _validate_binary_expr(self, expr: BinaryExpr) -> None:
        left_type = infer_type(expr.left, self.model.symbols)
        right_type = infer_type(expr.right, self.model.symbols)
        numeric = {"int", "float", "unknown", "na"}
        if expr.op in {"-", "*", "/", "%"}:
            if left_type not in numeric or right_type not in numeric:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator {expr.op} requires numeric operands, got {left_type} and {right_type}.",
                    expr.span,
                )
        elif expr.op == "+":
            string_concat = left_type == right_type == "string"
            numeric_add = left_type in numeric and right_type in numeric
            if not (string_concat or numeric_add):
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator + requires numeric operands or string concatenation, got {left_type} and {right_type}.",
                    expr.span,
                )
        elif expr.op in {"and", "or"}:
            if left_type not in {"bool", "unknown"} or right_type not in {"bool", "unknown"}:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator {expr.op} requires bool operands, got {left_type} and {right_type}.",
                    expr.span,
                )
        elif expr.op in {"<", "<=", ">", ">="}:
            comparable = (left_type in numeric and right_type in numeric) or (
                left_type == right_type == "string"
            )
            if not comparable:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator {expr.op} requires comparable operands, got {left_type} and {right_type}.",
                    expr.span,
                )

    def _type_ref_name(self, type_ref) -> str:
        return type_ref_name(type_ref)

    def _for_in_target_types(self, iterable_type: str, target_count: int) -> list[str]:
        return for_in_target_types(iterable_type, target_count)

    def _split_type_args(self, inner: str) -> list[str]:
        return split_type_args(inner)

    def _validate_type_ref(self, type_ref) -> None:
        base = type_ref.name
        # Builtin templates such as array<float> are declared by their base name. Dotted builtins
        # such as chart.point are also registered as types in builtins_v6.json.
        if self._resolve(base) is None and base not in {"int", "float", "bool", "string", "color"}:
            self._diag(
                Severity.ERROR,
                getattr(codes, "UNKNOWN_TYPE", codes.METHOD_RECEIVER_TYPE_NOT_FOUND),
                f"Unknown type {base}.",
                type_ref.span,
            )
        args = list(getattr(type_ref, "template_args", []) or [])
        if base == "map" and args:
            key_type = self._type_ref_name(args[0])
            if not is_valid_map_key_type(key_type, enum_types=self._enum_members.keys()):
                self._diag(
                    Severity.ERROR,
                    codes.COLLECTION_ELEMENT_TYPE,
                    f"Map key type must be a value or enum type, got {key_type}.",
                    args[0].span,
                )
        for arg in args:
            self._validate_type_ref(arg)

    def _tuple_element_types(self, typ: str) -> list[str]:
        return tuple_element_types(typ)

    def _generic_type_parts(self, typ: str | None) -> tuple[str | None, list[str]]:
        return generic_type_parts(typ)

    def _is_assignable_type(self, expected: str | None, actual: str | None) -> bool:
        return is_assignable_type(expected, actual)

    def _uses_v6_bool_rules(self) -> bool:
        return self.language_profile.uses_v6_bool_rules

    def _is_bool_target_type(self, typ: str | None) -> bool:
        if typ == "bool":
            return True
        return bool(typ and typ.startswith("series<") and typ.endswith(">") and typ[7:-1] == "bool")

    def _expr_can_be_na(self, expr: Expression) -> bool:
        if isinstance(expr, Literal):
            return expr.literal_type == "na"
        if isinstance(expr, ConditionalExpr):
            return self._expr_can_be_na(expr.if_true) or self._expr_can_be_na(expr.if_false)
        return False

    def _validate_bool_cannot_be_na(self, expected: str | None, expr: Expression) -> None:
        if (
            self._uses_v6_bool_rules()
            and self._is_bool_target_type(expected)
            and self._expr_can_be_na(expr)
        ):
            self._diag(
                Severity.ERROR,
                codes.BOOL_CANNOT_BE_NA,
                "Pine v6 bool cannot be na.",
                expr.span,
            )

    def _validate_argument_type(self, callee: str, arg, param: dict | None) -> None:
        if not param:
            return
        expected = param.get("type")
        if not expected or expected in {"any", "array"}:
            return
        actual = infer_type(arg.value, self.model.symbols)
        if callee == "line.new" and (param.get("name") in {"x1", "y1"}) and actual == "chart.point":
            # Pine v6 has an overload line.new(first_point, second_point, ...). The registry
            # remains a single signature snapshot, so accept chart.point for the first two
            # positional slots without weakening x/y validation for numeric overloads.
            return
        # Allow plain "any" from user functions/input/source in oracle probes; downstream
        # lowerers/runtime preserve Pine's na/value behavior for the actual operation.
        if actual == "any":
            return
        # Allow series<any> arguments where series<T> is expected (e.g. input.source -> ta.sma)
        if actual.startswith("series<") and actual.endswith(">"):
            inner = actual[len("series<") : -1]
            if inner == "any":
                return
        if not self._is_assignable_type(expected, actual):
            pname = param.get("name") or "<positional>"
            self._diag(
                Severity.ERROR,
                codes.ARGUMENT_TYPE,
                f"Argument {pname} for {callee} expects {expected}, got {actual}.",
                arg.span,
            )
        self._validate_bool_cannot_be_na(expected, arg.value)
