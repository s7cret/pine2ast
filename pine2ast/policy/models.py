from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pine2ast.versioning import PineVersionContext


def _pairs(value: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple((str(key), value[key]) for key in sorted(value))


@dataclass(frozen=True, slots=True)
class SyntaxPolicy:
    pine_version: int
    catalog_hash: str
    keyword_spellings: frozenset[str]
    operator_spellings: frozenset[str]
    declaration_spellings: frozenset[str]
    annotation_spellings: frozenset[str]
    capabilities: tuple[tuple[str, bool], ...]
    rule_ids: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.catalog_hash.startswith("sha256:"):
            raise ValueError("syntax policy must be bound to a catalog hash")
        if not self.rule_ids:
            raise ValueError("syntax policy rule IDs are required")
        if not self.declaration_spellings:
            raise ValueError("at least one Pine declaration spelling is required")

    def capability(self, name: str) -> bool:
        values = dict(self.capabilities)
        if name not in values:
            raise KeyError(f"syntax policy has no capability {name!r}")
        return bool(values[name])

    def rule_id(self, name: str) -> str:
        values = dict(self.rule_ids)
        if name not in values:
            raise KeyError(f"syntax policy has no rule ID {name!r}")
        return values[name]

    def validate_context(self, context: PineVersionContext) -> None:
        if self.pine_version != context.pine_version:
            raise ValueError("syntax policy Pine version does not match PineVersionContext")
        if self.catalog_hash != context.catalog_hash:
            raise ValueError("syntax policy catalog hash does not match PineVersionContext")

    def to_dict(self) -> dict[str, Any]:
        return {
            "pine_version": self.pine_version,
            "catalog_hash": self.catalog_hash,
            "keyword_spellings": sorted(self.keyword_spellings),
            "operator_spellings": sorted(self.operator_spellings),
            "declaration_spellings": sorted(self.declaration_spellings),
            "annotation_spellings": sorted(self.annotation_spellings),
            "capabilities": dict(self.capabilities),
            "rule_ids": dict(self.rule_ids),
        }


@dataclass(frozen=True, slots=True)
class SemanticPolicy:
    pine_version: int
    catalog_hash: str
    qualifier_model: str
    qualifier_order: tuple[str, ...]
    logical_evaluation: str
    ternary_evaluation: str
    bool_allows_na: bool
    numeric_condition_allowed: bool
    bool_to_number: str
    const_int_division: str
    request_default: str
    security_lookahead_default: str
    for_range_end: str
    self_reference_declaration: str
    forward_reference_declaration: str
    builtin_named_arguments: str
    na_declaration_type: str
    mutable_in_security_expression: str
    rule_ids: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.qualifier_order != ("const", "input", "simple", "series"):
            raise ValueError("unsupported Pine qualifier lattice")
        _one_of("qualifier_model", self.qualifier_model, {"LEGACY", "V4", "MODERN"})
        _one_of("logical_evaluation", self.logical_evaluation, {"EAGER", "LAZY"})
        _one_of("ternary_evaluation", self.ternary_evaluation, {"EAGER", "LAZY"})
        _one_of("bool_to_number", self.bool_to_number, {"ALLOW", "FORBID"})
        _one_of("const_int_division", self.const_int_division, {"TRUNCATE", "FRACTIONAL"})
        _one_of("request_default", self.request_default, {"STATIC", "DYNAMIC"})
        _one_of("security_lookahead_default", self.security_lookahead_default, {"ON", "OFF"})
        _one_of("for_range_end", self.for_range_end, {"FIXED", "DYNAMIC"})
        _one_of("self_reference_declaration", self.self_reference_declaration, {"ALLOW", "FORBID"})
        _one_of(
            "forward_reference_declaration", self.forward_reference_declaration, {"ALLOW", "FORBID"}
        )
        _one_of(
            "builtin_named_arguments",
            self.builtin_named_arguments,
            {"ALL", "DECLARATIONS_ONLY", "NONE"},
        )
        _one_of("na_declaration_type", self.na_declaration_type, {"INFER", "EXPLICIT_REQUIRED"})
        _one_of(
            "mutable_in_security_expression",
            self.mutable_in_security_expression,
            {"ALLOW", "FORBID", "NOT_APPLICABLE"},
        )
        if not self.rule_ids:
            raise ValueError("semantic policy rule IDs are required")

    def validate_context(self, context: PineVersionContext) -> None:
        if self.pine_version != context.pine_version:
            raise ValueError("semantic policy Pine version does not match PineVersionContext")
        if self.catalog_hash != context.catalog_hash:
            raise ValueError("semantic policy catalog hash does not match PineVersionContext")

    def qualifier_rank(self, name: str | None) -> int:
        normalized = name if name in self.qualifier_order else "series"
        return self.qualifier_order.index(normalized)

    def qualifier_allows(self, maximum: str | None, actual: str | None) -> bool:
        if maximum is None:
            return True
        return self.qualifier_rank(actual) <= self.qualifier_rank(maximum)

    def rule_id(self, name: str) -> str:
        values = dict(self.rule_ids)
        if name not in values:
            raise KeyError(f"semantic policy has no rule ID {name!r}")
        return values[name]

    @property
    def dynamic_requests_default(self) -> bool:
        return self.request_default == "DYNAMIC"

    @property
    def const_int_division_fractional(self) -> bool:
        return self.const_int_division == "FRACTIONAL"

    @property
    def uses_v6_bool_rules(self) -> bool:
        return not self.bool_allows_na and not self.numeric_condition_allowed

    @property
    def allows_bool_to_number(self) -> bool:
        return self.bool_to_number == "ALLOW"

    @property
    def allows_self_reference(self) -> bool:
        return self.self_reference_declaration == "ALLOW"

    @property
    def allows_forward_reference(self) -> bool:
        return self.forward_reference_declaration == "ALLOW"

    @property
    def requires_explicit_na_type(self) -> bool:
        return self.na_declaration_type == "EXPLICIT_REQUIRED"

    @property
    def forbids_mutable_security_expression(self) -> bool:
        return self.mutable_in_security_expression == "FORBID"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pine_version": self.pine_version,
            "catalog_hash": self.catalog_hash,
            "qualifier_model": self.qualifier_model,
            "qualifier_order": list(self.qualifier_order),
            "logical_evaluation": self.logical_evaluation,
            "ternary_evaluation": self.ternary_evaluation,
            "bool_allows_na": self.bool_allows_na,
            "numeric_condition_allowed": self.numeric_condition_allowed,
            "bool_to_number": self.bool_to_number,
            "const_int_division": self.const_int_division,
            "request_default": self.request_default,
            "security_lookahead_default": self.security_lookahead_default,
            "for_range_end": self.for_range_end,
            "self_reference_declaration": self.self_reference_declaration,
            "forward_reference_declaration": self.forward_reference_declaration,
            "builtin_named_arguments": self.builtin_named_arguments,
            "na_declaration_type": self.na_declaration_type,
            "mutable_in_security_expression": self.mutable_in_security_expression,
            "rule_ids": dict(self.rule_ids),
        }


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    syntax: SyntaxPolicy
    semantic: SemanticPolicy

    def validate_context(self, context: PineVersionContext) -> None:
        self.syntax.validate_context(context)
        self.semantic.validate_context(context)
        if self.syntax.catalog_hash != self.semantic.catalog_hash:
            raise ValueError("syntax and semantic policies are not from one catalog pack")


