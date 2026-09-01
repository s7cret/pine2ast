from pine2ast import ParseOptions, parse_code

SOURCE_NAME = "synthetic_v6_semantic_acceptance.pine"
SOURCE = """//@version=6
strategy("Synthetic semantic acceptance", overlay=true)

f_synthetic(float _src, int _length, int _detection) =>
    ta.highest(_src, _length) - ta.lowest(_src, _detection)

probe = f_synthetic(close, 3, 2)
if probe > 0
    strategy.entry("L", strategy.long)
"""


def test_synthetic_v6_strategy_has_complete_static_facts():
    result = parse_code(
        SOURCE,
        ParseOptions(source_name=SOURCE_NAME, producer_commit="a" * 40),
    )
    assert not [item for item in result.diagnostics if item.is_error]
    assert result.ok
    bundle = result.semantic_model.semantic_facts
    assert bundle.coverage.ok
    assert bundle.coverage.total_nodes == bundle.coverage.fact_nodes
    assert bundle.coverage.expression_nodes == bundle.coverage.typed_expression_nodes
    assert bundle.coverage.call_nodes == bundle.coverage.resolved_call_nodes
    assert bundle.coverage.unresolved_calls == ()
    assert all(call.resolution_status == "RESOLVED" for call in bundle.calls)
    assert all(call.overload_id for call in bundle.calls)
    assert result.semantic_facts_artifact["content_hash"] == bundle.artifact["content_hash"]


def test_synthetic_udf_is_inferred_without_unknown_fallback():
    result = parse_code(SOURCE)
    inference = result.semantic_model.callable_inference
    assert inference.return_types["f_synthetic"] == "float"
    assert inference.parameter_types["f_synthetic"] == {
        "_src": "float",
        "_length": "int",
        "_detection": "int",
    }
    assert result.semantic_model.symbols["probe"].type == "float"
