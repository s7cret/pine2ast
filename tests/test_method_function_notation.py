"""Explicit method receivers reuse the exact method overload/visibility owner."""
from copy import deepcopy

import pytest

from pine2ast.api import ParseOptions, ParsePipeline
from pine2ast.hardening import consumer_bundle as owner
from pine2ast.hardening.method_functions import METHOD_FUNCTION_CAPABILITY as CAP
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries
from tests.test_library_method_projection import checked, lib, source
from tests.test_method_receiver_admission import reseal, reseal_facts


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("call", ["plus(2)", "plus(2,n=3)", "plus(n=3,self=2)"])
@pytest.mark.parametrize("qualifier", ["", "simple "])
def test_local_explicit_receiver_has_full_types_and_exact_parameter_indices(version,call,qualifier):
    text=f'//@version={version}\nindicator("receiver")\nmethod plus({qualifier}int self,int n=1)=>self+n\nplot({call})\n'
    bundle=owner.build_consumer_bundle(text,producer_commit="a"*40)
    fact=next(c for c in bundle["semantic_facts"]["calls"] if c["call_form"]=="USER_METHOD")
    assert fact["resolution_status"]=="RESOLVED"
    assert fact["receiver_type"]=="int"
    assert next(a for a in fact["arguments"] if a["parameter_name"]=="self")["parameter_index"]==0
    assert all(a["actual_type"] and a["expected_type"] for a in fact["arguments"])
    assert CAP in bundle["consumer_contract"]["required_capabilities"]
    owner.verify_consumer_bundle(bundle,expected_producer_commit=bundle["producer"].get("commit"))


@pytest.mark.parametrize("v", [5, 6])
@pytest.mark.parametrize("call", ["m.plus(2)","m.plus(n=3,self=2)","m.plus(m.plus(2))"])
def test_library_callee_is_projected_without_argument_wrappers(v,call):
    text=source(f'// preserve m.plus(2)\ns="m.plus(2)"\nplot({call})',v=v)
    decl=lib("export method plus(simple int self,simple int n=1)=>self+n",v=v)
    linked=link_libraries(text,LibraryStore.create({"u/M/1":decl}))
    assert "// preserve m.plus(2)" in linked.code and '"m.plus(2)"' in linked.code
    result=ParsePipeline(ParseOptions(library_context=linked.qualifier_context())).parse(linked.code)
    assert result.ok,[d.message for d in result.diagnostics]
    # Alpha-renaming only: no wrapper FunctionDeclaration introduced by the linker.
    assert not any(type(n).__name__=="FunctionDeclaration" for n in result.ast.items)
    first=linked.receipt()
    assert link_libraries(text,LibraryStore.create({"u/M/1":decl})).receipt()==first
    linked.verify()


@pytest.mark.parametrize("v", [5, 6])
@pytest.mark.parametrize("call", ["m.plus()",'m.plus("bad")',"m.plus(close)","m.plus(2,self=3)","m.plus(self=2,2)","m.plus(2,unknown=3)","m.secret(2)"])
def test_explicit_receiver_never_bypasses_types_qualifiers_or_visibility(v,call):
    decl="method secret(simple int self)=>self\nexport method plus(simple int self,int n=1)=>self+n"
    with pytest.raises((LibraryError,owner.ConsumerBundleError)):
        checked(f"plot({call})",{"u/M/1":lib(decl,v=v)},v=v)


@pytest.mark.parametrize("v", [5, 6])
def test_nominal_namespace_cannot_choose_foreign_same_named_receiver(v):
    libs={f"u/{n}/1":lib("export type P\n    int n=1\nexport method val(P self)=>self.n",n,v)
          for n in ["A","B"]}
    imports="import u/A/1 as a\nimport u/B/1 as b"
    checked("p=a.P.new()\nq=b.P.new()\nplot(a.val(p))\nplot(b.val(q))",libs,imports,v)
    with pytest.raises(LibraryError):
        checked("p=a.P.new()\nplot(b.val(p))",libs,imports,v)


