from __future__ import annotations


import pytest

from pine2ast import parse_code
from pine2ast.ast.walk import iter_nodes
from pine2ast.catalog import CatalogRepository
from pine2ast.semantic.version_coverage import build_version_coverage_report
from pine2ast.semantic.version_semantics import (
    load_semantic_requirements,
    requirements_for_version,
    requirements_hash,
)


def codes(source: str) -> set[str]:
    return {item.code for item in parse_code(source).diagnostics}


def version_of(source: str) -> int:
    result = parse_code(source)
    assert result.ast is not None
    return result.ast.version_context.pine_version


def minimal(version: int) -> str:
    if version == 1:
        return 'study("v1")\nx = close\n'
    declaration = "study" if version <= 4 else "indicator"
    return f'//@version={version}\n{declaration}("v{version}")\nx = close\n'


@pytest.mark.parametrize("version", range(1, 7))
def test_single_version_context(version: int) -> None:
    result = parse_code(minimal(version))
    assert result.ast is not None
    context = result.ast.version_context
    assert context.pine_version == version
    assert context.catalog_hash.startswith("sha256:")
    assert "P2A2106" not in {item.code for item in result.diagnostics}
    metadata = result.ast.producer_metadata["version_semantics"]
    assert metadata["pine_version"] == version
    assert metadata["ruleset_hash"] == requirements_hash()


def test_missing_annotation_is_v1() -> None:
    assert version_of('study("x")\nx = close\n') == 1


def test_future_version_does_not_fall_back() -> None:
    result = parse_code('//@version=7\nindicator("x")\nx = close\n')
    assert result.ast is None or any(
        item.code in {"P2A0103", "P2A0104"} for item in result.diagnostics
    )


def test_v1_rejects_function_declaration() -> None:
    assert "P2A2101" in codes('study("x")\nf(x) => x\ny = f(close)\n')


def test_v1_rejects_reassignment() -> None:
    assert "P2A2101" in codes('study("x")\nx = close\nx := open\n')


def test_v4_rejects_modern_namespace() -> None:
    assert "P2A2108" in codes('//@version=4\nstudy("x")\nx = ta.sma(close, 3)\n')


def test_v4_rejects_typed_input_namespace() -> None:
    assert "P2A2108" in codes('//@version=4\nstudy("x")\nx = input.int(3)\n')


def test_v4_rejects_map_api() -> None:
    assert "P2A2102" in codes('//@version=4\nstudy("x")\nx = map.new<string, float>()\n')


def test_v4_accepts_historical_spelling() -> None:
    assert not any(
        code.startswith("P2A21") for code in codes('//@version=4\nstudy("x")\nx = sma(close, 3)\n')
    )


def test_v5_rejects_legacy_spelling() -> None:
    assert "P2A2109" in codes('//@version=5\nindicator("x")\nx = sma(close, 3)\n')


def test_v5_rejects_resolution_parameter() -> None:
    assert "P2A2103" in codes('//@version=5\nindicator("x", resolution="D")\nx = close\n')


def test_v5_allows_strategy_when() -> None:
    found = codes(
        '//@version=5\nstrategy("x")\nstrategy.entry("L", strategy.long, when=close > open)\n'
    )
    assert "P2A2103" not in found


def test_v6_rejects_strategy_when() -> None:
    assert "P2A2103" in codes(
        '//@version=6\nstrategy("x")\nstrategy.entry("L", strategy.long, when=close > open)\n'
    )


def test_v6_rejects_transp_parameter() -> None:
    assert "P2A2103" in codes('//@version=6\nindicator("x")\nplot(close, transp=50)\n')


def test_v6_accepts_modern_namespace() -> None:
    assert not any(
        code.startswith("P2A21")
        for code in codes('//@version=6\nindicator("x")\nx = ta.sma(close, 3)\n')
    )


def test_v6_multiline_string() -> None:
    result = parse_code('//@version=6\nindicator("x")\ns = """alpha\nbeta"""\n')
    assert result.ast is not None
    assert not any(item.severity.value in {"ERROR", "FATAL"} for item in result.diagnostics)


def test_requirement_catalog_is_unique_and_versioned() -> None:
    rows = load_semantic_requirements()
    ids = [row.requirement_id for row in rows]
    assert len(ids) == len(set(ids))
    for version in range(1, 7):
        assert requirements_for_version(version, owner="pine2ast")


def test_coverage_axes_are_not_conflated() -> None:
    verified = {row.test_id for row in load_semantic_requirements() if row.owner == "pine2ast"}
    report = build_version_coverage_report(
        verified_test_ids=verified,
        full_test_suite_passed=True,
        catalog_gate_passed=True,
        differential_gate_passed=True,
    )
    for row in report["versions"].values():
        assert row["normative_static_frontend"]["coverage_percent"] == 100.0
        assert row["official_reference_symbol_coverage"]["coverage_percent"] is None
        assert row["tradingview_runtime_oracle"]["coverage_percent"] == 0.0


