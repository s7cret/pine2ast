from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pine2ast.catalog import CatalogRepository

_REQUIRED_SECTIONS = (
    "annotations",
    "keywords",
    "operators",
    "declarations",
    "functions",
    "methods",
    "variables",
    "constants",
    "types",
    "namespaces",
    "enum_values",
)
_REQUIRED_SEMANTIC_RULES = {
    "condition",
    "logical_and",
    "logical_or",
    "ternary",
    "const_int_division",
    "request_default",
    "security_lookahead_default",
    "for_range_end",
    "qualifier_lattice",
    "self_reference_declaration",
    "forward_reference_declaration",
    "bool_to_number",
    "na_declaration_type",
    "mutable_in_security_expression",
    "builtin_named_arguments",
}
_QUALIFIERS = {"const", "input", "simple", "series"}
_FORBIDDEN_DOWNSTREAM_FIELDS = {
    "runtime_contract_unsupported",
    "ast2python_lowerable",
    "pinelib_runtime_support",
    "simulation_support",
    "live_safe",
    "codegen",
    "runtime",
    "simulation",
}
_EXPECTED_STATUS = {
    1: "HISTORICAL_STATIC_SNAPSHOT",
    2: "HISTORICAL_STATIC_SNAPSHOT",
    3: "HISTORICAL_STATIC_SNAPSHOT",
    4: "HISTORICAL_STATIC_SNAPSHOT",
    5: "STATIC_COMPLETE",
    6: "STATIC_COMPLETE",
}


@dataclass(frozen=True, slots=True)
class StaticCompletenessReport:
    pine_version: int
    catalog_hash: str
    status: str
    coverage_basis: str
    scope: str
    symbol_count: int
    callable_count: int
    overload_count: int
    operator_count: int
    checked_field_count: int
    gaps: tuple[dict[str, Any], ...]

    @property
    def ok(self) -> bool:
        return not self.gaps

    @property
    def coverage_ratio(self) -> float:
        denominator = self.checked_field_count + len(self.gaps)
        return 1.0 if denominator == 0 else self.checked_field_count / denominator

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "pine.static_completeness.v2",
            "pine_version": self.pine_version,
            "catalog_hash": self.catalog_hash,
            "status": self.status,
            "coverage_basis": self.coverage_basis,
            "scope": self.scope,
            "ok": self.ok,
            "coverage_ratio": self.coverage_ratio,
            "symbol_count": self.symbol_count,
            "callable_count": self.callable_count,
            "overload_count": self.overload_count,
            "operator_count": self.operator_count,
            "checked_field_count": self.checked_field_count,
            "gap_count": len(self.gaps),
            "gaps": list(self.gaps),
        }


def _gap(gaps: list[dict[str, Any]], code: str, path: str, message: str) -> None:
    gaps.append({"code": code, "path": path, "message": message})


def _validate_parameter(
    param: object,
    *,
    path: str,
    names: set[str],
    gaps: list[dict[str, Any]],
) -> int:
    checked = 0
    if not isinstance(param, Mapping):
        _gap(gaps, "PARAMETER", path, "parameter must be an object")
        return checked
    name = param.get("name")
    typ = param.get("type")
    if not isinstance(name, str) or not name or name in names:
        _gap(gaps, "PARAMETER_NAME", f"{path}.name", "unique parameter name required")
    else:
        names.add(name)
        checked += 1
    if not isinstance(typ, str) or not typ:
        _gap(gaps, "PARAMETER_TYPE", f"{path}.type", "parameter type required")
    else:
        checked += 1
    qualifier = param.get("qualifier_max")
    if qualifier is not None and qualifier not in _QUALIFIERS:
        _gap(gaps, "PARAMETER_QUALIFIER", f"{path}.qualifier_max", "invalid qualifier")
    else:
        checked += 1
    return checked