@pytest.mark.parametrize("v", [5, 6])
@pytest.mark.parametrize("body",[
    "method plus(simple int self)=>plus(self)\nplot(plus(1))",
    "method plus(simple int self)=>helper(self)\nhelper(simple int x)=>plus(x)\nplot(plus(1))",
])
def test_explicit_calls_participate_in_declaration_recursion_graph(v,body):
    with pytest.raises(owner.ConsumerBundleError):
        owner.build_consumer_bundle(f'//@version={v}\nindicator("cycles")\n'+body+'\n')


@pytest.mark.parametrize("v", [1,2,3,4])
def test_new_consumer_feature_does_not_backport_methods(v):
    with pytest.raises(owner.ConsumerBundleError):
        owner.build_consumer_bundle(f'//@version={v}\nstudy("old")\nmethod plus(int self)=>self+1\nplot(plus(1))\n')


@pytest.mark.parametrize("v", [5,6])
def test_exported_result_floor_survives_explicit_namespace_call(v):
    with pytest.raises((LibraryError,owner.ConsumerBundleError)):
        checked('n=m.fixed(1)\nx=input.int(n)\nplot(x)',{"u/M/1":lib("export method fixed(simple int self)=>7",v=v)},v=v)


@pytest.mark.parametrize("qualifier", ["", "simple "])
@pytest.mark.parametrize("fault", ["receiver", "argument", "default", "constant"])
def test_resealed_proofs_still_require_fresh_ast_semantics(monkeypatch,qualifier,fault):
    text=f'//@version=6\nindicator("admission")\nmethod plus({qualifier}int self,int n=1)=>self+n\nplot(plus(2))\n'
    good=owner.build_consumer_bundle(text,producer_commit="a"*40)
    bad=deepcopy(good)
    call=next(c for c in bad["semantic_facts"]["calls"] if c["call_form"]=="USER_METHOD")
    if fault=="receiver":call["receiver_type"]="float"
    elif fault=="argument":call["arguments"][0]["actual_qualifier"]="simple"
    elif fault=="default":
        call["defaults_applied"][0].update(default_known=True,default_value=99)
    else:
        next(f for f in bad["semantic_facts"]["facts"] if f.get("const_value")==2)["const_value"]=99
    reseal_facts(bad)
    def forbidden(*args,**kwargs):
        raise AssertionError("source-free verification must replay AST, not parse unavailable source")
    monkeypatch.setattr(owner,"parse_source",forbidden)
    owner.verify_consumer_bundle(good,expected_producer_commit="a"*40)
    with pytest.raises(owner.ConsumerBundleError,match="fresh producer analysis"):
        owner.verify_consumer_bundle(bad,expected_producer_commit="a"*40)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "minimum", "unsupported"])
def test_capability_set_must_match_actual_explicit_call_syntax(fault):
    bundle=owner.build_consumer_bundle('//@version=6\nindicator("caps")\nmethod plus(int self)=>self+1\nplot(plus(2))\n')
    contract=bundle["consumer_contract"]
    if fault=="missing":contract["required_capabilities"].remove(CAP)
    elif fault=="duplicate":contract["required_capabilities"].append(CAP)
    elif fault=="minimum":contract["minimum_consumer_version"]="4.0.0"
    else:contract["required_capabilities"].append("unknown_method_feature")
    reseal(bundle)
    with pytest.raises(owner.ConsumerBundleError):owner.verify_consumer_bundle(bundle,expected_producer_commit=bundle["producer"].get("commit"))


def test_unused_or_dot_only_method_does_not_change_existing_capabilities():
    for body in ["plot(1)","x=1\nplot(x.plus())"]:
        bundle=owner.build_consumer_bundle('//@version=6\nindicator("old")\nmethod plus(int self)=>self+1\n'+body+'\n')
        assert CAP not in bundle["consumer_contract"]["required_capabilities"]
        owner.verify_consumer_bundle(bundle,expected_producer_commit=bundle["producer"].get("commit"))
