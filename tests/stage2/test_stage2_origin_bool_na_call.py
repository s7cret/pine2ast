"""F2.3: a v5 library call that passes na to a bool parameter stays admitted.

Catalog: v5 bool_allows_na=true, v6 false. Declaration form is
tests/stage2/test_stage2_origin_bool_na.py. This file is the call gate:
SignatureResolver must read the argument span's origin, not the consumer.
"""

from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries
from pine2ast.libraries.store import LibraryError


def _lib(version: int) -> str:
    return (
        f'//@version={version}\nlibrary("Lib")\n'
        "f(bool x) =>\n"
        "    x ? 1 : 0\n"
        "export flag() =>\n"
        "    f(na)\n"
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
    assert f"//@version={library_version}" in receipt["sources"]["user/Lib/1"]["raw_text"]
    return linked


def test_v6_consumer_v5_library_bool_na_call_is_admitted() -> None:
    linked = _linked(6, 5)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    assert build_consumer_bundle(linked.code, linked_source=linked)["content_hash"]


def test_v6_same_version_library_bool_na_call_is_rejected() -> None:
    linked = _linked(6, 6)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert not parsed.ok
    assert codes.BOOL_CANNOT_BE_NA in {d.code for d in parsed.diagnostics}
    try:
        build_consumer_bundle(linked.code, linked_source=linked)
    except ConsumerBundleError:
        return
    raise AssertionError("v6 library bool na call must fail consumer-bundle admission")


def test_v5_same_version_library_bool_na_call_is_admitted() -> None:
    linked = _linked(5, 5)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    assert build_consumer_bundle(linked.code, linked_source=linked)["content_hash"]


def _method_lib(version: int) -> str:
    return (
        f'//@version={version}\nlibrary("Lib")\n'
        "method m(bool src, bool x) =>\n"
        "    x ? 1 : 0\n"
        "export flag() =>\n"
        "    true.m(na)\n"
    )


def test_v6_consumer_v5_library_bool_na_method_call_is_admitted() -> None:
    linked = link_libraries(
        _root(6),
        LibraryStore.create({"user/Lib/1": _method_lib(5)}),
    )
    linked.verify()
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]


def test_v6_same_version_library_bool_na_method_call_is_rejected() -> None:
    try:
        link_libraries(
            _root(6),
            LibraryStore.create({"user/Lib/1": _method_lib(6)}),
        )
    except LibraryError as exc:
        assert "cannot be na" in str(exc)
        return
    raise AssertionError("v6 library bool na method call must fail binding")
