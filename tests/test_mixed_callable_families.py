"""Mixed-family exact binding; independently specified cases, not TV recordings."""

from copy import deepcopy

import pytest
from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import (
    ConsumerBundleError,
    build_consumer_bundle,
    verify_consumer_bundle,
)
from pine2ast.hardening.model import content_hash
from pine2ast.libraries import LibraryStore, link_libraries
from tests.test_user_function_overload_families import source

CAP = "mixed_user_callable_families_v1"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("order", [False, True])
@pytest.mark.parametrize(
    "fn,method,calls",
    [
        ("f(string x)=>str.length(x)", "method f(int self)=>self+1", 'a=f(2)\nb=f("abc")'),
        ("f(float x)=>x+0.5", "method f(int self)=>self+1", "a=f(2)\nb=f(2.0)"),
        ("f(int x,int y)=>x+y", "method f(int self)=>self+1", "a=f(2)\nb=f(2,3)"),
        (
            "f(string x,int n=2)=>str.length(x)+n",
            "method f(int self,int n=1)=>self+n",
            'a=f(n=3,self=2)\nb=f(x="abc")',
        ),
        (
            "f(bool x)=>not x",
            "method f(array<int> self)=>self.size()",
            "a=f(array.new<int>(2))\nb=f(true)",
        ),
    ],
)
def test_explicit_call_uses_both_families_regardless_of_declaration_order(
    version, order, fn, method, calls
):
    text = source((method + "\n" + fn if order else fn + "\n" + method) + "\n" + calls, version)
    bundle = build_consumer_bundle(text, producer_commit="a" * 40)
    assert CAP in bundle["consumer_contract"]["required_capabilities"]
    verify_consumer_bundle(bundle, expected_producer_commit="a" * 40)
    call_rows = [c for c in bundle["semantic_facts"]["calls"] if c.get("callee") == "f"]
    assert [c["call_form"] for c in call_rows] == ["USER_METHOD", "USER_FUNCTION"]
    assert len({c["symbol_id"] for c in call_rows}) == 2
    assert all(c["resolution_status"] == "RESOLVED" for c in call_rows)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("bad", ["f(true)", "f(z=1)", "f(1,self=2)", "f()", "f(1,2,3)"])
def test_invalid_calls_do_not_fall_back_to_one_name_table(version, bad):
    text = source("f(string x)=>str.length(x)\nmethod f(int self)=>self+1\n" + bad, version)
    assert not parse_code(text).ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(text, producer_commit="a" * 40)


@pytest.mark.parametrize("version", [5, 6])
def test_dot_notation_does_not_make_an_ordinary_function_a_method(version):
    p = parse_code(
        source('f(string x)=>str.length(x)\nmethod f(int self)=>self+1\ns="abc"\nx=s.f()', version)
    )
    assert not p.ok


@pytest.mark.parametrize("version", [5, 6])
def test_equal_applicable_explicit_signatures_are_not_chosen_by_source_order(version):
    for definitions in [
        "f(int x)=>x+1\nmethod f(int self)=>self+2",
        "method f(int self)=>self+2\nf(int x)=>x+1",
    ]:
        p = parse_code(source(definitions + "\nx=f(2)", version))
        assert not p.ok and any(d.code == "P2A2002" for d in p.diagnostics)


