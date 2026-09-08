"""Independent v5/v6 receiver scenarios; original before matrix is archived."""

from pathlib import Path
import json

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import (
    ConsumerBundleError,
    build_consumer_bundle,
    verify_consumer_bundle,
)

SCENARIOS = json.loads(
    (Path(__file__).parent / "data/method_receiver_qualifiers.json").read_text(encoding="utf-8")
)["scenarios"]


@pytest.mark.parametrize("case", SCENARIOS, ids=lambda r: f"v{r['version']}-{r['id']}")
def test_independent_receiver_source_contract(case):
    parsed = parse_code(case["source"])
    if case["expected_status"] != "accept":
        assert not parsed.ok, case["id"]
        assert any(d.is_error for d in parsed.diagnostics)
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(case["source"])
        return
    assert parsed.ok, parsed.diagnostics
    bundle = build_consumer_bundle(case["source"])
    verify_consumer_bundle(bundle)
    verify_consumer_bundle(bundle, source=case["source"])
    old_control = case["id"] == "absent_receiver_control"
    assert bundle["ast"]["schema_version"] == ("2.0" if old_control else "2.1")
    assert (
        "method_receiver_qualifiers_v1" in bundle["consumer_contract"]["required_capabilities"]
    ) is not old_control
    facts = {r["node_id"]: r for r in bundle["semantic_facts"]["facts"]}
    methods = [r for r in bundle["semantic_facts"]["calls"] if r["call_form"] == "USER_METHOD"]
    assert methods
    assert all(
        facts[c["node_id"]]["resolved_type"]["qualifier"] == case["expected_result_qualifier"]
        for c in methods
    )
    if case["id"] == "named_order_keeps_indices":
        assert [r["parameter_index"] for r in methods[0]["arguments"]] == [1, 0]
    elif case["id"] == "positional_order_keeps_indices":
        assert [r["parameter_index"] for r in methods[0]["arguments"]] == [0, 1]
    elif case["id"] == "default_parameter_index_zero":
        assert methods[0]["arguments"] == []
        assert methods[0]["defaults_applied"][0]["parameter_index"] == 0
        declaration = next(n for n in bundle["ast"]["items"] if n["kind"] == "MethodDeclaration")
        assert declaration["parameters"][0]["default_value"]["value"] == 3


@pytest.mark.parametrize("version", [5, 6])
def test_explicit_simple_string_parameter_preserves_simple_result(version):
    source = f"""//@version={version}
indicator("Explicit simple argument")
method plus(simple int self,simple string step)=>self+str.length(step)
a=2
plot(a.plus("abcd"))
"""
    bundle = build_consumer_bundle(source)
    verify_consumer_bundle(bundle)
    call = next(c for c in bundle["semantic_facts"]["calls"] if c["call_form"] == "USER_METHOD")
    fact = next(f for f in bundle["semantic_facts"]["facts"] if f["node_id"] == call["node_id"])
    assert fact["resolved_type"] == {"base": "int", "qualifier": "simple", "nullable": False}
    assert call["arguments"][0]["max_qualifier"] == "simple"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("regular", [False, True])
def test_custom_nz_method_uses_selected_user_identity(version, regular):
    parameter = ",simple bool other" if regular else ""
    result = "other" if regular else "self"
    argument = "false" if regular else ""
    source = f"""//@version={version}
indicator("User method identity")
method nz(simple bool self{parameter})=>{result}
a=true
plot(a.nz({argument})?1:0)
"""
    bundle = build_consumer_bundle(source)
    verify_consumer_bundle(bundle)
    call = next(c for c in bundle["semantic_facts"]["calls"] if c["call_form"] == "USER_METHOD")
    assert call["symbol_id"].startswith("user:method:nz:")
    assert call["return_type"] == "bool"


@pytest.mark.parametrize("name", ["na", "nz", "fixnan"])
def test_real_v6_builtin_bool_prohibition_remains(name):
    source = f'//@version=6\nindicator("Builtin identity")\nx={name}(true)\n'
    parsed = parse_code(source)
    assert not parsed.ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("annotation", ["simple", "series"])
@pytest.mark.parametrize(
    "dtype,prelude,constructor",
    [
        ("array<int>", "", "array.new<int>(1,2)"),
        ("matrix<float>", "", "matrix.new<float>(1,1,2.5)"),
        ("map<string,float>", "", "map.new<string,float>()"),
        ("P", "type P\n    int n=1\n", "P.new()"),
    ],
)
def test_v6_reference_receiver_annotation_is_provenance_not_a_simple_reference(
    annotation, dtype, prelude, constructor
):
    text = f'//@version=6\nindicator("Reference annotation")\n{prelude}method identity({annotation} {dtype} self)=>self\np={constructor}\nq=p.identity()\n'
    bundle = build_consumer_bundle(text)
    verify_consumer_bundle(bundle)
    declaration = next(n for n in bundle["ast"]["items"] if n["kind"] == "MethodDeclaration")
    assert declaration["receiver_explicit_qualifier"] == annotation
    call = next(c for c in bundle["semantic_facts"]["calls"] if c["call_form"] == "USER_METHOD")
    fact = next(f for f in bundle["semantic_facts"]["facts"] if f["node_id"] == call["node_id"])
    assert call["return_type"] == dtype
    assert fact["resolved_type"]["qualifier"] == "series"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("series", [False, True])
def test_enum_value_receiver_keeps_simple_constraint(version, series):
    initializer = "bar_index>0 ? E.a : E.b" if series else "E.a"
    text = f'//@version={version}\nindicator("Enum qualifier")\nenum E\n    a\n    b\nmethod identity(simple E self)=>self\np={initializer}\nq=p.identity()\n'
    if series:
        assert not parse_code(text).ok
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(text)
    else:
        bundle = build_consumer_bundle(text)
        verify_consumer_bundle(bundle)
        call = next(c for c in bundle["semantic_facts"]["calls"] if c["call_form"] == "USER_METHOD")
        fact = next(f for f in bundle["semantic_facts"]["facts"] if f["node_id"] == call["node_id"])
        assert fact["resolved_type"]["base"] == "E"
        assert fact["resolved_type"]["qualifier"] == "simple"


def test_v6_reference_annotations_do_not_manufacture_distinct_overloads():
    text = '//@version=6\nindicator("Reference duplicate")\nmethod identity(simple array<int> self)=>self\nmethod identity(series array<int> self)=>self\na=array.new<int>(1,2)\nb=a.identity()\n'
    assert not parse_code(text).ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(text)
