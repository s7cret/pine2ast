"""Comprehensive verification tests for Pine v6 parity matrix remaining entries.

Tests all IMPLEMENTED_UNVERIFIED and NOT_STARTED entries from parity_matrix.json
to move them to DONE_VERIFIED status.

Groups:
  K. NOT_STARTED (5) - strategy.closedtrades/opentrades.max_*_percent, strategy.risk.max_position_size
  J. Plot semantic (10) - plot, plotarrow, plotbar, plotcandle, plotchar, plotshape, barcolor, bgcolor, fill, hline
  I. Strategy variables (19) - strategy.avg_trade, strategy.max_drawdown, etc.
  D. Map functions (10) - map.new, map.put, map.get, etc.
  E. Matrix functions (50) - matrix.new, matrix.get, matrix.det, etc.
  F. request.* (3) - request.dividends, request.earnings, request.splits
  G. volume_row type (1)
  A. Drawing functions (33) - box.*, label.*, line.*, linefill.*, table.*, chart.point.*, color.*, input.*
  C. Drawing types (6) - box, chart.point, color, label, line, linefill
  B. Method-style (15) - b.set_border_style, l.set_text, ln.set_color, etc.
"""

from pathlib import Path


from pine2ast import parse_code


def _assert_no_errors(source: str, label: str = "") -> None:
    """Parse source and assert no ERROR-level diagnostics."""
    result = parse_code(source)
    errors = [d for d in result.diagnostics if d.severity.value == "ERROR"]
    assert not errors, f"{label} parse errors: {errors}"


# ---------------------------------------------------------------------------
# K. NOT_STARTED — 5 entries that needed implementation
# ---------------------------------------------------------------------------


class TestNotStarted:
    """K.1–K.5: Functions that were NOT_STARTED, now implemented in builtins_v6.json."""

    def test_strategy_closedtrades_max_drawdown_percent(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
a = strategy.closedtrades.max_drawdown_percent(0)
""",
            "strategy.closedtrades.max_drawdown_percent",
        )

    def test_strategy_closedtrades_max_runup_percent(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
a = strategy.closedtrades.max_runup_percent(0)
""",
            "strategy.closedtrades.max_runup_percent",
        )

    def test_strategy_opentrades_max_drawdown_percent(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
a = strategy.opentrades.max_drawdown_percent(0)
""",
            "strategy.opentrades.max_drawdown_percent",
        )

    def test_strategy_opentrades_max_runup_percent(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
a = strategy.opentrades.max_runup_percent(0)
""",
            "strategy.opentrades.max_runup_percent",
        )

    def test_strategy_risk_max_position_size(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
strategy.risk.max_position_size(100.0)
""",
            "strategy.risk.max_position_size",
        )


# ---------------------------------------------------------------------------
# J. Plot functions — parser DONE_VERIFIED, semantic verification
# ---------------------------------------------------------------------------


class TestPlotFunctions:
    """J.1–J.10: Plot functions that parse correctly, verify no errors."""

    def test_plot(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=false)
plot(close, "Close", color=color.red)
""",
            "plot",
        )

    def test_plotarrow(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=false)
plotarrow(close - open)
""",
            "plotarrow",
        )

    def test_plotbar(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=false)
plotbar(open, high, low, close)
""",
            "plotbar",
        )

    def test_plotcandle(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=false)
plotcandle(open, high, low, close)
""",
            "plotcandle",
        )

    def test_plotchar(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=false)
plotchar(close > open, "buy", "▲", location.belowbar, color.green)
""",
            "plotchar",
        )

    def test_plotshape(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=false)
plotshape(close > open, "buy", shape.triangleup, location.belowbar, color.green)
""",
            "plotshape",
        )

    def test_barcolor(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
barcolor(close > open ? color.green : color.red)
""",
            "barcolor",
        )

    def test_bgcolor(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
bgcolor(color.new(color.blue, 90))
""",
            "bgcolor",
        )

    def test_fill(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=false)
h1 = hline(50, "Upper", color=color.gray)
h2 = hline(30, "Lower", color=color.gray)
fill(h1, h2, color=color.new(color.blue, 90))
""",
            "fill",
        )

    def test_hline(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=false)
