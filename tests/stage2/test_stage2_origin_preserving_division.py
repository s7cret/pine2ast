"""F2.2: linked library expressions keep origin const-int division.

Catalog authority is pine2ast/catalog_source/version_rules.json:
v5 ``const_int_division=TRUNCATE`` (5/2 -> int 2), v6 ``FRACTIONAL`` (5/2 -> 2.5).
Same-script control: tests/test_constant_round_binding.py. This file is the
mixed-import case: inlining a v5 body into a v6 consumer must not apply v6.
"""

from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries


def _lib(version: int) -> str:
    return f'//@version={version}\nlibrary("Lib")\nexport div() => 5/2\n'


def _root(version: int) -> str:
    return f'//@version={version}\nindicator("s2")\nimport user/Lib/1 as lib\nplot(lib.div())\n'


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


def test_v6_consumer_v5_library_const_int_division_truncates():
    fact = _linked_division_fact(6, 5)
    assert fact.const_value == 2
    assert type(fact.const_value) is int
    assert fact.resolved_type.base == "int"
    assert "operator.division.const_int.v5" in fact.semantic_rule_ids


def test_v6_same_version_library_const_int_division_is_fractional():
    fact = _linked_division_fact(6, 6)
    assert fact.const_value == 2.5
    assert type(fact.const_value) is float
    assert fact.resolved_type.base == "float"
    assert "operator.division.const_int.v6" in fact.semantic_rule_ids


def test_v5_same_version_library_const_int_division_truncates():
    fact = _linked_division_fact(5, 5)
    assert fact.const_value == 2
    assert type(fact.const_value) is int
    assert fact.resolved_type.base == "int"
    assert "operator.division.const_int.v5" in fact.semantic_rule_ids
