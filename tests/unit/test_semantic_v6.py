from pine2ast import parse_code


def codes(src):
    return {d.code for d in parse_code(src).diagnostics}


def test_bool_context_and_bool_na():
    src = '''//@version=6
indicator("bad")
if close
    x = 1
bool b = na
'''
    got = codes(src)
    assert "P2A1201" in got
    assert "P2A1203" in got


def test_history_and_strategy_when_and_plot_local():
    src = '''//@version=6
strategy("bad")
x = 1[2]
y = close[1][2]
strategy.entry("L", strategy.long, when = close > open)
if close > open
    plot(close)
'''
    got = codes(src)
    assert "P2A1301" in got
    assert "P2A1302" in got
    assert "P2A1501" in got
    assert "P2A1503" in got


def test_reassignment_break_continue():
    src = '''//@version=6
indicator("bad")
x := 1
break
'''
    got = codes(src)
    assert "P2A1103" in got
    assert "P2A1701" in got
