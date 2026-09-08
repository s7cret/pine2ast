"""Exact v5/v6 string source names, required arity, and declared types."""

import pytest
from pine2ast import parse_code
from pine2ast.hardening.introspection import semantic_facts_payload

CASES = [
    ("str.upper()", False),
    ("str.lower()", False),
    ("str.upper(7)", False),
    ("str.lower(7)", False),
    ('str.upper(source="Ab")', True),
    ('str.lower(source="Ab")', True),
    ('str.tonumber(string="2.5")', True),
    ('str.tonumber(source="2.5")', False),
    ("str.tonumber()", False),
    ("str.tonumber(7)", False),
    ('str.upper("Ab")', True),
    ('str.lower("Ab")', True),
    ('str.tonumber("2.5")', True),
    ("str.upper(source=7)", False),
    ("str.lower(source=7)", False),
    ("str.tonumber(string=7)", False),
    ('str.upper("Ab", source="Cd")', False),
    ('str.lower("Ab", source="Cd")', False),
    ('str.tonumber("2.5", string="3")', False),
]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("expression,accepted", CASES)
def test_primary_string_source_contract(version, expression, accepted):
    parsed = parse_code(f'//@version={version}\nindicator("strings")\nresult={expression}\n')
    assert parsed.ok is accepted, [(d.code, d.message) for d in parsed.diagnostics]
    if accepted:
        name = expression.split("(")[0]
        call = next(
            c
            for c in semantic_facts_payload(parsed)["calls"]
            if c["symbol_id"] == "pine:function:" + name
        )
        assert call["return_type"] == ("float" if name == "str.tonumber" else "string")
        assert [a["parameter_name"] for a in call["arguments"]] == [
            "string" if name == "str.tonumber" else "source"
        ]
