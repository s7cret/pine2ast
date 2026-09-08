"""Closed model reconstruction and admission budgets, independent of inference."""

from copy import deepcopy
from dataclasses import is_dataclass
import json

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.ast import nodes
from pine2ast.ast.base import ASTNode
from pine2ast.ast.decode import ASTAdmissionBudget, ASTDecodeError, ASTReplayLimits, decode_program
from pine2ast.ast.serialize import ast_to_dict
from pine2ast.ast.types import TypeRef
from pine2ast.ast.visitors import walk

MODEL_SOURCE = """//@version=6
indicator("Canonical model")
import qa/Types/1 as dep
type Point
    float value=1.0
    varip int ticks=0
enum Side
    long="Long"
    short
//@function documented function
//@param n count
choose(int n=2)=>
    var int total=0
    for i=0 to n by 1
        if i>2
            break
        else if i==1
            continue
        else
            total+=i
    values=array.new<int>(2,1)
    for [index,value] in values
        total+=value
    while total<3
        total+=1
    total
method pair(simple int self)=>[self,self+1]
varip int tick=0
once true
    tick+=1
a=2
[first,second]=a.pair()
selected=switch a
    1=>10
    =>20
literalFloat=1.5
literalBool=true
literalString="text"
literalColor=#ff0000
float missing=na
history=close[1]
negative=-a
condition=a>0 ? first : second
plot(choose()+selected+condition)
"""


def model_payload():
    parsed = parse_code(MODEL_SOURCE, ParseOptions(run_semantic=False))
    assert parsed.ok, parsed.diagnostics
    return ast_to_dict(parsed.ast)


def test_every_canonical_ast_node_kind_roundtrips_without_parser_replay():
    payload = model_payload()
    restored = decode_program(json.loads(json.dumps(payload)))
    assert ast_to_dict(restored) == payload
    covered = {node.kind for node in walk(restored)}
    canonical = {
        cls.__name__
        for cls in vars(nodes).values()
        if isinstance(cls, type) and issubclass(cls, ASTNode) and is_dataclass(cls)
    } | {TypeRef.__name__}
    assert covered == canonical


@pytest.mark.parametrize(
    "attack",
    [
        "unknown_kind",
        "unknown_field",
        "wrong_field_type",
        "bool_for_int",
        "null_items",
        "unknown_qualifier",
        "null_qualifier",
        "nonfinite",
        "surrogate",
        "cycle",
        "object",
    ],
)
def test_closed_model_rejects_malformed_payload(attack):
    payload = model_payload()
    if attack == "unknown_kind":
        payload["kind"] = "InjectedProgram"
    elif attack == "unknown_field":
        payload["python_constructor"] = "builtins.eval"
    elif attack == "wrong_field_type":
        payload["language"] = []
    elif attack == "bool_for_int":
        payload["span"]["start_offset"] = False
    elif attack == "null_items":
        payload["items"] = None
    elif attack in {"unknown_qualifier", "null_qualifier"}:
        method = next(n for n in payload["items"] if n["kind"] == "MethodDeclaration")
        method["receiver_explicit_qualifier"] = "guessed" if attack == "unknown_qualifier" else None
    elif attack == "nonfinite":
        payload["producer_metadata"]["number"] = float("nan")
    elif attack == "surrogate":
        payload["producer_metadata"]["text"] = "\ud800"
    elif attack == "cycle":
        payload["producer_metadata"]["cycle"] = payload
    else:
        payload["producer_metadata"]["object"] = object()
    with pytest.raises(ASTDecodeError):
        decode_program(payload)


@pytest.mark.parametrize(
    "limit,value",
    [
        ("max_bytes", 100),
        ("max_depth", 2),
        ("max_values", 10),
        ("max_ast_nodes", 2),
        ("max_container_items", 2),
        ("max_string_length", 2),
    ],
)
def test_one_admission_budget_bounds_preflight_and_reconstruction(limit, value):
    with pytest.raises(ASTDecodeError, match="limit"):
        decode_program(
            model_payload(), budget=ASTAdmissionBudget(ASTReplayLimits(**{limit: value}))
        )


@pytest.mark.parametrize("value", [0, -1, True, 1.0, 129])
def test_limits_cannot_disable_or_expand_the_declared_default(value):
    with pytest.raises(ASTDecodeError):
        ASTReplayLimits(max_depth=value)


def test_failed_union_alternatives_charge_the_same_budget():
    from pine2ast.ast.decode import _Decoder
    from pine2ast.lexer.token import SourceSpan

    payload = ast_to_dict(nodes.Literal(SourceSpan.zero(), 2, "int"))
    direct = ASTAdmissionBudget()
    union = ASTAdmissionBudget()
    _Decoder(direct).decode(deepcopy(payload), nodes.Expression)
    _Decoder(union).decode(deepcopy(payload), nodes.Block | nodes.Expression)
    assert union.work > direct.work
    limited = ASTAdmissionBudget(ASTReplayLimits(max_values=direct.work))
    with pytest.raises(ASTDecodeError, match="work"):
        _Decoder(limited).decode(payload, nodes.Block | nodes.Expression)


@pytest.mark.parametrize("attack", ["cycle", "oversize", "deep"])
def test_raw_bundle_is_bounded_before_copy_or_canonicalization(monkeypatch, attack):
    import pine2ast.hardening.consumer_bundle as consumer

    payload = {"ast": {"schema_version": "2.1"}}
    if attack == "cycle":
        payload["loop"] = payload
    elif attack == "oversize":
        payload["text"] = "x" * 1000
    else:
        value = []
        for _ in range(20):
            value = [value]
        payload["deep"] = value

    def forbidden(*args, **kwargs):
        raise AssertionError("copy/canonicalization occurred before admission limits")

    monkeypatch.setattr(consumer, "deepcopy", forbidden)
    monkeypatch.setattr(consumer, "content_hash", forbidden)
    with pytest.raises(consumer.ConsumerBundleError):
        consumer.verify_consumer_bundle(
            payload, ast_replay_limits=ASTReplayLimits(max_bytes=200, max_depth=10)
        )
