"""Collection call signature helpers for Pine static semantics.

This module is the Release 4.0 extraction seam for array/matrix/map function-form
and method-form calls.  The bundled TradingView registry still contains broad
or empty signatures for several generic collection APIs, so this layer
specializes parameters from the concrete receiver type, e.g. ``map<Key,float>``
turns ``put(key, value)`` into ``key: Key`` and ``value: float``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from pine2ast.ast.nodes import Argument, CallExpr, Identifier, MemberAccessExpr
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.type_helpers import generic_type_parts, is_assignable_type
from pine2ast.semantic.type_infer import callee_name

CollectionForm = Literal["function", "method"]
CollectionRole = Literal[
    "id", "index", "row", "column", "key", "value", "array_id", "order", "sort_field", "other"
]


@dataclass(frozen=True, slots=True)
class CollectionParameterSpec:
    """Concrete parameter expected by a collection operation."""

    name: str
    type_name: str | None
    role: CollectionRole = "other"
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_name,
            "role": self.role,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class CollectionArgumentBinding:
    argument: Argument
    parameter: CollectionParameterSpec | None
    parameter_index: int | None
    binding: Literal["positional", "named", "unknown", "extra_positional"]
    actual_type: str

    @property
    def expected_type(self) -> str | None:
        return self.parameter.type_name if self.parameter is not None else None


@dataclass(frozen=True, slots=True)
class CollectionSignatureIssue:
    severity: Severity
    code: str
    message: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CollectionCallResolution:
    operation: str
    function_form: str
    form: CollectionForm
    collection_kind: str
    receiver_type: str | None
    parameters: tuple[CollectionParameterSpec, ...]
    bindings: tuple[CollectionArgumentBinding, ...]
    return_type: str | None
    issues: tuple[CollectionSignatureIssue, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {Severity.ERROR, Severity.FATAL} for issue in self.issues)

    @property
    def is_mutation(self) -> bool:
        return self.operation in COLLECTION_MUTATION_OPERATIONS.get(
            self.collection_kind, frozenset()
        )

    @property
    def is_access(self) -> bool:
        return self.operation in COLLECTION_ACCESS_OPERATIONS.get(self.collection_kind, frozenset())


# Parameter templates intentionally model the method-form payload. Function-form
# calls simply prepend the collection id parameter. The optional fourth tuple
# item is the ``required`` flag; omitted means required=True.
CollectionParameterTemplate = (
    tuple[str, str | None, CollectionRole] | tuple[str, str | None, CollectionRole, bool]
)

COLLECTION_METHOD_PARAMETER_TEMPLATES: dict[str, dict[str, list[CollectionParameterTemplate]]] = {
    "array": {
        "abs": [],
        "avg": [],
        "binary_search": [
            ("value", "T", "value"),
            ("sort_field", "int|string", "sort_field", False),
        ],
        "binary_search_leftmost": [
            ("value", "T", "value"),
            ("sort_field", "int|string", "sort_field", False),
        ],
        "binary_search_rightmost": [
            ("value", "T", "value"),
            ("sort_field", "int|string", "sort_field", False),
        ],
        "clear": [],
        "concat": [("array_id", "array<T>", "array_id")],
        "copy": [],
        "covariance": [("array_id", "array<T>", "array_id")],
        "every": [],
        "fill": [
            ("value", "T", "value"),
            ("index_from", "int", "index", False),
            ("index_to", "int", "index", False),
        ],
        "first": [],
        "get": [("index", "int", "index")],
        "includes": [("value", "T", "value")],
        "indexof": [("value", "T", "value")],
        "insert": [("index", "int", "index"), ("value", "T", "value")],
        "join": [("separator", "string", "other", False)],
        "last": [],
        "lastindexof": [("value", "T", "value")],
        "max": [],
        "median": [],
        "min": [],
        "mode": [],
        "percentile_linear_interpolation": [("percentage", "float", "other")],
        "percentile_nearest_rank": [("percentage", "float", "other")],
        "percentrank": [("index", "int", "index")],
        "pop": [],
        "push": [("value", "T", "value")],
        "range": [],
        "remove": [("index", "int", "index")],
        "reverse": [],
        "set": [("index", "int", "index"), ("value", "T", "value")],
        "shift": [],
        "size": [],
        "slice": [("index_from", "int", "index"), ("index_to", "int", "index")],
        "some": [],
        "sort": [
            ("order", "string", "order", False),
            ("sort_field", "int|string", "sort_field", False),
        ],
        "sort_indices": [
            ("order", "string", "order", False),
            ("sort_field", "int|string", "sort_field", False),
        ],
        "standardize": [],
        "stdev": [],
        "sum": [],
        "unshift": [("value", "T", "value")],
        "variance": [],
    },
    "matrix": {
        "add_col": [("column", "int", "column"), ("array_id", "array<T>", "array_id", False)],
        "add_row": [("row", "int", "row"), ("array_id", "array<T>", "array_id", False)],
        "avg": [],
        "col": [("column", "int", "column")],
        "columns": [],
        "concat": [("other", "matrix<T>", "other")],
        "copy": [],
        "det": [],
        "diff": [("other", "matrix<T>", "other")],
        "eigenvalues": [],
        "eigenvectors": [],
        "elements_count": [],
        "fill": [
            ("value", "T", "value"),
            ("from_row", "int", "row", False),
            ("to_row", "int", "row", False),
            ("from_column", "int", "column", False),
            ("to_column", "int", "column", False),
        ],
        "get": [("row", "int", "row"), ("column", "int", "column")],
        "inv": [],
        "is_antidiagonal": [],
        "is_antisymmetric": [],
        "is_binary": [],
        "is_diagonal": [],
        "is_identity": [],
        "is_square": [],
        "is_stochastic": [],
        "is_symmetric": [],
        "is_triangular": [],
        "is_zero": [],
        "kron": [("other", "matrix<T>", "other")],
        "max": [],
        "median": [],
        "min": [],
        "mode": [],
        "mult": [("other", "unknown", "other")],
        "pinv": [],
        "pow": [("power", "int", "other")],
        "rank": [],
        "remove_col": [("column", "int", "column")],
        "remove_row": [("row", "int", "row")],
        "reshape": [("rows", "int", "row"), ("columns", "int", "column")],
        "reverse": [],
        "row": [("row", "int", "row")],
        "rows": [],
        "set": [("row", "int", "row"), ("column", "int", "column"), ("value", "T", "value")],
        "sort": [
            ("column", "int", "column", False),
            ("order", "string", "order", False),
            ("sort_field", "int|string", "sort_field", False),
        ],
        "submatrix": [
            ("from_row", "int", "row"),
            ("to_row", "int", "row"),
            ("from_column", "int", "column"),
            ("to_column", "int", "column"),
        ],
        "sum": [],
        "swap_columns": [("column1", "int", "column"), ("column2", "int", "column")],
        "swap_rows": [("row1", "int", "row"), ("row2", "int", "row")],
        "trace": [],
        "transpose": [],
    },
    "map": {
        "clear": [],
        "contains": [("key", "K", "key")],
        "copy": [],
        "get": [("key", "K", "key")],
        "keys": [],
        "put": [("key", "K", "key"), ("value", "V", "value")],
        "put_all": [("other", "map<K,V>", "other")],
        "remove": [("key", "K", "key")],
        "size": [],
        "values": [],
    },
}

COLLECTION_MUTATION_OPERATIONS: dict[str, frozenset[str]] = {
    "array": frozenset(
        {
            "clear",
            "concat",
            "fill",
            "insert",
            "pop",
            "push",
            "remove",
            "reverse",
            "set",
            "shift",
            "sort",
            "unshift",
        }
    ),
    "matrix": frozenset(
        {
            "add_col",
            "add_row",
            "concat",
            "fill",
            "remove_col",
            "remove_row",
            "reshape",
            "reverse",
            "set",
            "sort",
            "swap_columns",
            "swap_rows",
        }
    ),
    "map": frozenset({"clear", "put", "put_all", "remove"}),
}

COLLECTION_ACCESS_OPERATIONS: dict[str, frozenset[str]] = {
    kind: frozenset(set(operations) - COLLECTION_MUTATION_OPERATIONS.get(kind, frozenset()))
    for kind, operations in COLLECTION_METHOD_PARAMETER_TEMPLATES.items()
}

_GENERIC_TYPE_ARITY: dict[str, int] = {
    "array.new": 1,
    "matrix.new": 1,
    "map.new": 2,
}


def collection_kind_from_type(type_name: str | None) -> str | None:
    base, _ = generic_type_parts(type_name)
    return base if base in COLLECTION_METHOD_PARAMETER_TEMPLATES else None


def collection_kind_from_function_name(name: str) -> str | None:
    if "." not in name:
        return None
    root = name.split(".", 1)[0]
    return root if root in COLLECTION_METHOD_PARAMETER_TEMPLATES else None


def collection_operation_from_function_name(name: str) -> str | None:
    if "." not in name:
        return None
    kind, operation = name.split(".", 1)
    if kind not in COLLECTION_METHOD_PARAMETER_TEMPLATES:
        return None
    return operation if operation in COLLECTION_METHOD_PARAMETER_TEMPLATES[kind] else None


def collection_function_names() -> set[str]:
    return {
        f"{kind}.{operation}"
        for kind, operations in COLLECTION_METHOD_PARAMETER_TEMPLATES.items()
        for operation in operations
    }


def generic_constructor_expected_arity(name: str) -> int | None:
    return _GENERIC_TYPE_ARITY.get(name)


def _type_replacements(receiver_type: str | None) -> dict[str, str]:
    base, args = generic_type_parts(receiver_type)
    if base in {"array", "matrix"} and args:
        return {"T": args[0], "K": "unknown", "V": "unknown"}
    if base == "map" and len(args) >= 2:
        return {"K": args[0], "V": args[1], "T": "unknown"}
    return {"T": "unknown", "K": "unknown", "V": "unknown"}


def _substitute_type(template: str | None, replacements: dict[str, str]) -> str | None:
    if template is None:
        return None
    # Keep the replacement order deterministic so nested shapes like array<T>
    # stay stable in JSON contracts. This body intentionally differs from the
    # older facts helper because quality gates flag exact duplicate functions.
    result = template
    for name in ("K", "V", "T"):
        result = result.replace(name, replacements.get(name, "unknown"))
    return result


def _parameter_spec_from_template(
    template: CollectionParameterTemplate, replacements: dict[str, str]
) -> CollectionParameterSpec:
    if len(template) == 3:
        name, type_template, role = template
        required = True
    else:
        name, type_template, role, required = template
    return CollectionParameterSpec(
        name,
        _substitute_type(type_template, replacements),
        role,
        bool(required),
    )


def method_parameter_specs(
    receiver_type: str | None, operation: str
) -> tuple[CollectionParameterSpec, ...]:
    kind = collection_kind_from_type(receiver_type)
    if not kind:
        return ()
    templates = COLLECTION_METHOD_PARAMETER_TEMPLATES.get(kind, {}).get(operation)
    if templates is None:
        return ()
    replacements = _type_replacements(receiver_type)
    return tuple(_parameter_spec_from_template(template, replacements) for template in templates)


def function_parameter_specs(
    function_name: str,
    receiver_type: str | None,
) -> tuple[CollectionParameterSpec, ...]:
    kind = collection_kind_from_function_name(function_name)
    operation = collection_operation_from_function_name(function_name)
    if kind is None or operation is None:
        return ()
    concrete_receiver_type = receiver_type or kind
    id_spec = CollectionParameterSpec("id", concrete_receiver_type, "id")
    return (id_spec,) + method_parameter_specs(concrete_receiver_type, operation)


def collection_return_type(receiver_type: str | None, operation: str) -> str | None:
    kind = collection_kind_from_type(receiver_type)
    replacements = _type_replacements(receiver_type)
    element = replacements["T"]
    key_type = replacements["K"]
    value_type = replacements["V"]
    if kind == "array":
        if operation in {
            "get",
            "pop",
            "shift",
            "first",
            "last",
            "remove",
            "min",
            "max",
            "avg",
            "median",
            "mode",
            "sum",
            "stdev",
            "variance",
            "range",
            "covariance",
            "percentile_linear_interpolation",
            "percentile_nearest_rank",
        }:
            return element
        if operation in {
            "size",
            "indexof",
            "lastindexof",
            "binary_search",
            "binary_search_leftmost",
            "binary_search_rightmost",
            "percentrank",
        }:
            return "int"
        if operation in {"includes", "every", "some"}:
            return "bool"
        if operation in {"copy", "slice", "abs", "standardize"}:
            return receiver_type
        if operation == "sort_indices":
            return "array<int>"
        if operation == "join":
            return "string"
        return "void"
    if kind == "matrix":
        if operation in {"get", "avg", "det", "max", "median", "min", "mode", "sum", "trace"}:
            return element
        if operation in {"rows", "columns", "elements_count", "rank"}:
            return "int"
        if operation.startswith("is_"):
            return "bool"
        if operation in {"row", "col", "eigenvalues"}:
            return f"array<{element}>"
        if operation == "eigenvectors":
            return f"matrix<{element}>"
        if operation in {"copy", "diff", "inv", "kron", "pinv", "pow", "submatrix", "transpose"}:
            return receiver_type
        if operation == "mult":
            return "unknown"
        return "void"
    if kind == "map":
        if operation in {"get", "remove"}:
            return value_type
        if operation == "contains":
            return "bool"
        if operation == "keys":
            return f"array<{key_type}>"
        if operation == "values":
            return f"array<{value_type}>"
        if operation == "size":
            return "int"
        if operation == "copy":
            return receiver_type
        return "void"
    return None


def is_collection_method(receiver_type: str | None, operation: str) -> bool:
    kind = collection_kind_from_type(receiver_type)
    return bool(kind and operation in COLLECTION_METHOD_PARAMETER_TEMPLATES.get(kind, {}))


def _bind_arguments(
    operation_name: str,
    args: Sequence[Argument],
    specs: Sequence[CollectionParameterSpec],
    *,
    span: SourceSpan,
    infer_arg_type,
) -> tuple[tuple[CollectionArgumentBinding, ...], tuple[CollectionSignatureIssue, ...]]:
    issues: list[CollectionSignatureIssue] = []
    bindings: list[CollectionArgumentBinding] = []
    known = {spec.name for spec in specs}
    required = [spec.name for spec in specs if spec.required]
    positional = [arg for arg in args if arg.name is None]
    positional_names = [spec.name for spec in specs[: len(positional)]]
    named_values = [arg.name for arg in args if arg.name]
    named = {name for name in named_values if name}
    seen_named: set[str] = set()

    if len(positional) > len(specs):
        issues.append(
            CollectionSignatureIssue(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Too many positional arguments for collection operation {operation_name}.",
                span,
            )
        )

    for index, arg in enumerate(args):
        parameter: CollectionParameterSpec | None = None
        parameter_index: int | None = None
        binding: Literal["positional", "named", "unknown", "extra_positional"]
        if arg.name is None:
            if index < len(specs):
                parameter = specs[index]
                parameter_index = index
                binding = "positional"
            else:
                binding = "extra_positional"
        else:
            binding = "named"
            if arg.name in seen_named:
                issues.append(
                    CollectionSignatureIssue(
                        Severity.ERROR,
                        codes.DUPLICATE_NAMED_ARGUMENT,
                        f"Parameter {arg.name} for collection operation {operation_name} is supplied more than once.",
                        arg.span,
                    )
                )
            seen_named.add(arg.name)
            if arg.name not in known:
                binding = "unknown"
                issues.append(
                    CollectionSignatureIssue(
                        Severity.ERROR,
                        codes.UNKNOWN_PARAMETER,
                        f"Unknown parameter {arg.name} for collection operation {operation_name}.",
                        arg.span,
                    )
                )
            else:
                for spec_index, spec in enumerate(specs):
                    if spec.name == arg.name:
                        parameter = spec
                        parameter_index = spec_index
                        break
        actual_type = infer_arg_type(arg)
        bindings.append(
            CollectionArgumentBinding(arg, parameter, parameter_index, binding, actual_type)
        )
        if (
            parameter is not None
            and parameter.type_name
            and not is_assignable_type(parameter.type_name, actual_type)
        ):
            issues.append(
                CollectionSignatureIssue(
                    Severity.ERROR,
                    codes.COLLECTION_ELEMENT_TYPE,
                    (
                        f"Collection operation {operation_name} parameter {parameter.name} "
                        f"expects {parameter.type_name}, got {actual_type}."
                    ),
                    arg.span,
                )
            )

    for arg in args:
        if arg.name and arg.name in positional_names:
            issues.append(
                CollectionSignatureIssue(
                    Severity.ERROR,
                    codes.DUPLICATE_NAMED_ARGUMENT,
                    (
                        f"Parameter {arg.name} for collection operation {operation_name} "
                        "is supplied both positionally and by name."
                    ),
                    arg.span,
                )
            )
    supplied = set(positional_names) | (named & known)
    missing = [name for name in required if name not in supplied]
    if missing:
        issues.append(
            CollectionSignatureIssue(
                Severity.ERROR,
                codes.ARGUMENT_COUNT,
                f"Missing required parameter(s) for collection operation {operation_name}: {', '.join(missing)}.",
                span,
            )
        )
    return tuple(bindings), tuple(issues)


def resolve_collection_call(expr: CallExpr, *, engine) -> CollectionCallResolution | None:
    """Resolve a CallExpr if it targets an array/matrix/map operation."""

    name = callee_name(expr.callee)
    if isinstance(expr.callee, MemberAccessExpr):
        # ``array.push(id, value)`` is parsed as a member access on the builtin
        # namespace root. Treat that as function-form, not receiver method-form.
        namespace_root = (
            expr.callee.object.name
            if isinstance(expr.callee.object, Identifier)
            and expr.callee.object.name in COLLECTION_METHOD_PARAMETER_TEMPLATES
            else None
        )
        if namespace_root is None:
            receiver_type = engine.infer_type(expr.callee.object)
            kind = collection_kind_from_type(receiver_type)
            operation = expr.callee.member
            if not kind or operation not in COLLECTION_METHOD_PARAMETER_TEMPLATES.get(kind, {}):
                return None
            specs = method_parameter_specs(receiver_type, operation)
            bindings, issues = _bind_arguments(
                f"{kind}.{operation}",
                expr.arguments,
                specs,
                span=expr.span,
                infer_arg_type=lambda arg: engine.infer_type(arg.value),
            )
            return CollectionCallResolution(
                operation=operation,
                function_form=f"{kind}.{operation}",
                form="method",
                collection_kind=kind,
                receiver_type=receiver_type,
                parameters=specs,
                bindings=bindings,
                return_type=collection_return_type(receiver_type, operation),
                issues=issues,
            )

    kind = collection_kind_from_function_name(name)
    operation_opt = collection_operation_from_function_name(name)
    if not kind or operation_opt is None:
        return None
    operation = operation_opt
    receiver_type = engine.infer_type(expr.arguments[0].value) if expr.arguments else None
    if collection_kind_from_type(receiver_type) != kind:
        # For incomplete calls, still validate arity using the kind as a broad
        # receiver; for non-collection first args, let type validation report it.
        concrete_receiver_type = receiver_type or kind
    else:
        concrete_receiver_type = receiver_type
    specs = function_parameter_specs(name, concrete_receiver_type)
    bindings, issues = _bind_arguments(
        name,
        expr.arguments,
        specs,
        span=expr.span,
        infer_arg_type=lambda arg: engine.infer_type(arg.value),
    )
    return CollectionCallResolution(
        operation=operation,
        function_form=name,
        form="function",
        collection_kind=kind,
        receiver_type=concrete_receiver_type,
        parameters=specs,
        bindings=bindings,
        return_type=collection_return_type(concrete_receiver_type, operation),
        issues=issues,
    )


__all__ = [
    "COLLECTION_ACCESS_OPERATIONS",
    "COLLECTION_FUNCTION_NAMES",
    "COLLECTION_METHOD_PARAMETER_TEMPLATES",
    "COLLECTION_MUTATION_OPERATIONS",
    "CollectionArgumentBinding",
    "CollectionCallResolution",
    "CollectionParameterSpec",
    "CollectionSignatureIssue",
    "collection_function_names",
    "collection_kind_from_function_name",
    "collection_kind_from_type",
    "collection_operation_from_function_name",
    "collection_return_type",
    "function_parameter_specs",
    "generic_constructor_expected_arity",
    "is_collection_method",
    "method_parameter_specs",
    "resolve_collection_call",
]

# Backward-compatible constant for consumers that prefer a materialized set.
COLLECTION_FUNCTION_NAMES = collection_function_names()
