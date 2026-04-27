from pine2ast.api import ParseOptions, parse_code


def _errors(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_plot_extended_parameters_validate_cleanly():
    assert _errors("""//@version=6
indicator("T")
plot(close, offset=1, trackprice=false, histbase=0.0, join=false, editable=true, show_last=10)
""") == []


def test_const_variable_rejects_series_initializer():
    codes = _errors("""//@version=6
indicator("T")
const x = close
plot(close)
""")
    assert "P2A1405" in codes


def test_const_variable_allows_literal_initializer():
    assert _errors("""//@version=6
indicator("T")
const x = 1
plot(x)
""") == []


def test_negative_history_offset_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
plot(close[-1])
""")
    assert "P2A1303" in codes


def test_unknown_builtin_namespace_member_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
plot(close, color=color.foobar)
""")
    assert "P2A1403" in codes


def test_builtin_scalar_member_access_is_rejected_but_udt_field_is_allowed():
    bad = _errors("""//@version=6
indicator("T")
x = close.foo
plot(close)
""")
    assert "P2A1101" in bad

    ok = _errors("""//@version=6
indicator("T")
type Pivot
    int x
p = Pivot.new(bar_index)
plot(p.x)
""")
    assert ok == []


def test_common_time_request_and_session_constants_validate():
    assert _errors("""//@version=6
indicator("T", timeframe="D", timeframe_gaps=true, scale=scale.right)
s = input.session("0930-1600", "Session")
in_sess = not na(time(timeframe.period, s))
chg = timeframe.change("D")
rate = request.currency_rate(currency.USD, currency.EUR)
plot(chg ? close : open, offset=1)
""") == []