def _one_of(field: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed)}, got {value!r}")


def syntax_policy_from_catalog(
    context: PineVersionContext, catalog: Mapping[str, Any]
) -> SyntaxPolicy:
    rules = catalog.get("rules")
    if not isinstance(rules, Mapping) or not isinstance(rules.get("syntax"), Mapping):
        raise ValueError("catalog does not contain a structured syntax policy")
    section = rules["syntax"]
    capabilities = section.get("capabilities")
    rule_ids = section.get("rule_ids")
    if not isinstance(capabilities, Mapping) or not isinstance(rule_ids, Mapping):
        raise ValueError("catalog syntax policy is incomplete")
    declaration_spellings = set(str(item) for item in catalog.get("declarations", {}))
    if not declaration_spellings:
        for name, definition in catalog.get("functions", {}).items():
            if isinstance(definition, Mapping) and definition.get("kind") == "declaration":
                declaration_spellings.add(str(name))
    keyword_spellings = {str(item) for item in catalog.get("keywords", {})}
    semantic_section = rules.get("semantic")
    qualifier_model = (
        str(semantic_section.get("qualifier_model"))
        if isinstance(semantic_section, Mapping)
        else ""
    )
    if qualifier_model == "MODERN":
        keyword_spellings.update({"simple", "series"})
    if bool(capabilities.get("exported_const")):
        keyword_spellings.add("const")

    policy = SyntaxPolicy(
        pine_version=context.pine_version,
        catalog_hash=context.catalog_hash,
        keyword_spellings=frozenset(keyword_spellings),
        operator_spellings=frozenset(str(item) for item in catalog.get("operators", {})),
        declaration_spellings=frozenset(declaration_spellings),
        annotation_spellings=frozenset(str(item) for item in catalog.get("annotations", {})),
        capabilities=tuple((key, bool(value)) for key, value in _pairs(capabilities)),
        rule_ids=tuple((key, str(value)) for key, value in _pairs(rule_ids)),
    )
    policy.validate_context(context)
    return policy