hline(50, "Mid", color=color.gray)
""",
            "hline",
        )


# ---------------------------------------------------------------------------
# I. Strategy variables — 19 entries
# ---------------------------------------------------------------------------


class TestStrategyVariables:
    """I.1–I.20: Strategy performance variables."""

    def test_all_strategy_variables(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
a1 = strategy.account_currency
a2 = strategy.avg_losing_trade
a3 = strategy.avg_losing_trade_percent
a4 = strategy.avg_trade
a5 = strategy.avg_trade_percent
a6 = strategy.avg_winning_trade
a7 = strategy.avg_winning_trade_percent
a8 = strategy.grossloss_percent
a9 = strategy.grossprofit_percent
a10 = strategy.margin_liquidation_price
a11 = strategy.max_contracts_held_all
a12 = strategy.max_contracts_held_long
a13 = strategy.max_contracts_held_short
a14 = strategy.max_drawdown
a15 = strategy.max_drawdown_percent
a16 = strategy.max_runup
a17 = strategy.max_runup_percent
a18 = strategy.netprofit_percent
a19 = strategy.openprofit_percent
a20 = strategy.position_entry_name
""",
            "strategy variables",
        )


# ---------------------------------------------------------------------------
# D. Map functions — 10 entries
# ---------------------------------------------------------------------------


class TestMapFunctions:
    """D.1–D.10: Map collection functions."""

    def test_all_map_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
m = map.new<string, float>()
map.put(m, "high", high)
map.put(m, "low", low)
v = map.get(m, "high")
has = map.contains(m, "close")
sz = map.size(m)
k = map.keys(m)
vals = map.values(m)
map.remove(m, "low")
map.clear(m)
m2 = map.copy(m)
""",
            "map functions",
        )


# ---------------------------------------------------------------------------
# E. Matrix functions — 50 entries
# ---------------------------------------------------------------------------


class TestMatrixFunctions:
    """E.1–E.50: Matrix collection functions."""

    def test_all_matrix_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
m = matrix.new<float>(3, 3, 0.0)
m2 = matrix.copy(m)
v = matrix.get(m, 0, 0)
matrix.set(m, 0, 0, 1.0)
r = matrix.row(m, 0)
c = matrix.col(m, 0)
nr = matrix.rows(m)
nc = matrix.columns(m)
ec = matrix.elements_count(m)
matrix.add_row(m, 0, array.new<float>(3, 0.0))
matrix.add_col(m, 0, array.new<float>(3, 0.0))
matrix.remove_row(m, 0)
matrix.remove_col(m, 0)
matrix.fill(m, 1.0)
m3 = matrix.concat(m, m2)
matrix.sort(m, 0, order.ascending)
matrix.reverse(m)
d = matrix.det(m)
i = matrix.inv(m)
pi = matrix.pinv(m)
t = matrix.transpose(m)
rk = matrix.rank(m)
tr = matrix.trace(m)
s = matrix.sum(m)
diff = matrix.diff(m, m2)
avg = matrix.avg(m)
md = matrix.median(m)
mn = matrix.min(m)
mx = matrix.max(m)
mo = matrix.mode(m)
kr = matrix.kron(m, m2)
mp = matrix.pow(m, 2)
ml = matrix.mult(m, m2)
sq = matrix.is_square(m)
sym = matrix.is_symmetric(m)
asym = matrix.is_antisymmetric(m)
idi = matrix.is_identity(m)
diag = matrix.is_diagonal(m)
adiag = matrix.is_antidiagonal(m)
tri = matrix.is_triangular(m)
sto = matrix.is_stochastic(m)
bin = matrix.is_binary(m)
zero = matrix.is_zero(m)
matrix.reshape(m, 9, 1)
sm = matrix.submatrix(m, 0, 1, 0, 1)
matrix.swap_rows(m, 0, 1)
matrix.swap_columns(m, 0, 1)
ev = matrix.eigenvalues(m)
evc = matrix.eigenvectors(m)
""",
            "matrix functions",
        )


# ---------------------------------------------------------------------------
# F. request.* functions — 3 entries
# ---------------------------------------------------------------------------


