"""F2.8: a builtin call uses the library catalog, not the consumer catalog.

ta.rci is in the v6 catalog and absent from v5. A v5 library under a v6
consumer must be rejected. A builtin present in both catalogs stays admitted.
"""

from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries


def _lib(version: int, body: str) -> str:
    return f'//@version={version}\nlibrary("Lib")\nexport flag() =>\n{body}\n'


def _root(version: int) -> str:
    return (
        f'//@version={version}\nindicator("s2")\n' "import user/Lib/1 as lib\n" "plot(lib.flag())\n"
    )


def _linked(consumer_version: int, library_version: int, body: str):
    linked = link_libraries(
        _root(consumer_version),
        LibraryStore.create({"user/Lib/1": _lib(library_version, body)}),
    )
    linked.verify()
    receipt = linked.receipt()
    assert receipt["pine_version"] == consumer_version
    assert receipt["sources"]["user/Lib/1"]["pine_version"] == library_version
    return linked


def _errors(parsed):
    return [d for d in parsed.diagnostics if "ERROR" in str(d.severity)]


def test_v6_consumer_v5_library_v6_only_builtin_is_rejected() -> None:
    linked = _linked(6, 5, "    ta.rci(close, 3)")
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert not parsed.ok
    assert codes.UNKNOWN_CALL in {d.code for d in _errors(parsed)}
    assert any("Pine v5" in d.message for d in _errors(parsed))
    try:
        build_consumer_bundle(linked.code, linked_source=linked)
    except ConsumerBundleError:
        return
    raise AssertionError("v5 library must not admit a v6-only builtin")


def test_v6_same_version_library_v6_builtin_is_admitted() -> None:
    linked = _linked(6, 6, "    ta.rci(close, 3)")
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]
    assert build_consumer_bundle(linked.code, linked_source=linked)["content_hash"]


def test_v5_same_version_library_v6_builtin_is_rejected() -> None:
    linked = _linked(5, 5, "    ta.rci(close, 3)")
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert not parsed.ok
    assert codes.UNKNOWN_CALL in {d.code for d in _errors(parsed)}


def test_v6_consumer_v5_library_shared_builtin_is_admitted() -> None:
    linked = _linked(6, 5, "    ta.sma(close, 3)")
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]
    assert build_consumer_bundle(linked.code, linked_source=linked)["content_hash"]
