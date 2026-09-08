from __future__ import annotations


from pine2ast.ast.base import Expression
from pine2ast.ast.nodes import (
    CallExpr,
    GenericInstantiationExpr,
    Literal,
    UnaryExpr,
)
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.type_helpers import (
    is_valid_map_key_type,
)
from pine2ast.semantic.type_infer import callee_name
from pine2ast.semantic.collection_signatures import (
    generic_constructor_expected_arity,
    resolve_collection_call,
)
from pine2ast.semantic.analyzer_contract import AnalyzerMixinHost


class AnalyzerCollectionValidationMixin(AnalyzerMixinHost):
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

        owner = self.model.method_candidates
        selection = owner.resolve(expr, self.inference) if owner is not None else None
        if selection is not None and (selection.user_selected or not selection.resolution.ok):
            return
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
            value = binding.argument.value
            if (
                self.version_context.pine_version < 6
                and resolution.collection_kind == "array"
                and resolution.operation in {"get", "insert", "remove", "set"}
                and binding.parameter is not None
                and binding.parameter.role == "index"
                and isinstance(value, UnaryExpr)
                and value.op == "-"
                and isinstance(value.operand, Literal)
                and value.operand.literal_type == "int"
            ):
                self._diag(
                    Severity.ERROR,
                    codes.VERSION_SEMANTIC_RULE_VIOLATION,
                    "Negative array indices are available only in Pine v6.",
                    value.span,
                )

    def _validate_generic_constructor_call(self, name: str, expr: CallExpr) -> None:
        # array.new<float>(size, initial), matrix.new<float>(rows, cols, initial), map.new<string,float>()
        if not isinstance(expr.callee, GenericInstantiationExpr) or not expr.callee.type_args:
            return
        base = callee_name(expr.callee.base)
        for type_arg in expr.callee.type_args:
            self._validate_type_ref(type_arg)
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
            actual = self._infer_type(expr.arguments[1].value)
            self._diag_collection_value(
                name,
                expected,
                actual,
                expr.arguments[1].span,
                expr.arguments[1].value,
            )
        elif base == "matrix.new" and len(expr.arguments) >= 3 and len(type_args) >= 1:
            expected = type_args[0]
            actual = self._infer_type(expr.arguments[2].value)
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
