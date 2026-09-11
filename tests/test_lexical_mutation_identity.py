"""Mutation classification is lexical, not a property of a variable spelling.

Manual typing fixtures. These do not claim an external TradingView execution.
"""

import pytest

from pine2ast import parse_code
from pine2ast.ast.nodes import VarDeclaration
from pine2ast.ast.walk import iter_nodes
from pine2ast.hardening.consumer_bundle import build_consumer_bundle, verify_consumer_bundle
from pine2ast.semantic.mutation_identity import reassigned_declarations


def check(body, version=6):
    title = "indicator" if version >= 5 else "study"
    return parse_code(f'//@version={version}\n{title}("lexical writes")\n{body}\n')


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["method", "function"])
@pytest.mark.parametrize("use", ["receiver", "input_default"])
def test_local_write_does_not_strengthen_unrelated_global_qualifier(version, kind, use):
    declaration = (
        "method count(simple int self,int step)" if kind == "method" else "count(int step)"
    )
    body = (
        declaration + "=>\n    var int n=1000\n    n+=step\n    n\n"
        "method stable(simple int self)=>self\nn=2\n"
    )
    body += "plot(n.stable())" if use == "receiver" else "plot(input.int(n))"
    parsed = check(body, version)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    bundle = build_consumer_bundle(f'//@version={version}\nindicator("lexical writes")\n{body}\n')
    verify_consumer_bundle(bundle)


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_function_local_mutation_does_not_change_global_constant(version):
    body = "counter()=>\n    n=1\n    n:=n+1\n    n\nn=2\nplot(n)"
    parsed = check(body, version)
    assert parsed.ok, parsed.diagnostics
    global_n = next(n for n in parsed.ast.items if isinstance(n, VarDeclaration) and n.name == "n")
    writes = reassigned_declarations(parsed.ast)
    assert id(global_n) not in writes
    assert len(writes) == 1


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("write", ["n+=1", "if bar_index>0\n    n+=1"])
def test_real_global_mutation_still_rejects_simple_receiver(version, write):
    parsed = check(
        "method stable(simple int self)=>self\nn=2\n" + write + "\nplot(n.stable())", version
    )
    assert not parsed.ok
    assert any(d.code == "P2A1405" and "simple" in d.message for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [5, 6])
def test_unrelated_mutated_method_local_does_not_poison_simple_result(version):
    body = (
        "method changed(simple int self)=>\n    n=1\n    n+=self\n    n\n"
        "method stable(simple int self)=>\n    n=self\n    n\n"
        "a=2\nplot(ta.ema(close,a.stable()))"
    )
    parsed = check(body, version)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("scope", ["block", "tuple", "loop", "parameter"])
def test_local_shadow_bindings_never_mark_outer_variable(version, scope):
    body = {
        "block": "n=2\nif close>0\n    n=1\n    n+=1\nplot(n)",
        "tuple": "pair()=>[1,2]\nn=2\nif close>0\n    [n,m]=pair()\n    n+=1\nplot(n)",
        "loop": "n=2\nfor n=0 to 1\n    a=n+1\nplot(n)",
        "parameter": "n=2\nidentity(int n)=>n+1\nplot(n)",
    }[scope]
    parsed = check(body, version)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    outer = next(n for n in parsed.ast.items if isinstance(n, VarDeclaration) and n.name == "n")
    assert id(outer) not in reassigned_declarations(parsed.ast)


@pytest.mark.parametrize("version", [5, 6])
def test_write_before_local_shadow_marks_outer_but_later_write_marks_local(version):
    parsed = check("n=2\nif close>0\n    n+=1\n    n=7\n    n+=1\nplot(n)", version)
    assert parsed.ok, parsed.diagnostics
    nodes = [n for n in iter_nodes(parsed.ast) if isinstance(n, VarDeclaration) and n.name == "n"]
    assert len(nodes) == 2
    assert reassigned_declarations(parsed.ast) == {id(n) for n in nodes}
