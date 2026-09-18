"""IMPORT-02: allowed consumer/library Pine version combinations."""

from __future__ import annotations

import pytest

from pine2ast.libraries import LibraryError, LibraryStore, link_libraries
from pine2ast.libraries.import_version_matrix import decide_import_versions


def _lib(body: str, version: int, name: str = "Lib") -> str:
    return f'//@version={version}\nlibrary("{name}")\n{body}\n'


def _root(version: int, imports: str = "import user/Lib/1 as lib") -> str:
    header = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{header}("s2")\n{imports}\nplot(lib.add(1))\n'


@pytest.mark.parametrize("version", [5, 6])
def test_stage2_same_version_consumer_and_library_link(version):
    linked = link_libraries(
        _root(version),
        LibraryStore.create({"user/Lib/1": _lib("export add(int x)=>x+1", version)}),
    )
    linked.verify()
    receipt = linked.receipt()
    assert receipt["sources"]["user/Lib/1"]["pine_version"] == version
    assert receipt["pine_version"] == version


def test_stage2_v6_consumer_may_import_v5_library():
    linked = link_libraries(
        _root(6),
        LibraryStore.create({"user/Lib/1": _lib("export add(int x)=>x+1", 5)}),
    )
    linked.verify()
    receipt = linked.receipt()
    assert receipt["pine_version"] == 6
    assert receipt["sources"]["user/Lib/1"]["pine_version"] == 5
    assert "//@version=5" in receipt["sources"]["user/Lib/1"]["raw_text"]


def test_stage2_v5_consumer_cannot_import_v6_library():
    with pytest.raises(LibraryError, match="VERSION"):
        link_libraries(
            _root(5),
            LibraryStore.create({"user/Lib/1": _lib("export add(int x)=>x+1", 6)}),
        )


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_stage2_pre_v5_consumer_cannot_import_libraries(version):
    with pytest.raises(LibraryError):
        link_libraries(
            _root(version),
            LibraryStore.create({"user/Lib/1": _lib("export add(int x)=>x+1", 5)}),
        )


def test_import_version_matrix_covers_all_pairs():
    allowed = {
        (5, 5),
        (6, 6),
        (6, 5),
    }
    for consumer in range(1, 7):
        for library in range(1, 7):
            decision, reason = decide_import_versions(consumer, library)
            expect = "allowed" if (consumer, library) in allowed else "rejected_by_language"
            assert decision == expect, (consumer, library, reason)
            assert reason
