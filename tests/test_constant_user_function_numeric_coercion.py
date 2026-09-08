"""Independent admitted-type promotions at constant UDF expression boundaries."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle


def source(version, declaration):
    return f'//@version={version}\nindicator("Coercion")\n{declaration}\nx=value()\nplot(x)\n'


def fact(parsed):
    return next(
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.kind == "CallExpr" and f.call_form == "USER_FUNCTION" and f.scope_id == "scope:global"
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declaration,expected",
    [
        ("value()=>\n    float n=5\n    n/2", 2.5),
        ("value()=>\n    float n=-5\n    n/2", -2.5),
        ("value()=>(true?5:0.5)/2", 2.5),
        ("value()=>(false?0.5:5)/2", 2.5),
        ("value()=>\n    float n=5\n    n", 5.0),
        ("value()=>true?5:0.5", 5.0),
        ("value()=>\n    float n=5\n    float m=n\n    m/2", 2.5),
        ("inner()=>\n    float n=5\n    n\nvalue()=>inner()/2", 2.5),
        ("value()=>math.abs(true?5:0.5)/2", 2.5),
        ("value()=>-(true?5:0.5)/2", -2.5),
        ("value()=>(false?0.5:(true?5:2.5))/2", 2.5),
        ("value()=>((true?5:0.5)+1)/2", 3.0),
        ("value()=>float(5)/2", 2.5),
        ("value()=>math.round(2.5,0)/2", 1.5),
    ],
)
def test_admitted_float_boundaries_promote_before_parent_operations(version, declaration, expected):
    code = source(version, declaration)
    parsed = parse_code(code)
    assert parsed.ok, [d.to_dict() for d in parsed.diagnostics]
    value = fact(parsed)
    assert value.resolved_type.base == "float" and value.resolved_type.qualifier == "const"
    assert value.const_value == expected and type(value.const_value) is float
    build_consumer_bundle(code)


@pytest.mark.parametrize("version,expected", [(5, 2), (6, 2.5)])
@pytest.mark.parametrize(
    "declaration",
    [
        "value()=>5/2",
        "value()=>\n    float n=5\n    int(n)/2",
        "value()=>(true?5:1)/2",
        "value(float unused=0.5)=>5/2",
    ],
)
def test_float_coercion_does_not_erase_explicit_int_or_version_rules(
    version, expected, declaration
):
    parsed = parse_code(source(version, declaration))
    assert parsed.ok
    actual = fact(parsed).const_value
    assert actual == expected and type(actual) is type(expected)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declaration",
    [
        "value(float n=5)=>n/2",
        "value(simple float n=5)=>n/2",
        "value()=>(true?5.0:na)/2",
    ],
)
def test_promotion_does_not_authorize_nonconst_or_missing_values(version, declaration):
    parsed = parse_code(source(version, declaration))
    assert parsed.ok
    assert fact(parsed).const_value is None
