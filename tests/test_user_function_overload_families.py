"""Exact declaration identity for ordinary v5/v6 function overloads."""

from copy import deepcopy

import pytest
from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import (
    ConsumerBundleError,
    build_consumer_bundle,
    verify_consumer_bundle,
)
from pine2ast.catalog.hashing import seal_hash
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries


def source(body, version=6):
    return f'//@version={version}\nindicator("families")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "f(int x)=>x+1\nf(float x)=>x+0.5\na=f(2)\nb=f(2.0)\nplot(a+b)",
        "f(x,y)=>x*y\nf(x,y,z)=>x*y*z\nplot(f(2,3)+f(2,3,4))",
        "f(float x)=>-x\nf(bool x)=>not x\nplot(f(true) ? f(1.0) : f(2.0))",
        "f(int x)=>x+1\nf(int x,int y)=>f(x)+y\nplot(f(1,2))",
        'f(simple int x)=>x+1\nf(string x)=>str.length(x)\nn=input.int(2)\nplot(f(n)+f("abc"))',
        "f(array<int> x)=>array.size(x)\nf(matrix<float> x)=>matrix.rows(x)\nplot(f(array.new<int>(2))+f(matrix.new<float>(3,1,1.0)))",
        'f(int x,float scale=2.0)=>x*scale\nf(string x)=>str.length(x)\nplot(f(scale=3.0,x=2)+f("a"))',
    ],
)
def test_distinct_type_arity_defaults_and_nested_overloads(version, body):
    parsed = parse_code(source(body, version))
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    bundle = build_consumer_bundle(source(body, version), producer_commit="a" * 40)
    assert "user_function_overloads_v1" in bundle["consumer_contract"]["required_capabilities"]
    verify_consumer_bundle(bundle, expected_producer_commit="a" * 40)
    calls = [
        c
        for c in bundle["semantic_facts"]["calls"]
        if c.get("symbol_id", "").startswith("user:function:f:")
    ]
    assert len({c["symbol_id"] for c in calls}) == 2
    assert all(c["resolution_status"] == "RESOLVED" for c in calls)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "f(int x)=>x\nf(int other)=>other+1\nplot(f(1))",
        "f(int x)=>x\nf(int x,int y=0)=>x+y\nplot(f(1))",
        "f(int x)=>x\nf(int x)=>true\nplot(f(1))",
        "f(x)=>x\nf(int x)=>x+1\nplot(f(1))",
        'f(int x)=>x\nf(float x)=>x\nplot(f("bad"))',
        "f(int x)=>x\nf(float x)=>x\nplot(f(z=1))",
        "f(int x)=>f(x)\nf(float x)=>x\nplot(f(1))",
        "f(int x)=>f(x,1)\nf(int x,int y)=>x+y\nplot(f(1))",
        "f(simple int x)=>x\nf(string x)=>str.length(x)\nplot(f(bar_index))",
    ],
)
def test_invalid_duplicate_ambiguous_recursive_and_qualified_calls(version, body):
    parsed = parse_code(source(body, version))
    assert not parsed.ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source(body, version), producer_commit="a" * 40)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_older_version_profile_not_silently_extended(version):
    parsed = parse_code(
        source("f(x)=>x\nf(x,y)=>x+y\nplot(f(1))", version).replace("indicator(", "study(")
    )
    assert not parsed.ok


def test_missing_capability_rejected_after_external_rehash():
    bundle = build_consumer_bundle(
        source("f(int x)=>x\nf(float x)=>x\nplot(f(1))"), producer_commit="a" * 40
    )
    damaged = deepcopy(bundle)
    damaged["consumer_contract"]["required_capabilities"].remove("user_function_overloads_v1")
    damaged = seal_hash({k: v for k, v in damaged.items() if k != "content_hash"})
    with pytest.raises(ConsumerBundleError, match="overload"):
        verify_consumer_bundle(damaged, expected_producer_commit="a" * 40)


@pytest.mark.parametrize("version", [5, 6])
def test_library_public_private_overloads_are_separate(version):
    libs = {
        "u/Lib/1": f'//@version={version}\nlibrary("Lib")\nf(int x)=>x+100\nexport f(float x)=>x+1\nexport g(int x)=>f(x)\n'
    }
    root = source("import u/Lib/1 as lib\nplot(lib.f(2))\nplot(lib.g(2))", version)
    linked = link_libraries(root, LibraryStore.create(libs))
    bundle = build_consumer_bundle(linked.code, linked_source=linked, producer_commit="a" * 40)
    assert "library_function_overloads_v1" in bundle["consumer_contract"]["required_capabilities"]
    linked.verify()
    with pytest.raises(LibraryError):
        link_libraries(
            source('import u/Lib/1 as lib\nplot(lib.f("bad"))', version), LibraryStore.create(libs)
        )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "parameter,expression",
    [
        ("map<string,int>", "map.new<string,int>()"),
        ("matrix<int>", "matrix.new<int>(1,1,0)"),
        ("array<bool>", "array.new<bool>(1,false)"),
        ("array<float>", "array.new<float>(1,0.0)"),
        ("color", "#abcdef"),
        ("string", '"text"'),
    ],
)
def test_explicit_type_families_are_admitted_without_guessing_elements(
    version, parameter, expression
):
    text = source(f"f({parameter} x)=>1\nf(int x)=>2\nplot(f({expression})+f(1))", version)
    bundle = build_consumer_bundle(text, producer_commit="a" * 40)
    verify_consumer_bundle(bundle, expected_producer_commit="a" * 40)
    calls = [c for c in bundle["semantic_facts"]["calls"] if c["call_form"] == "USER_FUNCTION"]
    assert len(calls) == 2 and len({c["symbol_id"] for c in calls}) == 2