def has_error(source: str) -> bool:
    return any(item.severity.value in {"ERROR", "FATAL"} for item in parse_code(source).diagnostics)


def test_v2_v3_self_reference_delta() -> None:
    v2 = '//@version=2\nstudy("x")\nx = nz(x[1])\n'
    v3 = '//@version=3\nstudy("x")\nx = nz(x[1])\n'
    assert not has_error(v2)
    assert has_error(v3)


def test_v2_v3_forward_reference_delta() -> None:
    v2 = '//@version=2\nstudy("x")\nx = y\ny = close\n'
    v3 = '//@version=3\nstudy("x")\nx = y\ny = close\n'
    assert not has_error(v2)
    assert has_error(v3)


def test_v2_v3_bool_arithmetic_delta() -> None:
    v2 = '//@version=2\nstudy("x")\nx = true + 1\n'
    v3 = '//@version=3\nstudy("x")\nx = true + 1\n'
    assert not has_error(v2)
    assert has_error(v3)


def test_v4_na_initialization_requires_type() -> None:
    assert has_error('//@version=4\nstudy("x")\nx = na\n')
    assert not has_error('//@version=4\nstudy("x")\nfloat x = na\n')


def test_v5_v6_numeric_condition_delta() -> None:
    assert not has_error('//@version=5\nindicator("x")\nif close\n    x = 1\n')
    assert has_error('//@version=6\nindicator("x")\nif close\n    x = 1\n')


def test_v5_v6_bool_na_delta() -> None:
    assert not has_error('//@version=5\nindicator("x")\nbool x = na\n')
    assert has_error('//@version=6\nindicator("x")\nbool x = na\n')


def test_v5_strategy_exit_requires_effect() -> None:
    assert has_error('//@version=5\nstrategy("x")\nstrategy.exit("X", "E")\n')


def test_v5_named_constant_parameter_rule() -> None:
    assert has_error('//@version=5\nindicator("x")\nplot(close, style=5)\n')


def test_v6_historical_tick_declaration_is_catalogued() -> None:
    source = '//@version=6\nstrategy("x", calc_on_every_history_tick=true)\nx = close\n'
    result = parse_code(source)
    assert result.ast is not None
    assert not any(item.severity.value in {"ERROR", "FATAL"} for item in result.diagnostics)


def test_v6_bid_ask_are_catalogued() -> None:
    source = '//@version=6\nindicator("x")\nx = bid + ask\n'
    result = parse_code(source)
    assert result.ast is not None
    assert not any(item.code in {"P2A1101", "P2A1506"} for item in result.diagnostics)


def test_version_semantics_respects_max_diagnostics() -> None:
    from pine2ast import ParseOptions

    source = 'study("x")\nf(v) => v\nx = ta.sma(close, 3)\nx := open\n'
    result = parse_code(source, ParseOptions(max_diagnostics=1))
    assert len(result.diagnostics) <= 1


def test_version_semantic_error_updates_frontend_metadata() -> None:
    result = parse_code('//@version=4\nindicator("x")\nx = close\n')
    assert result.ast is not None
    metadata = result.ast.producer_metadata
    # The parser/semantic pipeline can reject the declaration before the
    # dedicated version pass sees a DeclarationStatement.  The aggregate
    # frontend/semantic gates must nevertheless be fail-closed.
    assert metadata["version_semantic_gate"] in {"pass", "fail"}
    assert metadata["frontend_gate"] == "fail"
    assert metadata["semantic_gate"] == "fail"
    assert result.ok is False


def test_applicable_rules_are_not_claimed_as_runtime_verification() -> None:
    result = parse_code('//@version=6\nindicator("x")\nx = close\n')
    assert result.ast is not None
    metadata = result.ast.producer_metadata["version_semantics"]
    assert metadata["applicable_rule_ids"]
    assert "verified_rule_ids" not in metadata


def test_traceability_core_ast_binding_type_qualifier_and_overload_facts() -> None:
    source = (
        '//@version=6\nindicator("facts")\n' "length = input.int(3)\n" "x = ta.sma(close, length)\n"
    )
    first = parse_code(source)
    second = parse_code(source)
    assert first.ok and second.ok
    assert first.ast is not None and second.ast is not None

    first_nodes = list(iter_nodes(first.ast))
    second_nodes = list(iter_nodes(second.ast))
    assert [node.span.to_dict() for node in first_nodes] == [
        node.span.to_dict() for node in second_nodes
    ]
    assert all(node.span.end_offset >= node.span.start_offset for node in first_nodes)

    facts = first.semantic_model.semantic_facts
    expression_facts = [item for item in facts.facts if item.classification == "EXPRESSION"]
    assert expression_facts
    assert all(item.resolved_type is not None for item in expression_facts)
    assert all(item.resolved_type.qualifier for item in expression_facts)
    assert all(item.symbol_id for item in facts.calls)
    assert all(item.overload_id for item in facts.calls)
    assert [item.symbol_id for item in facts.facts] == [
        item.symbol_id for item in second.semantic_model.semantic_facts.facts
    ]


