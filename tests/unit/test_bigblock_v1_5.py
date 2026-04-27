from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.semantic.extractors import extract_inputs, extract_strategy_calls


def _codes(src: str):
    res = parse_code(src, ParseOptions(source_name="test.pine"))
    return res, [d.code for d in res.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]


def test_const_title_variable_is_allowed_in_indicator_declaration():
    res, errors = _codes("""//@version=6
const string TITLE = "Const title"
indicator(TITLE, overlay = true)
plot(close)
""")
    assert codes.DECLARATION_ARGS_NOT_CONST not in errors
    assert res.ast is not None


def test_na_function_call_is_recognised_as_builtin():
    res, errors = _codes("""//@version=6
indicator("NA")
x = na(close)
plot(close)
""")
    assert codes.UNDECLARED_VARIABLE not in errors
    assert res.ast is not None


def test_input_source_defval_can_be_series_and_is_extracted():
    res, errors = _codes("""//@version=6
indicator("Input source")
src = input.source(close, "Source")
len = input.int(14, "Length", minval = 1, maxval = 100, options = [10, 14, 20])
plot(src)
""")
    assert codes.ARGUMENT_QUALIFIER not in errors
    inputs = extract_inputs(res.ast, res.semantic_model)
    assert [i.name for i in inputs] == ["src", "len"]
    assert inputs[0].title == "Source"
    assert inputs[1].options == [10, 14, 20]


def test_member_constants_have_const_qualifier_for_builtin_params():
    res, errors = _codes("""//@version=6
indicator("Colors")
plot(close, color = color.green, display = display.all)
""")
    assert codes.ARGUMENT_QUALIFIER not in errors
    assert res.ast is not None


def test_common_strategy_state_and_ta_builtins_do_not_emit_unknowns():
    res, errors = _codes("""//@version=6
strategy("Common strategy", overlay = true)
fast = ta.ema(close, 12)
slow = ta.sma(close, 26)
longCond = ta.crossover(fast, slow) and strategy.position_size <= 0
if longCond
    strategy.entry("L", strategy.long)
""")
    assert codes.UNDECLARED_VARIABLE not in errors
    assert codes.UNKNOWN_PARAMETER not in errors
    assert len(extract_strategy_calls(res.ast)) == 1


def test_request_financial_and_barstate_members_are_supported():
    res, errors = _codes("""//@version=6
indicator("Request")
eps = request.financial(syminfo.tickerid, "EARNINGS_PER_SHARE", "FQ")
ok = barstate.isconfirmed and not na(eps)
plot(eps)
""")
    assert codes.REQUEST_SIGNATURE not in errors
    assert codes.UNDECLARED_VARIABLE not in errors
