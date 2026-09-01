from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pine2ast.hardening import introspection
from pine2ast.hardening.introspection import FrontendIntrospectionError
from pine2ast.semantic.type_model import (
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "unknown"),
        ("", "unknown"),
        ("   ", "unknown"),
        ("const int", "int"),
        ("input float", "float"),
        ("simple bool", "bool"),
        ("series int", "series<int>"),
        ("array<map<string,float>>", "array<map<string,float>>"),
        ("map<string,array<float>>", "map<string,array<float>>"),
        ("tuple<int,float,bool>", "tuple<int,float,bool>"),
    ],
)
def test_type_parser_and_string_roundtrip(raw: str | None, expected: str) -> None:
    parsed = parse_type_string(raw)
    assert parsed.to_string() == expected
    assert str(parsed) == expected
    assert PineType.parse(raw) == parsed
    assert type_to_string(parsed) == expected
    assert type_to_string(raw) == expected


def test_type_properties_and_qualifiers_cover_value_reference_and_series_shapes() -> None:
    const = PineQualifier("const")
    series = PineQualifier("series")
    assert const.rank == 0
    assert series.rank == 3
    assert const.allowed_by(None)
    assert const.allowed_by("simple")
    assert not series.allowed_by("input")
    assert PineQualifier("invalid").rank == 3  # type: ignore[arg-type]

    assert normalize_qualifier("input") == "input"
    assert normalize_qualifier("invalid", default="simple") == "simple"
    assert join_qualifiers() == "series"
    assert join_qualifiers("const", "input", "simple") == "simple"
    assert qualifier_allows("simple", "input")
    assert not qualifier_allows("input", "series")

    integer = PineType("int")
    unknown = PineType("unknown")
    na_type = PineType("na")
    array = PineType("array", (integer,))
    series_int = PineType("series", (integer,))
    assert integer.name == "int"
    assert integer.is_numeric and integer.is_value_type
    assert not integer.is_collection and not integer.is_reference
    assert unknown.is_unknownish and unknown.is_unknown
    assert na_type.is_na
    assert array.is_collection and array.is_reference_type and array.is_reference
    assert integer.is_value_or_enum_type
    assert PineType("display").is_value_or_enum_type
    assert series_int.inner_series_type == integer
    assert PineType("series").inner_series_type is None
    assert series_int.with_series_unwrapped() == integer
    assert strip_series_type(integer) == integer
    assert array.is_valid_map_key_type is False
    assert PineType("string").is_valid_map_key_type is True
    assert PineType("float").is_assignable_from(PineType("int"))

    qualified = QualifiedType("array<float>", "series")
    assert qualified.is_reference
    assert qualified.is_collection
    assert not QualifiedType("float").is_reference


def test_type_splitting_generic_parts_and_collection_value_lookup() -> None:
    assert split_top_level_csv("") == []
    assert split_top_level_csv("int,map<string,float>,,array<int>") == [
        "int",
        "map<string,float>",
        "unknown",
        "array<int>",
    ]
    assert generic_type_parts(None) == (None, [])
    assert generic_type_parts("array<map<string,float>>") == (
        "array",
        ["map<string,float>"],
    )
    assert collection_value_type("array<int>") == "int"
    assert collection_value_type("matrix<float>") == "float"
    assert collection_value_type("map<string,array<int>>") == "array<int>"
    assert collection_value_type("map<string,array<int>>", key=True) == "string"
    assert collection_value_type("float") is None


def test_reference_and_map_key_rules_cover_builtin_enum_and_user_types() -> None:
    assert is_reference_type("series array<float>")
    assert is_reference_type("line")
    assert not is_reference_type("float")
    assert is_reference_type_name("Point", enum_types={"Direction"})
    assert not is_reference_type_name("Direction", enum_types={"Direction"})
    assert not is_reference_type_name("unknown", enum_types={"Direction"})

    for value in ("unknown", "any", "int", "float", "bool", "string", "display"):
        assert is_valid_map_key_type(value)
    assert is_valid_map_key_type("Direction", enum_types={"Direction"})
    assert not is_valid_map_key_type("Point", enum_types={"Direction"})
    assert not is_valid_map_key_type("array<int>")


