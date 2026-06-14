from __future__ import annotations

from pathlib import Path

from pine2ast.api import ParseOptions, parse_code
from pine2ast.inspect_contract import build_inspect_payload
from pine2ast.openpine_contract import build_openpine_contract_payload
from pine2ast.compatibility.release_features import (
    load_v6_release_features,
    release_feature_summary,
)


def test_request_contract_marks_v6_local_request_as_dynamic_runtime_dependency() -> None:
    code = """//@version=6
indicator("R")
for i = 0 to 1
    req = request.security("NASDAQ:AAPL", "D", close)
plot(close)
"""
    result = parse_code(code, ParseOptions(source_name="request_v6.pine"))
    assert result.ok

    payload = build_openpine_contract_payload(result, source_path="request_v6.pine")
    request = payload["requests"]["requests"][0]

    assert payload["requests"]["profile"] == "pine_v6"
    assert request["kind"] == "request.security"
    assert request["local_scope"] is True
    assert request["dynamic"]["enabled"] is True
    assert request["dynamic"]["requires_dynamic"] is True
    assert request["dynamic"]["static_ok"] is True
    assert request["symbol"]["value"] == "NASDAQ:AAPL"
    assert request["timeframe"]["value"] == "D"


def test_request_contract_marks_v5_dynamic_false_local_request_as_runtime_blocker() -> None:
    code = """//@version=5
indicator("R", dynamic_requests=false)
if close > open
    req = request.security("NASDAQ:AAPL", "D", close)
plot(close)
"""
    result = parse_code(code, ParseOptions(version=5, source_name="request_v5.pine"))
    assert not result.ok

    payload = build_openpine_contract_payload(result, source_path="request_v5.pine")
    request = payload["requests"]["requests"][0]

    assert payload["requests"]["profile"] == "pine_v5"
    assert payload["requests"]["dynamic_requests"] == {
        "default": False,
        "explicit": False,
        "enabled": False,
    }
    assert request["dynamic"]["requires_dynamic"] is True
    assert request["dynamic"]["static_ok"] is False
    assert request["dynamic"]["disabled_reasons"] == ["local_scope"]


def test_strategy_contract_buckets_orders_and_exits() -> None:
    code = """//@version=6
strategy("S")
if close > open
    strategy.entry("L", strategy.long)
strategy.exit("XL", from_entry="L", stop=low)
"""
    result = parse_code(code, ParseOptions(source_name="strategy_v6.pine"))
    assert result.ok

    strategy = build_openpine_contract_payload(result, source_path="strategy_v6.pine")["strategy"]

    assert strategy["script"] == {"type": "strategy", "title": "S", "pine_version": 6}
    assert [order["kind"] for order in strategy["orders"]] == ["strategy.entry"]
    assert strategy["orders"][0]["id"]["value"] == "L"
    assert strategy["orders"][0]["direction"]["value"] == "strategy.long"
    assert [exit_call["kind"] for exit_call in strategy["exits"]] == ["strategy.exit"]
    assert strategy["exits"][0]["from_entry"]["value"] == "L"
    assert strategy["exits"][0]["direction"] is None


def test_inspect_contract_can_optionally_embed_openpine_contract(tmp_path: Path) -> None:
    code = '//@version=6\nindicator("I")\nplot(close)\n'
    result = parse_code(code, ParseOptions(source_name="embed.pine"))
    base = build_inspect_payload(result, source_path="embed.pine")
    embedded = build_inspect_payload(
        result,
        source_path="embed.pine",
        include_openpine_contract=True,
    )

    assert "openpine_contract" not in base
    assert embedded["openpine_contract"]["contract"] == "openpine.frontend.v1"


def test_release_feature_matrix_has_no_unknown_statuses() -> None:
    payload = load_v6_release_features()
    allowed = set(payload["status_values"])
    statuses = {feature["status"] for feature in payload["features"]}

    assert statuses <= allowed
    assert release_feature_summary(payload)["runtime_contract"] >= 3
    assert any(feature["id"] == "v6.request_footprint" for feature in payload["features"])


