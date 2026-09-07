"""Nominal library types use the locked module identity and normal frontend.

Rules: TradingView concepts/libraries, UDT and enum export requirements.
These engineering tests are not TradingView execution exports.
"""

from dataclasses import replace

import pytest

from pine2ast import parse_code
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries
from pine2ast.libraries.store import canonical, source_hash


def library(body, version=6, name="Lib"):
    return f'//@version={version}\nlibrary("{name}")\n{body}\n'


def root(body, version=6, imports="import qa/Lib/1 as lib"):
    return f'//@version={version}\nindicator("types")\n{imports}\n{body}\n'


def linked(body, usage, version=6):
    result = link_libraries(root(usage, version), LibraryStore.create({"qa/Lib/1": library(body, version)}))
    result.verify()
    return result


@pytest.mark.parametrize("version", [5, 6])
def test_udt_constructor_fields_arguments_returns_and_explicit_annotation(version):
    result = linked(
        "export type Point\n    int x=1\nexport move(Point p, int step=1)=>\n    p.x+=step\n    p",
        "lib.Point p=lib.Point.new(2)\nq=lib.move(p,step=3)\nplot(q.x)", version,
    )
    assert result.receipt()["profile"] == "same_version_reference_types_v4"
    parsed = parse_code(result.code)
    assert parsed.ok, parsed.diagnostics
    declarations = {d["name"]: d["linked_name"] for d in result.receipt()["declarations"]}
    assert set(declarations) == {"Point", "move"}
    assert declarations["Point"] + " p=" in result.code
    assert result.original_location(result.code.rindex(declarations["Point"]))["source"] == "<memory>"


@pytest.mark.parametrize("version", [5, 6])
def test_enum_export_member_parameter_return_and_udt_field(version):
    result = linked(
        'export enum Direction\n    up="Up"\n    down="Down"\nexport type Point\n    Direction direction=Direction.up\nexport echo(Direction d)=>d',
        "lib.Direction d=lib.echo(lib.Direction.down)\np=lib.Point.new(d)\nplot(p.direction==lib.Direction.down ? 1 : 0)", version,
    )
    parsed = parse_code(result.code)
    assert parsed.ok, parsed.diagnostics
    assert {d["name"] for d in result.receipt()["declarations"]} == {"Point", "Direction", "echo"}


@pytest.mark.parametrize("version", [5, 6])
def test_same_name_types_from_distinct_publishers_and_revisions_stay_distinct(version):
    body = "export type Point\n    int x=1\nexport read(Point p)=>p.x"
    sources = {ref: library(body, version) for ref in ("qa/Lib/1", "qb/Lib/1", "qa/Lib/2")}
    source = root("a=a.Point.new(1)\nb=b.Point.new(2)\nc=c.Point.new(3)\nplot(a.x+b.x+c.x)", version,
                  "import qa/Lib/1 as a\nimport qb/Lib/1 as b\nimport qa/Lib/2 as c")
    # Keep alias names separate from local variables (the language forbids alias shadowing).
    source = source.replace("a=a.Point", "pa=a.Point").replace("b=b.Point", "pb=b.Point").replace("c=c.Point", "pc=c.Point").replace("plot(a.x+b.x+c.x)", "plot(pa.x+pb.x+pc.x)")
    result = link_libraries(source, LibraryStore.create(sources))
    types = [d["linked_name"] for d in result.receipt()["declarations"] if d["name"] == "Point"]
    assert len(set(types)) == 3
    assert parse_code(result.code).ok
    result.verify()
    bad = link_libraries(root("p=b.Point.new(1)\nplot(a.read(p))", version,
                             "import qa/Lib/1 as a\nimport qb/Lib/1 as b"), LibraryStore.create(sources))
    assert not parse_code(bad.code).ok


@pytest.mark.parametrize("kind", ["array", "map"])
def test_collection_of_exported_udt_type_arguments_are_projected(kind):
    declaration = "array<Point>" if kind == "array" else "map<string,Point>"
    constructor = "array.new<lib.Point>()" if kind == "array" else "map.new<string,lib.Point>()"
    result = linked("export type Point\n    int x=1\nexport size(" + declaration + " xs)=>" + kind + ".size(xs)",
                    "xs=" + constructor + "\nplot(lib.size(xs))")
    assert parse_code(result.code).ok
    assert "<lib.Point>" not in result.code