@pytest.mark.parametrize(
    ("expected", "actual", "allowed"),
    [
        ("float", "int", True),
        ("int", "float", False),
        ("any", "Point", True),
        ("Point", "unknown", True),
        ("Point", "na", True),
        ("int|float", "int", True),
        ("int|float", "string", False),
        ("float", "int|float", True),
        ("int", "int|float", False),
        ("array<float>", "tuple<int,float>", True),
        ("array<any>", "tuple<int,string>", True),
        ("array<float>", "map<string,float>", False),
        ("array<float>", "array<int>", False),
        ("map<string,float>", "map<string,int>", False),
        ("map<string,float>", "map<string>", False),
        ("int", "display", True),
        ("strategy_direction", "strategy.long", True),
        ("bool", "string", False),
    ],
)
def test_assignability_matrix(expected: str, actual: str, allowed: bool) -> None:
    assert is_assignable_type(expected, actual) is allowed
    assert type_is_assignable(PineType.parse(expected), PineType.parse(actual)) is allowed


def test_type_merging_covers_unknown_identical_numeric_and_incompatible_values() -> None:
    assert merge_type_names([]) == "unknown"
    assert merge_type_names(["unknown", "na"]) == "unknown"
    assert merge_type_names(["int", "int", "unknown"]) == "int"
    assert merge_type_names(["int", "float", "na"]) == "float"
    assert merge_type_names(["string", "bool"]) == "unknown"


@dataclass
class _SerializableAst:
    kind: str = "Program"
    children: tuple[Any, ...] = ()


class _NotSerializable:
    __slots__ = ()


def test_introspection_ast_diagnostics_and_result_status_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = introspection.parse_source(
        '//@version=6\nindicator("x")\nx=close\n', source_name="x.pine"
    )
    payload = introspection.ast_payload(parsed)
    assert payload["kind"] == "Program"
    assert introspection.result_ok(parsed)
    assert introspection.diagnostics_payload(parsed) == []

    with pytest.raises(FrontendIntrospectionError, match="no AST"):
        introspection.ast_payload(SimpleNamespace(ast=None))

    monkeypatch.setattr(introspection, "to_plain", lambda value: "not-a-dict")
    with pytest.raises(FrontendIntrospectionError, match="not serializable"):
        introspection.ast_payload(SimpleNamespace(ast=_SerializableAst()))

    monkeypatch.undo()
    assert introspection.result_ok(SimpleNamespace(ok=True))
    assert not introspection.result_ok(
        SimpleNamespace(diagnostics=[{"severity": "ERROR", "message": "bad"}])
    )
    assert introspection.result_ok(SimpleNamespace(diagnostics=[{"severity": "WARNING"}]))


def test_version_context_discovery_aliases_and_failure_paths() -> None:
    result_context = SimpleNamespace(
        version_context={"effective_version": 5, "pack_hash": "sha256:abc"},
        ast={"kind": "Program"},
    )
    context = introspection.version_context_payload(result_context, {"kind": "Program"})
    assert context["pine_version"] == 5
    assert context["catalog_hash"] == "sha256:abc"
    assert str(context["context_hash"]).startswith("sha256:")
    assert introspection.effective_version(result_context) == 5

    ast_context = introspection.version_context_payload(
        SimpleNamespace(),
        {"kind": "Program", "language_identity": {"version": 4, "profile_hash": "sha256:def"}},
    )
    assert ast_context["pine_version"] == 4
    assert ast_context["catalog_hash"] == "sha256:def"

    artifact_context = introspection.version_context_payload(
        SimpleNamespace(frontend_artifact={"pine_version_context": {"pine_version": 6}}),
        {"kind": "Program"},
    )
    assert artifact_context["pine_version"] == 6

    # Non-object and non-integer candidates are ignored rather than accepted.
    with pytest.raises(FrontendIntrospectionError, match="context is missing"):
        introspection.version_context_payload(
            SimpleNamespace(
                version_context="v6", ast_artifact={"version_context": {"version": "6"}}
            ),
            {"kind": "Program"},
        )


