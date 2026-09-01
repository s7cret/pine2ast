from __future__ import annotations


from pine2ast.ast.base import Expression
from pine2ast.ast.nodes import (
    BinaryExpr,
    ConditionalExpr,
    Literal,
)
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.type_helpers import (
    for_in_target_types,
    generic_type_parts,
    is_assignable_type,
    is_valid_map_key_type,
    split_type_args,
    tuple_element_types,
    type_ref_name,
)
from pine2ast.semantic.qualifier_validation import qualifier_rank
from pine2ast.semantic.analyzer_contract import AnalyzerMixinHost


class AnalyzerTypeValidationMixin(AnalyzerMixinHost):
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
        left_type = self._infer_type(expr.left)
        right_type = self._infer_type(expr.right)
        arithmetic = {"+", "-", "*", "/", "%"}
        has_bool_operand = left_type == "bool" or right_type == "bool"
        if expr.op in arithmetic and has_bool_operand:
            if self.policy.allows_bool_to_number:
                # Pine v1/v2 implicitly coerce bool to 0/1 in arithmetic. The
                # coercion itself is recorded in Semantic Facts by the binder.
                return
            self._diag(
                Severity.ERROR,
                codes.BOOL_TO_NUMBER_FORBIDDEN,
                (
                    f"Pine v{self.version_context.pine_version} does not allow "
                    f"implicit bool-to-number conversion for operator {expr.op}."
                ),
                expr.span,
            )
            return

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
            allowed = {"bool", "unknown"}
            if self.policy.numeric_condition_allowed:
                allowed.update({"int", "float"})
            if left_type not in allowed or right_type not in allowed:
                self._diag(
                    Severity.ERROR,
                    codes.TYPE_MISMATCH,
                    f"Operator {expr.op} requires condition-compatible operands, got {left_type} and {right_type}.",
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
        return self.policy.uses_v6_bool_rules

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
        actual = self._infer_type(arg.value)
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
