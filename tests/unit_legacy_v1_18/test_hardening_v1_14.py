from pine2ast.api import ParseOptions, parse_code


def _error_codes(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_builtin_argument_type_mismatch_is_reported():
    codes = _error_codes("""//@version=6
indicator("T")
plot(close, linewidth="wide")
""")
    assert "P2A1406" in codes


def test_builtin_argument_type_match_still_passes():
    assert _error_codes("""//@version=6
indicator("T")
plot(close, linewidth=2, color=color.new(color.blue, 0))
""") == []


def test_v5_strategy_and_reassigned_flags_compile_in_compat_mode():
    assert _error_codes("""//@version=5
strategy("T")
g = "Signals"
show = input.bool(true, group=g)
sig = false
sig := close > open
plot(show and sig ? close : na)
""") == ["P2A0103"]


def test_footprint_and_alert_namespaces_are_registered():
    assert _error_codes("""//@version=6
indicator("T")
fp = request.footprint(10, 70, 300)
plot(not na(fp) ? fp.delta() : close, style=plot.style_linebr)
alert("x", alert.freq_once_per_bar_close)
""") == []


def test_unary_not_requires_bool_operand():
    codes = _error_codes("""//@version=6
indicator("T")
x = not close
plot(close)
""")
    assert "P2A1801" in codes


def test_arithmetic_operator_rejects_string_operand_but_allows_string_concat():
    bad = _error_codes("""//@version=6
indicator("T")
x = close + "bad"
plot(close)
""")
    assert "P2A1801" in bad

    ok = _error_codes("""//@version=6
indicator("T")
s = "a" + "b"
plot(close)
""")
    assert ok == []


def test_typed_variable_reassignment_type_mismatch():
    codes = _error_codes("""//@version=6
indicator("T")
int x = 1
x := "bad"
plot(close)
""")
    assert "P2A1801" in codes


def test_numeric_widening_still_allows_float_reassignment_from_int():
    assert _error_codes("""//@version=6
indicator("T")
float x = 1
x := 2
plot(close)
""") == []


def test_udt_field_reassignment_type_mismatch():
    codes = _error_codes("""//@version=6
indicator("T")
type Pivot
    int x
var Pivot p = Pivot.new(1)
p.x := "bad"
plot(close)
""")
    assert "P2A1801" in codes
