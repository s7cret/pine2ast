"""Release 4.0 static semantic rules shared by analyzer and OpenPine contracts.

The legacy :class:`SemanticAnalyzer` still performs the broad statement/expression
walk.  This module contains rules that are better expressed as read-only passes
over the completed AST + symbol model:

* fixed arity for generic type references and collection constructors;
* dynamic ``request.*`` restrictions for Pine v5 and ``dynamic_requests=false``;
* library export constraints that TradingView enforces statically;
* ``strategy.exit()`` calls that do not specify any effective exit action.

The helpers intentionally return small issue objects instead of mutating the
analyzer.  That keeps the rules reusable by OpenPine contract extraction and
makes future migration to independent passes straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from pine2ast.ast.nodes import (
    Argument,
    CallExpr,
    DeclarationStatement,
    FunctionDeclaration,
    GenericInstantiationExpr,
    Literal,
    MethodDeclaration,
    Program,
    TypeDeclaration,
    UnaryExpr,
    VarDeclaration,
)
from pine2ast.ast.types import TypeRef
from pine2ast.ast.walk import iter_nodes
from pine2ast.semantic._static_validation_walk import (
    iter_calls_with_context_fast as _iter_calls_with_context_fast,
)
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.versioning import PineVersionContext
from pine2ast.lexer.token import SourceSpan
from pine2ast.catalog import load_catalog_readonly_view
from pine2ast.semantic.collection_signatures import (
    generic_constructor_expected_arity,
    resolve_collection_call,
)
from pine2ast.semantic.inference import PineInferenceEngine
from pine2ast.semantic.type_helpers import generic_type_parts, type_ref_name
from pine2ast.semantic.type_infer import callee_name

_GENERIC_TYPE_ARITY: dict[str, int] = {
    "array": 1,
    "matrix": 1,
    "map": 2,
}

_REQUEST_CONTEXT_PARAMETER_NAMES = frozenset(
    {
        "symbol",
        "ticker",
        "timeframe",
        "currency",
        "financial_id",
        "period",
        "field",
        "gaps",
        "lookahead",
    }
)
_LOCAL_REQUEST_CONTEXT_MARKERS = frozenset(
    {"if", "switch", "for_range", "for_in", "while", "function", "method"}
)
_STRATEGY_EXIT_ACTION_PARAMETERS = frozenset({"profit", "limit", "loss", "stop"})
_STRATEGY_EXIT_TRAIL_PRICE_PARAMETERS = frozenset({"trail_price", "trail_points"})
_STRATEGY_EXIT_TRAIL_OFFSET_PARAMETER = "trail_offset"
_SORT_FIELD_COLLECTION_OPERATIONS = frozenset(
    {("array", "sort"), ("array", "sort_indices"), ("matrix", "sort")}
)
_SORTABLE_UDT_FIELD_TYPES = frozenset({"int", "float", "string"})


@dataclass(frozen=True, slots=True)
class StaticValidationIssue:
    """A diagnostics-ready Release 4.0 static validation issue."""

    severity: Severity
    code: str
    message: str
    span: SourceSpan
    rule: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": (
                self.severity.value if hasattr(self.severity, "value") else str(self.severity)
            ),
            "code": self.code,
            "message": self.message,
            "rule": self.rule,
            "span": self.span.to_dict(),
            "details": self.details or {},
        }


@dataclass(frozen=True, slots=True)
class StaticValidationReport:
    schema_version: str
    issues: tuple[StaticValidationIssue, ...]
    generic_type_ref_count: int
    generic_constructor_count: int
    dynamic_request_count: int
    exported_declaration_count: int
    strategy_exit_count: int
    udt_sort_field_count: int = 0

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {Severity.ERROR, Severity.FATAL} for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "summary": {
                "issue_count": len(self.issues),
                "generic_type_ref_count": self.generic_type_ref_count,
                "generic_constructor_count": self.generic_constructor_count,
                "dynamic_request_count": self.dynamic_request_count,
                "exported_declaration_count": self.exported_declaration_count,
                "strategy_exit_count": self.strategy_exit_count,
                "udt_sort_field_count": self.udt_sort_field_count,
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _profile_for_program(
    program: Program, profile: PineVersionContext | None
) -> PineVersionContext:
    return profile or program.version_context


def _symbols(semantic_model: Any | None) -> Mapping[str, Any] | None:
    return getattr(semantic_model, "symbols", None)


def _iter_type_refs(program: Program) -> Iterable[TypeRef]:
    for node in iter_nodes(program):
        if isinstance(node, TypeRef):
            yield node


def _iter_generic_instantiations(program: Program) -> Iterable[GenericInstantiationExpr]:
    for node in iter_nodes(program):
        if isinstance(node, GenericInstantiationExpr):
            yield node


def _validate_type_ref_arity(type_ref: TypeRef) -> StaticValidationIssue | None:
    expected = _GENERIC_TYPE_ARITY.get(type_ref.name)
    actual = len(type_ref.template_args or [])
    if expected is None or actual == 0 or actual == expected:
        return None
    return StaticValidationIssue(
        Severity.ERROR,
        codes.ARGUMENT_COUNT,
        f"Generic type {type_ref.name}<...> expects {expected} type argument(s), got {actual}.",
        type_ref.span,
        "generic_type_arity",
        {"type": type_ref.name, "expected": expected, "actual": actual},
    )


def _validate_generic_constructor_arity(
    expr: GenericInstantiationExpr,
) -> StaticValidationIssue | None:
    base = callee_name(expr.base)
    expected = generic_constructor_expected_arity(base)
    if expected is None:
        return None
    actual = len(expr.type_args or [])
    if actual == expected:
        return None
    return StaticValidationIssue(
        Severity.ERROR,
        codes.ARGUMENT_COUNT,
        f"Generic constructor {base}<...>() expects {expected} type argument(s), got {actual}.",
        expr.span,
        "generic_constructor_arity",
        {"constructor": base, "expected": expected, "actual": actual},
    )


def _declaration_dynamic_requests(program: Program, profile: PineVersionContext) -> dict[str, Any]:
    default = profile.dynamic_requests_default
    explicit: bool | None = None
    if isinstance(program.declaration, DeclarationStatement):
        for arg in program.declaration.call.arguments:
            if (
                arg.name == "dynamic_requests"
                and isinstance(arg.value, Literal)
                and arg.value.literal_type == "bool"
            ):
                explicit = bool(arg.value.value)
                break
    return {
        "default": default,
        "explicit": explicit,
        "enabled": default if explicit is None else explicit,
    }


def _active_parameter_names(function_name: str, profile: PineVersionContext) -> list[str]:
    entry = (
        load_catalog_readonly_view(pine_version=profile.pine_version)
        .get("functions", {})
        .get(function_name)
        or {}
    )
    names: list[str] = []
    for param in entry.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        removed_in = param.get("removed_in")
        if removed_in and profile.pine_version >= int(removed_in):
            continue
        added_in = param.get("added_in")
        if added_in and profile.pine_version < int(added_in):
            continue
        name = param.get("name")
        if name:
            names.append(str(name))
    return names


def _bind_argument_names(
    function_name: str, args: list[Argument], profile: PineVersionContext
) -> list[tuple[Argument, str | None]]:
    params = _active_parameter_names(function_name, profile)
    result: list[tuple[Argument, str | None]] = []
    positional_index = 0
    for arg in args:
        if arg.name is not None:
            result.append((arg, arg.name))
            continue
        param_name = params[positional_index] if positional_index < len(params) else None
        positional_index += 1
        result.append((arg, param_name))
    return result


def _dynamic_request_issues(
    calls: list,
    *,
    program: Program,
    profile: PineVersionContext,
    semantic_model: Any | None,
) -> Iterable[StaticValidationIssue]:
    dynamic = _declaration_dynamic_requests(program, profile)
    engine = PineInferenceEngine(version_context=profile, symbols=_symbols(semantic_model))
    for call, context in calls:
        name = callee_name(call.callee)
        if not name.startswith("request."):
            continue
        bound = _bind_argument_names(name, call.arguments, profile)
        local_scope = any(marker in _LOCAL_REQUEST_CONTEXT_MARKERS for marker in context)
        series_context_params: list[str] = []
        for arg, param_name in bound:
            if param_name not in _REQUEST_CONTEXT_PARAMETER_NAMES:
                continue
            if engine.infer_qualifier(arg.value) == "series":
                series_context_params.append(str(param_name))
        requires_dynamic = local_scope or bool(series_context_params)
        if requires_dynamic and not dynamic["enabled"]:
            reasons: list[str] = []
            if local_scope:
                reasons.append("local scope")
            if series_context_params:
                reasons.append(
                    "series context argument(s): " + ", ".join(sorted(set(series_context_params)))
                )
            yield StaticValidationIssue(
                Severity.ERROR,
                codes.REQUEST_SIGNATURE,
                (
                    f"{name}() requires dynamic requests because it uses "
                    f"{'; '.join(reasons)}. Enable dynamic_requests or move the call/arguments to a static context."
                ),
                call.span,
                "dynamic_request_required",
                {
                    "kind": name,
                    "context": list(context),
                    "local_scope": local_scope,
                    "series_context_parameters": sorted(set(series_context_params)),
                    "dynamic_requests": dict(dynamic),
                },
            )


def _strategy_exit_issues(
    calls: list, *, profile: PineVersionContext
) -> Iterable[StaticValidationIssue]:
    for call, _context in calls:
        if callee_name(call.callee) != "strategy.exit":
            continue
        named = {
            name
            for _, name in _bind_argument_names("strategy.exit", call.arguments, profile)
            if name
        }
        has_direct_action = bool(named & _STRATEGY_EXIT_ACTION_PARAMETERS)
        has_trailing_action = (
            bool(named & _STRATEGY_EXIT_TRAIL_PRICE_PARAMETERS)
            and _STRATEGY_EXIT_TRAIL_OFFSET_PARAMETER in named
        )
        if has_direct_action or has_trailing_action:
            continue
        yield StaticValidationIssue(
            Severity.ERROR,
            codes.ARGUMENT_COUNT,
            (
                "strategy.exit() must specify an effective exit action: profit, limit, loss, stop, "
                "or a trailing pair using trail_offset with trail_price/trail_points."
            ),
            call.span,
            "strategy_exit_must_do_something",
            {
                "supplied_named_parameters": sorted(name for name in named if name),
                "required_action_parameters": sorted(_STRATEGY_EXIT_ACTION_PARAMETERS),
                "trailing_action_requires": ["trail_offset", "trail_price or trail_points"],
            },
        )


def _script_type(program: Program) -> str | None:
    return (
        program.declaration.script_type
        if isinstance(program.declaration, DeclarationStatement)
        else None
    )


def _library_export_issues(
    program: Program, *, profile: PineVersionContext
) -> Iterable[StaticValidationIssue]:
    if _script_type(program) != "library":
        return
    for node in iter_nodes(program):
        if isinstance(node, FunctionDeclaration) and node.is_exported:
            for param in node.parameters:
                if param.type_ref is None:
                    yield StaticValidationIssue(
                        Severity.ERROR,
                        codes.UNKNOWN_TYPE,
                        f"Exported library function {node.name}() requires an explicit type for parameter {param.name}.",
                        param.span,
                        "exported_function_parameter_type_required",
                        {"function": node.name, "parameter": param.name},
                    )
        elif isinstance(node, MethodDeclaration) and node.is_exported:
            if node.receiver_type is None or not node.receiver_name:
                yield StaticValidationIssue(
                    Severity.ERROR,
                    codes.METHOD_RECEIVER_REQUIRED,
                    f"Exported library method {node.name}() requires a typed first receiver parameter.",
                    node.span,
                    "exported_method_receiver_required",
                    {"method": node.name},
                )
            for param in node.parameters:
                if param.type_ref is None:
                    yield StaticValidationIssue(
                        Severity.ERROR,
                        codes.UNKNOWN_TYPE,
                        f"Exported library method {node.name}() requires an explicit type for parameter {param.name}.",
                        param.span,
                        "exported_method_parameter_type_required",
                        {"method": node.name, "parameter": param.name},
                    )
        elif isinstance(node, VarDeclaration) and node.is_exported:
            if node.explicit_qualifier != "const":
                yield StaticValidationIssue(
                    Severity.ERROR,
                    codes.UNSUPPORTED_FEATURE,
                    f"Exported library variable {node.name} must be declared with const qualifier.",
                    node.span,
                    "exported_variable_requires_const",
                    {"variable": node.name, "qualifier": node.explicit_qualifier},
                )
            elif not profile.supports_exported_const:
                yield StaticValidationIssue(
                    Severity.ERROR,
                    codes.UNSUPPORTED_FEATURE,
                    f"Exported const variables are not available in Pine v{profile.pine_version}.",
                    node.span,
                    "exported_const_requires_v6",
                    {"variable": node.name, "profile": f"pine_v{profile.pine_version}"},
                )


def _type_fields(program: Program) -> dict[str, tuple[tuple[str, str, SourceSpan], ...]]:
    fields: dict[str, tuple[tuple[str, str, SourceSpan], ...]] = {}
    for node in iter_nodes(program):
        if isinstance(node, TypeDeclaration):
            fields[node.name] = tuple(
                (field.name, type_ref_name(field.type_ref), field.span) for field in node.fields
            )
    return fields


def _literal_int_value(expr: Any) -> int | None:
    if isinstance(expr, Literal) and expr.literal_type == "int":
        return int(str(expr.value))
    if isinstance(expr, UnaryExpr) and expr.op in {"+", "-"}:
        value = _literal_int_value(expr.operand)
        if value is None:
            return None
        return value if expr.op == "+" else -value
    return None


def _literal_string_value(expr: Any) -> str | None:
    if isinstance(expr, Literal) and expr.literal_type == "string":
        return str(expr.value)
    return None


def _sort_field_binding(call: CallExpr, resolution: Any) -> Any | None:
    for binding in resolution.bindings:
        param = binding.parameter
        if param is not None and (param.role == "sort_field" or param.name == "sort_field"):
            return binding
    return None


def _collection_element_type(receiver_type: str | None, collection_kind: str) -> str | None:
    base, args = generic_type_parts(receiver_type)
    if base in {"array", "matrix"} and collection_kind == base and args:
        return args[0]
    return None


def _sort_field_target_field(
    binding: Any | None,
    fields: tuple[tuple[str, str, SourceSpan], ...],
) -> tuple[str, str, int] | None:
    if binding is None:
        index = 0
        return (fields[index][0], fields[index][1], index) if fields else None
    expr = binding.argument.value
    field_name = _literal_string_value(expr)
    if field_name is not None:
        for index, (name, field_type, _span) in enumerate(fields):
            if name == field_name:
                return name, field_type, index
        return None
    field_index = _literal_int_value(expr)
    if field_index is not None and 0 <= field_index < len(fields):
        name, field_type, _span = fields[field_index]
        return name, field_type, field_index
    return None


def _selected_collection_call(call: Any, engine: PineInferenceEngine):
    owner = getattr(engine, "method_candidates", None)
    selection = owner.resolve(call, engine) if owner is not None else None
    if selection is not None and (selection.user_selected or not selection.resolution.ok):
        return None
    return resolve_collection_call(call, engine=engine)


def _sort_field_issues(
    calls: list,
    *,
    program: Program,
    profile: PineVersionContext,
    semantic_model: Any | None,
) -> Iterable[StaticValidationIssue]:
    fields_by_type = _type_fields(program)
    engine = PineInferenceEngine(
        version_context=profile or program.version_context,
        symbols=_symbols(semantic_model),
    )
    if (
        semantic_model is not None
        and getattr(semantic_model, "method_candidates", None) is not None
    ):
        engine.bind_model(semantic_model)
    for call, _context in calls:
        resolution = _selected_collection_call(call, engine)
        if resolution is None:
            continue
        if (
            resolution.collection_kind,
            resolution.operation,
        ) not in _SORT_FIELD_COLLECTION_OPERATIONS:
            continue
        binding = _sort_field_binding(call, resolution)
        element_type = _collection_element_type(
            resolution.receiver_type, resolution.collection_kind
        )
        if binding is not None and element_type not in fields_by_type:
            yield StaticValidationIssue(
                Severity.ERROR,
                codes.ARGUMENT_TYPE,
                (
                    f"{resolution.function_form}() sort_field is only valid for UDT "
                    f"array/matrix collections, got {resolution.receiver_type or 'unknown'}."
                ),
                binding.argument.span,
                "udt_sort_field_requires_udt_collection",
                {
                    "operation": resolution.function_form,
                    "receiver_type": resolution.receiver_type,
                    "element_type": element_type,
                },
            )
            continue
        if element_type not in fields_by_type:
            continue
        fields = fields_by_type[element_type]
        span = binding.argument.span if binding is not None else call.span
        if binding is not None:
            qualifier = engine.infer_qualifier(binding.argument.value)
            if qualifier != "const":
                yield StaticValidationIssue(
                    Severity.ERROR,
                    codes.ARGUMENT_QUALIFIER,
                    (
                        f"{resolution.function_form}() sort_field requires const int/string, "
                        f"got {qualifier}."
                    ),
                    span,
                    "udt_sort_field_requires_const",
                    {
                        "operation": resolution.function_form,
                        "receiver_type": resolution.receiver_type,
                        "element_type": element_type,
                        "qualifier": qualifier,
                    },
                )
            actual_type = engine.infer_type(binding.argument.value)
            if actual_type not in {"int", "string", "unknown", "any"}:
                yield StaticValidationIssue(
                    Severity.ERROR,
                    codes.ARGUMENT_TYPE,
                    (
                        f"{resolution.function_form}() sort_field expects const int or const string, "
                        f"got {actual_type}."
                    ),
                    span,
                    "udt_sort_field_argument_type",
                    {
                        "operation": resolution.function_form,
                        "receiver_type": resolution.receiver_type,
                        "element_type": element_type,
                        "actual_type": actual_type,
                    },
                )
                continue
        if binding is not None:
            literal_selector = (
                _literal_string_value(binding.argument.value) is not None
                or _literal_int_value(binding.argument.value) is not None
            )
            if not literal_selector:
                # Const variables and const expressions are accepted by Pine. This
                # frontend validates their type/qualifier above, but deliberately
                # avoids pretending to constant-fold arbitrary field names/indexes.
                continue
        target = _sort_field_target_field(binding, fields)
        if target is None:
            detail = "default field 0" if binding is None else "the supplied field selector"
            yield StaticValidationIssue(
                Severity.ERROR,
                codes.UNKNOWN_FIELD,
                f"{resolution.function_form}() sort_field cannot resolve {detail} on UDT {element_type}.",
                span,
                "udt_sort_field_unknown_field",
                {
                    "operation": resolution.function_form,
                    "element_type": element_type,
                    "available_fields": [name for name, _type, _span in fields],
                    "selector": (
                        None
                        if binding is None
                        else _literal_string_value(binding.argument.value)
                        or _literal_int_value(binding.argument.value)
                    ),
                },
            )
            continue
        field_name, field_type, field_index = target
        if field_type not in _SORTABLE_UDT_FIELD_TYPES:
            yield StaticValidationIssue(
                Severity.ERROR,
                codes.ARGUMENT_TYPE,
                (
                    f"{resolution.function_form}() can sort UDT {element_type} only by int, float, or string fields; "
                    f"field {field_name} has type {field_type}."
                ),
                span,
                "udt_sort_field_type_not_sortable",
                {
                    "operation": resolution.function_form,
                    "receiver_type": resolution.receiver_type,
                    "element_type": element_type,
                    "field": field_name,
                    "field_index": field_index,
                    "field_type": field_type,
                    "sortable_field_types": sorted(_SORTABLE_UDT_FIELD_TYPES),
                },
            )


def build_static_validation_report(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineVersionContext | None = None,
) -> StaticValidationReport:
    actual_profile = _profile_for_program(program, profile)
    issues: list[StaticValidationIssue] = []
    type_refs = list(_iter_type_refs(program))
    generic_instantiations = list(_iter_generic_instantiations(program))
    for type_ref in type_refs:
        issue = _validate_type_ref_arity(type_ref)
        if issue is not None:
            issues.append(issue)
    for expression in generic_instantiations:
        issue = _validate_generic_constructor_arity(expression)
        if issue is not None:
            issues.append(issue)
    dynamic_request_count = 0
    exported_declaration_count = 0
    strategy_exit_count = 0
    udt_sort_field_count = 0
    sort_field_engine = PineInferenceEngine(
        version_context=actual_profile,
        symbols=_symbols(semantic_model),
    )
    if (
        semantic_model is not None
        and getattr(semantic_model, "method_candidates", None) is not None
    ):
        sort_field_engine.bind_model(semantic_model)

    # Walk the program once and collect every (call, context) pair. The shared
    # ``iter_calls_with_context`` helper builds a context tuple at every AST
    # node, but the static-validation pass needs the same call set from three
    # different angles (counts / dynamic-request / strategy.exit / sort_field).
    # Doing three independent walks quadruples AST visits on perf_stress.pine
    # and blows the P1.5 perf gate. We collect once and feed the same list to
    # all three downstream passes.
    _REQUEST_PREFIX = "request."
    _STRATEGY_EXIT = "strategy.exit"
    _SORT_FIELD_OPS = _SORT_FIELD_COLLECTION_OPERATIONS
    calls: list[tuple[Any, tuple]] = list(_iter_calls_with_context_fast(program))
    for call, _context in calls:
        name = callee_name(call.callee)
        if name.startswith(_REQUEST_PREFIX):
            dynamic_request_count += 1
        elif name == _STRATEGY_EXIT:
            strategy_exit_count += 1
        resolution = _selected_collection_call(call, sort_field_engine)
        if (
            resolution is not None
            and (resolution.collection_kind, resolution.operation) in _SORT_FIELD_OPS
        ):
            if _sort_field_binding(call, resolution) is not None:
                udt_sort_field_count += 1
    for node in iter_nodes(program):
        if getattr(node, "is_exported", False):
            exported_declaration_count += 1

    issues.extend(
        _dynamic_request_issues(
            calls,
            program=program,
            profile=actual_profile,
            semantic_model=semantic_model,
        )
    )
    issues.extend(_strategy_exit_issues(calls, profile=actual_profile))
    issues.extend(_library_export_issues(program, profile=actual_profile))
    issues.extend(
        _sort_field_issues(
            calls,
            program=program,
            profile=actual_profile,
            semantic_model=semantic_model,
        )
    )

    return StaticValidationReport(
        schema_version="pine2ast.static_validation.v1",
        issues=tuple(issues),
        generic_type_ref_count=sum(1 for ref in type_refs if ref.template_args),
        generic_constructor_count=len(generic_instantiations),
        dynamic_request_count=dynamic_request_count,
        exported_declaration_count=exported_declaration_count,
        strategy_exit_count=strategy_exit_count,
        udt_sort_field_count=udt_sort_field_count,
    )


def validate_static_semantics(
    program: Program,
    *,
    semantic_model: Any | None = None,
    profile: PineVersionContext | None = None,
) -> tuple[StaticValidationIssue, ...]:
    return build_static_validation_report(
        program, semantic_model=semantic_model, profile=profile
    ).issues


__all__ = [
    "StaticValidationIssue",
    "StaticValidationReport",
    "build_static_validation_report",
    "validate_static_semantics",
]
