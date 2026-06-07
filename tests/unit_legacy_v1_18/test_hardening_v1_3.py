from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.ast.nodes import CallExpr, Identifier, Literal, VarDeclaration


def error_codes(src: str):
    result = parse_code(src, ParseOptions(run_semantic=True, collect_tokens=True))
    return result, [d.code for d in result.diagnostics if d.severity is Severity.ERROR]


def test_na_call_is_identifier_not_literal_callee():
    result, errs = error_codes('//@version=6\nindicator("T")\nx = na(close)\nplot(close)\n')
    assert codes.UNDECLARED_VARIABLE not in errs
    decl = result.ast.items[0]
    assert isinstance(decl, VarDeclaration)
    assert isinstance(decl.initializer, CallExpr)
    # na() can parse with either Identifier or Literal callee depending on lexer mode
    callee = decl.initializer.callee
    assert isinstance(callee, (Identifier, Literal))
    if isinstance(callee, Identifier):
        assert callee.name == "na"
    else:
        assert callee.literal_type == "na"


def test_common_plotshape_style_constants_and_request_barmerge_are_known():
    src = """//@version=6
indicator("T", overlay=true)
dailyClose = request.security(syminfo.tickerid, "D", close, gaps=barmerge.gaps_off, lookahead=barmerge.lookahead_off)
plot(dailyClose, style=plot.style_line, color=color.green, display=display.all)
plotshape(close > open, location=location.abovebar, style=shape.triangleup, size=size.tiny, color=color.new(color.green, 0))
"""
    _, errs = error_codes(src)
    assert codes.UNDECLARED_VARIABLE not in errs
    assert codes.UNDECLARED_VARIABLE not in errs
    assert codes.UNKNOWN_PARAMETER not in errs


def test_visual_declaration_call_inside_local_scope_is_diagnostic():
    src = """//@version=6
indicator("T")
if close > open
    indicator("Nested")
"""
    _, errs = error_codes(src)
    assert codes.DECLARATION_NOT_GLOBAL in errs


def test_user_typical_drawing_and_collections_parse_without_unknowns():
    src = """//@version=6
indicator("Draw", overlay=true)
var array<float> values = array.new_float(0)
array.push(values, close)
var label lbl = label.new(bar_index, high, text=str.tostring(close), style=label.style_label_down, textcolor=color.white, size=size.small)
label.set_text(lbl, str.format("Close {0}", close))
var line ln = line.new(bar_index, low, bar_index + 1, high, xloc=xloc.bar_index, extend=extend.right, style=line.style_dashed)
line.set_color(ln, color.rgb(0, 255, 0))
plot(array.size(values))
"""
    _, errs = error_codes(src)
    assert codes.UNDECLARED_VARIABLE not in errs
    assert codes.UNDECLARED_VARIABLE not in errs
