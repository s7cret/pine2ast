from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.openpine_contract import build_openpine_contract_payload
from pine2ast.semantic.facts import extract_semantic_facts

BIG_CONTRACT_SOURCE = """//@version=6
indicator("big-step")
type Pivot
    int x
    float y = 1.0
    string tag = "default"
enum Side
    long
    short
method add(array<float> this, float value) =>
    this.push(value)
    this
Pivot p = Pivot.new(1, tag="a")
float yy = p.y
Side s = Side.long
array<float> xs = array.new<float>()
xs.add(close)
xs.set(0, close)
float z = xs.get(0)
map<Side, float> weights = map.new<Side, float>()
weights.put(Side.long, close)
float w = weights.get(Side.long)
"""


def _payload():
    result = parse_code(BIG_CONTRACT_SOURCE, ParseOptions(source_name="big_step.pine"))
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    return result, build_openpine_contract_payload(result, source_path="big_step.pine")


def test_openpine_types_contract_reports_udt_constructor_field_and_enum_facts() -> None:
    _result, payload = _payload()
    types = payload["types"]

    assert types["contract"] == "openpine.types.v1"
    pivot = next(item for item in types["udts"] if item["name"] == "Pivot")
    assert [field["name"] for field in pivot["fields"]] == ["x", "y", "tag"]
    assert pivot["fields"][1]["default_type"] == "float"

    constructor = next(item for item in types["constructors"] if item["type"] == "Pivot")
    assert constructor["missing_fields"] == []
    assert constructor["unknown_fields"] == []
    assert [arg["parameter"] for arg in constructor["arguments"]] == ["x", "tag"]
    assert all(arg["type_ok"] for arg in constructor["arguments"])

    field_access = next(item for item in types["field_accesses"] if item["path"] == "p.y")
    assert field_access["owner_type"] == "Pivot"
    assert field_access["type"] == "float"
    assert field_access["known"] is True

    enum_use = next(
        item for item in types["enum_member_uses"] if item["qualified_name"] == "Side.long"
    )
    assert enum_use["known"] is True
    assert enum_use["qualifier"] == "const"


def test_openpine_methods_contract_reports_user_and_builtin_collection_method_calls() -> None:
    _result, payload = _payload()
    methods = payload["methods"]

    assert methods["contract"] == "openpine.methods.v1"
    declaration = next(item for item in methods["declarations"] if item["name"] == "add")
    assert declaration["receiver"]["type"] == "array<float>"
    assert declaration["parameters"][0]["type"] == "float"

    user_call = next(item for item in methods["calls"] if item["name"] == "add")
    assert user_call["kind"] == "user_defined"
    assert user_call["receiver"]["type"] == "array<float>"
    assert user_call["arguments"][0]["expected_type"] == "float"
    assert user_call["arguments"][0]["type_ok"] is True

    builtin_set = next(item for item in methods["calls"] if item["name"] == "set")
    assert builtin_set["kind"] == "builtin_collection"
    assert builtin_set["function_form"] == "array.set"
    assert [arg["expected_type"] for arg in builtin_set["arguments"]] == ["int", "float"]


def test_openpine_collections_contract_specializes_method_form_mutations_and_accesses() -> None:
    _result, payload = _payload()
    collections = payload["collections"]

    set_mutation = next(item for item in collections["mutations"] if item["operation"] == "set")
    assert set_mutation["function_form"] == "array.set"
    assert [param["type"] for param in set_mutation["method_parameters"]] == ["int", "float"]
    assert [arg["type_ok"] for arg in set_mutation["arguments"]] == [True, True]

    put_mutation = next(item for item in collections["mutations"] if item["operation"] == "put")
    assert put_mutation["function_form"] == "map.put"
    assert put_mutation["key"]["expected_type"] == "Side"
    assert put_mutation["value"]["expected_type"] == "float"
    assert put_mutation["key"]["type_ok"] is True
    assert put_mutation["value"]["type_ok"] is True

    map_access = next(
        item
        for item in collections["accesses"]
        if item["operation"] == "get" and item["target"]["kind"] == "map"
    )
    assert map_access["function_form"] == "map.get"
    assert map_access["result_type"] == "float"
    assert map_access["key"]["expected_type"] == "Side"


def test_semantic_facts_facade_exposes_type_and_method_contracts() -> None:
    result = parse_code(BIG_CONTRACT_SOURCE, ParseOptions(source_name="facts.pine"))
    assert result.ok
    facts = extract_semantic_facts(result.ast, semantic_model=result.semantic_model)

    assert facts["schema_version"] == 1
    assert facts["types"]["contract"] == "openpine.types.v1"
    assert facts["methods"]["contract"] == "openpine.methods.v1"
    assert any(item["name"] == "add" for item in facts["methods"]["declarations"])
