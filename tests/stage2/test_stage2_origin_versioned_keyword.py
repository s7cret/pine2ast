"""F2.11: a library identifier keeps the library keyword set.

once is a keyword in Pine v6 and an identifier in v5. A v5 library that
assigns once must still link under a v6 consumer. A v6 library must still
treat once as the statement keyword.
"""

from __future__ import annotations

import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.libraries import LibraryStore, link_libraries
from pine2ast.libraries.store import LibraryError


def _lib(version: int, body: str) -> str:
    return f'//@version={version}\nlibrary("Lib")\n{body}\n'


def _root(version: int) -> str:
    return (
        f'//@version={version}\nindicator("s2")\n' "import user/Lib/1 as lib\n" "plot(lib.flag())\n"
    )


def _parsed(consumer_version: int, library_version: int, body: str):
    linked = link_libraries(
        _root(consumer_version),
        LibraryStore.create({"user/Lib/1": _lib(library_version, body)}),
    )
    linked.verify()
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    return linked, parsed


def _errors(parsed):
    return [d for d in parsed.diagnostics if "ERROR" in str(d.severity)]


def test_v6_consumer_v5_library_once_identifier_is_admitted() -> None:
    linked, parsed = _parsed(
        6,
        5,
        "export flag() =>\n    once = 1\n    once",
    )
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5


def test_v5_same_version_library_once_identifier_is_admitted() -> None:
    _linked, parsed = _parsed(
        5,
        5,
        "export flag() =>\n    once = 1\n    once",
    )
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]


def test_v6_library_once_assignment_is_rejected() -> None:
    with pytest.raises(LibraryError):
        _parsed(
            6,
            6,
            "export flag() =>\n    once = 1\n    once",
        )


def test_v6_library_once_statement_is_admitted() -> None:
    _linked, parsed = _parsed(
        6,
        6,
        "export flag() =>\n    var int n = 0\n    once\n        n += 1\n    n",
    )
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]
