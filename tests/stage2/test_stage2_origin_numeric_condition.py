"""F2.3: linked library conditions keep origin numeric-condition policy.

Catalog authority is pine2ast/catalog_source/version_rules.json:
v5 ``numeric_condition_allowed=true`` (``if 1`` is admitted),
v6 ``numeric_condition_allowed=false`` (``if 1`` is P2A1201).
Same-script control: tests/test_stage22_bool_na_history.py and
tests/stage3/test_version_differentials.py. This file is the mixed-import
case: inlining a v5 body into a v6 consumer must not apply v6.
"""

from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries


def _lib(version: int) -> str:
    return (
        f'//@version={version}\nlibrary("Lib")\n'
        "export flag() =>\n"
        "    if 1\n"
        "        1\n"
        "    else\n"
        "        0\n"
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


def test_v6_consumer_v5_library_numeric_if_is_admitted() -> None:
    linked = _linked(6, 5)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    assert build_consumer_bundle(linked.code, linked_source=linked)["content_hash"]


def test_v6_same_version_library_numeric_if_is_rejected() -> None:
    linked = _linked(6, 6)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert not parsed.ok
    assert codes.NON_BOOL_CONDITION in {d.code for d in parsed.diagnostics}
    try:
        build_consumer_bundle(linked.code, linked_source=linked)
    except ConsumerBundleError:
        return
    raise AssertionError("v6 library numeric if must fail consumer-bundle admission")


def test_v5_same_version_library_numeric_if_is_admitted() -> None:
    linked = _linked(5, 5)
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    assert build_consumer_bundle(linked.code, linked_source=linked)["content_hash"]