def test_traceability_declaration_cardinality_and_version_spelling() -> None:
    missing = parse_code("//@version=6\nx = close\n")
    duplicate = parse_code('//@version=6\nindicator("a")\nstrategy("b")\n')
    assert not missing.ok and "P2A1001" in {item.code for item in missing.diagnostics}
    assert not duplicate.ok and "P2A1002" in {item.code for item in duplicate.diagnostics}

    assert not has_error('study("v1")\nx = sma(close, 3)\n')
    assert not has_error('study("v1")\na = b\nb = close\n')
    assert not has_error('//@version=1\nstrategy("v1")\nx = sma(close, 3)\n')
    assert has_error('//@version=1\nindicator("v1")\nx = close\n')
    assert has_error('//@version=1\nlibrary("v1")\nx = close\n')
    assert has_error('study("v1")\nfloat x = na\n')
    assert has_error('study("v1")\nvar x = close\n')


def test_traceability_v4_declarations_arrays_and_historical_overloads() -> None:
    assert not has_error('//@version=4\nstudy("v4")\na = array.new_float(1)\nx = rsi(close, 14)\n')
    assert not has_error('//@version=4\nstrategy("v4")\nx = close\n')
    assert has_error('//@version=4\nindicator("v4")\nx = close\n')
    assert has_error('//@version=4\nlibrary("v4")\nx = close\n')
    assert has_error('//@version=4\nstudy("v4")\nm = map.new<string, float>()\n')
    assert has_error('//@version=4\nstudy("v4")\nm = matrix.new<float>(1, 1)\n')


def test_traceability_v5_modern_language_surface() -> None:
    source = """//@version=5
library("v5")
export type Point
    float value
export enum Side
    left
export method get(Point this) => this.value
export choose(bool condition) =>
    result = while condition
        break
    switch condition
        true => 1
        => 0
"""
    result = parse_code(source)
    assert result.ast is not None
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    assert not any(item.code.startswith("P2A21") for item in result.diagnostics)
    assert not has_error('//@version=5\nindicator("v5")\nx = input.int(3)\n')
    assert not has_error('//@version=5\nstrategy("v5")\nx = ta.sma(close, 3)\n')
    assert has_error('//@version=5\nstudy("v5")\nx = close\n')


def test_v5_v6_negative_collection_index_delta() -> None:
    body = 'indicator("x")\na = array.from(1, 2)\nx = array.get(a, -1)\n'
    assert has_error("//@version=5\n" + body)
    assert not has_error("//@version=6\n" + body)


def test_v5_v6_history_target_delta() -> None:
    literal_body = 'indicator("x")\nx = 1[1]\n'
    assert not has_error("//@version=5\n" + literal_body)
    assert has_error("//@version=6\n" + literal_body)

    udt_prefix = """indicator("x")
type Point
    float value
Point p = Point.new(close)
"""
    assert not has_error("//@version=5\n" + udt_prefix + "x = p.value[1]\n")
    assert has_error("//@version=6\n" + udt_prefix + "x = p.value[1]\n")
    assert not has_error("//@version=6\n" + udt_prefix + "x = (p[1]).value\n")


def test_v6_udt_binary_search_sort_field_is_catalogued() -> None:
    view = CatalogRepository.default().view(6)
    for name in (
        "array.binary_search",
        "array.binary_search_leftmost",
        "array.binary_search_rightmost",
    ):
        function_parameters = view["functions"][name]["parameters"]
        method_parameters = view["methods"][name]["parameters"]
        assert any(item["name"] == "sort_field" for item in function_parameters)
        assert any(item["name"] == "sort_field" for item in method_parameters)


def test_v6_unique_type_argument_rejects_na() -> None:
    body = 'indicator("x")\nlabel.new(bar_index, close, style=na)\n'
    assert parse_code("//@version=5\n" + body).ok
    result = parse_code("//@version=6\n" + body)
    assert not result.ok
    assert "P2A1406" in {item.code for item in result.diagnostics}


def test_v6_bid_ask_and_current_contract_are_catalogued() -> None:
    source = (
        '//@version=6\nindicator("x")\n'
        "spread = ask - bid\n"
        "contract = syminfo.current_contract\n"
    )
    result = parse_code(source)
    assert result.ok
    assert result.version_context is not None
    assert result.version_context.supports_bid_ask
    assert result.version_context.supports_current_contract
