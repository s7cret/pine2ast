"""Semantic value facts used by Release 4.0 signature and contract layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from pine2ast.ast.nodes import ConditionalExpr, Literal
from pine2ast.semantic.qualifier_infer import infer_qualifier
from pine2ast.semantic.type_infer import infer_type
from pine2ast.semantic.type_model import QUALIFIER_ORDER, generic_type_parts, is_reference_type


def is_bool_target_type(value: str | None) -> bool:
    if value == "bool":
        return True
    return bool(
        value and value.startswith("series<") and value.endswith(">") and value[7:-1] == "bool"
    )


def expression_can_be_na(expr) -> bool:
    if isinstance(expr, Literal):
        return expr.literal_type == "na"
    if isinstance(expr, ConditionalExpr):
        return expression_can_be_na(expr.if_true) or expression_can_be_na(expr.if_false)
    return False


@dataclass(frozen=True, slots=True)
class SemanticValue:
    type_name: str
    qualifier: str
    can_be_na: bool = False

    @property
    def is_reference(self) -> bool:
        return is_reference_type(self.type_name)

    @property
    def is_collection(self) -> bool:
        return generic_type_parts(self.type_name)[0] in {"array", "matrix", "map"}


def infer_semantic_value(expr, symbols: Mapping[str, object] | None = None) -> SemanticValue:
    return SemanticValue(
        type_name=infer_type(expr, symbols),
        qualifier=infer_qualifier(expr, symbols),
        can_be_na=expression_can_be_na(expr),
    )


__all__ = [
    "QUALIFIER_ORDER",
    "SemanticValue",
    "expression_can_be_na",
    "infer_semantic_value",
    "is_bool_target_type",
]
