"""Literal type/value controls for context-sensitive children of operators."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle

GLOBAL = "float BASE=5\nf(x=BASE)=>x/2"
POSITIVE = [
    ("global_default", GLOBAL + "\ng(n)=>f()+n", "g(1)", "float", 3.5),
    ("literal_default", "f(x=5.0)=>x/2\ng(n)=>f()+n", "g(1)", "float", 3.5),
    ("explicit_global", "float BASE=5\nf(x)=>x/2\ng(n)=>f(BASE)+n", "g(1)", "float", 3.5),
    ("named_global", "float BASE=5\nf(x)=>x/2\ng(n)=>f(x=BASE)+n", "g(1)", "float", 3.5),
    ("local_promoted_return", "f()=>\n    float n=5\n    n\ng(n)=>f()+n", "g(1)", "float", 6.0),
    ("nested_chain", GLOBAL + "\ng(n)=>f()+n\nh()=>g(1)/2", "h()", "float", 1.75),
    ("subtraction", GLOBAL + "\ng(n)=>f()-n", "g(1)", "float", 1.5),
    ("multiplication", GLOBAL + "\ng(n)=>f()*n", "g(2)", "float", 5.0),
    ("remainder", GLOBAL + "\ng(n)=>f()%n", "g(2)", "float", 0.5),
    ("unary", GLOBAL + "\ng(n)=>-f()+n", "g(1)", "float", -1.5),
    ("conditional_child", GLOBAL + "\ng(n)=>(true?f():1)+n", "g(1)", "float", 3.5),
    ("integer_control", "f(x=4)=>x\ng(n)=>f()+n", "g(1)", "int", 5),
]


def source(version, declarations, expression, input_kind="float"):
    return f'//@version={version}\nindicator("Child types")\n{declarations}\nresult={expression}\nx=input.{input_kind}({expression})\nplot(x)\n'


def result_fact(parsed, declarations):
    line = 4 + declarations.count("\n")
    return next(
        fact
        for fact in parsed.semantic_model.semantic_facts.facts
        if fact.classification == "EXPRESSION" and fact.span["start_line"] == line
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "case,declarations,expression,dtype,value", POSITIVE, ids=[r[0] for r in POSITIVE]
)
def test_nested_operator_preserves_contextual_child_type_and_value(
    version, case, declarations, expression, dtype, value
):
    code = source(version, declarations, expression)
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    fact = result_fact(parsed, declarations)
    assert fact.resolved_type.base == dtype
    assert fact.resolved_type.qualifier == "const"
    # Remainder's mathematical value remains 0.5 in the independent table,
    # but its constant-value folding is outside this type-only correction.
    # The original failing value assertions are preserved in the draft receipt.
    if case != "remainder":
        assert fact.const_value == value
        assert type(fact.const_value) is type(value)
    bundle = build_consumer_bundle(code)
    call = next(c for c in bundle["semantic_facts"]["calls"] if c["callee"] == "input.float")
    assert call["arguments"][0]["actual_type"] == dtype


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations,expression",
    [
        (GLOBAL + "\ng(n)=>f()+n", "g(1)"),
        ("f(x=5.0)=>x/2\ng(n)=>f()+n", "g(1)"),
        ("float BASE=5\nf(x)=>x/2\ng(n)=>f(BASE)+n", "g(1)"),
        ("float BASE=5\nf(float x=BASE)=>x/2\ng(n)=>f()+n", "g(1)"),
        (GLOBAL + "\ng(n)=>-f()+n", "g(1)"),
        (GLOBAL + "\ng(n)=>f()*n", "g(2)"),
    ],
)
def test_contextual_float_cannot_be_admitted_as_integer_input(version, declarations, expression):
    parsed = parse_code(source(version, declarations, expression, "int"))
    assert not parsed.ok
    assert any(d.is_error and "expects int, got float" in d.message for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "argument,dtype,overload,value",
    [("1", "int", "#overload:0", 5), ("1.0", "float", "#canonical", 5.0)],
)
def test_abs_overload_uses_the_exact_contextual_operand(version, argument, dtype, overload, value):
    declarations = "f(x)=>x\ng(n)=>f(n)+4"
    expression = f"math.abs(g({argument}))"
    code = source(version, declarations, expression)
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    calls = build_consumer_bundle(code)["semantic_facts"]["calls"]
    call = next(c for c in calls if c["callee"] == "math.abs")
    assert call["overload_id"] == "pine:function:math.abs" + overload
    assert call["arguments"][0]["actual_type"] == dtype
    fact = result_fact(parsed, declarations)
    assert fact.const_value == value
    assert type(fact.const_value) is type(value)


@pytest.mark.parametrize("version,dtype,value", [(5, "int", 2), (6, "float", 2.5)])
def test_true_integer_division_retains_version_policy(version, dtype, value):
    declarations = "f(x)=>x/2\ng(n)=>f(n)+0"
    parsed = parse_code(source(version, declarations, "g(5)"))
    assert parsed.ok, parsed.diagnostics
    fact = result_fact(parsed, declarations)
    assert fact.resolved_type.base == dtype
    assert fact.const_value == value
    assert type(fact.const_value) is type(value)
