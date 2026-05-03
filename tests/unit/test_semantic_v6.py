from pine2ast import parse_code


def codes(src):
    return {d.code for d in parse_code(src).diagnostics}


def test_bool_context_and_bool_na():
    src = """//@version=6
indicator("bad")
if close
    x = 1
bool b = na
"""
    got = codes(src)
    assert "P2A1201" in got
    assert "P2A1203" in got


def test_history_and_strategy_when_and_plot_local():
    src = """//@version=6
strategy("bad")
x = 1[2]
y = close[1][2]
strategy.entry("L", strategy.long, when = close > open)
if close > open
    plot(close)
"""
    got = codes(src)
    assert "P2A1301" in got
    assert "P2A1302" in got
    assert "P2A1501" in got
    assert "P2A1503" in got


def test_strategy_commission_constants_are_const_qualified():
    src = """//@version=6
strategy("S", commission_type=strategy.commission.percent, commission_value=0.1)
strategy.entry("L", strategy.long)
"""
    got = codes(src)
    assert "P2A1405" not in got
    assert "P2A1101" not in got


def test_strategy_default_qty_type_constants_are_const_strings():
    src = """//@version=6
strategy("S", default_qty_type=strategy.cash, default_qty_value=100)
strategy.entry("L", strategy.long)
"""
    got = codes(src)
    assert "P2A1406" not in got
    assert "P2A1101" not in got

    src = """//@version=6
strategy("S", default_qty_type=strategy.percent_of_equity, default_qty_value=10)
strategy.entry("L", strategy.long)
"""
    got = codes(src)
    assert "P2A1406" not in got
    assert "P2A1101" not in got


def test_reassignment_break_continue():
    src = """//@version=6
indicator("bad")
x := 1
break
"""
    got = codes(src)
    assert "P2A1103" in got
    assert "P2A1701" in got


def test_varip_declaration_parses_with_mode_and_type_ref():
    src = """//@version=6
strategy("S", calc_on_every_tick=true)
varip int ticks = 0
ticks := ticks + 1
"""
    result = parse_code(src)
    assert result.diagnostics == []
    ast = result.ast.to_dict()
    decl = ast["items"][0]
    assert decl["kind"] == "VarDeclaration"
    assert decl["mode"] == "varip"
    assert decl["type_ref"]["name"] == "int"
    assert ast["items"][1]["kind"] == "Reassignment"
