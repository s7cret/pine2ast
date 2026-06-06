from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.builtin_registry import load_builtin_registry, validate_builtin_registry

ORDER_SIGNATURES = {
    "strategy.entry": [
        "id",
        "direction",
        "qty",
        "limit",
        "stop",
        "oca_name",
        "oca_type",
        "comment",
        "alert_message",
        "disable_alert",
        "when",
    ],
    "strategy.order": [
        "id",
        "direction",
        "qty",
        "limit",
        "stop",
        "oca_name",
        "oca_type",
        "comment",
        "alert_message",
        "disable_alert",
        "when",
    ],
    "strategy.exit": [
        "id",
        "from_entry",
        "qty",
        "qty_percent",
        "profit",
        "limit",
        "loss",
        "stop",
        "trail_price",
        "trail_points",
        "trail_offset",
        "oca_name",
        "oca_type",
        "comment",
        "comment_profit",
        "comment_loss",
        "comment_trailing",
        "alert_message",
        "alert_profit",
        "alert_loss",
        "alert_trailing",
        "disable_alert",
        "when",
    ],
    "strategy.close": [
        "id",
        "comment",
        "qty",
        "qty_percent",
        "alert_message",
        "immediately",
        "disable_alert",
        "when",
    ],
    "strategy.close_all": ["comment", "alert_message", "immediately", "disable_alert", "when"],
    "strategy.cancel": ["id", "when"],
    "strategy.cancel_all": ["when"],
}


def _error_codes(source: str, *, strict_v6: bool = True) -> list[str]:
    result = parse_code(
        source,
        ParseOptions(strict_v6=strict_v6, strict_builtin_namespaces=True),
    )
    return [
        diag.code
        for diag in result.diagnostics
        if diag.severity in {Severity.ERROR, Severity.FATAL}
    ]


def test_strategy_p0_registry_signatures_are_known_and_schema_valid() -> None:
    registry = load_builtin_registry()
    validate_builtin_registry(registry)

    strategy_params = [param["name"] for param in registry["functions"]["strategy"]["parameters"]]
    for name in {
        "scale",
        "close_entries_rule",
        "explicit_plot_zorder",
        "calc_bars_count",
        "risk_free_rate",
        "fill_orders_on_standard_ohlc",
        "dynamic_requests",
        "behind_chart",
    }:
        assert name in strategy_params

    for name, expected_params in ORDER_SIGNATURES.items():
        assert [
            param["name"] for param in registry["functions"][name]["parameters"]
        ] == expected_params

    for name in {
        "strategy.closedtrades.max_drawdown_percent",
        "strategy.closedtrades.max_runup_percent",
        "strategy.opentrades.max_drawdown_percent",
        "strategy.opentrades.max_runup_percent",
    }:
        entry = registry["functions"][name]
        assert entry["parameters"][0]["name"] == "trade_num"
        assert entry["returns"] == "float"

    assert registry["variables"]["strategy.closedtrades.first_index"]["type"] == "int"
    assert registry["variables"]["strategy.opentrades.capital_held"]["type"] == "float"
    assert registry["functions"]["strategy.risk.max_position_size"]["unsupported"] is True


def test_strategy_calls_accept_normalized_p0_named_parameters() -> None:
    source = """//@version=6
strategy("strategy signatures", overlay=true, close_entries_rule="ANY", margin_long=100, margin_short=100, dynamic_requests=true)
strategy.entry("L", strategy.long, qty=1, limit=low, stop=high, oca_name="grp", oca_type=strategy.oca.cancel, comment="entry", alert_message="entry alert", disable_alert=false)
strategy.order("S", strategy.short, qty=1, limit=high, stop=low, oca_name="grp", oca_type=strategy.oca.reduce, comment="order", alert_message="order alert", disable_alert=true)
strategy.exit("LX", from_entry="L", qty_percent=50, profit=10, limit=high, loss=5, stop=low, trail_price=high, trail_points=1, trail_offset=2, oca_name="exit", oca_type=strategy.oca.reduce, comment="exit", comment_profit="tp", comment_loss="sl", comment_trailing="trail", alert_message="exit alert", alert_profit="tp alert", alert_loss="sl alert", alert_trailing="trail alert", disable_alert=false)
strategy.close("L", comment="close", qty=1, qty_percent=50, alert_message="close alert", immediately=true, disable_alert=false)
strategy.close_all(comment="all", alert_message="all alert", immediately=true, disable_alert=true)
strategy.cancel("S")
strategy.cancel_all()
closedPercent = strategy.closedtrades.max_drawdown_percent(0) + strategy.closedtrades.max_runup_percent(0)
openPercent = strategy.opentrades.max_drawdown_percent(0) + strategy.opentrades.max_runup_percent(0)
plot(strategy.closedtrades.first_index + strategy.opentrades.capital_held + closedPercent + openPercent)
"""

    errors = _error_codes(source)
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNKNOWN_PARAMETER not in errors
    assert codes.ARGUMENT_COUNT not in errors
    assert codes.ARGUMENT_TYPE not in errors
    assert codes.UNSUPPORTED_FEATURE not in errors


def test_strategy_unsupported_api_and_parameter_emit_explicit_diagnostics() -> None:
    unsupported_api = """//@version=6
strategy("unsupported risk")
strategy.risk.max_position_size(10)
"""
    api_result = parse_code(unsupported_api, ParseOptions(strict_builtin_namespaces=True))
    assert any(
        diag.code == codes.UNSUPPORTED_FEATURE and diag.severity is Severity.ERROR
        for diag in api_result.diagnostics
    )
    assert not any(diag.code == codes.UNKNOWN_BUILTIN_MEMBER for diag in api_result.diagnostics)

    unsupported_param = """//@version=6
strategy("unsupported param", use_bar_magnifier=true)
"""
    param_result = parse_code(unsupported_param, ParseOptions(strict_builtin_namespaces=True))
    assert any(
        diag.code == codes.UNSUPPORTED_FEATURE and diag.severity is Severity.ERROR
        for diag in param_result.diagnostics
    )
    assert not any(diag.code == codes.UNKNOWN_PARAMETER for diag in param_result.diagnostics)


def test_strategy_when_parameter_is_v6_removed_but_v5_compatible() -> None:
    v6_source = """//@version=6
strategy("when removed")
strategy.cancel("L", when=true)
strategy.cancel_all(when=true)
strategy.close("L", when=true)
"""
    v6_errors = _error_codes(v6_source)
    assert v6_errors.count(codes.STRATEGY_WHEN_REMOVED) == 3
    assert codes.UNKNOWN_PARAMETER not in v6_errors

    v5_source = """//@version=5
strategy("when allowed")
strategy.entry("L", strategy.long, when=true)
strategy.cancel_all(when=true)
"""
    v5_errors = _error_codes(v5_source, strict_v6=False)
    assert codes.STRATEGY_WHEN_REMOVED not in v5_errors
    assert codes.UNKNOWN_PARAMETER not in v5_errors
