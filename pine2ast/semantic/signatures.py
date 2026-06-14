from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping

from pine2ast.ast.nodes import Argument
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.type_helpers import is_assignable_type
from pine2ast.semantic.type_model import generic_type_parts
from pine2ast.semantic.values import (
    QUALIFIER_ORDER,
    expression_can_be_na,
    infer_semantic_value,
    is_bool_target_type,
)

ArgumentBindingKind = Literal["positional", "named", "unknown"]
ArgResolver = Callable[[Argument], str | None]


@dataclass(frozen=True, slots=True)
class SignatureIssue:
    """A diagnostics-ready issue produced by signature binding."""

    severity: Severity
    code: str
    message: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ResolvedArgument:
    argument: Argument
    parameter: dict[str, Any] | None
    parameter_index: int | None
    binding: ArgumentBindingKind
    actual_type: str | None = None
    actual_qualifier: str | None = None
    can_be_na: bool = False


@dataclass(frozen=True, slots=True)
class SignatureResolution:
    callee: str
    kind: str
    entry: dict[str, Any]
    active_parameters: tuple[dict[str, Any], ...]
    removed_parameters: dict[str, dict[str, Any]]
    resolved_arguments: tuple[ResolvedArgument, ...]
    issues: tuple[SignatureIssue, ...] = field(default_factory=tuple)
    overload_index: int | None = None
    overload_id: str | None = None
    return_type: str | None = None

    @property
    def ok(self) -> bool:
        return not any(issue.severity in {Severity.ERROR, Severity.FATAL} for issue in self.issues)

    @property
    def known_parameter_names(self) -> set[str]:
        return {p["name"] for p in self.active_parameters if p.get("name")}

    @property
    def selected_overload_index(self) -> int | None:
        return self.overload_index

    @property
    def uses_overload(self) -> bool:
        return self.overload_index is not None

    @property
    def result_type(self) -> str | None:
        return self.return_type


