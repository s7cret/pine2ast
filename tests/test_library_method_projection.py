"""Literal acceptance examples for source-scoped, pinned method imports.

Expected values/visibility are specified independently of linked output. These
are engineering fixtures, not captured TradingView execution results.
"""

from copy import deepcopy
import pytest
from pine2ast.api import ParseOptions, ParsePipeline
from pine2ast.ast.nodes import MethodDeclaration
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries
from pine2ast.libraries.store import canonical, source_hash
from pine2ast.hardening.consumer_bundle import (
    build_consumer_bundle,
    ConsumerBundleError,
    verify_consumer_bundle,
)


def lib(body, title="M", v=6):
    return f'//@version={v}\nlibrary("{title}")\n{body}\n'


def source(body, imports="import u/M/1 as m", v=6):
    return f'//@version={v}\nindicator("method fixtures")\n{imports}\n{body}\n'


def checked(body, libs, imports="import u/M/1 as m", v=6):
    linked = link_libraries(source(body, imports, v), LibraryStore.create(libs))
    ctx = linked.qualifier_context()
    parsed = ParsePipeline(ParseOptions(library_context=ctx, created_at_utc_ms=0)).parse(
        linked.code
    )
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    linked.verify()
    return linked, parsed


@pytest.mark.parametrize("v", [5, 6])
@pytest.mark.parametrize(
    "body,decl",
    [
        (
            "a=2\nplot(a.plus(step=3))",
            "export method plus(simple int self,simple int step=3)=>self+step",
        ),
        (
            "var array<float> a=array.new<float>()\nplot(a.add(close))",
            "export method add(array<float> self,float x)=>\n    self.push(x)\n    self.size()",
        ),
        (
            "p=m.Point.new(2)\nplot(p.plus(3))",
            "export type Point\n    int n=0\nexport method plus(Point self,int step=3)=>self.n+step",
        ),
        (
            "s=m.Side.up\nplot(s.number())",
            "export enum Side\n    up\n    down\nexport method number(Side self)=>self==Side.up ? 1 : -1",
        ),
        (
            "a=2\nb=2.5\nplot(a.plus())\nplot(b.plus())",
            "export method plus(simple int self)=>self+1\nexport method plus(simple float self)=>self+10",
        ),
        ("a=2\nplot(a.plus().plus())", "export method plus(simple int self)=>self+1"),
    ],
)
def test_typed_public_receiver_methods_and_overloads(v, body, decl):
    linked, parsed = checked(body, {"u/M/1": lib(decl, v=v)}, v=v)
    assert linked.receipt()["profile"] == "same_version_methods_v5"
    ctx = linked.qualifier_context()
    assert ctx.to_dict()["schema_id"] == "pine2ast.library_qualifier_context.v2"
    # Context admission accepts pristine syntax, before producer metadata is attached.
    from pine2ast.libraries.qualifier_context import _syntax

    syntax = _syntax(linked.code)
    ids = ctx.declaration_ids(syntax)
    assert ids and all(isinstance(n, MethodDeclaration) for n in syntax.items if id(n) in ids)


@pytest.mark.parametrize("v", [5, 6])
def test_private_helper_is_usable_only_inside_its_module(v):
    decl = "method secret(simple int self)=>self+7\nexport method public(simple int self)=>self.secret()"
    checked("a=2\nplot(a.public())", {"u/M/1": lib(decl, v=v)}, v=v)
    with pytest.raises(LibraryError, match="visible"):
        checked("a=2\nplot(a.secret())", {"u/M/1": lib(decl, v=v)}, v=v)


@pytest.mark.parametrize("v", [5, 6])
def test_transitive_method_does_not_leak_into_consumer(v):
    libs = {
        "u/D/1": lib("export method deep(simple int self)=>self+10", "D", v),
        "u/M/1": lib("import u/D/1 as d\nexport method outer(simple int self)=>self.deep()+1", v=v),
    }
    checked("a=2\nplot(a.outer())", libs, v=v)
    with pytest.raises(LibraryError, match="visible"):
        checked("a=2\nplot(a.deep())", libs, v=v)
    checked("a=2\nplot(a.deep())", libs, imports="import u/M/1 as m\nimport u/D/1 as d", v=v)


@pytest.mark.parametrize("v", [5, 6])
def test_foreign_private_same_name_method_and_local_method_are_independent(v):
    libs = {
        "u/A/1": lib(
            "method secret(simple int self)=>self+1\nexport method fromA(simple int self)=>self.secret()",
            "A",
            v,
        ),
        "u/B/1": lib(
            "method secret(simple int self)=>self+10\nexport method fromB(simple int self)=>self.secret()",
            "B",
            v,
        ),
    }
    checked(
        "method secret(simple int self)=>self+100\na=2\nplot(a.fromA())\nplot(a.fromB())\nplot(a.secret())",
        libs,
        "import u/A/1 as liba\nimport u/B/1 as libb",
        v,
    )


def test_ambiguous_public_methods_are_not_selected_by_import_order():
    libs = {
        "u/A/1": lib("export method plus(simple int self)=>self+1", "A"),
        "u/B/1": lib("export method plus(simple int self)=>self+10", "B"),
    }
    for imports in ("import u/A/1 as a\nimport u/B/1 as b", "import u/B/1 as b\nimport u/A/1 as a"):
        with pytest.raises(LibraryError):
            checked("n=2\nplot(n.plus())", libs, imports)


