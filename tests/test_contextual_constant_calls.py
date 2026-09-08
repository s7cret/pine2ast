"""Independent per-call qualified types and definition-visible constant values."""

from dataclasses import FrozenInstanceError

import pytest

from pine2ast import parse_code
from pine2ast.ast.nodes import CallExpr, Identifier
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.semantic import callable_context


def source(version, declarations, expression):
    return f'//@version={version}\nindicator("Context")\n{declarations}\nresult={expression}\nplot(result)\n'


def result_fact(parsed, declarations):
    line = 4 + declarations.count("\n")
    return next(
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.classification == "EXPRESSION" and f.span["start_line"] == line
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations,expression,expected",
    [
        ("add(a,b)=>a+b", "add(2,3)", 5),
        ("add(a,b)=>a+b\nvalue()=>add(2,3)*2", "value()", 10),
        ("int BASE=2\nvalue()=>BASE", "value()", 2),
        ("value(x)=>x?2:3", "value(true)", 2),
        ("value(x)=>x?2:3", "value(false)", 3),
        ("A=2\nB=A+3\nvalue()=>B", "value()", 5),
        ("add(a,b)=>a+b\nBASE=add(2,3)\nvalue()=>BASE", "value()", 5),
        ("float BASE=5\nvalue()=>BASE/2", "value()", 2.5),
        ("BASE=2\nvalue(x=BASE)=>x+1", "value()", 3),
        ("value(x=2)=>x+1", "value()", 3),
        ("value(x=math.round(2.5))=>x+1", "value()", 4),
        ("sub(a,b)=>a-b", "sub(b=2,a=5)", 3),
        ("BASE=2\ninner()=>BASE\nvalue()=>\n    BASE=9\n    inner()+BASE", "value()", 11),
        ("BASE=2\nvalue(BASE)=>BASE+1", "value(3)", 4),
        ("half(n)=>n/2", "half(5.0)", 2.5),
        ("value(x)=>\n    float n=x\n    n/2", "value(5)", 2.5),
        ("value(x)=>\n    n=true?x:0.5\n    n/2", "value(5)", 2.5),
        ("inner(x)=>x\nvalue(x)=>inner(x)/2", "value(5.0)", 2.5),
        ("BASE=2\ninner(x=BASE)=>x\nvalue()=>\n    BASE=9\n    inner()", "value()", 2),
        ("inner(x=2)=>x+1\nBASE=inner()\nvalue()=>BASE", "value()", 3),
    ],
)
def test_definition_visible_globals_and_untyped_call_context_supply_const_evidence(
    version, declarations, expression, expected
):
    code = source(version, declarations, expression)
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    fact = result_fact(parsed, declarations)
    assert fact.resolved_type.qualifier == "const"
    assert fact.const_value == expected and type(fact.const_value) is type(expected)
    build_consumer_bundle(code)