def semantic_policy_from_catalog(
    context: PineVersionContext, catalog: Mapping[str, Any]
) -> SemanticPolicy:
    rules = catalog.get("rules")
    if not isinstance(rules, Mapping) or not isinstance(rules.get("semantic"), Mapping):
        raise ValueError("catalog does not contain a structured semantic policy")
    section = rules["semantic"]
    rule_ids = section.get("rule_ids")
    if not isinstance(rule_ids, Mapping):
        raise ValueError("catalog semantic policy rule IDs are missing")
    qualifier_order = tuple(str(item) for item in section.get("qualifier_order", ()))
    policy = SemanticPolicy(
        pine_version=context.pine_version,
        catalog_hash=context.catalog_hash,
        qualifier_model=str(section.get("qualifier_model")),
        qualifier_order=qualifier_order,
        logical_evaluation=str(section.get("logical_evaluation")),
        ternary_evaluation=str(section.get("ternary_evaluation")),
        bool_allows_na=bool(section.get("bool_allows_na")),
        numeric_condition_allowed=bool(section.get("numeric_condition_allowed")),
        bool_to_number=str(section.get("bool_to_number")),
        const_int_division=str(section.get("const_int_division")),
        request_default=str(section.get("request_default")),
        security_lookahead_default=str(section.get("security_lookahead_default")),
        for_range_end=str(section.get("for_range_end")),
        self_reference_declaration=str(section.get("self_reference_declaration")),
        forward_reference_declaration=str(section.get("forward_reference_declaration")),
        builtin_named_arguments=str(section.get("builtin_named_arguments")),
        na_declaration_type=str(section.get("na_declaration_type")),
        mutable_in_security_expression=str(section.get("mutable_in_security_expression")),
        rule_ids=tuple((key, str(value)) for key, value in _pairs(rule_ids)),
    )
    policy.validate_context(context)
    return policy


def policy_bundle_from_catalog(
    context: PineVersionContext, catalog: Mapping[str, Any]
) -> PolicyBundle:
    if str(catalog.get("pine_version")) != str(context.pine_version):
        raise ValueError("catalog Pine version does not match PineVersionContext")
    if catalog.get("catalog_hash") != context.catalog_hash:
        raise ValueError("catalog hash does not match PineVersionContext")
    bundle = PolicyBundle(
        syntax=syntax_policy_from_catalog(context, catalog),
        semantic=semantic_policy_from_catalog(context, catalog),
    )
    bundle.validate_context(context)
    return bundle


__all__ = [
    "PolicyBundle",
    "SemanticPolicy",
    "SyntaxPolicy",
    "policy_bundle_from_catalog",
    "semantic_policy_from_catalog",
    "syntax_policy_from_catalog",
]
