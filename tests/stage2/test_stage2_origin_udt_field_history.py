"""F2.7: UDT field history follows the library origin, not the consumer.

Pine v5 admits p.value[1]. Pine v6 rejects it and wants (p[1]).value.
A v5 library under a v6 consumer must keep the v5 admission.
"""

from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries


def _lib(version: int) -> str:
    return (
        f'//@version={version}\nlibrary("Lib")\n'
        "type Point\n"
        "    float value\n"
        "export flag() =>\n"
        "    Point p = Point.new(close)\n"
        "    p.value[1]\n"
    )


def _root(version: int) -> str:
    return (
        f'//@version={version}\nindicator("s2")\n' "import user/Lib/1 as lib\n" "plot(lib.flag())\n"
    )


def _linked(consumer_version: int, library_version: int):
    linked = link_libraries(
        _root(consumer_version),
        LibraryStore.create({"user/Lib/1": _lib(library_version)}),
    )
    linked.verify()
    receipt = linked.receipt()
    assert receipt["pine_version"] == consumer_version
    assert receipt["sources"]["user/Lib/1"]["pine_version"] == library_version
    return linked


def _errors(parsed):
    return [d for d in parsed.diagnostics if "ERROR" in str(d.severity)]


def test_v6_consumer_v5_library_udt_field_history_is_admitted() -> None:
    linked = _linked(6, 5)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]
    assert codes.HISTORY_ON_UDT_FIELD not in {d.code for d in _errors(parsed)}
    assert build_consumer_bundle(linked.code, linked_source=linked)["content_hash"]


def test_v6_same_version_library_udt_field_history_is_rejected() -> None:
    linked = _linked(6, 6)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert not parsed.ok
    assert codes.HISTORY_ON_UDT_FIELD in {d.code for d in _errors(parsed)}
    try:
        build_consumer_bundle(linked.code, linked_source=linked)
    except ConsumerBundleError:
        return
    raise AssertionError("v6 library UDT field history must fail consumer-bundle admission")


def test_v5_same_version_library_udt_field_history_is_admitted() -> None:
    linked = _linked(5, 5)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in _errors(parsed)]
    assert build_consumer_bundle(linked.code, linked_source=linked)["content_hash"]