def test_collection_contract_tracks_method_mutations_and_limits() -> None:
    code = """//@version=6
indicator("C")
array<float> xs = array.new<float>()
map<string, float> weights = map.new<string, float>()
xs.push(close)
weights.put("a", close)
"""
    result = parse_code(code, ParseOptions(source_name="collections_v6.pine"))
    assert result.ok

    collections = build_openpine_contract_payload(
        result,
        source_path="collections_v6.pine",
    )["collections"]

    assert collections["contract"] == "openpine.collections.v1"
    assert collections["limits"]["array_max_elements"] == 100_000
    assert {decl["name"] for decl in collections["declarations"]} == {"xs", "weights"}
    assert {ctor["kind"] for ctor in collections["constructors"]} == {"array.new", "map.new"}
    assert any(
        ctor["map_key_valid"] is True
        for ctor in collections["constructors"]
        if ctor["kind"] == "map.new"
    )
    assert [mutation["operation"] for mutation in collections["mutations"]] == [
        "push",
        "put",
    ]
    assert collections["mutations"][1]["target"]["key_type"] == "string"
    assert collections["mutations"][1]["value"]["type"] == "float"


def test_collection_contract_tracks_constructors_declarations_and_mutations() -> None:
    code = """//@version=6
indicator("C")
array<float> xs = array.new<float>()
map<string, float> weights = map.new<string, float>()
xs.push(close)
weights.put("a", close)
"""
    result = parse_code(code, ParseOptions(source_name="collections_v6.pine"))
    assert result.ok

    collections = build_openpine_contract_payload(result, source_path="collections_v6.pine")[
        "collections"
    ]

    assert collections["contract"] == "openpine.collections.v1"
    assert collections["limits"]["map_pairs"] == 50_000
    assert [decl["name"] for decl in collections["declarations"]] == ["xs", "weights"]
    assert {ctor["collection_kind"] for ctor in collections["constructors"]} == {"array", "map"}
    assert {mutation["operation"] for mutation in collections["mutations"]} == {"push", "put"}
    map_decl = next(decl for decl in collections["declarations"] if decl["name"] == "weights")
    assert map_decl["key_type"] == "string"
    assert map_decl["map_key_valid"] is True


def test_collection_contract_exports_constructors_mutations_and_limits() -> None:
    code = '//@version=6\nindicator("C")\nvar array<float> values = array.new<float>(0, 1.0)\narray.push(values, close)\nvar map<string, float> weights = map.new<string, float>()\nmap.put(weights, "AAPL", close)\n'
    result = parse_code(code, ParseOptions(source_name="collections.pine"))
    assert result.ok

    collections = build_openpine_contract_payload(result, source_path="collections.pine")[
        "collections"
    ]

    assert collections["limits"]["array_elements"] == 100_000
    assert collections["limits"]["map_pairs"] == 50_000
    assert [item["kind"] for item in collections["constructors"]] == ["array.new", "map.new"]
    assert collections["constructors"][0]["assigned_to"][0]["name"] == "values"
    assert [item["operation"] for item in collections["mutations"]] == ["push", "put"]
    assert collections["mutations"][1]["target"]["kind"] == "map"


def test_map_reference_key_type_is_a_static_error_but_enum_key_is_allowed() -> None:
    bad = parse_code(
        '//@version=6\nindicator("bad")\nvar map<label, float> labels = map.new<label, float>()\n',
        ParseOptions(source_name="bad_map.pine"),
    )
    assert any(d.code == "P2A1805" for d in bad.diagnostics)

    good = parse_code(
        '//@version=6\nindicator("good")\nenum Key\n    A\nvar map<Key, float> labels = map.new<Key, float>()\n',
        ParseOptions(source_name="good_map.pine"),
    )
    assert good.ok
    payload = build_openpine_contract_payload(good, source_path="good_map.pine")
    map_decl = payload["collections"]["declarations"][0]
    assert map_decl["key_type"] == "Key"
    assert map_decl["map_key_valid"] is True
