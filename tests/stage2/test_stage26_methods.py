"""Stage 2.6 producer matrix: method/function resolution by receiver and signature."""

from __future__ import annotations

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries


def _src(body: str, version: int = 6) -> str:
    header = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{header}("s26")\n{body}\n'


def _lib(body: str, version: int = 6, name: str = "Lib") -> str:
    return f'//@version={version}\nlibrary("{name}")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
def test_stage26_same_name_methods_resolve_by_receiver_not_name(version):
    code = _src(
        "type A\n    int n=1\ntype B\n    int n=10\n"
        "method score(A self, int step=1)=>self.n+step\n"
        "method score(B self, int step=2)=>self.n*step\n"
        "plot(A.new().score())\nplot(B.new().score(step=3))",
        version,
    )
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    calls = [
        row
        for row in build_consumer_bundle(code)["semantic_facts"]["calls"]
        if row.get("call_form") == "USER_METHOD"
    ]
    assert len(calls) == 2
    by_receiver = {row["receiver_type"]: row for row in calls}
    assert set(by_receiver) == {"A", "B"}
    assert by_receiver["A"]["symbol_id"] != by_receiver["B"]["symbol_id"]
    assert by_receiver["A"]["return_type"] == "int"
    assert by_receiver["B"]["return_type"] == "int"


@pytest.mark.parametrize("version", [5, 6])
def test_stage26_collection_receivers_keep_element_type(version):
    code = _src(
        "method firstValue(array<int> self)=>array.get(self, 0)\n"
        "method firstValue(array<string> self)=>array.get(self, 0)\n"
        "xs=array.new<int>(1, 2)\nys=array.new<string>(1, \"x\")\n"
        "n=xs.firstValue()\n"
        "s=ys.firstValue()\n"
        "plot(n)\nplot(str.length(s))",
        version,
    )
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    calls = [
        row
        for row in build_consumer_bundle(code)["semantic_facts"]["calls"]
        if row.get("call_form") == "USER_METHOD" and "firstValue" in str(row.get("name", row.get("symbol_id", "")))
    ]
    assert {(row["receiver_type"], row["return_type"]) for row in calls} == {
        ("array<int>", "int"),
        ("array<string>", "string"),
    }


@pytest.mark.parametrize("version", [5, 6])
def test_stage26_named_defaults_select_exact_overload(version):
    code = _src(
        "method choose(int self, int n, float extra=0.5)=>n+extra\n"
        "method choose(int self, string text)=>str.length(text)\n"
        "a=1\nplot(a.choose(n=4))\nplot(a.choose(\"abcd\"))",
        version,
    )
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    calls = [
        row
        for row in build_consumer_bundle(code)["semantic_facts"]["calls"]
        if row.get("call_form") == "USER_METHOD"
    ]
    assert {row["return_type"] for row in calls} == {"float", "int"}


@pytest.mark.parametrize(
    "body",
    [
        "method score(A self)=>1\nplot(score())",
        "f(int x)=>x\nplot(1.f())",
        "method choose(int self, int n)=>n\nmethod choose(int self, int other)=>other\nplot(1.choose(2))",
        "method walk(A self)=>self.walk()\ntype A\n    int n\nplot(A.new().walk())",
        "method get(array<int> self, int index)=>index\nplot(array.new<int>(1,2).get(0))",
        "method read(array<int> self)=>array.get(self,0)\nplot(array.new<float>(1,1.0).read())",
    ],
)
def test_stage26_name_only_ambiguity_recursion_and_wrong_receiver_fail(body):
    parsed = parse_code(_src(body))
    assert not parsed.ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(_src(body))


@pytest.mark.parametrize("version", range(1, 5))
def test_stage26_methods_not_backported_before_v5(version):
    result = parse_code(_src("method score(int self)=>self", version))
    assert not result.ok


def test_stage26_exported_library_methods_keep_source_bound_receivers():
    sources = {
        "ownerA/Lib/1": _lib("export type Point\n    int n=1\nexport method score(Point self)=>self.n", name="Lib"),
        "ownerB/Lib/1": _lib("export type Point\n    int n=10\nexport method score(Point self)=>self.n*2", name="Lib"),
    }
    good = (
        '//@version=6\nindicator("s26")\n'
        "import ownerA/Lib/1 as a\nimport ownerB/Lib/1 as b\n"
        "plot(a.Point.new().score())\nplot(b.Point.new().score())\n"
    )
    linked = link_libraries(good, LibraryStore.create(sources))
    linked.verify()
    assert parse_code(linked.code).ok
    mixed = (
        '//@version=6\nindicator("s26")\n'
        "import ownerA/Lib/1 as a\nimport ownerB/Lib/1 as b\n"
        "plot(a.Point.new().score())\nplot(b.score(a.Point.new()))\n"
    )
    with pytest.raises(LibraryError, match="LIBRARY_METHOD_BINDING"):
        link_libraries(mixed, LibraryStore.create(sources))


def test_stage26_private_library_method_cannot_be_imported():
    with pytest.raises(LibraryError, match="LIBRARY_METHOD_BINDING|PRIVATE"):
        link_libraries(
            '//@version=6\nindicator("s26")\nimport qa/Lib/1 as lib\nplot(lib.Point.new().hidden())\n',
            LibraryStore.create(
                {
                    "qa/Lib/1": _lib(
                        "export type Point\n    int n=1\nmethod hidden(Point self)=>self.n\nexport read(int x)=>x"
                    )
                }
            ),
        )