class SignatureResolver:
    """Bind Pine call arguments to registry signatures.

    Release 4.0.1 extends the earlier foundation with overload candidates and a
    small type/qualifier scoring layer. The resolver remains optional from the
    legacy analyzer's perspective: it only emits type/qualifier issues when the
    caller supplies symbol facts or explicit resolver callbacks.
    """

    def __init__(self, *, pine_version: int = 6) -> None:
        self.pine_version = 5 if pine_version == 5 else 6

    def resolve_builtin(
        self,
        callee: str,
        entry: dict[str, Any],
        args: list[Argument],
        span: SourceSpan | None,
        *,
        kind: str = "builtin",
        symbols: Mapping[str, object] | None = None,
        validate_types: bool = False,
        validate_qualifiers: bool = False,
        infer_arg_type: ArgResolver | None = None,
        infer_arg_qualifier: ArgResolver | None = None,
        argument_type_resolver: ArgResolver | None = None,
        argument_qualifier_resolver: ArgResolver | None = None,
    ) -> SignatureResolution:
        call_span = span or SourceSpan.zero()
        type_resolver = argument_type_resolver or infer_arg_type
        qualifier_resolver = argument_qualifier_resolver or infer_arg_qualifier
        should_validate_types = validate_types or symbols is not None or type_resolver is not None
        should_validate_qualifiers = (
            validate_qualifiers or symbols is not None or qualifier_resolver is not None
        )

        candidates = self._candidate_entries(entry)
        best: tuple[tuple[int, int, int, int], SignatureResolution] | None = None
        for candidate in candidates:
            resolution = self._bind_entry(
                callee,
                candidate,
                args,
                call_span,
                kind=kind,
                symbols=symbols,
                validate_types=should_validate_types,
                validate_qualifiers=should_validate_qualifiers,
                type_resolver=type_resolver,
                qualifier_resolver=qualifier_resolver,
            )
            score = self._resolution_score(resolution)
            if best is None or score < best[0]:
                best = (score, resolution)
        assert best is not None
        return best[1]

    def _candidate_entries(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        overloads = entry.get("overloads") or entry.get("signatures") or []
        candidates: list[dict[str, Any]] = []
        if isinstance(overloads, list):
            for index, overload in enumerate(overloads):
                if not isinstance(overload, dict):
                    continue
                merged = {k: v for k, v in entry.items() if k not in {"overloads", "signatures"}}
                merged.update(overload)
                merged["__overload_index"] = index
                if "id" not in merged and "overload_id" in overload:
                    merged["id"] = overload["overload_id"]
                candidates.append(merged)
        canonical = {k: v for k, v in entry.items() if k not in {"overloads", "signatures"}}
        canonical["__overload_index"] = None
        candidates.append(canonical)
        return candidates

    def _bind_entry(
        self,
        callee: str,
        entry: dict[str, Any],
        args: list[Argument],
        span: SourceSpan,
        *,
        kind: str,
        symbols: Mapping[str, object] | None,
        validate_types: bool,
        validate_qualifiers: bool,
        type_resolver: ArgResolver | None,
        qualifier_resolver: ArgResolver | None,
    ) -> SignatureResolution:
        params = tuple(entry.get("parameters") or ())
        active = tuple(p for p in params if self._param_active(p))
        removed = {
            str(p.get("name")): p for p in params if p.get("name") and not self._param_active(p)
        }
        specialized_return_type = entry.get("returns")
        active, specialized_return_type = self._specialize_collection_signature(
            callee,
            args,
            active,
            specialized_return_type,
            symbols=symbols,
            type_resolver=type_resolver,
        )
        issues: list[SignatureIssue] = []
        resolved: list[ResolvedArgument] = []

        if not active:
            for arg in args:
                if arg.name and arg.name in removed:
                    removed_param = removed[arg.name]
                    issues.append(
                        SignatureIssue(
                            Severity.ERROR,
                            removed_param.get("diagnostic_code") or codes.UNKNOWN_PARAMETER,
                            (
                                f"Parameter {arg.name} was removed or is not valid for "
                                f"{callee} in Pine v{self.pine_version}"
                                f"{self._version_note(removed_param)}."
                            ),
                            arg.span,
                        )
                    )
                resolved.append(
                    self._resolved_argument(
                        arg,
                        None,
                        None,
                        "unknown",
                        symbols=symbols,
                        type_resolver=type_resolver,
                        qualifier_resolver=qualifier_resolver,
                    )
                )
            return SignatureResolution(
                callee=callee,
                kind=kind,
                entry=entry,
                active_parameters=active,
                removed_parameters=removed,
                resolved_arguments=tuple(resolved),
                issues=tuple(issues),
                overload_index=entry.get("__overload_index"),
                overload_id=entry.get("id") or entry.get("overload_id"),
                return_type=specialized_return_type,
            )

        known = {p.get("name") for p in active if p.get("name")}
        required = [p for p in active if p.get("required")]
        positional = [a for a in args if a.name is None]
        named_values = [a.name for a in args if a.name]
        named = {name for name in named_values if name}

        if len(positional) > len(active) and not entry.get("allow_extra_positional"):
            issues.append(
                SignatureIssue(
                    Severity.ERROR,
                    codes.ARGUMENT_COUNT,
                    f"Too many positional arguments for {kind} {callee}.",
                    span,
                )
            )

        positional_param_names = [p.get("name") for p in active[: len(positional)] if p.get("name")]
        seen_named: set[str] = set()

        for arg_index, arg in enumerate(args):
            param: dict[str, Any] | None = None
            param_index: int | None = None
            binding: ArgumentBindingKind = "unknown"
            if arg.name:
                binding = "named"
                if arg.name in seen_named:
                    issues.append(
                        SignatureIssue(
                            Severity.ERROR,
                            codes.DUPLICATE_NAMED_ARGUMENT,
                            f"Parameter {arg.name} for {kind} {callee} is supplied more than once.",
                            arg.span,
                        )
                    )
                seen_named.add(arg.name)
                if arg.name in removed:
                    removed_param = removed[arg.name]
                    issues.append(
                        SignatureIssue(
                            Severity.ERROR,
                            removed_param.get("diagnostic_code") or codes.UNKNOWN_PARAMETER,
                            (
                                f"Parameter {arg.name} was removed or is not valid for "
                                f"{callee} in Pine v{self.pine_version}{self._version_note(removed_param)}."
                            ),
                            arg.span,
                        )
                    )
                elif known and arg.name not in known:
                    issues.append(
                        SignatureIssue(
                            Severity.ERROR,
                            codes.UNKNOWN_PARAMETER,
                            f"Unknown parameter {arg.name} for {kind} {callee}.",
                            arg.span,
                        )
                    )
                else:
                    for idx, candidate in enumerate(active):
                        if candidate.get("name") == arg.name:
                            param = candidate
                            param_index = idx
                            break
            elif arg_index < len(active):
                binding = "positional"
                param = active[arg_index]
                param_index = arg_index
            else:
                binding = "positional"
            resolved_arg = self._resolved_argument(
                arg,
                param,
                param_index,
                binding,
                symbols=symbols,
                type_resolver=type_resolver,
                qualifier_resolver=qualifier_resolver,
            )
            resolved.append(resolved_arg)
            if param is not None:
                issues.extend(
                    self._semantic_argument_issues(
                        callee,
                        kind,
                        resolved_arg,
                        param,
                        validate_types=validate_types,
                        validate_qualifiers=validate_qualifiers,
                    )
                )

        for arg in args:
            if arg.name and arg.name in positional_param_names:
                issues.append(
                    SignatureIssue(
                        Severity.ERROR,
                        codes.DUPLICATE_NAMED_ARGUMENT,
                        (
                            f"Parameter {arg.name} for {kind} {callee} is supplied both "
                            "positionally and by name."
                        ),
                        arg.span,
                    )
                )

        supplied = set(positional_param_names) | (named & known)
        missing_required = [
            str(p.get("name"))
            for p in required
            if p.get("name") is not None and p.get("name") not in supplied
        ]
        if missing_required:
            issues.append(
                SignatureIssue(
                    Severity.ERROR,
                    codes.ARGUMENT_COUNT,
                    f"Missing required parameter(s) for {callee}: {', '.join(missing_required)}.",
                    span,
                )
            )

        return SignatureResolution(
            callee=callee,
            kind=kind,
            entry=entry,
            active_parameters=active,
            removed_parameters=removed,
            resolved_arguments=tuple(resolved),
            issues=tuple(issues),
            overload_index=entry.get("__overload_index"),
            overload_id=entry.get("id") or entry.get("overload_id"),
            return_type=specialized_return_type,
        )

    def _resolved_argument(
        self,
        arg: Argument,
        param: dict[str, Any] | None,
        param_index: int | None,
        binding: ArgumentBindingKind,
        *,
        symbols: Mapping[str, object] | None,
        type_resolver: ArgResolver | None,
        qualifier_resolver: ArgResolver | None,
    ) -> ResolvedArgument:
        semantic = infer_semantic_value(arg.value, symbols)
        actual_type = type_resolver(arg) if type_resolver else semantic.type_name
        actual_qualifier = qualifier_resolver(arg) if qualifier_resolver else semantic.qualifier
        return ResolvedArgument(
            arg,
            param,
            param_index,
            binding,
            actual_type=actual_type,
            actual_qualifier=actual_qualifier,
            can_be_na=semantic.can_be_na or expression_can_be_na(arg.value),
        )

    def _specialize_collection_signature(
        self,
        callee: str,
        args: list[Argument],
        active: tuple[dict[str, Any], ...],
        return_type: str | None,
        *,
        symbols: Mapping[str, object] | None,
        type_resolver: ArgResolver | None,
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        """Specialize generic collection signatures from the actual id argument.

        The official Pine collection APIs are generic, but the bundled registry
        stores some entries with broad ``string``/``any`` placeholders. When the
        first argument is ``map<K,V>``, ``array<T>``, or ``matrix<T>``, use that
        concrete shape for key/value/element parameters and result types.
        """

        if not args:
            return active, return_type
        collection_type = self._argument_type_for_specialization(args[0], symbols, type_resolver)
        base, type_args = generic_type_parts(collection_type)
        if base == "map" and len(type_args) >= 2:
            key_type, value_type = type_args[0], type_args[1]
            if callee in {"map.put"}:
                return (
                    self._replace_parameter_types(active, {"key": key_type, "value": value_type}),
                    return_type,
                )
            if callee in {"map.get", "map.contains", "map.remove"}:
                replacement = {"key": key_type}
                specialized_return = (
                    value_type if callee in {"map.get", "map.remove"} else return_type
                )
                return self._replace_parameter_types(active, replacement), specialized_return
            if callee == "map.keys":
                return active, f"array<{key_type}>"
            if callee == "map.values":
                return active, f"array<{value_type}>"
            if callee == "map.copy":
                return active, collection_type
        if base in {"array", "matrix"} and type_args:
            element_type = type_args[0]
            if callee in {"array.push", "array.unshift"}:
                return self._replace_parameter_types(active, {"value": element_type}), return_type
            if callee == "array.set":
                return self._replace_parameter_types(active, {"value": element_type}), return_type
            if callee in {"array.get", "array.pop", "array.shift", "array.first", "array.last"}:
                return active, element_type
            if callee == "array.copy":
                return active, collection_type
            if callee == "matrix.set":
                return self._replace_parameter_types(active, {"value": element_type}), return_type
            if callee == "matrix.get":
                return active, element_type
            if callee == "matrix.copy":
                return active, collection_type
        return active, return_type

    def _argument_type_for_specialization(
        self,
        arg: Argument,
        symbols: Mapping[str, object] | None,
        type_resolver: ArgResolver | None,
    ) -> str | None:
        if type_resolver is not None:
            return type_resolver(arg)
        return infer_semantic_value(arg.value, symbols).type_name

    def _replace_parameter_types(
        self,
        params: tuple[dict[str, Any], ...],
        replacements: Mapping[str, str | None],
    ) -> tuple[dict[str, Any], ...]:
        result: list[dict[str, Any]] = []
        for param in params:
            name = param.get("name")
            replacement = replacements.get(str(name)) if name is not None else None
            if replacement:
                updated = dict(param)
                updated["type"] = replacement
                result.append(updated)
            else:
                result.append(param)
        return tuple(result)

    def _semantic_argument_issues(
        self,
        callee: str,
        kind: str,
        resolved: ResolvedArgument,
        param: dict[str, Any],
        *,
        validate_types: bool,
        validate_qualifiers: bool,
    ) -> list[SignatureIssue]:
        issues: list[SignatureIssue] = []
        pname = param.get("name") or "<positional>"
        expected_type = param.get("type") or param.get("value_type")
        if (
            validate_types
            and expected_type
            and not is_assignable_type(expected_type, resolved.actual_type)
        ):
            issues.append(
                SignatureIssue(
                    Severity.ERROR,
                    codes.ARGUMENT_TYPE,
                    f"Argument {pname} for {callee} expects {expected_type}, got {resolved.actual_type}.",
                    resolved.argument.span,
                )
            )
        if (
            validate_types
            and self.pine_version >= 6
            and is_bool_target_type(expected_type)
            and resolved.can_be_na
        ):
            issues.append(
                SignatureIssue(
                    Severity.ERROR,
                    codes.BOOL_CANNOT_BE_NA,
                    f"Argument {pname} for {callee} expects bool, but Pine v6 bool cannot be na.",
                    resolved.argument.span,
                )
            )
        max_q = param.get("qualifier_max")
        if validate_qualifiers and max_q:
            if QUALIFIER_ORDER.get(resolved.actual_qualifier or "series", 3) > QUALIFIER_ORDER.get(
                max_q, 3
            ):
                issues.append(
                    SignatureIssue(
                        Severity.ERROR,
                        codes.ARGUMENT_QUALIFIER,
                        f"Argument {pname} for {callee} requires {max_q} or weaker qualifier, got {resolved.actual_qualifier}.",
                        resolved.argument.span,
                    )
                )
        return issues

    def _resolution_score(self, resolution: SignatureResolution) -> tuple[int, int, int, int]:
        error_weight = 0
        type_weight = 0
        qualifier_weight = 0
        for issue in resolution.issues:
            if issue.severity not in {Severity.ERROR, Severity.FATAL}:
                continue
            if issue.code == codes.ARGUMENT_TYPE:
                type_weight += 1
            elif issue.code == codes.ARGUMENT_QUALIFIER:
                qualifier_weight += 1
            else:
                error_weight += 1
        unresolved = sum(1 for arg in resolution.resolved_arguments if arg.parameter is None)
        # Prefer fewer structural errors, then fewer type mismatches, then fewer
        # qualifier mismatches, then the candidate that binds more arguments.
        return (error_weight, type_weight, qualifier_weight, unresolved)

    def _param_active(self, param: dict[str, Any]) -> bool:
        removed_in = param.get("removed_in")
        if removed_in and self.pine_version >= int(removed_in):
            return False
        added_in = param.get("added_in")
        if added_in and self.pine_version < int(added_in):
            return False
        return True

    def _version_note(self, param: dict[str, Any]) -> str:
        removed_in = param.get("removed_in")
        added_in = param.get("added_in")
        if removed_in:
            return f"; removed in Pine v{removed_in}"
        if added_in:
            return f"; added in Pine v{added_in}"
        return ""