def test_transitive_type_fields_and_parameters_close_over_exact_type_identity():
    sources = {
        "qa/Types/1": library("export enum Direction\n    up\n    down\nexport type Point\n    int x=1", name="Types"),
        "qa/Lib/1": library("import qa/Types/1 as t\nexport type Box\n    t.Point point\n    t.Direction direction=t.Direction.up\nexport read(t.Point p)=>p.x"),
    }
    result = link_libraries(root("p=t.Point.new(2)\nbox=lib.Box.new(p,t.Direction.down)\nplot(lib.read(box.point))", imports="import qa/Lib/1 as lib\nimport qa/Types/1 as t"), LibraryStore.create(sources))
    assert parse_code(result.code).ok
    assert set(result.dependency_hashes) == set(sources)
    assert result == link_libraries(root("p=t.Point.new(2)\nbox=lib.Box.new(p,t.Direction.down)\nplot(lib.read(box.point))", imports="import qa/Lib/1 as lib\nimport qa/Types/1 as t"), LibraryStore.create(dict(reversed(list(sources.items())))))
    result.verify()


@pytest.mark.parametrize("body,usage", [
    ("type Point\n    int x=1\nexport read(Point p)=>p.x", "plot(1)"),
    ("enum Direction\n    up\nexport echo(Direction d)=>d", "plot(1)"),
    ("type Point\n    int x=1\nexport make()=>Point.new(1)", "p=lib.make()\nplot(p.x)"),
    ("enum Direction\n    up\nexport make()=>Direction.up", "d=lib.make()\nplot(1)"),
    ("type Point\n    int x=1\nexport type Box\n    Point point", "plot(1)"),
    ("enum Direction\n    up\nexport type Box\n    Direction direction", "plot(1)"),
])
def test_private_types_cannot_escape_public_signatures_fields_or_returns(body, usage):
    with pytest.raises(LibraryError, match="PRIVATE"):
        linked(body, usage)


def test_private_udt_may_be_used_inside_scalar_export_without_being_exposed():
    result = linked("type Point\n    int x=1\nexport read(int n)=>\n    p=Point.new(n)\n    p.x", "plot(lib.read(4))")
    assert parse_code(result.code).ok


@pytest.mark.parametrize("declaration,returned", [
    ("type Private\n    int x=1", "Private.new()"),
    ("enum Hidden\n    a", "Hidden.a"),
])
def test_unused_public_return_cannot_hide_private_type(declaration, returned):
    with pytest.raises(LibraryError, match="PRIVATE"):
        linked(declaration + "\nexport leak()=>" + returned + "\nexport read(int n)=>n", "plot(lib.read(1))")


@pytest.mark.parametrize("usage", ["p=lib.Private.new(1)", "lib.Private p=na", "d=lib.Hidden.up"])
def test_private_types_and_enums_cannot_be_imported(usage):
    with pytest.raises(LibraryError, match="PRIVATE"):
        linked("type Private\n    int x=1\nenum Hidden\n    up\nexport read(int x)=>x", usage)


def test_reference_profile_is_monotonic_and_dependency_edits_invalidate_identity():
    sources = {
        "qa/Lib/1": library("export type Point\n    int x=1"),
        "qa/Array/1": library("export size(array<int> xs)=>array.size(xs)", name="Array"),
    }
    source = root("p=lib.Point.new(1)\nxs=array.new<int>()\nplot(a.size(xs))", imports="import qa/Lib/1 as lib\nimport qa/Array/1 as a")
    before = link_libraries(source, LibraryStore.create(sources))
    sources["qa/Lib/1"] = library("export type Point\n    int x=2")
    after = link_libraries(source, LibraryStore.create(sources))
    assert before.receipt()["profile"] == after.receipt()["profile"] == "same_version_reference_types_v4"
    assert before.receipt()["closure_hash"] != after.receipt()["closure_hash"]
    assert before.code != after.code
    receipt = before.receipt()
    receipt["declarations"][0]["linked_name"] += "corrupt"
    receipt["content_hash"] = source_hash(canonical({k: v for k, v in receipt.items() if k != "content_hash"}))
    with pytest.raises(LibraryError, match="PROJECTION"):
        replace(before, _receipt=canonical(receipt)).verify()