class TestRequestFunctions:
    """F.1–F.3: request.dividends, request.earnings, request.splits."""

    def test_request_dividends(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
d = request.dividends(syminfo.tickerid, dividends.gross)
""",
            "request.dividends",
        )

    def test_request_earnings(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
e = request.earnings(syminfo.tickerid, earnings.actual)
""",
            "request.earnings",
        )

    def test_request_splits(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
s = request.splits(syminfo.tickerid, splits.numerator)
""",
            "request.splits",
        )


# ---------------------------------------------------------------------------
# G. volume_row type — 1 entry
# ---------------------------------------------------------------------------


class TestVolumeRowType:
    """G.1: volume_row type."""

    def test_volume_row_type_exists(self):
        """Verify volume_row is registered as a type in builtins_v6.json."""
        import json

        with open(
            Path(__file__).parent.parent.parent
            / "pine2ast"
            / "semantic"
            / "builtins_v6.json"
        ) as f:
            bv = json.load(f)
        assert "volume_row" in bv.get("types", {}), "volume_row not in types section"


# ---------------------------------------------------------------------------
# A. Drawing functions — 33 entries
# ---------------------------------------------------------------------------


class TestDrawingFunctions:
    """A.1–A.33: Drawing object functions (function-style)."""

    def test_box_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low, border_color=color.red)
box.set_bgcolor(b, color.blue)
box.set_border_color(b, color.green)
box.set_border_width(b, 2)
box.set_text(b, "hello")
box.set_text_color(b, color.white)
box.set_text_halign(b, text.align_left)
box.set_text_valign(b, text.align_top)
box.set_text_size(b, size.normal)
box.delete(b)
""",
            "box functions",
        )

    def test_label_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
l = label.new(bar_index, high, "test", color=color.green, style=label.style_label_down)
label.set_text(l, "new text")
label.set_textcolor(l, color.yellow)
label.set_tooltip(l, "tip")
label.set_size(l, size.large)
label.set_textalign(l, text.align_center)
label.delete(l)
""",
            "label functions",
        )

    def test_line_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low, color=color.red, width=2)
line.set_color(ln, color.blue)
line.set_width(ln, 3)
line.delete(ln)
""",
            "line functions",
        )

    def test_linefill_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
""",
            "linefill functions",
        )

    def test_table_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
tbl = table.new(position.top_right, 2, 2, bgcolor=color.black)
table.cell(tbl, 0, 0, "hello", text_color=color.white)
table.delete(tbl)
""",
            "table functions",
        )

    def test_color_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
c1 = color.new(color.red, 50)
c2 = color.rgb(255, 0, 0, 50)
""",
            "color functions",
        )

    def test_chart_point_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
p1 = chart.point.now(high)
p2 = chart.point.copy(p1)
p3 = chart.point.from_index(bar_index, high)
p4 = chart.point.from_time(time, high)
""",
            "chart.point functions",
        )

    def test_input_functions(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
x = input.int(14, "Length", minval=1)
s = input.session("0930-1600", "Session")
""",
            "input functions",
        )

    def test_box_set_border_style_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
box.set_border_style(b, line.style_dotted)
""",
            "box.set_border_style function-style",
        )

    def test_box_set_extend_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
box.set_extend(b, extend.none)
""",
            "box.set_extend function-style",
        )

    def test_box_set_top_left_point_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
box.set_top_left_point(b, chart.point.now(high))
""",
            "box.set_top_left_point function-style",
        )

    def test_box_set_bottom_right_point_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
box.set_bottom_right_point(b, chart.point.now(low))
""",
            "box.set_bottom_right_point function-style",
        )

    def test_label_set_point_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
l = label.new(bar_index, high, "test")
label.set_point(l, chart.point.now(low))
""",
            "label.set_point function-style",
        )

    def test_label_set_style_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
l = label.new(bar_index, high, "test")
label.set_style(l, label.style_label_down)
""",
            "label.set_style function-style",
        )

    def test_line_set_extend_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
line.set_extend(ln, extend.both)
""",
            "line.set_extend function-style",
        )

    def test_line_set_first_point_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
line.set_first_point(ln, chart.point.now(high))
""",
            "line.set_first_point function-style",
        )

    def test_line_set_second_point_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
line.set_second_point(ln, chart.point.now(low))
""",
            "line.set_second_point function-style",
        )

    def test_line_set_style_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
line.set_style(ln, line.style_dashed)
""",
            "line.set_style function-style",
        )

    def test_linefill_set_color_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
linefill.set_color(lf, color.blue)
""",
            "linefill.set_color function-style",
        )

    def test_linefill_get_line1_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
