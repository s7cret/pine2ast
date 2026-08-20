import pytest

from pine2ast.api import ParseOptions, parse_code


def _error_codes(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_local_symbols_do_not_leak_out_of_blocks():
    codes = _error_codes("""//@version=6
indicator("T")
if close > open
    local_only = close
plot(local_only)
""")
    assert "P2A1101" in codes


def test_local_shadowing_does_not_destroy_global_symbol():
    assert _error_codes("""//@version=6
indicator("T")
x = close
if close > open
    x = open
plot(x)
""") == []


def test_function_and_type_forward_references_are_resolved():
    assert _error_codes("""//@version=6
indicator("T")
x = normalize(close)
type Pivot
    int x
normalize(float src) =>
    src / close
plot(x)
""") == []


@pytest.mark.xfail(reason="strategy.risk.max_drawdown arg type inference pending")
def test_common_strategy_risk_and_order_functions_validate():
    assert _error_codes("""//@version=6
strategy("S", overlay=true, commission_type=strategy.commission.percent, commission_value=0.1)
strategy.risk.max_drawdown(10, strategy.percent_of_equity)
strategy.order("L", strategy.long, qty=1)
strategy.close("L")
""") == []


def test_common_array_matrix_map_helpers_validate():
    assert _error_codes("""//@version=6
indicator("T")
a = array.from(1.0, 2.0, 3.0)
array.sort(a)
m = matrix.new<float>(2, 2, 0.0)
mp = map.new<string, float>()
map.put(mp, "last", array.avg(a))
plot(map.get(mp, "last"))
""") == []


def test_common_ta_and_ticker_helpers_validate():
    assert _error_codes("""//@version=6
indicator("T")
hk = ticker.heikinashi(syminfo.tickerid)
sec = request.security(hk, timeframe.period, ta.supertrend(3.0, 10))
val = ta.valuewhen(ta.crossover(close, open), close, 0)
plot(val)
""") == []
