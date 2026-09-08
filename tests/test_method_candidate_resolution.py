"""Independent ordinary-method identities and binding examples for Pine v5/v6.

Arithmetic expectations are literal fixture documentation; this producer suite
asserts admitted types/identities and does not claim execution from parsing.
"""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle

POSITIVE = [
    (
        "receiver_overloads",
        "method choose(int self)=>self+1\nmethod choose(float self)=>self+0.5\na=2\nb=2.0\nplot(a.choose()+b.choose())",
        ("int", "float"),
        5.5,
    ),
    (
        "parameter_overloads",
        "method choose(int self,int value)=>self+value\nmethod choose(int self,float value)=>self+value\na=2\nplot(a.choose(3)+a.choose(3.5))",
        ("int", "float"),
        10.5,
    ),
    (
        "named_parameter_overloads",
        "method choose(int self,int value)=>self+value\nmethod choose(int self,float value)=>self+value\na=2\nplot(a.choose(value=3)+a.choose(value=3.5))",
        ("int", "float"),
        10.5,
    ),
    (
        "arity_overloads",
        "method choose(int self)=>self+1\nmethod choose(int self,int value)=>self+value\na=2\nplot(a.choose()+a.choose(3))",
        ("int", "int"),
        8,
    ),
    (
        "selected_defaults",
        "method choose(int self,int value=3)=>self+value\nmethod choose(float self,float value=0.5)=>self+value\na=2\nb=2.0\nplot(a.choose()+b.choose())",
        ("int", "float"),
        7.5,
    ),
    (
        "generic_receiver_identity",
        "method choose(array<int> self)=>self.get(0)+1\nmethod choose(array<float> self)=>self.get(0)+0.5\na=array.new<int>(1,2)\nb=array.new<float>(1,2.0)\nplot(a.choose()+b.choose())",
        ("int", "float"),
        5.5,
    ),
    (
        "nominal_receiver_identity",
        "type A\n    int value\ntype B\n    float value\nmethod choose(A self)=>self.value+1\nmethod choose(B self)=>self.value+0.5\na=A.new(2)\nb=B.new(2.0)\nplot(a.choose()+b.choose())",
        ("int", "float"),
        5.5,
    ),
    (
        "builtin_coexistence",
        "method get(array<int> self,int index,int offset)=>array.get(self,index)+offset\na=array.new<int>(1,2)\nplot(a.get(0,3)+a.get(0))",
        ("int",),
        7,
    ),
    (
        "builtin_coexistence_named",
        "method get(array<int> self,int index,int offset)=>array.get(self,index)+offset\na=array.new<int>(1,2)\nplot(a.get(offset=3,index=0)+a.get(index=0))",
        ("int",),
        7,
    ),
    (
        "method_body_calls_overload",
        "method choose(int self,int value)=>self+value\nmethod choose(int self,float value)=>self+value\nmethod combined(int self)=>self.choose(3)+self.choose(3.5)\na=2\nplot(a.combined())",
        ("int", "float", "float"),
        10.5,
    ),
    (
        "receiver_expression_once",
        "method choose(int self,int value)=>self+value\nmethod choose(int self,float value)=>self+value\nnextValue()=>\n    var int counter=1\n    counter+=1\n    counter\nplot(nextValue().choose(3))",
        ("int",),
        5,
    ),
    (
        "preserved_simple_parameter",
        "method choose(int self,simple int value)=>self+value\na=2\nplot(a.choose(3))",
        ("int",),
        5,
    ),
]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("case,body,returns,manual_value", POSITIVE, ids=[r[0] for r in POSITIVE])
def test_exact_method_candidate_facts(version, case, body, returns, manual_value):
    source = f'//@version={version}\nindicator("Method candidates")\n{body}\n'
    parsed = parse_code(source)
    assert parsed.ok, [d.to_dict() for d in parsed.diagnostics]
    bundle = build_consumer_bundle(source)
    calls = [c for c in bundle["semantic_facts"]["calls"] if c["call_form"] == "USER_METHOD"]
    assert tuple(c["return_type"] for c in calls) == returns
    assert all(c["resolution_status"] == "RESOLVED" for c in calls)
    assert all(c["overload_id"] == c["symbol_id"] + "#signature" for c in calls)
    assert len({c["symbol_id"] for c in calls}) == len(calls)
    for call in calls:
        assert call["receiver_type"]
        for argument in call["arguments"]:
            assert argument["parameter_name"]
            assert argument["parameter_index"] is not None
            assert argument["actual_type"] and argument["expected_type"]
    if case.startswith("builtin_coexistence"):
        builtins = [
            c
            for c in bundle["semantic_facts"]["calls"]
            if c["call_form"] == "METHOD" and c["callee"] == "array.get"
        ]
        assert len(builtins) == 1
        assert builtins[0]["return_type"] == "int"
    if case == "selected_defaults":
        assert [c["defaults_applied"][0]["parameter_name"] for c in calls] == ["value", "value"]
        assert [c["defaults_applied"][0]["expected_type"] for c in calls] == ["int", "float"]
    if case == "receiver_expression_once":
        assert (
            len([c for c in bundle["semantic_facts"]["calls"] if c["call_form"] == "USER_FUNCTION"])
            == 1
        )
    assert type(manual_value) in {int, float}


