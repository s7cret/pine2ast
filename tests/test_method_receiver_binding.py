"""Receiver viability uses the shared resolver without changing source args."""

from copy import deepcopy

import pytest

from pine2ast import parse_code
from pine2ast.ast.nodes import CallExpr, MemberAccessExpr
from pine2ast.ast.serialize import ast_to_dict
from pine2ast.diagnostics import codes
from pine2ast.semantic import method_candidates
from pine2ast.semantic.signatures import ReceiverArgumentEvidence


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("receiver_mode", ["valid", "missing", "too_strong"])
def test_receiver_constraint_uses_existing_binding_indices_and_source_identity(
    version, receiver_mode
):
    text = f'//@version={version}\nindicator("Receiver binding")\nmethod add(simple int self,int n=3,int other=4)=>self+n+other\na=2\nplot(a.add(other=5))\n'
    parsed = parse_code(text)
    assert parsed.ok, parsed.diagnostics
    owner = parsed.semantic_model.method_candidates
    candidate = owner.candidates[0]
    call = next(
        n
        for n in owner.index.nodes
        if isinstance(n, CallExpr)
        and isinstance(n.callee, MemberAccessExpr)
        and n.callee.member == "add"
    )
    before = deepcopy(ast_to_dict(call))
    receiver = (
        None
        if receiver_mode == "missing"
        else ReceiverArgumentEvidence(
            owner.index.id_for(call.callee.object),
            call.callee.object.span,
            "int",
            "series" if receiver_mode == "too_strong" else "const",
            False,
        )
    )
    resolution = owner.resolver.resolve_candidates(
        "add",
        [owner.entry(candidate)],
        call.arguments,
        call.span,
        kind="method",
        validate_types=True,
        validate_qualifiers=True,
        infer_arg_type=lambda arg: "int",
        infer_arg_qualifier=lambda arg: "const",
        receiver=receiver,
    )
    assert ast_to_dict(call) == before
    assert len(call.arguments) == len(resolution.resolved_arguments) == 1
    bound = resolution.resolved_arguments[0]
    assert bound.argument is call.arguments[0]
    assert bound.parameter_index == 1 and bound.parameter["name"] == "other"
    assert resolution.defaulted_parameters[0]["name"] == "n"
    assert resolution.active_parameters[0]["name"] == "n"
    assert resolution.ok is (receiver_mode == "valid")
    if receiver_mode == "missing":
        assert any("receiver evidence" in issue.message for issue in resolution.issues)
    elif receiver_mode == "too_strong":
        assert any("qualifier" in issue.message.lower() for issue in resolution.issues)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("limit", ["MAX_METHOD_WORK", "MAX_METHOD_CACHE"])
def test_receiver_candidates_including_failures_consume_shared_limits(monkeypatch, version, limit):
    monkeypatch.setattr(method_candidates, limit, 5 if limit == "MAX_METHOD_WORK" else 0)
    text = f'//@version={version}\nindicator("Receiver work")\nmethod choose(simple int self,int n)=>n\nmethod choose(simple int self,float n)=>n\nmethod choose(simple int self,string n)=>str.length(n)\nplot(bar_index.choose(true))\n'
    parsed = parse_code(text)
    assert not parsed.ok
    assert any(
        d.code == codes.UNSUPPORTED_FEATURE and "Method candidate inference work limit" in d.message
        for d in parsed.diagnostics
    )
    if limit == "MAX_METHOD_WORK":
        assert parsed.semantic_model.method_candidates.spent > 5
