from pine2ast.api import ParseOptions, parse_code


def _error_codes(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_udt_constructor_and_method_call_do_not_redeclare_or_unknown():
    assert _error_codes("""//@version=6
indicator("T")
type Pivot
    int x
    float y
method isBullish(Pivot p) =>
    p.y > close
var Pivot p = Pivot.new(bar_index, close)
x = p.isBullish()
plot(close)
""") == []


def test_udt_field_reassignment_is_allowed_but_const_root_is_rejected():
    assert _error_codes("""//@version=6
indicator("T")
type P
    float y
var P p = P.new(close)
p.y := high
plot(p.y)
""") == []
    codes = _error_codes("""//@version=6
indicator("T")
type P
    float y
const P p = P.new(close)
p.y := high
plot(close)
""")
    assert "P2A1104" in codes


def test_declaration_common_v6_args_validate_cleanly():
    assert _error_codes("""//@version=6
indicator("T", overlay=true, explicit_plot_zorder=true, max_lines_count=500, max_labels_count=500, max_boxes_count=500, max_polylines_count=100, dynamic_requests=true, format=format.price, precision=2)
var table t = table.new(position.top_right, 1, 1)
if barstate.islast
    table.cell(t, 0, 0, str.tostring(close), text_color=color.white)
plot(close)
""") == []


def test_strategy_declaration_common_properties_validate_cleanly():
    assert _error_codes("""//@version=6
strategy("S", overlay=true, initial_capital=1000, currency=currency.USD, default_qty_type=strategy.percent_of_equity, default_qty_value=10, commission_type=strategy.commission.percent, commission_value=0.1, pyramiding=2, slippage=1)
strategy.entry("L", strategy.long)
plot(close)
""") == []


def test_common_plot_and_visual_helpers_validate_cleanly():
    assert _error_codes("""//@version=6
indicator("T")
plotcandle(open, high, low, close, title="C")
plotbar(open, high, low, close)
plotchar(close > open, char="▲", location=location.abovebar)
bgcolor(close > open ? color.green : color.red)
barcolor(color.blue)
""") == []