NEGATIVE = [
    (
        "duplicate_signature",
        "method choose(int self,int value)=>self+value\nmethod choose(int self,int value)=>self-value\na=2\nplot(a.choose(3))",
    ),
    ("wrong_receiver", "method choose(int self,int value)=>self+value\na=2.0\nplot(a.choose(3))"),
    (
        "generic_receiver_mismatch",
        "method choose(array<int> self)=>self.get(0)\na=array.new<float>(1,2.0)\nplot(a.choose())",
    ),
    (
        "missing_argument",
        "method choose(int self,int value)=>self+value\nmethod choose(int self,float value)=>self+value\na=2\nplot(a.choose())",
    ),
    (
        "extra_argument",
        "method choose(int self,int value)=>self+value\nmethod choose(int self,float value)=>self+value\na=2\nplot(a.choose(3,4))",
    ),
    (
        "wrong_type",
        'method choose(int self,int value)=>self+value\nmethod choose(int self,float value)=>self+value\na=2\nplot(a.choose("wrong"))',
    ),
    (
        "bool_not_numeric",
        "method choose(int self,int value)=>self+value\nmethod choose(int self,float value)=>self+value\na=2\nplot(a.choose(true))",
    ),
    (
        "unknown_named",
        "method choose(int self,int value)=>self+value\na=2\nplot(a.choose(other=3))",
    ),
    (
        "duplicate_named",
        "method choose(int self,int value)=>self+value\na=2\nplot(a.choose(3,value=4))",
    ),
    (
        "simple_parameter_series",
        "method choose(int self,simple int value)=>self+value\na=2\nplot(a.choose(bar_index))",
    ),
    (
        "ambiguous_defaults",
        "method choose(int self,int value=1)=>self+value\nmethod choose(int self,float value=1.0)=>self+value\na=2\nplot(a.choose())",
    ),
    (
        "builtin_and_user_invalid",
        'method get(array<int> self,int index,int offset)=>array.get(self,index)+offset\na=array.new<int>(1,2)\nplot(a.get("wrong"))',
    ),
]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("case,body", NEGATIVE, ids=[r[0] for r in NEGATIVE])
def test_invalid_method_candidates_rejected(version, case, body):
    source = f'//@version={version}\nindicator("Method candidates")\n{body}\n'
    parsed = parse_code(source)
    assert not parsed.ok
    assert any(d.is_error for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_methods_not_backported(version):
    source = f'//@version={version}\nstudy("Methods")\nmethod choose(int self)=>self+1\na=2\nplot(a.choose())\n'
    parsed = parse_code(source)
    assert not parsed.ok
    assert any(d.is_error for d in parsed.diagnostics)
