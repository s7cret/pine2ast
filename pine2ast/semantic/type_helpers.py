"""Pure semantic type-string helpers."""

from __future__ import annotations

from pine2ast.semantic.type_model import (
    collection_value_type,
    generic_type_parts,
    is_assignable_type,
    is_reference_type,
    is_valid_map_key_type,
    split_top_level_csv,
)

__all__ = [
    "collection_value_type",
    "for_in_target_types",
    "generic_type_parts",
    "is_assignable_type",
    "is_reference_type",
    "is_valid_map_key_type",
    "split_type_args",
    "tuple_element_types",
    "type_ref_name",
]


def type_ref_name(type_ref) -> str:
    if type_ref is None:
        return "unknown"
    args = getattr(type_ref, "template_args", None) or []
    if not args:
        return type_ref.name
    return type_ref.name + "<" + ",".join(type_ref_name(arg) for arg in args) + ">"


def split_type_args(inner: str) -> list[str]:
    return split_top_level_csv(inner)


def for_in_target_types(iterable_type: str, target_count: int) -> list[str]:
    if iterable_type.startswith("array<") and iterable_type.endswith(">"):
        element = iterable_type[len("array<") : -1].strip() or "unknown"
        return ["int", element] if target_count == 2 else [element]
    if iterable_type.startswith("matrix<") and iterable_type.endswith(">"):
        element = iterable_type[len("matrix<") : -1].strip() or "unknown"
        row = f"array<{element}>"
        return ["int", row] if target_count == 2 else [row]
    if iterable_type.startswith("map<") and iterable_type.endswith(">"):
        parts = split_type_args(iterable_type[len("map<") : -1])
        if target_count == 2 and len(parts) >= 2:
            return [parts[0], parts[1]]
        return ["tuple<" + ",".join(parts[:2]) + ">" if parts else "unknown"]
    if iterable_type.startswith("tuple<") and iterable_type.endswith(">"):
        return split_type_args(iterable_type[len("tuple<") : -1])
    return ["unknown"] * target_count


def tuple_element_types(typ: str) -> list[str]:
    if not typ.startswith("tuple<") or not typ.endswith(">"):
        return list()
    return split_type_args(typ[len("tuple<") : -1])
