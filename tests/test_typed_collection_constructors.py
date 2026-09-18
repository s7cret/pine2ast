"""Generic constructor identity and matrix row facts belong to the active catalog."""

import pytest
from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.hardening.introspection import parse_source, semantic_facts_payload, ast_payload


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "dtype,expression",
    [
        ("array<int>", "array.new<int>(1,0)"),
        ("array<float>", "array.new<float>()"),
        ("map<string,int>", "map.new<string,int>()"),
        ("matrix<int>", "matrix.new<int>(2,2,0)"),
    ],
)
def test_generic_call_and_base_have_exact_template_facts(version, dtype, expression):
    source = f'//@version={version}\nindicator("typed")\nx={expression}\n'
    parsed = parse_source(source, source_name="typed.pine")
    facts = semantic_facts_payload(parsed, ast_payload(parsed))
    # The strict consumer gate must accept the full expression tree, not only its result.
    bundle = build_consumer_bundle(source)
    assert bundle
    nodes = facts["facts"]
    calls = [
        n
        for n in nodes
        if n.get("kind") == "CallExpr"
        and (n.get("symbol_id") or "").startswith("pine:function:" + dtype.split("<")[0] + ".new")
    ]
    assert len(calls) == 1
    assert calls[0]["resolved_type"]["base"] == dtype
    assert "u003ctype" in calls[0]["symbol_id"]
    for n in nodes:
        if n.get("kind") == "MemberAccessExpr" and (n.get("symbol_id") or "").endswith("u003e"):
            assert n["resolved_type"]["base"] == "function"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("target", ["row", "[i,row]"])
def test_matrix_for_in_target_is_an_array_not_an_element(version, target):
    source = f'//@version={version}\nindicator("rows")\nm=matrix.new<int>(2,2,3)\ns=0\nfor {target} in m\n    s:=s+array.get(row,0)\nplot(s)\n'
    assert parse_code(source).ok
    assert build_consumer_bundle(source)


@pytest.mark.parametrize("version", [5, 6])
def test_map_requires_two_targets(version):
    parsed = parse_code(
        f'//@version={version}\nindicator("pairs")\nm=map.new<string,int>()\nfor k in m\n    x=k\n'
    )
    assert not parsed.ok
    assert any("key, value" in d.message for d in parsed.diagnostics)


@pytest.mark.parametrize(
    "expression", ["map.new<array<int>,int>()", "matrix.new<missing>(1,1)", "array.unknown<int>()"]
)
def test_invalid_generic_type_or_unknown_constructor_is_not_promoted(expression):
    source = f'//@version=6\nindicator("invalid")\nx={expression}\n'
    result = parse_code(source)
    assert not result.ok or any(d.severity.value == "ERROR" for d in result.diagnostics)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("namespace", ["map", "matrix"])
def test_generic_namespace_not_available_in_old_version(version, namespace):
    typ = "string,int" if namespace == "map" else "int"
    result = parse_code(f'//@version={version}\nstudy("old")\nx={namespace}.new<{typ}>()\n')
    assert not result.ok

@pytest.mark.parametrize("kind,typename,make,read",[
    ("array","array<int>","array.new<int>(1,2)","array.get(a,0)"),
    ("map","map<string,int>","map.new<string,int>()",'map.get(a,"x")'),
    ("matrix","matrix<int>","matrix.new<int>(1,1,2)","matrix.get(a,0,0)"),
])
@pytest.mark.parametrize("version",[5,6])
def test_later_global_does_not_retype_local_collection(kind,typename,make,read,version):
    del kind,typename
    source=f'//@version={version}\nindicator("scope")\nf()=>\n    var a={make}\n    {read}\na=7\nplot(f())\n'
    assert parse_code(source).ok
    assert build_consumer_bundle(source)
