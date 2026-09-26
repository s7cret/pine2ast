"""F2.9: a method call uses the library catalog, not the consumer catalog.

label.set_text_formatting exists in v6 and not in v5. A v5 library under a
v6 consumer must be rejected. A method present in both catalogs stays admitted.
"""

from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.libraries import LibraryStore, link_libraries


def _lib(version: int, call: str) -> str:
    return (
        f'//@version={version}\nlibrary("Lib")\n'
        "export flag() =>\n"
        '    id = label.new(bar_index, close, "x")\n'
        f"    {call}\n"
        "    close\n"
    )


def _root(version: int) -> str:
    return (
        f'//@version={version}\nindicator("s2")\n' "import user/Lib/1 as lib\n" "plot(lib.flag())\n"
    )


def _linked(consumer_version: int, library_version: int, call: str):
    linked = link_libraries(
        _root(consumer_version),
        LibraryStore.create({"user/Lib/1": _lib(library_version, call)}),
    )
    linked.verify()
    receipt = linked.receipt()
    assert receipt["pine_version"] == consumer_version
    assert receipt["sources"]["user/Lib/1"]["pine_version"] == library_version
    return linked


def _errors(parsed):
    return [d for d in parsed.diagnostics if "ERROR" in str(d.severity)]


def test_v6_consumer_v5_library_v6_only_method_is_rejected() -> None:
    linked = _linked(6, 5, "id.set_text_formatting(text.format_bold)")
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert not parsed.ok
    assert codes.UNKNOWN_FIELD in {d.code for d in _errors(parsed)}


def test_v6_same_version_library_v6_method_is_admitted() -> None:
    linked = _linked(6, 6, "id.set_text_formatting(text.format_bold)")
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]


def test_v5_same_version_library_v6_method_is_rejected() -> None:
    linked = _linked(5, 5, "id.set_text_formatting(text.format_bold)")
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert not parsed.ok
    assert codes.UNKNOWN_FIELD in {d.code for d in _errors(parsed)}


def test_v6_consumer_v5_library_shared_method_is_admitted() -> None:
    linked = _linked(6, 5, 'id.set_text("x")')
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]
