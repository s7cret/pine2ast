from __future__ import annotations

from pine2ast.api import ParseOptions, parse_code
from pine2ast.openpine_contract import build_openpine_contract_payload
from pine2ast.semantic.facts import collection_method_parameter_specs


def test_openpine_exports_type_method_callable_and_control_flow_contracts() -> None:
    code = """//@version=6
strategy("Big")
type Pivot
    int x
    float y = 1.0
enum Key
    A
method plus(Pivot this, int n) =>
    this.x + n
Pivot p = Pivot.new(1)
int z = p.plus(2)
array<float> xs = array.new<float>(0, 1.0)
xs.set(0, close)
float first = xs.get(0)
for i = 0 to 3
    strategy.entry("L", strategy.long)
float prev = close[1]
"""
    result = parse_code(code, ParseOptions(source_name="big_intermediate.pine"))
    assert result.ok

    payload = build_openpine_contract_payload(result, source_path="big_intermediate.pine")

    assert payload["types"]["contract"] == "openpine.types.v1"
    assert payload["types"]["udts"][0]["name"] == "Pivot"
    assert payload["types"]["constructors"][0]["type"] == "Pivot"
    assert payload["types"]["constructors"][0]["missing_fields"] == []
    assert payload["types"]["constructors"][0]["arguments"][0]["expected_type"] == "int"
    assert payload["methods"]["contract"] == "openpine.methods.v1"
    assert payload["callables"]["contract"] == "openpine.callables.v1"
    assert payload["callables"]["method_calls"][0]["name"] == "plus"
    assert payload["callables"]["method_calls"][0]["arguments"][0]["expected_type"] == "int"
    assert payload["collections"]["mutations"][0]["operation"] == "set"
    assert payload["collections"]["mutations"][0]["value"]["expected_type"] == "float"
    assert payload["collections"]["accesses"][0]["operation"] == "get"
    assert payload["collections"]["accesses"][0]["result_type"] == "float"
    assert payload["control_flow"]["contract"] == "openpine.control_flow.v1"
    assert payload["control_flow"]["loops"][0]["static_iterations"] == 4
    assert payload["control_flow"]["history_refs"][0]["static_offset"] == 1


def test_builtin_collection_method_facts_specialize_map_enum_key_and_value() -> None:
    code = """//@version=6
indicator("M")
enum Key
    A
var map<Key,float> weights = map.new<Key,float>()
weights.put(Key.A, close)
float x = weights.get(Key.A)
bool ok = weights.contains(Key.A)
array<Key> keys = weights.keys()
"""
    result = parse_code(code, ParseOptions(source_name="method_map_contract.pine"))
    assert result.ok

    payload = build_openpine_contract_payload(result, source_path="method_map_contract.pine")
    method_calls = payload["methods"]["calls"]

    assert [call["name"] for call in method_calls] == ["put", "get", "contains", "keys"]
    assert method_calls[0]["kind"] == "builtin_collection"
    assert method_calls[0]["arguments"][0]["expected_type"] == "Key"
    assert method_calls[0]["arguments"][1]["expected_type"] == "float"
    assert method_calls[1]["return_type"] == "float"
    assert method_calls[2]["return_type"] == "bool"
    assert method_calls[3]["return_type"] == "array<Key>"
    assert payload["collections"]["mutations"][0]["key"]["type_ok"] is True
    assert [access["operation"] for access in payload["collections"]["accesses"]] == [
        "get",
        "contains",
        "keys",
    ]


def test_collection_method_parameter_specs_are_receiver_specialized() -> None:
    assert collection_method_parameter_specs("map<Key,float>", "put") == [
        {"name": "key", "type": "Key", "role": "key", "required": True},
        {"name": "value", "type": "float", "role": "value", "required": True},
    ]
    assert collection_method_parameter_specs("array<line>", "set") == [
        {"name": "index", "type": "int", "role": "index", "required": True},
        {"name": "value", "type": "line", "role": "value", "required": True},
    ]