def test_semantic_fact_normalization_and_fallback_paths() -> None:
    normalized = introspection.normalize_semantic_facts(
        {
            "schema_id": "x",
            "payload": {
                "nodes": [
                    {"id": "a", "kind": "Literal", "source_span": {"start": 0}},
                    "skip-me",
                ]
            },
        }
    )
    assert normalized["facts"] == [
        {
            "id": "a",
            "kind": "Literal",
            "source_span": {"start": 0},
            "node_id": "a",
            "node_kind": "Literal",
            "span": {"start": 0},
        }
    ]
    assert "nodes" not in normalized

    direct = introspection.semantic_facts_payload(
        SimpleNamespace(semantic_snapshot={"node_facts": [{"ast_kind": "Identifier"}]})
    )
    assert direct["facts"][0]["node_id"] == "n00000000"
    assert direct["facts"][0]["node_kind"] == "Identifier"

    frontend = introspection.semantic_facts_payload(
        SimpleNamespace(frontend_artifact={"semantic_facts": {"facts": [{"kind": "Literal"}]}})
    )
    assert frontend["facts"][0]["node_kind"] == "Literal"

    ast = {
        "kind": "Program",
        "span": None,
        "annotations": [{"kind": "VERSION"}],
        "children": [{"kind": "Literal", "node_id": "n1", "span": {"start": 1}}],
    }
    model = SimpleNamespace(node_types={1: "float", 2: "int"}, node_qualifiers={1: "series"})
    fallback = introspection.semantic_facts_payload(SimpleNamespace(semantic_model=model), ast)
    assert fallback["schema_id"] == "pine.semantic_facts.fallback.v1"
    assert fallback["canonical"] is False
    assert [fact["node_kind"] for fact in fallback["facts"]] == ["Program", "Literal"]
    assert fallback["facts"][0]["resolved_type"] == "float"
    assert fallback["facts"][0]["resolved_qualifier"] == "series"
    assert fallback["facts"][1]["resolved_type"] == "int"


def test_iter_ast_nodes_artifact_payload_and_version_pack_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = {
        "kind": "Program",
        "metadata": {"kind": "DESCRIPTION"},
        "items": [{"kind": "Literal"}, {"kind": "UNKNOWN"}],
    }
    assert [row["kind"] for row in introspection.iter_ast_nodes(tree)] == ["Program", "Literal"]
    assert introspection.artifact_payload(
        SimpleNamespace(frontend_artifact={"x": 1}), "frontend_artifact"
    ) == {"x": 1}
    assert (
        introspection.artifact_payload(SimpleNamespace(frontend_artifact={}), "frontend_artifact")
        is None
    )

    root = tmp_path / "pine2ast"
    root.mkdir()
    monkeypatch.setattr(introspection, "package_root", lambda: root)
    with pytest.raises(FrontendIntrospectionError, match="found 0"):
        introspection.version_pack(6)

    pack = root / "catalog_data" / "packs" / "pine_v6.pack.json"
    pack.parent.mkdir(parents=True)
    pack.write_text('{"pine_version": 6}', encoding="utf-8")
    assert introspection.version_pack(6) == {"pine_version": 6}

    duplicate = root / "duplicate" / "pine_v6.pack.json"
    duplicate.parent.mkdir()
    duplicate.write_text('{"pine_version": 6}', encoding="utf-8")
    with pytest.raises(FrontendIntrospectionError, match="found 2"):
        introspection.version_pack(6)


def test_parse_source_uses_native_rc6_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import pine2ast

    calls: list[tuple[str, object | None]] = []

    def native_parse(source: str, options: object | None = None) -> object:
        calls.append((source, options))
        return {"source": source}

    monkeypatch.setattr(pine2ast, "parse_code", native_parse)
    assert introspection.parse_source("x", source_name="native", producer_commit="a" * 40) == {
        "source": "x"
    }
    assert len(calls) == 1
    options = calls[0][1]
    assert options is not None
    assert options.source_name == "native"
    assert options.producer_commit == "a" * 40