@pytest.mark.parametrize("version", [5, 6])
def test_typed_qualifier_bound_on_selected_receiver_is_not_erased(version):
    p = parse_code(
        source(
            "f(string x)=>str.length(x)\nmethod f(simple int self)=>self+1\nx=f(bar_index)", version
        )
    )
    assert not p.ok
    assert parse_code(
        source(
            "f(string x)=>str.length(x)\nmethod f(simple int self)=>self+1\nn=input.int(2)\nx=f(n)",
            version,
        )
    ).ok


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize("fault", ["capability", "selected", "argument", "constant"])
def test_resealed_mixed_facts_require_original_declaration_and_bounded_replay(
    version, imported, fault, monkeypatch
):
    from pine2ast.hardening import consumer_bundle as owner
    from tests.test_method_receiver_admission import reseal_facts

    declarations = "f(string x)=>str.length(x)\nmethod f(int self)=>self+1"
    text = source(declarations + '\na=f(2)\nb=f("abc")', version)
    kwargs = {}
    if imported:
        store = LibraryStore.create(
            {
                "u/Lib/1": f'//@version={version}\nlibrary("Lib")\nexport '
                + declarations.replace("\nmethod", "\nexport method")
                + "\n"
            }
        )
        linked = link_libraries(
            source('import u/Lib/1 as lib\na=lib.f(2)\nb=lib.f("abc")', version), store
        )
        text = linked.code
        kwargs["linked_source"] = linked
    good = build_consumer_bundle(text, producer_commit="a" * 40, **kwargs)
    bad = deepcopy(good)
    calls = [
        c
        for c in bad["semantic_facts"]["calls"]
        if c["call_form"] in ("USER_FUNCTION", "USER_METHOD")
    ]
    if fault == "capability":
        bad["consumer_contract"]["required_capabilities"].remove(CAP)
        bad["content_hash"] = content_hash({k: v for k, v in bad.items() if k != "content_hash"})
    elif fault == "selected":
        calls[0]["symbol_id"] = calls[1]["symbol_id"]
        calls[0]["overload_id"] = calls[1]["overload_id"]
        reseal_facts(bad)
    elif fault == "argument":
        calls[0]["arguments"][0]["actual_type"] = "float"
        reseal_facts(bad)
    else:
        next(f for f in bad["semantic_facts"]["facts"] if f.get("const_value") == 2)[
            "const_value"
        ] = 99
        reseal_facts(bad)
    if not imported:

        def no_parse(*a, **kw):
            raise AssertionError("source-free replay must not parse strings")

        monkeypatch.setattr(owner, "parse_source", no_parse)
    verify_consumer_bundle(good, expected_producer_commit="a" * 40)
    with pytest.raises(ConsumerBundleError):
        verify_consumer_bundle(bad, expected_producer_commit="a" * 40)


def test_mixed_work_budget_cannot_escape_into_method_fallback(monkeypatch):
    import pine2ast.semantic.function_candidates as owner

    monkeypatch.setattr(owner, "MAX_FUNCTION_WORK", 1)
    p = parse_code(source("f(string x)=>str.length(x)\nmethod f(int self)=>self+1\nx=f(2)"))
    assert not p.ok
    assert any("work limit" in d.message for d in p.diagnostics)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_mixed_capability_cannot_be_transplanted_to_older_versions(version):
    text = source(
        "f(string x)=>str.length(x)\nmethod f(int self)=>self+1\nx=f(2)", version
    ).replace("indicator(", "study(")
    assert not parse_code(text).ok


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("fields", [False, True])
def test_return_and_lvalue_facts_remain_lexical_across_mixed_declarations(version, reverse, fields):
    if fields:
        prefix = "type C\n    int n=0\n"
        fn = "f(int self)=>self+1"
        method = "method f(C self)=>\n    self.n+=1\n    self"
        body = "c=C.new()\na=f(c)\nb=f(2)"
        expected = ["C", "int"]
    else:
        prefix = ""
        fn = "f(float step)=>\n    var float n=0.0\n    n+=step\n    n"
        method = "method f(int step)=>\n    var int n=0\n    n+=step\n    n"
        body = "int a=f(1)\nfloat b=f(2.0)"
        expected = ["int", "float"]
    text = source(
        prefix + (method + "\n" + fn if reverse else fn + "\n" + method) + "\n" + body, version
    )
    b = build_consumer_bundle(text, producer_commit="a" * 40)
    verify_consumer_bundle(b, expected_producer_commit="a" * 40)
    calls = [c for c in b["semantic_facts"]["calls"] if c["callee"] == "f"]
    assert [c["return_type"] for c in calls] == expected
    assert b["semantic_facts"]["coverage"]["ok"]


@pytest.mark.parametrize("version", [5, 6])
def test_multiple_members_of_each_kind_share_the_same_binding_owner(version):
    text = source(
        'f(float x)=>x+0.5\nf(string x)=>str.length(x)\nmethod f(int self)=>self+1\nmethod f(bool self)=>not self\na=f(2)\nb=f(2.0)\nc=f("abc")\nd=f(false)',
        version,
    )
    b = build_consumer_bundle(text, producer_commit="a" * 40)
    rows = [c for c in b["semantic_facts"]["calls"] if c["callee"] == "f"]
    assert [r["call_form"] for r in rows] == [
        "USER_METHOD",
        "USER_FUNCTION",
        "USER_FUNCTION",
        "USER_METHOD",
    ]
    assert len({r["symbol_id"] for r in rows}) == 4
    verify_consumer_bundle(b, expected_producer_commit="a" * 40)
