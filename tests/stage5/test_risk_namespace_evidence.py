"""Intermediate enum namespaces must have typed identity in every admitted version."""

import pytest
from pine2ast.hardening.consumer_bundle import build_consumer_bundle


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("direction", ["long", "short", "all"])
def test_risk_direction_namespace_is_not_unknown(version, direction):
    bundle = build_consumer_bundle(
        f'//@version={version}\nstrategy("risk")\nstrategy.risk.allow_entry_in(strategy.direction.{direction})\n'
    )
    assert bundle["release_axes"]["bundle_fact_coverage_complete"]["status"] == "PASS"
    facts = bundle["semantic_facts"]["facts"]
    namespace = [f for f in facts if f.get("symbol_id") == "pine:namespace:strategy.direction"]
    if version == 5:
        assert namespace and all(f["resolved_type"]["base"] == "namespace" for f in namespace)
    assert bundle["semantic_facts"]["coverage"]["ok"]


@pytest.mark.parametrize("version", range(1, 7))
def test_unknown_direction_member_still_fails_closed(version):
    from pine2ast.hardening.consumer_bundle import ConsumerBundleError

    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(
            f'//@version={version}\nstrategy("unknown")\nstrategy.risk.allow_entry_in(strategy.direction.sideways)\n'
        )


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("kind", ["input", "series"])
def test_entry_risk_parameter_qualifiers_are_version_bound(version, kind):
    from pine2ast.hardening.consumer_bundle import ConsumerBundleError

    declaration = "n=input.int(3)" if version >= 5 else "n=input(3)"
    value = "n" if kind == "input" else "close"
    source = f'//@version={version}\nstrategy("types")\n{declaration}\nstrategy.risk.max_position_size({value})\n'
    if kind == "series":
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(source)
    else:
        assert build_consumer_bundle(source)["semantic_facts"]["coverage"]["ok"]


@pytest.mark.parametrize("version", range(1, 7))
def test_source_input_cannot_disguise_a_series_as_a_simple_risk_value(version):
    from pine2ast.hardening.consumer_bundle import ConsumerBundleError

    call = "input.source(close)" if version >= 5 else "input(close)"
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(
            f'//@version={version}\nstrategy("source")\nn={call}\nstrategy.risk.max_position_size(n)\n'
        )
