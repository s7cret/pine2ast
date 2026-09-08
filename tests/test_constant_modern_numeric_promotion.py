"""Literal expected values at modern non-UDF numeric promotion boundaries."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("true?5:0.5", 5.0),
        ("false?0.5:5", 5.0),
        ("(true?5:0.5)/2", 2.5),
        ("(false?0.5:5)/2", 2.5),
        ("-(true?5:0.5)/2", -2.5),
        ("((true?5:0.5)+1)/2", 3.0),
        ("math.abs(true?5:0.5)/2", 2.5),
        ("math.round(number=(true?5:0.5)/2)", 3),
        ("math.round(precision=1,number=(true?5:0.5)/2)", 2.5),
        ("math.min(true?5:0.5,6)/2", 2.5),
    ],
)
def test_top_level_and_builtin_arguments_use_admitted_numeric_types(version, expression, expected):
    code = f'//@version={version}\nindicator("Promotion")\nx={expression}\nplot(x)\n'
    parsed = parse_code(code)
    assert parsed.ok
    fact = next(
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.classification == "EXPRESSION" and f.span["start_line"] == 3
    )
    assert fact.const_value == expected and type(fact.const_value) is type(expected)
    build_consumer_bundle(code)


@pytest.mark.parametrize("version,expected", [(5, 2), (6, 2.5)])
@pytest.mark.parametrize(
    "expression", ["5/2", "(true?5:1)/2", "int(true?5:0.5)/2", "math.min(5,6)/2"]
)
def test_true_integer_expressions_preserve_the_version_division_rule(version, expected, expression):
    # A float declaration does not retrospectively change the initializer's
    # integer arithmetic; conversion happens at the assignment boundary.
    parsed = parse_code(
        f'//@version={version}\nindicator("Int control")\nfloat x={expression}\nplot(x)\n'
    )
    assert parsed.ok
    fact = next(
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.classification == "EXPRESSION" and f.span["start_line"] == 3
    )
    assert fact.const_value == expected and type(fact.const_value) is type(expected)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "expression,expected", [("(true?5:0.5)/2", 2.5), ("math.round((true?5:0.5)/2)", 3)]
)
def test_input_default_binding_retains_the_promoted_value(version, expression, expected):
    code = (
        f'//@version={version}\nindicator("Default")\nx=input.float(defval={expression})\nplot(x)\n'
    )
    bundle = build_consumer_bundle(code)
    call = next(c for c in bundle["semantic_facts"]["calls"] if c["callee"] == "input.float")
    parameter = call["arguments"][0]
    assert parameter["parameter_name"] == "defval" and parameter["actual_qualifier"] == "const"
    argument_id = parameter["argument_node_id"]
    # The first descendant expression starts at the parameter value, after the
    # named wrapper; AST provenance identifies it without evaluating an oracle.
    argument = next(f for f in bundle["semantic_facts"]["facts"] if f["node_id"] == argument_id)
    values = [
        f
        for f in bundle["semantic_facts"]["facts"]
        if f["classification"] == "EXPRESSION"
        and f["span"]["start_offset"] >= argument["span"]["start_offset"]
        and f["span"]["end_offset"] <= argument["span"]["end_offset"]
    ]
    assert values and values[0]["const_value"] == expected


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_legacy_expression_facts_are_not_silently_reinterpreted(version):
    declaration = 'study("Legacy")'
    parsed = parse_code(f"//@version={version}\n{declaration}\nx=true?5:0.5\nplot(x)\n")
    assert parsed.ok
    fact = next(
        f for f in parsed.semantic_model.semantic_facts.facts if f.kind == "ConditionalExpr"
    )
    assert fact.const_value == 5 and type(fact.const_value) is int
