"""F2.3: linked library ternary keeps origin evaluation policy.

Catalog authority is pine2ast/catalog_source/version_rules.json:
v5 ``ternary_evaluation=LAZY`` (``operator.ternary.lazy.v5``),
v6 ``ternary_evaluation=LAZY`` (``operator.ternary.lazy.v6``).
Same-script control: tests/stage5/test_pairwise_version_differentials.py.
This file is the mixed-import case: inlining a v5 body into a v6 consumer
must not stamp the consumer ternary rule.
"""

from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.libraries import LibraryStore, link_libraries


def _lib(version: int) -> str:
    return f'//@version={version}\nlibrary("Lib")\nexport flag() => true ? 1 : 0\n'


def _root(version: int) -> str:
    return (
        f'//@version={version}\nindicator("s2")\n' "import user/Lib/1 as lib\n" "plot(lib.flag())\n"
    )


def _linked_ternary_fact(consumer_version: int, library_version: int):
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
    facts = [
        row for row in parsed.semantic_model.semantic_facts.facts if row.kind == "ConditionalExpr"
    ]
    assert len(facts) == 1
    fact = facts[0]
    start = fact.span["start_offset"]
    origin = linked.original_locations([start])[0]
    assert origin is not None
    assert origin["source"] == "user/Lib/1"
    build_consumer_bundle(linked.code, linked_source=linked)
    return fact


def test_v6_consumer_v5_library_ternary_keeps_v5_rule():
    fact = _linked_ternary_fact(6, 5)
    assert "operator.ternary.lazy.v5" in fact.semantic_rule_ids
    assert "operator.ternary.lazy.v6" not in fact.semantic_rule_ids


def test_v6_same_version_library_ternary_keeps_v6_rule():
    fact = _linked_ternary_fact(6, 6)
    assert "operator.ternary.lazy.v6" in fact.semantic_rule_ids


def test_v5_same_version_library_ternary_keeps_v5_rule():
    fact = _linked_ternary_fact(5, 5)
    assert "operator.ternary.lazy.v5" in fact.semantic_rule_ids