def pinned_catalog_static_completeness(
    pine_version: int,
    *,
    repository: CatalogRepository | None = None,
) -> StaticCompletenessReport:
    """Validate every field in one immutable Pine version pack.

    For Pine v1-v4 this proves internal completeness of the documented historical
    snapshot assembled from official migration guides and archived manuals. It is
    deliberately not an assertion that TradingView published an exhaustive
    machine-readable reference for those versions. Pine v5/v6 retain the pinned
    reference-registry scope used by the prior release stages.
    """

    if pine_version not in _EXPECTED_STATUS:
        raise ValueError("Pine version must be an integer from 1 through 6")
    repo = repository or CatalogRepository.default()
    pack = repo.pack(pine_version)
    gaps: list[dict[str, Any]] = []
    checked = 0

    status = str(pack.get("status") or "")
    expected_status = _EXPECTED_STATUS[pine_version]
    if status != expected_status:
        _gap(gaps, "STATUS", "status", f"expected {expected_status}, got {status!r}")
    else:
        checked += 1

    coverage_basis = str(pack.get("coverage_basis") or "")
    if not coverage_basis:
        _gap(gaps, "COVERAGE_BASIS", "coverage_basis", "coverage basis is required")
    else:
        checked += 1

    sections = pack.get("sections")
    if not isinstance(sections, Mapping):
        _gap(gaps, "SECTIONS", "sections", "catalog sections must be an object")
        sections = {}
    for section in _REQUIRED_SECTIONS:
        if not isinstance(sections.get(section), Mapping):
            _gap(gaps, "SECTION_MISSING", f"sections.{section}", "required section is missing")
        else:
            checked += 1

    rules_value = pack.get("rules")
    rules: Mapping[str, Any] = rules_value if isinstance(rules_value, Mapping) else {}
    syntax_value = rules.get("syntax")
    syntax: Mapping[str, Any] = syntax_value if isinstance(syntax_value, Mapping) else {}
    semantic_value = rules.get("semantic")
    semantic: Mapping[str, Any] = semantic_value if isinstance(semantic_value, Mapping) else {}
    syntax_caps_value = syntax.get("capabilities")
    syntax_caps: Mapping[str, Any] = (
        syntax_caps_value if isinstance(syntax_caps_value, Mapping) else {}
    )
    syntax_ids_value = syntax.get("rule_ids")
    syntax_ids: Mapping[str, Any] = (
        syntax_ids_value if isinstance(syntax_ids_value, Mapping) else {}
    )
    semantic_ids_value = semantic.get("rule_ids")
    semantic_ids: Mapping[str, Any] = (
        semantic_ids_value if isinstance(semantic_ids_value, Mapping) else {}
    )

    if not syntax_caps:
        _gap(gaps, "SYNTAX_CAPABILITIES", "rules.syntax.capabilities", "capability map is required")
    for name, value in sorted(syntax_caps.items()):
        if type(value) is not bool:
            _gap(
                gaps,
                "SYNTAX_CAPABILITY",
                f"rules.syntax.capabilities.{name}",
                "boolean capability required",
            )
        else:
            checked += 1
        rule_id = syntax_ids.get(name)
        if not isinstance(rule_id, str) or not rule_id:
            _gap(gaps, "SYNTAX_RULE_ID", f"rules.syntax.rule_ids.{name}", "stable rule ID required")
        else:
            checked += 1
    extra_syntax_ids = sorted(set(syntax_ids) - set(syntax_caps))
    if extra_syntax_ids:
        _gap(
            gaps,
            "ORPHAN_SYNTAX_RULE_ID",
            "rules.syntax.rule_ids",
            f"orphan IDs: {extra_syntax_ids}",
        )

    for name in sorted(_REQUIRED_SEMANTIC_RULES):
        rule_id = semantic_ids.get(name)
        if not isinstance(rule_id, str) or not rule_id:
            _gap(
                gaps,
                "SEMANTIC_RULE_ID",
                f"rules.semantic.rule_ids.{name}",
                "stable rule ID required",
            )
        else:
            checked += 1
    if semantic.get("qualifier_order") != ["const", "input", "simple", "series"]:
        _gap(
            gaps,
            "QUALIFIER_LATTICE",
            "rules.semantic.qualifier_order",
            "exact Pine qualifier order required",
        )
    else:
        checked += 1

    seen_symbol_ids: set[str] = set()
    symbol_count = 0
    callable_count = 0
    overload_count = 0
    operator_count = 0
    for section, mapping in sections.items():
        if not isinstance(mapping, Mapping):
            continue
        for name, definition in mapping.items():
            symbol_count += 1
            path = f"sections.{section}.{name}"
            if not isinstance(definition, Mapping):
                _gap(gaps, "DEFINITION", path, "symbol definition must be an object")
                continue
            symbol_id = definition.get("symbol_id")
            if not isinstance(symbol_id, str) or not symbol_id:
                _gap(gaps, "SYMBOL_ID", f"{path}.symbol_id", "stable symbol_id required")
            elif symbol_id in seen_symbol_ids:
                _gap(gaps, "SYMBOL_ID_DUPLICATE", f"{path}.symbol_id", "symbol_id must be unique")
            else:
                seen_symbol_ids.add(symbol_id)
                checked += 1
            if definition.get("name") != name:
                _gap(gaps, "NAME", f"{path}.name", "definition name must match active spelling")
            else:
                checked += 1
            forbidden = sorted(_FORBIDDEN_DOWNSTREAM_FIELDS & set(definition))
            if forbidden:
                _gap(
                    gaps,
                    "DOWNSTREAM_FIELD",
                    path,
                    f"downstream-owned fields are forbidden: {forbidden}",
                )
            else:
                checked += 1

            if section in {"functions", "methods"}:
                callable_count += 1
                params = definition.get("parameters")
                overloads = definition.get("overloads")
                if params is None and not isinstance(overloads, list):
                    _gap(gaps, "CALLABLE_SIGNATURE", path, "parameters or overloads are required")
                elif params is not None:
                    if not isinstance(params, list):
                        _gap(gaps, "PARAMETERS", f"{path}.parameters", "parameter list required")
                    else:
                        checked += 1
                        names: set[str] = set()
                        for index, param in enumerate(params):
                            checked += _validate_parameter(
                                param,
                                path=f"{path}.parameters[{index}]",
                                names=names,
                                gaps=gaps,
                            )
                returns = definition.get("returns")
                if returns is not None:
                    if not isinstance(returns, str) or not returns:
                        _gap(gaps, "RETURN_TYPE", f"{path}.returns", "return type required")
                    elif returns in {"unknown", "any"} and not isinstance(
                        definition.get("return_rule_id"), str
                    ):
                        _gap(
                            gaps,
                            "RETURN_RULE",
                            f"{path}.return_rule_id",
                            "parametric return rule required",
                        )
                    else:
                        checked += 1
                elif not isinstance(overloads, list):
                    _gap(
                        gaps,
                        "RETURN_TYPE",
                        f"{path}.returns",
                        "return type or overload returns required",
                    )
                if section == "methods":
                    receiver = definition.get("receiver_type")
                    if not isinstance(receiver, str) or not receiver:
                        _gap(
                            gaps,
                            "RECEIVER",
                            f"{path}.receiver_type",
                            "method receiver type required",
                        )
                    else:
                        checked += 1
                if overloads is not None:
                    if not isinstance(overloads, list):
                        _gap(gaps, "OVERLOADS", f"{path}.overloads", "overloads must be an array")
                    else:
                        overload_ids: set[str] = set()
                        for index, overload in enumerate(overloads):
                            overload_count += 1
                            opath = f"{path}.overloads[{index}]"
                            if not isinstance(overload, Mapping):
                                _gap(gaps, "OVERLOAD", opath, "overload must be an object")
                                continue
                            oid = overload.get("overload_id")
                            if not isinstance(oid, str) or not oid or oid in overload_ids:
                                _gap(
                                    gaps,
                                    "OVERLOAD_ID",
                                    f"{opath}.overload_id",
                                    "unique stable overload_id required",
                                )
                            else:
                                overload_ids.add(oid)
                                checked += 1
                            oparams = overload.get("parameters")
                            if not isinstance(oparams, list):
                                _gap(
                                    gaps,
                                    "OVERLOAD_PARAMETERS",
                                    f"{opath}.parameters",
                                    "overload parameter list required",
                                )
                            else:
                                checked += 1
                                names = set()
                                for pindex, param in enumerate(oparams):
                                    checked += _validate_parameter(
                                        param,
                                        path=f"{opath}.parameters[{pindex}]",
                                        names=names,
                                        gaps=gaps,
                                    )
                            oreturn = overload.get("returns")
                            if not isinstance(oreturn, str) or not oreturn:
                                _gap(
                                    gaps,
                                    "OVERLOAD_RETURN",
                                    f"{opath}.returns",
                                    "overload return type required",
                                )
                            else:
                                checked += 1

            if section == "operators":
                operator_count += 1
                if (
                    not isinstance(definition.get("static_rule_id"), str)
                    or not definition["static_rule_id"]
                ):
                    _gap(
                        gaps,
                        "OPERATOR_RULE",
                        f"{path}.static_rule_id",
                        "operator static rule ID required",
                    )
                else:
                    checked += 1

    scope = (
        "documented_historical_static_snapshot"
        if pine_version <= 4
        else "pinned_hash_bound_reference_catalog"
    )
    return StaticCompletenessReport(
        pine_version=pine_version,
        catalog_hash=str(pack.get("catalog_hash") or ""),
        status=status,
        coverage_basis=coverage_basis,
        scope=scope,
        symbol_count=symbol_count,
        callable_count=callable_count,
        overload_count=overload_count,
        operator_count=operator_count,
        checked_field_count=checked,
        gaps=tuple(gaps),
    )


__all__ = ["StaticCompletenessReport", "pinned_catalog_static_completeness"]