@pytest.mark.parametrize("v", [5, 6])
def test_nominal_receivers_same_type_spelling_are_distinct(v):
    libs = {
        "u/A/1": lib("export type P\n    int n=1\nexport method plus(P self)=>self.n+1", "A", v),
        "u/B/1": lib("export type P\n    int n=10\nexport method plus(P self)=>self.n+10", "B", v),
    }
    checked(
        "p=a.P.new()\nq=b.P.new()\nplot(p.plus())\nplot(q.plus())",
        libs,
        "import u/A/1 as a\nimport u/B/1 as b",
        v,
    )


@pytest.mark.parametrize(
    "bad",
    [
        "export method f(simple int self, x)=>x",
        "export method f(simple int self)=>input.int(2)",
        "g=close\nexport method f(simple int self)=>g",
        "type Private\n    int n=0\nexport method f(Private self)=>self.n",
        "type Private\n    int n=0\nexport method f(simple int self)=>Private.new()",
        "export method f(simple int self)=>self.f()",
    ],
)
def test_invalid_exported_method_does_not_enter_linked_artifact(bad):
    with pytest.raises((LibraryError, ConsumerBundleError)):
        linked = link_libraries(
            source("a=2\nplot(a.f())"), LibraryStore.create({"u/M/1": lib(bad)})
        )
        build_consumer_bundle(linked.code, producer_commit="a" * 40, linked_source=linked)


@pytest.mark.parametrize("v", [5, 6])
def test_library_result_floor_cannot_be_lost_on_a_method(v):
    libs = {"u/M/1": lib("export method fixed(simple int self)=>7", v=v)}
    linked, _ = checked("a=2\nb=a.fixed()\nplot(b)", libs, v=v)
    bundle = build_consumer_bundle(linked.code, producer_commit="a" * 40, linked_source=linked)
    assert "library_method_projection_v1" in bundle["consumer_contract"]["required_capabilities"]
    with pytest.raises((LibraryError, ConsumerBundleError)):
        checked("a=2\nb=a.fixed()\nx=input.int(b)\nplot(x)", libs, v=v)


@pytest.mark.parametrize("fault", ["capability", "floor", "declaration", "schema", "code"])
def test_source_and_context_tampering_is_rejected(fault):
    linked, _ = checked(
        "a=2\nplot(a.plus())", {"u/M/1": lib("export method plus(simple int self)=>self+1")}
    )
    bundle = build_consumer_bundle(linked.code, producer_commit="a" * 40, linked_source=linked)
    altered = deepcopy(bundle)
    if fault == "capability":
        altered["consumer_contract"]["required_capabilities"].remove("library_method_projection_v1")
    else:
        ctx = altered["library_context"]
        if fault == "floor":
            ctx["exported_functions"][0]["minimum_return_qualifier"] = "const"
        elif fault == "declaration":
            ctx["exported_functions"] = []
        elif fault == "schema":
            ctx["schema_id"] = "pine2ast.library_qualifier_context.v1"
        else:
            ctx["linkage_receipt"]["sources"]["u/M/1"]["raw_text"] += "\n// changed\n"
        ctx["content_hash"] = source_hash(
            canonical({k: v for k, v in ctx.items() if k != "content_hash"})
        )
        altered["ast"]["producer_metadata"]["library_qualifier_context_ref"] = ctx["content_hash"]
    altered["content_hash"] = source_hash(
        canonical({k: v for k, v in altered.items() if k != "content_hash"})
    )
    with pytest.raises((ConsumerBundleError, LibraryError)):
        verify_consumer_bundle(altered, expected_producer_commit="a" * 40)


def test_ordinary_function_name_cannot_collide_with_generated_method_name():
    decl = "method_plus(simple int x)=>x+10\nexport method plus(simple int self)=>method_plus(self)"
    checked("a=2\nplot(a.plus())", {"u/M/1": lib(decl)})


def test_unrelated_library_does_not_change_dependency_identity():
    libs = {"u/M/1": lib("export method plus(simple int self)=>self+1")}
    a, _ = checked("n=2\nplot(n.plus())", libs)
    b, _ = checked(
        "n=2\nplot(n.plus())",
        {**libs, "u/Other/1": lib("export method f(simple int x)=>x", "Other")},
    )
    assert a._receipt == b._receipt and a.code == b.code


@pytest.mark.parametrize(
    "body",
    [
        "f(int x)=>f(x)",
        "f(int x)=>g(x)\ng(int x)=>f(x)",
        "method f(simple int self)=>self.f()",
        "method f(simple int self)=>self.g()\nmethod g(simple int self)=>self.f()",
    ],
)
def test_direct_and_mutual_user_call_cycles_rejected_by_frontend(body):
    result = ParsePipeline().parse('//@version=6\nindicator("cycle")\n' + body + "\n")
    assert not result.ok
    assert any(d.code == "P2A1512" for d in result.diagnostics), [
        (d.code, d.message) for d in result.diagnostics
    ]


def test_same_method_name_different_overload_is_not_recursion():
    result = ParsePipeline().parse(
        '//@version=6\nindicator("not cycle")\n'
        "method f(simple float self)=>self+1\nmethod f(simple int self)=>float(self).f()\nx=2\nplot(x.f())\n"
    )
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
