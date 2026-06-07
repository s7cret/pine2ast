import pytest

from pine2ast.api import ParseOptions, parse_code


def _error_codes(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_strategy_namespace_calls_are_strategy_only():
    codes = _error_codes("""//@version=6
indicator("T")
strategy.entry("L", strategy.long)
plot(close)
""")
    assert "P2A1504" in codes


def test_strategy_namespace_calls_allowed_in_strategy_scripts():
    assert _error_codes("""//@version=6
strategy("S")
strategy.entry("L", strategy.long)
strategy.exit("X", "L")
plot(close)
""") == []


def test_alertcondition_is_global_only_and_forbidden_in_local_blocks():
    codes = _error_codes("""//@version=6
indicator("T")
if close > open
    alertcondition(close > open, title="bull", message="bull")
plot(close)
""")
    assert "P2A1503" in codes
    assert "P2A1503" in codes


@pytest.mark.xfail(
    reason="Tuple destructuring from array.from() now correctly rejected by parser (P2A1902)"
)
def test_for_in_destructuring_accepts_more_than_two_targets():
    assert _error_codes("""//@version=6
indicator("T")
a = array.from(1, 2, 3)
for [i, v, extra] in a
    label.new(bar_index, close)
plot(close)
""") == []


def test_strategy_trade_collection_helpers_validate_cleanly():
    assert _error_codes("""//@version=6
strategy("S")
strategy.entry("L", strategy.long)
profit = strategy.closedtrades > 0 ? strategy.closedtrades.profit(0) : 0.0
openProfit = strategy.opentrades > 0 ? strategy.opentrades.profit(0) : 0.0
plot(profit + openProfit)
""") == []