l1 = linefill.get_line1(lf)
""",
            "linefill.get_line1 function-style",
        )

    def test_linefill_get_line2_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
l2 = linefill.get_line2(lf)
""",
            "linefill.get_line2 function-style",
        )

    def test_linefill_delete_function(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
linefill.delete(lf)
""",
            "linefill.delete function-style",
        )


# ---------------------------------------------------------------------------
# C. Drawing types — 6 entries
# ---------------------------------------------------------------------------


class TestDrawingTypes:
    """C.1–C.6: Drawing object types."""

    def test_box_type(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
""",
            "box type",
        )

    def test_chart_point_type(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
p = chart.point.now(high)
""",
            "chart.point type",
        )

    def test_color_type(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
c = color.red
""",
            "color type",
        )

    def test_label_type(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
l = label.new(bar_index, high, "test")
""",
            "label type",
        )

    def test_line_type(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
""",
            "line type",
        )

    def test_linefill_type(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
""",
            "linefill type",
        )


# ---------------------------------------------------------------------------
# B. Method-style — 15 entries
# ---------------------------------------------------------------------------


class TestMethodStyle:
    """B.1–B.15: Method-style calls (obj.method(args))."""

    def test_box_set_border_style_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
b.set_border_style(line.style_dotted)
""",
            "box.set_border_style method",
        )

    def test_box_set_extend_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
b.set_extend(extend.none)
""",
            "box.set_extend method",
        )

    def test_box_set_top_left_point_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
b.set_top_left_point(chart.point.now(high))
""",
            "box.set_top_left_point method",
        )

    def test_box_set_bottom_right_point_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
b = box.new(bar_index[10], high[10], bar_index, low)
b.set_bottom_right_point(chart.point.now(low))
""",
            "box.set_bottom_right_point method",
        )

    def test_chart_point_copy_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
p1 = chart.point.now(high)
p2 = p1.copy()
""",
            "chart.point.copy method",
        )

    def test_label_set_point_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
l = label.new(bar_index, high, "test")
l.set_point(chart.point.now(low))
""",
            "label.set_point method",
        )

    def test_label_set_style_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
l = label.new(bar_index, high, "test")
l.set_style(label.style_label_down)
""",
            "label.set_style method",
        )

    def test_line_set_extend_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
ln.set_extend(extend.both)
""",
            "line.set_extend method",
        )

    def test_line_set_first_point_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
ln.set_first_point(chart.point.now(high))
""",
            "line.set_first_point method",
        )

    def test_line_set_second_point_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
ln.set_second_point(chart.point.now(low))
""",
            "line.set_second_point method",
        )

    def test_line_set_style_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln = line.new(bar_index[10], high[10], bar_index, low)
ln.set_style(line.style_dashed)
""",
            "line.set_style method",
        )

    def test_linefill_delete_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
lf.delete()
""",
            "linefill.delete method",
        )

    def test_linefill_get_line1_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
l1 = lf.get_line1()
""",
            "linefill.get_line1 method",
        )

    def test_linefill_get_line2_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
l2 = lf.get_line2()
""",
            "linefill.get_line2 method",
        )

    def test_linefill_set_color_method(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
ln1 = line.new(bar_index[10], high[10], bar_index, low)
ln2 = line.new(bar_index[10], low[10], bar_index, high)
lf = linefill.new(ln1, ln2, color.new(color.red, 90))
lf.set_color(color.blue)
""",
            "linefill.set_color method",
        )


# ---------------------------------------------------------------------------
# Previously UNSUPPORTED — now pass-through (log.*, runtime.error)
# ---------------------------------------------------------------------------


class TestPreviouslyUnsupported:
    """Functions that were UNSUPPORTED_DIAGNOSTIC, now accepted as pass-through."""

    def test_log_info(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
log.info("debug message: close = " + str.tostring(close))
""",
            "log.info",
        )

    def test_log_warning(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
log.warning("warning: volume low")
""",
            "log.warning",
        )

    def test_log_error(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
log.error("error: invalid state")
""",
            "log.error",
        )

    def test_runtime_error(self):
        _assert_no_errors(
            """//@version=6
strategy("test", overlay=true)
runtime.error("unreachable")
""",
            "runtime.error",
        )
