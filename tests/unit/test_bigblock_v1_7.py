from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.semantic.extractors import extract_inputs


def _codes(src: str):
    res = parse_code(src, ParseOptions(source_name="v17.pine"))
    return res, [d.code for d in res.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]


def test_tuple_declaration_gets_element_types_from_tuple_return():
    res, errors = _codes("""//@version=6
indicator("Tuple types")
[basis, upper, lower] = ta.bb(close, 20, 2)
plot(upper)
""")
    assert codes.SYNTAX_ERROR not in errors
    assert res.semantic_model.symbols["basis"].type == "float"
    assert res.semantic_model.symbols["upper"].type == "float"
    assert res.semantic_model.symbols["lower"].type == "float"


def test_user_function_argument_type_and_count_are_validated():
    res, errors = _codes("""//@version=6
indicator("User call checks")
f(float x, int n) => x + n
badType = f("x", 2)
badCount = f(close, 2, 3)
plot(close)
""")
    assert codes.ARGUMENT_TYPE in errors
    assert codes.ARGUMENT_COUNT in errors


def test_builtin_argument_type_and_count_are_validated():
    res, errors = _codes("""//@version=6
indicator("Builtin call checks")
a = ta.linreg(close, "20", 0)
b = ta.linreg(close, 20, 0, 1)
c = ta.linreg(close, 20)
plot(close)
""")
    assert codes.ARGUMENT_TYPE in errors
    assert codes.ARGUMENT_COUNT in errors
    messages = [d.message for d in res.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]
    assert any("Missing required parameter(s) for ta.linreg: offset" in msg for msg in messages)


def test_unknown_builtin_namespace_value_is_rejected():
    res, errors = _codes("""//@version=6
indicator("Builtin namespace value checks")
plot(ta.atr20)
""")
    assert codes.UNKNOWN_BUILTIN_MEMBER in errors
    messages = [d.message for d in res.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]
    assert any("Builtin namespace member ta.atr20" in msg for msg in messages)


def test_syminfo_mintick_is_known_simple_float():
    res, errors = _codes("""//@version=6
indicator("Syminfo mintick")
plot(syminfo.mintick)
""")
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNDECLARED_VARIABLE not in errors
    assert res.semantic_model.symbols["syminfo.mintick"].type == "float"
    assert res.semantic_model.symbols["syminfo.mintick"].qualifier == "simple"


def test_strategy_commission_namespace_and_initial_capital_are_known():
    res, errors = _codes("""//@version=6
strategy("Strategy metadata", commission_type=strategy.commission.percent, initial_capital=10000)
plot(strategy.initial_capital)
""")
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNDECLARED_VARIABLE not in errors
    assert res.semantic_model.symbols["strategy.initial_capital"].type == "float"
    assert res.semantic_model.symbols["strategy.initial_capital"].qualifier == "simple"


def test_strategy_entry_qty_type_is_validated_but_direction_constant_is_ok():
    res, errors = _codes("""//@version=6
strategy("Strategy type checks")
strategy.entry("L", strategy.long, qty = "bad")
""")
    assert codes.ARGUMENT_TYPE in errors
    assert codes.UNDECLARED_VARIABLE not in errors


def test_udt_constructor_required_fields_and_field_types_are_validated():
    res, errors = _codes("""//@version=6
indicator("UDT ctor checks")
type Pivot
    int x
    float y
missing = Pivot.new(bar_index)
bad = Pivot.new(bar_index, "bad")
plot(close)
""")
    assert codes.ARGUMENT_COUNT in errors
    assert codes.ARGUMENT_TYPE in errors


def test_udt_constructor_default_field_can_be_omitted():
    res, errors = _codes("""//@version=6
indicator("UDT ctor defaults")
type Pivot
    int x
    float y = 0.0
p = Pivot.new(bar_index)
plot(p.y)
""")
    assert codes.ARGUMENT_COUNT not in errors
    assert codes.ARGUMENT_TYPE not in errors


def test_input_enum_member_options_are_extracted_as_stable_names():
    res, errors = _codes("""//@version=6
indicator("Input enum options")
enum Mode
    Fast "Fast"
    Slow "Slow"
mode = input.enum(Mode.Fast, "Mode", options = [Mode.Fast, Mode.Slow])
plot(close)
""")
    assert codes.SYNTAX_ERROR not in errors
    inputs = extract_inputs(res.ast, res.semantic_model)
    assert inputs[0].default_value == "Mode.Fast"
    assert inputs[0].options == ["Mode.Fast", "Mode.Slow"]


def test_typed_tuple_target_overflow_is_diagnosed():
    res, errors = _codes("""//@version=6
indicator("Tuple overflow")
[a, b, c, d] = ta.bb(close, 20, 2)
plot(close)
""")
    assert codes.ARGUMENT_COUNT in errors
