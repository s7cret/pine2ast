from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.ast.nodes import ArrayLiteralExpr, TupleDeclaration, VarDeclaration


def error_codes(src: str):
    result = parse_code(src, ParseOptions(run_semantic=True, collect_tokens=True))
    return result, [d.code for d in result.diagnostics if d.severity is Severity.ERROR]


def assert_no_errors(src: str):
    result, errs = error_codes(src)
    assert result.ast is not None
    assert not errs, [d.to_dict() for d in result.diagnostics]
    return result


def test_import_before_declaration_is_preserved():
    result = assert_no_errors("""//@version=6
import TradingView/ta/7 as ta2
indicator("T")
plot(ta2.sma(close, 10))
""")
    assert result.ast.declaration.script_type == "indicator"
    assert result.ast.items[0].path == "TradingView/ta/7"


def test_request_security_tuple_expression_argument():
    result = assert_no_errors("""//@version=6
indicator("T")
[hh, ll] = request.security(syminfo.tickerid, "D", [high, low])
plot(hh)
""")
    tup = result.ast.items[0]
    assert isinstance(tup, TupleDeclaration)
    assert isinstance(tup.initializer.arguments[2].value, ArrayLiteralExpr)


def test_mutable_var_reassignment_allowed_but_explicit_const_reassignment_rejected():
    _, errs = error_codes("""//@version=6
indicator("T")
var int x = na
if barstate.isconfirmed
    x := 1
plot(x)
""")
    assert codes.CONST_REASSIGNMENT not in errs

    _, errs = error_codes("""//@version=6
indicator("T")
const int x = 1
x := 2
plot(x)
""")
    assert codes.CONST_REASSIGNMENT in errs


def test_array_literal_expression_in_call():
    result = assert_no_errors("""//@version=6
indicator("T")
a = array.from([1, 2, 3])
plot(close)
""")
    item = result.ast.items[0]
    assert isinstance(item, VarDeclaration)
    assert isinstance(item.initializer.arguments[0].value, ArrayLiteralExpr)


def test_duplicate_and_positional_after_named_still_reported():
    _, errs = error_codes("""//@version=6
indicator("T")
plot(series=close, series=open)
""")
    assert codes.DUPLICATE_NAMED_ARGUMENT in errs

    _, errs = error_codes("""//@version=6
indicator("T")
plot(series=close, open)
""")
    assert codes.POSITIONAL_AFTER_NAMED in errs


def test_chart_point_and_drawing_registry_expansion():
    result = assert_no_errors("""//@version=6
indicator("T")
p = chart.point.now(close)
l = line.new(p, p)
label.new(bar_index, close, text="x", style=label.style_label_up)
plot(close)
""")
    assert result.ast is not None
