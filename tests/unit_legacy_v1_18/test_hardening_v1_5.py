from pine2ast.api import parse_code, ParseOptions


def _error_codes(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_plot_title_requires_const_qualifier():
    codes = _error_codes('''//@version=6
indicator("T")
plot(close, title=str.tostring(close))
''')
    assert "P2A1405" in codes


def test_hline_price_allows_input_but_rejects_series():
    ok = _error_codes('''//@version=6
indicator("T")
level = input.float(0.0)
hline(level)
''')
    assert ok == []
    bad = _error_codes('''//@version=6
indicator("T")
hline(close)
''')
    assert "P2A1405" in bad


def test_too_many_positional_args_for_strict_signature():
    codes = _error_codes('''//@version=6
indicator("T")
plot(close, "C", color.red, 1, plot.style_line, display.all, 1, false, 0.0, false, true, 10, 123)
''')
    assert "P2A1404" in codes


def test_export_is_library_only():
    codes = _error_codes('''//@version=6
indicator("T")
export f(float x) =>
    x + 1
plot(close)
''')
    assert "P2A1604" in codes


def test_export_allowed_in_library():
    codes = _error_codes('''//@version=6
library("L")
export f(float x) =>
    x + 1
''')
    assert codes == []


def test_common_objects_and_alertcondition_validate():
    codes = _error_codes('''//@version=6
indicator("T", overlay=true, max_labels_count=100, format=format.price)
len = input.int(14, title="Length", minval=1)
ma = ta.sma(close, len)
alertcondition(close > ma, title="cross", message="cross")
var table t = table.new(position.top_right, 2, 2)
if barstate.islast
    label.new(bar_index, close, text=str.tostring(close), style=label.style_label_up)
plot(ma, title="MA", color=color.new(color.blue, 0))
''')
    assert codes == []
