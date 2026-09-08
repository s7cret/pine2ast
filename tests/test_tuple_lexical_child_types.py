"""Tuple element types must retain exact lexical and call-context evidence."""

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import Identifier, Literal, TupleExpr
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic.inference import PineInferenceEngine
from pine2ast.semantic.symbols import Symbol, SymbolKind

# Written before the patch. Types follow loop variables, explicit float
# declarations, element types and ordinary int/float promotion, not SUT output.
CASES = [
    ("range", "f()=>\n    for i=1 to 3\n        [i,i+1]", "tuple<int,int>"),
    ("range_shadow", 'i="outer"\nf()=>\n    for i=1 to 3\n        [i,i+1]', "tuple<int,int>"),
    (
        "range_mixed",
        "f()=>\n    for i=1 to 3\n        float j=i+0.5\n        [j,i]",
        "tuple<float,int>",
    ),
    (
        "nested_range",
        "f()=>\n    for i=1 to 2\n        for j=1 to 3\n            [i,j]",
        "tuple<int,int>",
    ),
    ("while", "f()=>\n    n=0\n    while n<2\n        n+=1\n        [n,n+0.5]", "tuple<int,float>"),
    (
        "for_in",
        "f()=>\n    values=array.from(1.5,2.5)\n    for [index,value] in values\n        [index,value]",
        "tuple<int,float>",
    ),
    ("context_calls", "identity(x)=>x\nf()=>[identity(1),identity(1.5)]", "tuple<int,float>"),
    ("conditional", "f()=>[true?1:0.5,2]", "tuple<float,int>"),
    ("named_default", "value(float n=1.5)=>n\nf()=>[value(),value(n=2)]", "tuple<float,float>"),
]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("name,body,expected", CASES, ids=[r[0] for r in CASES])
def test_tuple_return_elements_keep_lexical_types(version, name, body, expected):
    source = f'//@version={version}\nindicator("Tuple types")\n{body}\n[a,b]=f()\nplot(a+b)\n'
    parsed = parse_code(source)
    assert parsed.ok, parsed.diagnostics
    facts = parsed.semantic_model.semantic_facts.artifact
    call = next(
        c for c in facts["calls"] if c["call_form"] == "USER_FUNCTION" and c["callee"] == "f"
    )
    assert call["return_type"] == expected
    assert facts["coverage"]["ok"]
    bundle = build_consumer_bundle(source)
    assert bundle["semantic_facts"]["coverage"]["ok"]
    if name == "range_shadow":
        assert parsed.semantic_model.symbols["i"].type == "string"


@pytest.mark.parametrize("version", [5, 6])
def test_loop_tuple_does_not_launder_series_into_simple_parameter(version):
    source = f'//@version={version}\nindicator("Tuple qualifier")\nf()=>\n    for i=1 to 3\n        [i,i+1]\n[a,b]=f()\nplot(ta.ema(close,a))\n'
    parsed = parse_code(source)
    assert not parsed.ok
    assert any("qualifier" in d.message.lower() for d in parsed.diagnostics if d.is_error)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", [5, 6])
def test_unresolved_tuple_element_still_rejects(version):
    source = f'//@version={version}\nindicator("Unknown tuple")\nf()=>\n    for i=1 to 3\n        [missing,i]\n[a,b]=f()\nplot(a+b)\n'
    assert not parse_code(source).ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", range(1, 7))
def test_trusted_child_dispatch_keeps_old_versions_and_ignores_cached_parent(version):
    parsed = parse_code(f"//@version={version}\nx=1\n", ParseOptions(run_semantic=False))
    span = SourceSpan.zero()
    name = Identifier(span, "i")
    expression = TupleExpr(span, [name, Literal(span, 0.5, "float")])
    engine = PineInferenceEngine(
        version_context=parsed.ast.version_context,
        symbols={
            "i": Symbol(1, "i", SymbolKind.VARIABLE, span, "string", "series", 0),
        },
    )
    engine._lexical_types[id(name)] = "int"
    engine._lexical_types[id(expression)] = "tuple<bool,bool>"
    assert engine.infer_type(expression) == (
        "tuple<int,float>" if version >= 5 else "tuple<string,float>"
    )
