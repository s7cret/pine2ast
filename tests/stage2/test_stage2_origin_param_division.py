"""F2.2: mixed-import int division on parameters keeps origin operator rule.

Const-fold case is tests/stage2/test_stage2_origin_preserving_division.py.
This file covers ``export div(int a, int b) => a / b`` so the ``/`` is not a
const-int fold; catalog ``operator.division.vN`` must still follow the library
``//@version``, not the consumer.
"""

from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries


def _lib(version: int) -> str:
    return f"//@version={version}\n" 'library("Lib")\n' "export div(int a, int b) => a / b\n"


def _root(version: int) -> str:
    return (
        f"//@version={version}\n"
        'indicator("s2")\n'
        "import user/Lib/1 as lib\n"
        "plot(lib.div(5, 2))\n"
    )


def _linked_division_fact(consumer_version: int, library_version: int):
    linked = link_libraries(
        _root(consumer_version),
        LibraryStore.create({"user/Lib/1": _lib(library_version)}),
    )
    linked.verify()
    receipt = linked.receipt()
    assert receipt["pine_version"] == consumer_version
    assert receipt["sources"]["user/Lib/1"]["pine_version"] == library_version
    assert f"//@version={library_version}" in receipt["sources"]["user/Lib/1"]["raw_text"]
    parsed = parse_code(linked.code, ParseOptions(library_context=linked.qualifier_context()))
    assert parsed.ok, parsed.diagnostics
    facts = [row for row in parsed.semantic_model.semantic_facts.facts if row.kind == "BinaryExpr"]
    assert len(facts) == 1
    fact = facts[0]
    start = fact.span["start_offset"]
    origin = linked.original_locations([start])[0]
    assert origin is not None
    assert origin["source"] == "user/Lib/1"
    build_consumer_bundle(linked.code, linked_source=linked)
    return fact


def test_v6_consumer_v5_library_param_division_keeps_v5_operator():
    fact = _linked_division_fact(6, 5)
    assert "operator.division.v5" in fact.semantic_rule_ids
    assert "operator.division.v6" not in fact.semantic_rule_ids
    assert "operator.division.const_int.v6" not in fact.semantic_rule_ids


def test_v6_same_version_library_param_division_keeps_v6_operator():
    fact = _linked_division_fact(6, 6)
    assert "operator.division.v6" in fact.semantic_rule_ids
    assert "operator.division.v5" not in fact.semantic_rule_ids


def test_v5_same_version_library_param_division_keeps_v5_operator():
    fact = _linked_division_fact(5, 5)
    assert "operator.division.v5" in fact.semantic_rule_ids