@pytest.mark.parametrize("version", [5, 6])
def test_same_name_global_and_local_parameters_do_not_merge_overload_types(version):
    text = source(
        'x=10.5\nf(int x)=>\n    y=x+1\n    y\nf(string x)=>\n    y=str.length(x)\n    y\nplot(f(2)+f("abcd")+x)',
        version,
    )
    parsed = parse_code(text)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    bundle = build_consumer_bundle(text, producer_commit="a" * 40)
    verify_consumer_bundle(bundle, expected_producer_commit="a" * 40)
    calls = [c for c in bundle["semantic_facts"]["calls"] if c["call_form"] == "USER_FUNCTION"]
    assert {a["actual_type"] for c in calls for a in c["arguments"]} == {"int", "string"}


def test_overload_work_budget_rejects_without_unbounded_fallback(monkeypatch):
    import pine2ast.semantic.function_candidates as module

    monkeypatch.setattr(module, "MAX_FUNCTION_WORK", 1)
    result = parse_code(source("f(int x)=>x\nf(float x)=>x\nplot(f(1))"))
    assert not result.ok
    assert any("work limit" in d.message for d in result.diagnostics)


@pytest.mark.parametrize(
    "fault", ["missing_library_capability", "swapped_library_version", "changed_dependency"]
)
def test_overloaded_linkage_remains_bound_to_exact_source_and_feature(fault):
    from pine2ast.libraries.store import canonical, source_hash

    store = LibraryStore.create(
        {"u/Lib/1": '//@version=6\nlibrary("Lib")\nexport f(int x)=>x+1\nexport f(float x)=>x+2\n'}
    )
    linked = link_libraries(source("import u/Lib/1 as lib\nplot(lib.f(1))"), store)
    bundle = build_consumer_bundle(linked.code, linked_source=linked, producer_commit="a" * 40)
    bad = deepcopy(bundle)
    if fault == "missing_library_capability":
        bad["consumer_contract"]["required_capabilities"].remove("library_function_overloads_v1")
    else:
        # Alter the mandatory projected-source receipt, leaving original source
        # bytes/IDs untouched. Rehash the outer envelope: reconstruction must win.
        context = bad["library_context"]
        if fault == "swapped_library_version":
            context["linkage_receipt"]["profile"] = "same_version_methods_v5"
        else:
            context["content_hash"] = "sha256:" + "0" * 64
    bad["content_hash"] = source_hash(
        canonical({k: v for k, v in bad.items() if k != "content_hash"})
    )
    with pytest.raises(ConsumerBundleError):
        verify_consumer_bundle(bad, expected_producer_commit="a" * 40)


@pytest.mark.parametrize("fault", ["selected", "argument", "default", "constant"])
@pytest.mark.parametrize("version", [5, 6])
def test_fully_resealed_source_free_overloads_require_fresh_semantics(monkeypatch, version, fault):
    from pine2ast.hardening import consumer_bundle as owner
    from tests.test_method_receiver_admission import reseal_facts

    text = source(
        "f(int x,int y=1)=>x+y\nf(float x,float y=0.5)=>x+y\nplot(f(2))\nplot(f(2.0))", version
    )
    good = owner.build_consumer_bundle(text, producer_commit="a" * 40)
    bad = deepcopy(good)
    calls = [c for c in bad["semantic_facts"]["calls"] if c["call_form"] == "USER_FUNCTION"]
    first = calls[0]
    if fault == "selected":
        first["symbol_id"] = calls[1]["symbol_id"]
        first["overload_id"] = calls[1]["overload_id"]
    elif fault == "argument":
        first["arguments"][0]["actual_qualifier"] = "series"
    elif fault == "default":
        first["defaults_applied"][0].update(default_known=True, default_value=999)
    else:
        next(f for f in bad["semantic_facts"]["facts"] if f.get("const_value") == 2)[
            "const_value"
        ] = 999
    reseal_facts(bad)

    def unavailable(*args, **kwargs):
        raise AssertionError("Source-free verification must reconstruct bounded AST semantics")

    monkeypatch.setattr(owner, "parse_source", unavailable)
    owner.verify_consumer_bundle(good, expected_producer_commit="a" * 40)
    with pytest.raises(ConsumerBundleError, match="fresh producer analysis"):
        owner.verify_consumer_bundle(bad, expected_producer_commit="a" * 40)