@pytest.mark.parametrize("version,expected", [(5, 4.5), (6, 5.0)])
def test_two_numeric_call_contexts_do_not_share_aggregate_promotion(version, expected):
    declarations = "half(n)=>n/2"
    parsed = parse_code(source(version, declarations, "half(5)+half(5.0)"))
    assert parsed.ok
    assert result_fact(parsed, declarations).const_value == expected
    calls = [
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.call_form == "USER_FUNCTION" and f.kind == "CallExpr"
    ]
    assert len(calls) == 2
    assert [f.const_value for f in calls] == ([2, 2.5] if version == 5 else [2.5, 2.5])


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("argument,qualifier", [("input.int(2)", "input"), ("bar_index", "series")])
def test_same_body_retains_const_and_nonconst_actual_call_qualifiers(version, argument, qualifier):
    code = f'//@version={version}\nindicator("Separate calls")\nvalue(n)=>n+1\na=value(2)\nb=value({argument})\nplot(b)\n'
    parsed = parse_code(code)
    assert parsed.ok
    calls = [
        f
        for f in parsed.semantic_model.semantic_facts.facts
        if f.kind == "CallExpr" and f.call_form == "USER_FUNCTION" and f.scope_id == "scope:global"
    ]
    assert len(calls) == 2
    assert [(f.resolved_type.qualifier, f.const_value) for f in calls] == [
        ("const", 3),
        (qualifier, None),
    ]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations,expression",
    [
        ("BASE=bar_index\nvalue()=>BASE", "value()"),
        ("BASE=2\nBASE:=3\nvalue()=>BASE", "value()"),
        ("BASE=2\nvalue()=>BASE\nBASE:=3", "value()"),
        ("var int BASE=2\nvalue()=>BASE", "value()"),
        ("value(simple int n)=>n", "value(2)"),
        ("value(series int n)=>n", "value(2)"),
        ("value(n)=>bar_index>0?n:n+1", "value(2)"),
        ("value(n)=>\n    x=n\n    x:=x+1\n    x", "value(2)"),
        ("value(n)=>\n    array.new_int(1)\n    n", "value(2)"),
    ],
)
def test_contextual_value_evidence_never_launders_mutability_or_fixed_bounds(
    version, declarations, expression
):
    parsed = parse_code(source(version, declarations, expression))
    assert parsed.ok, parsed.diagnostics
    assert result_fact(parsed, declarations).const_value is None


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "limit,value",
    [("MAX_ROOT_WORK", 1), ("MAX_BUILDER_WORK", 1), ("MAX_CACHE", 0), ("MAX_DEPTH", 1)],
)
def test_context_inference_exhaustion_fails_closed(monkeypatch, version, limit, value):
    monkeypatch.setattr(callable_context, limit, value)
    parsed = parse_code(source(version, "inner(n)=>n+1\nvalue(n)=>inner(n)", "value(2)"))
    fact = result_fact(parsed, "inner(n)=>n+1\nvalue(n)=>inner(n)")
    assert fact.const_value is None and fact.resolved_type.qualifier == "series"
    owner = parsed.semantic_model.callable_context
    assert owner.spent <= callable_context.MAX_BUILDER_WORK
    assert len(owner.cache) <= callable_context.MAX_CACHE


@pytest.mark.parametrize("version", [5, 6])
def test_context_proofs_are_immutable_and_bind_exact_argument_identity(version):
    parsed = parse_code(source(version, "value(n)=>n+1", "value(2)+value(3.0)"))
    assert parsed.ok
    owner = parsed.semantic_model.callable_context
    calls = [
        n
        for n in owner.index.nodes
        if isinstance(n, CallExpr) and isinstance(n.callee, Identifier) and n.callee.name == "value"
    ]
    proofs = [owner.infer_call(n, owner.engine(parsed.semantic_model.symbols)) for n in calls]
    assert all(p is not None for p in proofs)
    assert proofs[0].context_key != proofs[1].context_key
    for call, proof in zip(calls, proofs):
        assert proof.call_id == owner.index.id_for(call)
        assert proof.arguments[0].argument_id == owner.index.id_for(call.arguments[0])
        with pytest.raises(FrozenInstanceError):
            proof.qualifier = "series"
        with pytest.raises(TypeError):
            proof.node_types[id(call)] = "series"
        assert all(isinstance(snapshot, tuple) for snapshot in proof.symbols.values())


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "declarations,expression",
    [
        ("value(x=x)=>x", "value()"),
        ("value(x=y,y=2)=>x", "value()"),
        ("inner(x=missing)=>x\nvalue()=>\n    missing=2\n    inner()", "value()"),
        ("value(x=BASE)=>x\nBASE=2", "value()"),
        ("BASE=bar_index\nvalue(x=BASE)=>x", "value()"),
        ("value(a,b=2)=>a+b", "value()"),
        ("value(a,b=2)=>a+b", "value(a=1,a=2)"),
        ("value(a,b=2)=>a+b", "value(1,2,3)"),
        ("value(a=2)=>a", "value(unknown=2)"),
    ],
)
def test_default_selection_and_definition_scope_reject_invalid_constant_input(
    version, declarations, expression
):
    code = source(version, declarations, f"input.int({expression})")
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(code)
