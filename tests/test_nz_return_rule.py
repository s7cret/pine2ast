"""Numeric nz facts preserve integer counters; this does not admit a runtime builtin."""

import pytest
from pine2ast import parse_code
from pine2ast.hardening.introspection import parse_source, semantic_facts_payload, ast_payload


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize(
    "expression,dtype",
    [
        ("nz(1)", "int"),
        ("nz(1,0)", "int"),
        ("nz(source=1,replacement=0)", "int"),
        ("nz(replacement=0,source=1)", "int"),
        ("nz(1,0.0)", "float"),
        ("nz(1.0,0)", "float"),
    ],
)
def test_catalog_numeric_return_facts(version, expression, dtype):
    header = "indicator" if version >= 5 else "study"
    source = f'//@version={version}\n{header}("nz")\nx={expression}\n'
    p = parse_source(source, source_name="nz.pine")
    rows = semantic_facts_payload(p, ast_payload(p))["facts"]
    call = next(
        r for r in rows if r.get("kind") == "CallExpr" and r.get("symbol_id") == "pine:function:nz"
    )
    assert call["resolved_type"]["base"] == dtype


def test_integer_map_counter_no_longer_fails_type_check():
    parsed = parse_code(
        '//@version=6\nindicator("nz")\nm=map.new<string,int>()\nmap.put(m,"n",nz(map.get(m,"n"),0)+1)\n'
    )
    assert parsed.ok, parsed.diagnostics


def test_v6_bool_still_rejected():
    assert not parse_code('//@version=6\nindicator("bad")\nx=nz(false)\n').ok
