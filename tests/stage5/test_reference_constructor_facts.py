"""Generic constructors retain complete structural facts from the active catalog."""

import pytest
from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "constructor,result_type",
    [
        ("array.new<float>(1,close)", "array<float>"),
        ("array.new<int>(1,1)", "array<int>"),
        ("matrix.new<float>(1,1,close)", "matrix<float>"),
        ("map.new<string,float>()", "map<string,float>"),
    ],
)
def test_generic_bases_have_complete_consumer_facts(version, constructor, result_type):
    source = f'//@version={version}\nindicator("reference")\na={constructor}\n'
    result = parse_code(source)
    assert result.ok, result.diagnostics
    facts = result.semantic_model.semantic_facts.facts
    assert any(f.kind == "CallExpr" and f.resolved_type.base == result_type for f in facts)
    assert all(
        f.resolved_type.base != "unknown" and f.symbol_id
        for f in facts
        if f.kind == "MemberAccessExpr"
    )
    build_consumer_bundle(source, require_clean_frontend=True)


@pytest.mark.parametrize(
    "body",
    [
        "a=map.missing<string,float>()",
        "a=matrix.missing<float>(1,1)",
        "a=array.new<Unknown>()",
        "a=map.new<string,float>()\nmap.put(a,7,1)",
        'a=matrix.new<float>(1,1,0)\nmatrix.set(a,0,0,"text")',
    ],
)
def test_unknown_templates_and_wrong_element_types_are_rejected(body):
    assert not parse_code('//@version=6\nindicator("negative")\n' + body + "\n").ok


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("compound", [False, True])
def test_global_ids_cannot_be_reassigned_inside_functions(version, compound):
    body = (
        "var int a=0\nf()=>\n    a+=1\nf()"
        if compound
        else "var a=array.new_float(1,0)\nf()=>\n    a:=array.new_float(1,1)\nf()"
    )
    decl = "study" if version == 4 else "indicator"
    result = parse_code(f'//@version={version}\n{decl}("global")\n{body}\n')
    assert not result.ok
    assert any("Cannot reassign global" in d.message for d in result.diagnostics)


def test_mutating_global_array_contents_and_shadowing_remain_allowed():
    src = '//@version=6\nindicator("valid")\nvar a=array.new_float(1,0)\nf()=>\n    array.set(a,0,close)\n    a=array.new_float(1,1)\n    array.get(a,0)\nf()\n'
    assert parse_code(src).ok
