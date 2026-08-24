"""Wave 0 RED contracts for exact execution capability requirements."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pine2ast import ParseOptions, parse_code

HEAD_SHA = "a5870fc40b790b764d70e4eac9db0abbb31a2a15"


def _artifacts(source: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    result = parse_code(source, ParseOptions(producer_commit=HEAD_SHA))
    errors = [
        (diagnostic.code, diagnostic.message)
        for diagnostic in result.diagnostics
        if diagnostic.severity.value in {"ERROR", "FATAL"}
    ]
    assert result.ok, errors
    assert result.frontend_artifact is not None
    assert result.support_profile is not None
    return result.frontend_artifact, result.support_profile


def _features(profile: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {row["feature_id"]: row for row in profile["features"]}


def test_frontend_emits_exact_strategy_execution_settings() -> None:
    frontend, _ = _artifacts("""//@version=6
strategy("execution", calc_on_order_fills=true, calc_on_every_tick=false, process_orders_on_close=true)
strategy.entry("L", strategy.long)
""")

    assert frontend["strategy_settings"] == {
        "calc_on_order_fills": {
            "enabled": True,
            "capability": "calc_on_order_fills",
        },
        "calc_on_every_tick": {
            "enabled": False,
            "capability": "calc_on_every_tick",
        },
        "process_orders_on_close": {
            "enabled": True,
            "capability": "process_orders_on_close",
        },
    }


def test_syminfo_usage_emits_canonical_instrument_and_rules_requirements() -> None:
    frontend, profile = _artifacts("""//@version=6
indicator("instrument requirements")
plot(syminfo.mintick)
plot(syminfo.pointvalue)
plot(str.length(syminfo.tickerid))
""")

    expected_predicates = {
        "syminfo.tickerid": "canonical_instrument_identity",
        "syminfo.mintick": "canonical_instrument_rules",
        "syminfo.pointvalue": "canonical_instrument_rules",
    }
    referenced = set(frontend["referenced_builtins"])
    features = _features(profile)

    assert expected_predicates.keys() <= referenced
    for feature_id, predicate in expected_predicates.items():
        assert features[feature_id]["capability_predicate"] == predicate


def test_request_security_distinguishes_chart_and_requested_series_identity() -> None:
    frontend, profile = _artifacts("""//@version=6
indicator("series identities")
chart_ticker = syminfo.tickerid
requested_ticker = request.security("NASDAQ:AAPL", "1D", syminfo.tickerid)
plot(str.length(chart_ticker))
plot(str.length(requested_ticker))
""")

    identity_requirements = {
        "chart_series_identity",
        "requested_series_identity",
    }
    request_usage = set(frontend["request_usage"])
    features = _features(profile)

    assert identity_requirements <= request_usage
    assert identity_requirements <= features.keys()
    assert features["chart_series_identity"]["capability_predicate"] == (
        "canonical_chart_series_identity"
    )
    assert features["requested_series_identity"]["capability_predicate"] == (
        "canonical_requested_series_identity"
    )


def test_requested_expression_identity_does_not_claim_chart_identity() -> None:
    frontend, profile = _artifacts("""//@version=6
indicator("requested identity only")
requested_ticker = request.security("NASDAQ:AAPL", "1D", syminfo.tickerid)
plot(str.length(requested_ticker))
""")

    assert frontend["request_usage"] == [
        "mtf_requested_series",
        "requested_series_identity",
    ]
    assert "syminfo.tickerid" in frontend["referenced_builtins"]
    features = _features(profile)
    assert "requested_series_identity" in features
    assert "chart_series_identity" not in features


def test_frontend_emits_per_order_and_risk_capability_requirements() -> None:
    frontend, profile = _artifacts("""//@version=6
strategy("order and risk requirements")
strategy.entry("L", strategy.long, qty=1)
strategy.order("S", strategy.short, qty=1)
strategy.exit("LX", from_entry="L", stop=low)
strategy.risk.max_cons_loss_days(3)
""")

    required = {
        "strategy.entry",
        "strategy.order",
        "strategy.exit",
        "strategy.risk.max_cons_loss_days",
    }
    features = _features(profile)

    assert required <= set(frontend["referenced_builtins"])
    assert required <= features.keys()
    assert len(features) > 5
