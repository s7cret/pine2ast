"""Stage 2.5 producer matrix: UDT/enum declarations, identities and fail-closed errors."""

from __future__ import annotations

import pytest

from pine2ast import parse_code
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries


def _script(body: str, version: int = 6) -> str:
    header = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{header}("s25")\n{body}\n'


def _library(body: str, version: int = 6, name: str = "Lib") -> str:
    return f'//@version={version}\nlibrary("{name}")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_udt_and_enum_declarations_parse(version):
    result = parse_code(
        _script(
            "enum Side\n    buy\n    sell\n"
            "type Point\n    int x=1\n    Side side=Side.buy\n"
            "p=Point.new()\nplot(p.x)\nplot(p.side==Side.buy)",
            version,
        )
    )
    assert result.ok, result.diagnostics


@pytest.mark.parametrize("version", range(1, 5))
def test_stage25_udt_enum_unavailable_before_v5(version):
    result = parse_code(_script("enum Side\n    buy\ntype Point\n    int x", version))
    assert not result.ok


@pytest.mark.parametrize(
    "body",
    [
        "enum A\n    x\nenum B\n    x\nplot(A.x==B.x)",
        "enum A\n    x\na=A.missing",
        "type P\n    int n\np=P.new()\np.missing:=1",
        "type P\n    int n\np=P.new(unknown=1)",
    ],
)
def test_stage25_unknown_members_and_foreign_enum_equality_fail_closed(body):
    result = parse_code(_script(body))
    assert not result.ok


def test_stage25_same_name_library_types_keep_distinct_linked_identities():
    sources = {
        "ownerA/Geom/1": _library("export type Point\n    int n=1\nexport enum Side\n    left", name="Geom"),
        "ownerB/Geom/1": _library("export type Point\n    int n=10\nexport enum Side\n    left", name="Geom"),
    }
    source = _script(
        "import ownerA/Geom/1 as a\nimport ownerB/Geom/1 as b\n"
        "p=a.Point.new()\nq=b.Point.new()\nplot(p.n)\nplot(q.n)"
    )
    linked = link_libraries(source, LibraryStore.create(sources))
    linked.verify()
    points = [row["linked_name"] for row in linked.receipt()["declarations"] if row["name"] == "Point"]
    assert len(set(points)) == 2
    assert parse_code(linked.code).ok


@pytest.mark.parametrize(
    "lib_body,usage",
    [
        ("enum Hidden\n    a\nexport read(int n)=>n", "d=lib.Hidden.a"),
        ("type Private\n    int x=1\nexport read(int n)=>n", "p=lib.Private.new()"),
        ("enum Hidden\n    a\nexport leak()=>Hidden.a", "plot(1)"),
        ("type Private\n    int x=1\nexport leak()=>Private.new()", "plot(1)"),
    ],
)
def test_stage25_private_udt_enum_cannot_be_exported_or_imported(lib_body, usage):
    with pytest.raises(LibraryError, match="PRIVATE"):
        link_libraries(
            _script(f"import qa/Lib/1 as lib\n{usage}"),
            LibraryStore.create({"qa/Lib/1": _library(lib_body)}),
        )


@pytest.mark.parametrize("version", [5, 6])
def test_stage25_nested_udt_enum_title_and_method_receiver_parse(version):
    result = parse_code(
        _script(
            'enum Side\n    buy="Buy"\n    sell="Sell"\n'
            "type Point\n    int x=0\n    Side side=Side.buy\n"
            "type Box\n    Point point\n"
            "method moved(Point self, int step=1)=>\n    self.x+=step\n    self\n"
            "p=Point.new()\nb=Box.new(p)\nplot(b.point.moved(2).x)\nplot(p.side==Side.buy)",
            version,
        )
    )
    assert result.ok, result.diagnostics


def test_stage25_foreign_library_udt_is_not_accepted_as_local_parameter():
    sources = {
        "ownerA/Geom/1": _library("export type Point\n    int n=1\nexport read(Point p)=>p.n", name="Geom"),
        "ownerB/Geom/1": _library("export type Point\n    int n=10", name="Geom"),
    }
    source = _script(
        "import ownerA/Geom/1 as a\nimport ownerB/Geom/1 as b\n"
        "p=b.Point.new()\nplot(a.read(p))"
    )
    linked = link_libraries(source, LibraryStore.create(sources))
    parsed = parse_code(linked.code)
    assert not parsed.ok


@pytest.mark.parametrize(
    "body",
    [
        'enum Side\n    buy=1',
        "type P\n    int n\np=P.new()\np.n:=\"x\"",
        "type P\n    int n\ntype Q\n    int n\np=P.new()\nq=Q.new()\np:=q",
        "enum Side\n    buy\nplot(Side.buy==1)",
    ],
)
def test_stage25_additional_invalid_udt_enum_forms_fail_closed(body):
    result = parse_code(_script(body))
    assert not result.ok
