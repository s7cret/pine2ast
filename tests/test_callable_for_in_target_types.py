"""Loop target roles follow the existing collection element type owner."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("dtype,literal", [("int", "2"), ("float", "2.5"), ("string", '"text"')])
@pytest.mark.parametrize("indexed", [False, True])
def test_scalar_and_indexed_array_elements_keep_exact_types(version, dtype, literal, indexed):
    target = "[index,value]" if indexed else "value"
    returned = "[index,value]" if indexed else "value"
    declaration = "[a,b]=f()" if indexed else "b=f()"
    source = f"""//@version={version}
indicator("For-in target types")
f()=>
    values=array.new<{dtype}>(1,{literal})
    for {target} in values
        {returned}
{declaration}
"""
    parsed = parse_code(source)
    assert parsed.ok, parsed.diagnostics
    facts = parsed.semantic_model.semantic_facts.artifact
    call = next(
        c for c in facts["calls"] if c["call_form"] == "USER_FUNCTION" and c["callee"] == "f"
    )
    assert call["return_type"] == (f"tuple<int,{dtype}>" if indexed else dtype)
    assert facts["coverage"]["ok"]
    assert build_consumer_bundle(source)["semantic_facts"]["coverage"]["ok"]


@pytest.mark.parametrize("version", [5, 6])
def test_for_in_value_shadow_does_not_replace_outer_symbol_type(version):
    source = f"""//@version={version}
indicator("For-in scope")
value="outer"
index="also outer"
f()=>
    values=array.new<float>(1,2.5)
    for [index,value] in values
        [index,value]
[a,b]=f()
"""
    parsed = parse_code(source)
    assert parsed.ok, parsed.diagnostics
    assert parsed.semantic_model.symbols["value"].type == "string"
    assert parsed.semantic_model.symbols["index"].type == "string"
    bundle = build_consumer_bundle(source)
    call = next(c for c in bundle["semantic_facts"]["calls"] if c["callee"] == "f")
    assert call["return_type"] == "tuple<int,float>"
