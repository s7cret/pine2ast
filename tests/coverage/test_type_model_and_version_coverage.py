from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pine2ast.semantic import type_helpers
from pine2ast.semantic.type_model import (
    ANY_TYPE,
    COLLECTION_TYPE_BASES,
    ENUM_LIKE_BUILTIN_TYPES,
    NA_TYPE,
    UNKNOWN_TYPE,
    PineQualifier,
    PineType,
    QualifiedType,
    collection_value_type,
    generic_type_parts,
    is_assignable_type,
    is_reference_type,
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
from pine2ast.semantic.version_semantics import requirements_for_version
from pine2ast.semantic import version_coverage


def test_type_parser_qualifiers_and_round_trip() -> None:
    assert UNKNOWN_TYPE == PineType.parse(None) == PineType.parse(" ")
    assert ANY_TYPE.to_string() == "any"
    assert NA_TYPE.is_na
    assert parse_type_string("const int") == PineType("int")
    assert parse_type_string("input float") == PineType("float")
    assert parse_type_string("simple string") == PineType("string")

    series = parse_type_string("series array<map<string,array<float>>>")
    assert series.base == "series"
    assert series.inner_series_type is not None
    assert series.inner_series_type.to_string() == "array<map<string,array<float>>>"
    assert strip_series_type(series).to_string() == "array<map<string,array<float>>>"
    assert series.with_series_unwrapped() == strip_series_type(series)
    assert type_to_string(series) == "series<array<map<string,array<float>>>>"
    assert type_to_string("matrix<int>") == "matrix<int>"

    assert split_top_level_csv("int,map<string,array<float>>,tuple<int,string>") == [
        "int",
        "map<string,array<float>>",
        "tuple<int,string>",
    ]
    assert split_top_level_csv("int,,string,") == ["int", "unknown", "string"]
    assert generic_type_parts(None) == (None, [])
    assert generic_type_parts("map<string,array<float>>") == (
        "map",
        ["string", "array<float>"],
    )


def test_type_properties_reference_and_map_key_rules() -> None:
    numeric = PineType("int")
    assert numeric.name == "int"
    assert numeric.is_numeric and numeric.is_value_type and numeric.is_value_or_enum_type
    assert not numeric.is_collection and not numeric.is_reference
    assert numeric.is_valid_map_key_type

    collection = PineType.parse("array<float>")
    assert collection.is_collection and collection.is_reference_type and collection.is_reference
    assert not collection.is_value_or_enum_type and not collection.is_valid_map_key_type
    assert PineType("display").is_value_or_enum_type
    assert PineType("unknown").is_unknownish and PineType("any").is_unknown
    assert not PineType("tuple", (PineType("int"),)).is_numeric

    assert is_reference_type("series array<int>")
    assert is_reference_type_name("line")
    assert is_reference_type_name("MyUdt", enum_types={"MyEnum"})
    assert not is_reference_type_name("MyEnum", enum_types={"MyEnum"})
    assert not is_reference_type_name("display", enum_types={"MyEnum"})
    assert not is_reference_type_name("unknown", enum_types={"MyEnum"})

    for value in ("unknown", "any", "int", "float", "string", "display"):
        assert is_valid_map_key_type(value)
    assert is_valid_map_key_type("MyEnum", enum_types={"MyEnum"})
    for value in ("array<int>", "line", "MyUdt"):
        assert not is_valid_map_key_type(value, enum_types={"MyEnum"})

    assert collection_value_type("array<int>") == "int"
    assert collection_value_type("matrix<float>") == "float"
    assert collection_value_type("map<string,array<int>>") == "array<int>"
    assert collection_value_type("map<string,array<int>>", key=True) == "string"
    assert collection_value_type("map<string>") is None
    assert collection_value_type("int") is None


def test_qualifier_lattice_and_type_merging() -> None:
    assert PineQualifier("const").rank == 0
    assert PineQualifier("series").rank == 3
    assert PineQualifier("input").allowed_by("simple")
    assert not PineQualifier("series").allowed_by("simple")
    assert PineQualifier("series").allowed_by(None)

    assert normalize_qualifier("const") == "const"
    assert normalize_qualifier("invalid") == "series"
    assert normalize_qualifier(None, default="simple") == "simple"
    assert join_qualifiers() == "series"
    assert join_qualifiers("const", "input", "simple") == "simple"
    assert qualifier_allows("simple", "input")
    assert not qualifier_allows("input", "series")

    assert merge_type_names([]) == "unknown"
    assert merge_type_names(["na", "unknown"]) == "unknown"
    assert merge_type_names(["int", "int", "na"]) == "int"
    assert merge_type_names(["int", "float"]) == "float"
    assert merge_type_names(["string", "float"]) == "unknown"


def test_assignability_scalar_union_collection_and_direction_rules() -> None:
    accepted = [
        ("any", "line"),
        ("float", "unknown"),
        ("float", "na"),
        ("float", "float"),
        ("float", "int"),
        ("int", "display"),
        ("display", "display"),
        ("int|float", "int"),
        ("float", "int|float"),
        ("array<any>", "tuple<int,string>"),
        ("array<float>", "tuple<int,float>"),
        ("strategy_direction", "strategy.long"),
        ("series float", "series int"),
    ]
    rejected = [
        ("int", "float"),
        ("float", "int|string"),
        ("array<int>", "tuple<int,string>"),
        ("array<int>", "matrix<int>"),
        ("array<float>", "array<int>"),
        ("map<string,float>", "map<string,int>"),
        ("map<string,int>", "map<string,int,float>"),
        ("map<string,int>", "map<int,int>"),
        ("string", "bool"),
    ]
    for expected, actual in accepted:
        assert is_assignable_type(expected, actual), (expected, actual)
    for expected, actual in rejected:
        assert not is_assignable_type(expected, actual), (expected, actual)

    assert PineType("float").is_assignable_from(PineType("int"))
    assert type_is_assignable(PineType("float"), PineType("int"))
    assert not type_is_assignable("bool", "string")


def test_type_helpers_iterable_targets_tuple_and_type_refs() -> None:
    leaf = SimpleNamespace(name="int", template_args=[])
    nested = SimpleNamespace(name="array", template_args=[leaf])
    assert type_helpers.type_ref_name(None) == "unknown"
    assert type_helpers.type_ref_name(leaf) == "int"
    assert type_helpers.type_ref_name(nested) == "array<int>"

    assert type_helpers.split_type_args("int,map<string,float>") == [
        "int",
        "map<string,float>",
    ]
    assert type_helpers.for_in_target_types("array<float>", 1) == ["float"]
    assert type_helpers.for_in_target_types("array<float>", 2) == ["int", "float"]
    assert type_helpers.for_in_target_types("matrix<string>", 2) == ["int", "array<string>"]
    assert type_helpers.for_in_target_types("map<string,float>", 2) == ["string", "float"]
    assert type_helpers.for_in_target_types("map<string,float>", 1) == ["tuple<string,float>"]
    assert type_helpers.for_in_target_types("map<>", 1) == ["unknown"]
    assert type_helpers.for_in_target_types("tuple<int,string>", 3) == ["int", "string"]
    assert type_helpers.for_in_target_types("line", 2) == ["unknown", "unknown"]
    assert type_helpers.tuple_element_types("tuple<int,array<float>>") == [
        "int",
        "array<float>",
    ]
    assert type_helpers.tuple_element_types("array<int>") == []

    assert QualifiedType("array<int>").is_reference
    assert QualifiedType("matrix<float>").is_collection
    assert not QualifiedType("int").is_reference
    assert COLLECTION_TYPE_BASES == {"array", "matrix", "map"}
    assert "display" in ENUM_LIKE_BUILTIN_TYPES


def _rehash(report: dict[str, object]) -> None:
    body = dict(report)
    body.pop("content_hash", None)
    report["content_hash"] = version_coverage._hash(body)


def _all_frontend_test_ids() -> set[str]:
    return {
        requirement.test_id
        for version in range(1, 7)
        for requirement in requirements_for_version(version, owner="pine2ast")
    }


def test_version_coverage_builds_and_validates_all_axes() -> None:
    report = version_coverage.build_version_coverage_report(
        verified_test_ids=_all_frontend_test_ids(),
        full_test_suite_passed=True,
        catalog_gate_passed=True,
        differential_gate_passed=True,
    )
    assert version_coverage.validate_version_coverage_report(report) == ()
    assert report["full_test_suite_passed"] is True
    assert report["coverage_policy"]["internal_catalog_is_not_official_coverage"] is True
    assert set(report["versions"]) == {"1", "2", "3", "4", "5", "6"}
    for version, row in report["versions"].items():
        assert row["pine_version"] == int(version)
        assert row["version_resolution"]["coverage_percent"] == 100.0
        assert row["normative_static_frontend"]["coverage_percent"] == 100.0
        assert row["internal_catalog"]["structural_gate_passed"] is True
        assert row["internal_catalog"]["pack_sha256"].startswith("sha256:")
        assert row["official_reference_symbol_coverage"]["coverage_percent"] is None
        assert row["tradingview_runtime_oracle"]["coverage_percent"] == 0.0

    empty = version_coverage.build_version_coverage_report()
    assert version_coverage.validate_version_coverage_report(empty) == ()
    assert all(
        row["normative_static_frontend"]["verified"] == 0 for row in empty["versions"].values()
    )


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda report: report.__setitem__("schema_id", "bad"), "schema_id"),
        (lambda report: report.pop("content_hash"), "content_hash_missing"),
        (lambda report: report.__setitem__("content_hash", "sha256:bad"), "content_hash_mismatch"),
        (lambda report: report.__setitem__("versions", {}), "version_set"),
        (lambda report: report["versions"].__setitem__("1", []), "v1.row"),
        (
            lambda report: report["versions"]["1"].__setitem__("normative_static_frontend", None),
            "v1.static",
        ),
        (
            lambda report: report["versions"]["1"]["normative_static_frontend"].update(
                {"requirements_total": -1}
            ),
            "v1.static_counts",
        ),
        (
            lambda report: report["versions"]["1"]["normative_static_frontend"].update(
                {"coverage_percent": 12.34}
            ),
            "v1.static_percent",
        ),
        (
            lambda report: report["versions"]["1"].__setitem__(
                "official_reference_symbol_coverage",
                {"coverage_percent": 100.0, "status": "CLAIMED"},
            ),
            "v1.official_claim",
        ),
        (
            lambda report: report["versions"]["1"].__setitem__(
                "tradingview_runtime_oracle", {"coverage_percent": 1.0, "status": "PASS"}
            ),
            "v1.oracle_claim",
        ),
        (
            lambda report: report["versions"]["1"].__setitem__(
                "downstream_semantics", {"verified_by_pine2ast": 1}
            ),
            "v1.downstream_claim",
        ),
    ],
)
def test_version_coverage_validation_rejects_false_claims(mutator, expected: str) -> None:
    report = version_coverage.build_version_coverage_report()
    mutator(report)
    if expected not in {"content_hash_missing", "content_hash_mismatch"}:
        _rehash(report)
    assert expected in version_coverage.validate_version_coverage_report(report)


def test_pack_metric_fallback_and_unique_pack_invariant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "pine2ast"
    packs = root / "catalog_data" / "packs"
    packs.mkdir(parents=True)
    payload = {
        "status": "MATERIALIZED",
        "payload": [
            {"symbol_id": "f", "kind": "function"},
            {"symbol_id": "m", "kind": "method"},
            {"symbol_id": "op", "kind": "operator"},
            {"symbol_id": "v", "kind": "variable"},
        ],
    }
    pack = packs / "pine_v1.pack.json"
    pack.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(version_coverage, "_package_root", lambda: root)

    metrics = version_coverage._pack_metrics(1)
    assert metrics["symbol_count"] == 4
    assert metrics["callable_count"] == 2
    assert metrics["operator_count"] == 1
    assert metrics["status"] == "MATERIALIZED"

    duplicate = root / "other" / "pine-v1.pack.json"
    duplicate.parent.mkdir()
    duplicate.write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="exactly one"):
        version_coverage._find_pack(1)
    with pytest.raises(FileNotFoundError, match="Pine v2"):
        version_coverage._find_pack(2)
