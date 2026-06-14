"""Compatibility exports for the Release 4.0 Pine type model.

New code should prefer :mod:`pine2ast.semantic.type_model`; this module keeps the
older experimental import path stable for tests and downstream users.
"""

from __future__ import annotations

from pine2ast.semantic.type_model import (
    PineQualifier,
    PineType,
    collection_value_type,
    generic_type_parts,
    is_assignable_type,
    is_reference_type_name,
    is_valid_map_key_type,
    join_qualifiers,
    merge_type_names,
    normalize_qualifier,
    parse_type_string,
    qualifier_allows,
    split_top_level_csv,
    strip_series_type,
    type_is_assignable,
    type_to_string,
)

Qualifier = PineQualifier
is_reference_type = is_reference_type_name

__all__ = [
    "PineQualifier",
    "PineType",
    "Qualifier",
    "collection_value_type",
    "generic_type_parts",
    "is_assignable_type",
    "is_reference_type",
    "is_reference_type_name",
    "is_valid_map_key_type",
    "join_qualifiers",
    "merge_type_names",
    "normalize_qualifier",
    "parse_type_string",
    "qualifier_allows",
    "split_top_level_csv",
    "strip_series_type",
    "type_is_assignable",
    "type_to_string",
]
