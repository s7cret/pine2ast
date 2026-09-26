"""F2.10: a library identifier uses the library catalog, not the consumer catalog.

bid is a v6 variable and is absent from v5. A v5 library under a v6 consumer
must fail to link. close exists in both catalogs and stays linked.
"""

from __future__ import annotations

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.libraries import LibraryStore, link_libraries
from pine2ast.libraries.store import LibraryError


def _lib(version: int, expr: str) -> str:
    return f'//@version={version}\nlibrary("Lib")\n' "export flag() =>\n" f"    {expr}\n"


def _root(version: int) -> str:
    return (
        f'//@version={version}\nindicator("s2")\n' "import user/Lib/1 as lib\n" "plot(lib.flag())\n"
    )


def _link(consumer_version: int, library_version: int, expr: str):
    return link_libraries(
        _root(consumer_version),
        LibraryStore.create({"user/Lib/1": _lib(library_version, expr)}),
    )


def test_v6_consumer_v5_library_v6_only_identifier_is_rejected() -> None:
    with pytest.raises(LibraryError, match="unresolved library identifier: bid"):
        _link(6, 5, "bid")


def test_v5_same_version_library_v6_identifier_is_rejected() -> None:
    with pytest.raises(LibraryError, match="unresolved library identifier: bid"):
        _link(5, 5, "bid")


def test_v6_same_version_library_v6_identifier_is_admitted() -> None:
    linked = _link(6, 6, "bid")
    linked.verify()
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [
        (d.code, d.message) for d in parsed.diagnostics if "ERROR" in str(d.severity)
    ]


def test_v6_consumer_v5_library_shared_identifier_is_admitted() -> None:
    linked = _link(6, 5, "close")
    linked.verify()
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [
        (d.code, d.message) for d in parsed.diagnostics if "ERROR" in str(d.severity)
    ]
