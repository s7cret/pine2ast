"""Stage 2.8 producer matrix: exact library locks, identities and fail-closed lookup."""

from __future__ import annotations

import pytest

from pine2ast import parse_code
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries
from pine2ast.libraries.store import source_hash


def _lib(body: str, version: int = 6, name: str = "Lib") -> str:
    return f'//@version={version}\nlibrary("{name}")\n{body}\n'


def _root(body: str, imports: str, version: int = 6) -> str:
    return f'//@version={version}\nindicator("s28")\n{imports}\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
def test_stage28_exact_revision_lock_and_source_checksum(version):
    sources = {"user/Lib/1": _lib("export add(int x)=>x+1", version=version)}
    linked = link_libraries(
        _root("plot(lib.add(1))", "import user/Lib/1 as lib", version),
        LibraryStore.create(sources),
    )
    linked.verify()
    assert linked.dependency_hashes == {"user/Lib/1": source_hash(sources["user/Lib/1"])}
    receipt = linked.receipt()
    assert receipt["pine_version"] == version
    assert "user/Lib/1" in receipt["dependencies"]
    loc = linked.original_location(
        linked.code.rindex(linked.receipt()["declarations"][0]["linked_name"])
    )
    assert loc["source"] in {"<memory>", "user/Lib/1"}


def test_stage28_missing_revision_is_not_replaced_by_another_version():
    sources = {"user/Lib/2": _lib("export add(int x)=>x+1")}
    with pytest.raises(LibraryError):
        link_libraries(
            _root("plot(lib.add(1))", "import user/Lib/1 as lib"),
            LibraryStore.create(sources),
        )


def test_stage28_missing_library_is_not_replaced_by_similar_name():
    sources = {"user/LibX/1": _lib("export add(int x)=>x+1", name="LibX")}
    with pytest.raises(LibraryError):
        link_libraries(
            _root("plot(lib.add(1))", "import user/Lib/1 as lib"),
            LibraryStore.create(sources),
        )


def test_stage28_latest_token_is_rejected():
    with pytest.raises(LibraryError):
        link_libraries(
            _root("plot(lib.add(1))", "import user/Lib/latest as lib"),
            LibraryStore.create({"user/Lib/1": _lib("export add(int x)=>x+1")}),
        )


def test_stage28_dependency_change_changes_hashes_and_projection():
    src = _root("plot(lib.add(1))", "import user/Lib/1 as lib")
    first = link_libraries(src, LibraryStore.create({"user/Lib/1": _lib("export add(int x)=>x+1")}))
    second = link_libraries(
        src, LibraryStore.create({"user/Lib/1": _lib("export add(int x)=>x+2")})
    )
    first.verify()
    second.verify()
    assert first.dependency_hashes != second.dependency_hashes
    assert first.receipt()["closure_hash"] != second.receipt()["closure_hash"]
    assert first.code != second.code


def test_stage28_transitive_diamond_is_deterministic():
    sources = {
        "user/Core/1": _lib("export base(int x)=>x", name="Core"),
        "user/Left/1": _lib(
            "import user/Core/1 as core\nexport wrap(int x)=>core.base(x)+1", name="Left"
        ),
        "user/Right/1": _lib(
            "import user/Core/1 as core\nexport wrap(int x)=>core.base(x)+2", name="Right"
        ),
    }
    root = _root(
        "plot(left.wrap(1)+right.wrap(1))",
        "import user/Left/1 as left\nimport user/Right/1 as right",
    )
    a = link_libraries(root, LibraryStore.create(sources))
    b = link_libraries(root, LibraryStore.create(dict(reversed(list(sources.items())))))
    a.verify()
    b.verify()
    assert a.dependency_hashes == b.dependency_hashes
    assert a.receipt()["closure_hash"] == b.receipt()["closure_hash"]
    assert set(a.dependency_hashes) == set(sources)


def test_stage28_cycle_is_rejected():
    sources = {
        "user/A/1": _lib("import user/B/1 as b\nexport f(int x)=>b.g(x)", name="A"),
        "user/B/1": _lib("import user/A/1 as a\nexport g(int x)=>a.f(x)", name="B"),
    }
    with pytest.raises(LibraryError):
        link_libraries(_root("plot(a.f(1))", "import user/A/1 as a"), LibraryStore.create(sources))


@pytest.mark.parametrize(
    "lib_body,usage",
    [
        ("secret(int x)=>x\nexport pub(int x)=>x", "plot(lib.secret(1))"),
        ("enum Hidden\n    a\nexport pub(int x)=>x", "plot(lib.Hidden.a==lib.Hidden.a ? 1 : 0)"),
    ],
)
def test_stage28_private_symbols_are_not_imported(lib_body, usage):
    with pytest.raises(LibraryError):
        link_libraries(
            _root(usage, "import user/Lib/1 as lib"),
            LibraryStore.create({"user/Lib/1": _lib(lib_body)}),
        )


def test_stage28_same_library_name_two_owners_stay_distinct():
    sources = {
        "ownerA/Util/1": _lib("export n()=>1", name="Util"),
        "ownerB/Util/1": _lib("export n()=>10", name="Util"),
    }
    linked = link_libraries(
        _root("plot(a.n()+b.n())", "import ownerA/Util/1 as a\nimport ownerB/Util/1 as b"),
        LibraryStore.create(sources),
    )
    linked.verify()
    names = [row["linked_name"] for row in linked.receipt()["declarations"] if row["name"] == "n"]
    assert len(set(names)) == 2
    assert parse_code(linked.code).ok


def test_stage28_error_coordinates_point_at_original_library_source():
    sources = {"user/Lib/1": _lib("export add(int x)=>x+1")}
    linked = link_libraries(
        _root("plot(lib.add(1))", "import user/Lib/1 as lib"),
        LibraryStore.create(sources),
    )
    decl = next(row for row in linked.receipt()["declarations"] if row["name"] == "add")
    loc = linked.original_location(linked.code.index(decl["linked_name"]))
    assert loc["source"] == "user/Lib/1"
    assert loc["line"] >= 3
