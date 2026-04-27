from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import Block, SwitchStructure, VarDeclaration
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes
from pine2ast.semantic.extractors import extract_inputs
from pine2ast.semantic.type_infer import infer_type


def _codes(src: str):
    res = parse_code(src, ParseOptions(source_name="v16.pine"))
    return res, [d.code for d in res.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]


def test_trailing_commas_in_calls_generics_and_tuple_expr_are_accepted():
    res, errors = _codes("""//@version=6
indicator("Trailing", overlay = true,)
var array<float> values = array.new<float>(0,)
f(x,) => [x, x + 1,]
[a, b,] = f(close,)
plot(a,)
""")
    assert codes.SYNTAX_ERROR not in errors
    assert res.ast is not None


def test_switch_inline_case_can_hold_comma_statement_sequence():
    res, errors = _codes("""//@version=6
indicator("Switch seq")
mode = input.string("A", "Mode", options = ["A", "B"])
value = switch mode
    "A" => a = close + 1, b = a * 2, b
    => close
plot(value)
""")
    assert codes.SYNTAX_ERROR not in errors
    switch_nodes = [
        n
        for n in res.ast.items
        if isinstance(n, VarDeclaration) and isinstance(n.initializer, SwitchStructure)
    ]
    assert switch_nodes
    assert isinstance(switch_nodes[0].initializer.cases[0].body, Block)


def test_udt_constructor_and_member_field_type_inference():
    res, errors = _codes("""//@version=6
indicator("UDT type inference")
type Pivot
    int x
    float y
p = Pivot.new(bar_index, close)
y = p.y
plot(y)
""")
    assert codes.UNKNOWN_TYPE not in errors
    assert res.ast is not None
    y_decl = next(
        item for item in res.ast.items if isinstance(item, VarDeclaration) and item.name == "y"
    )
    assert infer_type(y_decl.initializer, res.semantic_model.symbols) == "float"


def test_method_receiver_type_mismatch_is_diagnosed():
    res, errors = _codes("""//@version=6
indicator("Method mismatch")
type Pivot
    int x
    float y
method isBullish(Pivot p) => p.y > close
x = 1
bad = x.isBullish()
plot(close)
""")
    assert codes.ARGUMENT_TYPE in errors


def test_input_options_array_from_is_extracted():
    res, errors = _codes("""//@version=6
indicator("Options")
len = input.int(14, "Length", options = array.from(10, 14, 20))
plot(close)
""")
    assert codes.SYNTAX_ERROR not in errors
    inputs = extract_inputs(res.ast, res.semantic_model)
    assert inputs[0].options == [10, 14, 20]


def test_unknown_type_ref_is_diagnostic():
    res, errors = _codes("""//@version=6
indicator("Unknown type")
NotAType x = na
plot(close)
""")
    assert codes.UNKNOWN_TYPE in errors
