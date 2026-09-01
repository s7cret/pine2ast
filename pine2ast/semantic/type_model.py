"""Formal Pine type and qualifier helpers for Release 4.0 semantic work.

The model is intentionally string-compatible with the existing AST/semantic
contracts. It centralizes Pine value/reference/collection/qualifier rules for
the signature resolver, legacy analyzer, and OpenPine contract extractors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

QualifierName = Literal["const", "input", "simple", "series"]

QUALIFIER_ORDER: dict[str, int] = {"const": 0, "input": 1, "simple": 2, "series": 3}
VALUE_TYPE_BASES = frozenset({"int", "float", "bool", "color", "string"})
COLLECTION_TYPE_BASES = frozenset({"array", "matrix", "map"})
REFERENCE_TYPE_BASES = frozenset(
    {
        "array",
        "matrix",
        "map",
        "line",
        "linefill",
        "label",
        "box",
        "table",
        "polyline",
        "chart.point",
        "footprint",
        "volume_row",
        "plot",
        "hline",
    }
)
ENUM_LIKE_BUILTIN_TYPES = frozenset(
    {
        "display",
        "line.style",
        "label.style",
        "box.style",
        "table.position",
        "barmerge.gaps",
        "barmerge.lookahead",
        "dividends.field",
        "earnings.field",
        "splits.field",
        "strategy.risk.type",
        "strategy.direction",
        "strategy.order_type",
        "extend",
        "order",
        "position",
        "scale",
        "xloc",
        "yloc",
        "location",
        "size",
        "shape",
        "format",
        "currency",
    }
)
# Backward-compatible names used by the foundation slice.
VALUE_TYPES = VALUE_TYPE_BASES
COLLECTION_TYPES = COLLECTION_TYPE_BASES
REFERENCE_TYPES = REFERENCE_TYPE_BASES
ENUM_LIKE_TYPES = ENUM_LIKE_BUILTIN_TYPES


@dataclass(frozen=True, slots=True)
class PineQualifier:
    name: QualifierName = "series"

    @property
    def rank(self) -> int:
        return QUALIFIER_ORDER.get(self.name, QUALIFIER_ORDER["series"])

    def allowed_by(self, maximum: str | None) -> bool:
        if not maximum:
            return True
        return self.rank <= QUALIFIER_ORDER.get(maximum, QUALIFIER_ORDER["series"])


@dataclass(frozen=True, slots=True)
class PineType:
    base: str
    args: tuple["PineType", ...] = ()

    @classmethod
    def parse(cls, value: str | None) -> "PineType":
        return parse_type_string(value)

    @property
    def name(self) -> str:
        return self.base

    @property
    def is_unknownish(self) -> bool:
        return self.base in {"unknown", "any"}

    @property
    def is_na(self) -> bool:
        return self.base == "na"

    @property
    def is_unknown(self) -> bool:
        return self.base in {"unknown", "any"}

    @property
    def is_numeric(self) -> bool:
        return self.base in {"int", "float"} and not self.args

    @property
    def is_value_type(self) -> bool:
        return self.base in VALUE_TYPE_BASES and not self.args

    @property
    def is_collection(self) -> bool:
        return self.base in COLLECTION_TYPE_BASES

    @property
    def is_reference_type(self) -> bool:
        return self.base in REFERENCE_TYPE_BASES

    @property
    def is_reference(self) -> bool:
        return self.is_reference_type

    @property
    def is_value_or_enum_type(self) -> bool:
        return (
            self.is_value_type or self.base in ENUM_LIKE_BUILTIN_TYPES
        ) and not self.is_collection

    @property
    def is_valid_map_key_type(self) -> bool:
        return is_valid_map_key_type(self.to_string())

    @property
    def inner_series_type(self) -> "PineType | None":
        if self.base == "series" and len(self.args) == 1:
            return self.args[0]
        return None

    def with_series_unwrapped(self) -> "PineType":
        return strip_series_type(self)

    def is_assignable_from(self, actual: "PineType") -> bool:
        return is_assignable_type(self.to_string(), actual.to_string())

    def to_string(self) -> str:
        if not self.args:
            return self.base
        return self.base + "<" + ",".join(arg.to_string() for arg in self.args) + ">"

    def __str__(self) -> str:
        return self.to_string()


UNKNOWN_TYPE = PineType("unknown")
ANY_TYPE = PineType("any")
NA_TYPE = PineType("na")


def normalize_qualifier(value: str | None, *, default: QualifierName = "series") -> QualifierName:
    if value in QUALIFIER_ORDER:
        return value  # type: ignore[return-value]
    return default


def join_qualifiers(*values: str | None) -> QualifierName:
    names = [normalize_qualifier(value) for value in values if value]
    if not names:
        return "series"
    return max(names, key=lambda value: QUALIFIER_ORDER.get(value, QUALIFIER_ORDER["series"]))


def qualifier_allows(maximum: str | None, actual: str | None) -> bool:
    return PineQualifier(normalize_qualifier(actual)).allowed_by(maximum)


def split_top_level_csv(inner: str) -> list[str]:
    result: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(inner):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            result.append(inner[start:idx].strip() or "unknown")
            start = idx + 1
    tail = inner[start:].strip()
    if tail:
        result.append(tail)
    return result


def parse_type_string(value: str | None) -> PineType:
    if not value:
        return UNKNOWN_TYPE
    text = str(value).strip()
    if not text:
        return UNKNOWN_TYPE
    for prefix in ("const ", "input ", "simple ", "series "):
        if text.startswith(prefix):
            qualifier = prefix.strip()
            inner_type = parse_type_string(text[len(prefix) :])
            if qualifier == "series":
                return PineType("series", (inner_type,))
            return inner_type
    if "<" not in text or not text.endswith(">"):
        return PineType(text)
    base, inner = text.split("<", 1)
    return PineType(
        base.strip(), tuple(parse_type_string(part) for part in split_top_level_csv(inner[:-1]))
    )


def type_to_string(value: PineType | str | None) -> str:
    if isinstance(value, PineType):
        return value.to_string()
    return parse_type_string(value).to_string()


def strip_series_type(value: PineType) -> PineType:
    return value.inner_series_type or value


def generic_type_parts(value: str | None) -> tuple[str | None, list[str]]:
    if not value:
        return None, []
    typ = parse_type_string(value)
    if typ.base == "unknown" and not value:
        return None, []
    return typ.base, [arg.to_string() for arg in typ.args]


def collection_value_type(value: str | None, *, key: bool = False) -> str | None:
    typ = parse_type_string(value)
    if typ.base in {"array", "matrix"} and typ.args:
        return typ.args[0].to_string()
    if typ.base == "map" and len(typ.args) >= 2:
        return typ.args[0 if key else 1].to_string()
    return None


def is_reference_type_name(value: str | None, *, enum_types: Iterable[str] | None = None) -> bool:
    typ = strip_series_type(parse_type_string(value))
    if typ.is_collection or typ.is_reference_type:
        return True
    enum_set = set(enum_types or ())
    if enum_set and typ.base not in VALUE_TYPE_BASES and typ.base not in enum_set:
        if typ.base not in ENUM_LIKE_BUILTIN_TYPES and typ.base not in {"unknown", "any", "na"}:
            return True
    return False


def is_reference_type(value: str | None) -> bool:
    return is_reference_type_name(value)


def is_valid_map_key_type(value: str | None, *, enum_types: Iterable[str] | None = None) -> bool:
    typ = strip_series_type(parse_type_string(value))
    if typ.base in {"unknown", "any"}:
        return True
    if typ.is_value_type:
        return True
    if typ.base in set(enum_types or ()):  # user-defined enum
        return True
    if typ.base in ENUM_LIKE_BUILTIN_TYPES:
        return True
    return False


def _split_top_level_union(value: str | None) -> list[str]:
    if not value or "|" not in value:
        return []
    result: list[str] = []
    depth = 0
    start = 0
    for idx, ch in enumerate(str(value)):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif ch == "|" and depth == 0:
            result.append(str(value)[start:idx].strip())
            start = idx + 1
    result.append(str(value)[start:].strip())
    return [part for part in result if part]


def is_assignable_type(expected: str | None, actual: str | None) -> bool:
    expected_union = _split_top_level_union(expected)
    if expected_union:
        return any(is_assignable_type(option, actual) for option in expected_union)
    actual_union = _split_top_level_union(actual)
    if actual_union:
        return all(is_assignable_type(expected, option) for option in actual_union)
    exp = strip_series_type(parse_type_string(expected))
    act = strip_series_type(parse_type_string(actual))
    if exp.base in {"any", "unknown"} or act.base in {"any", "unknown", "na"}:
        return True
    if exp == act:
        return True
    if exp.base == "float" and act.base == "int" and not exp.args and not act.args:
        return True
    if exp.base in ENUM_LIKE_BUILTIN_TYPES and act.base == exp.base:
        return True
    if exp.base == "int" and act.base in ENUM_LIKE_BUILTIN_TYPES:
        return True
    if exp.base in COLLECTION_TYPE_BASES:
        if exp.base == "array" and act.base == "tuple":
            if not exp.args or exp.args[0].base in {"any", "unknown"}:
                return True
            return all(
                is_assignable_type(exp.args[0].to_string(), arg.to_string()) for arg in act.args
            )
        if act.base != exp.base:
            return False
        if not exp.args or not act.args:
            return True
        if len(exp.args) != len(act.args):
            return False
        return all(
            expected_arg.base in {"any", "unknown"} or expected_arg == actual_arg
            for expected_arg, actual_arg in zip(exp.args, act.args, strict=True)
        )
    if exp.base.endswith("_direction") and act.base.startswith("strategy."):
        return True
    return False


def type_is_assignable(expected: str | PineType | None, actual: str | PineType | None) -> bool:
    return is_assignable_type(type_to_string(expected), type_to_string(actual))


def merge_type_names(values: list[str] | tuple[str, ...]) -> str:
    known = [value for value in values if value not in {"unknown", "na", None}]
    if not known:
        return "unknown"
    if all(value == known[0] for value in known):
        return known[0]
    if set(known) <= {"int", "float"}:
        return "float"
    return "unknown"


@dataclass(frozen=True, slots=True)
class QualifiedType:
    type_name: str
    qualifier: str = "series"

    @property
    def is_reference(self) -> bool:
        return is_reference_type_name(self.type_name)

    @property
    def is_collection(self) -> bool:
        return generic_type_parts(self.type_name)[0] in COLLECTION_TYPE_BASES
