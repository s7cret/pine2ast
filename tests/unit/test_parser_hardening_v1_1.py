from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import Block, FunctionDeclaration, GenericInstantiationExpr, VarDeclaration
from pine2ast.semantic.extractors import extract_inputs
from pine2ast.semantic.type_infer import callee_name


def test_generic_type_declaration_and_generic_call():
    src = """//@version=6
indicator("Array")
var array<float> values = array.new<float>()
"""
    result = parse_code(src, ParseOptions(run_semantic=True))
    assert not [d for d in result.diagnostics if d.severity.value in {"FATAL", "ERROR"}], [
        d.to_dict() for d in result.diagnostics
    ]
    item = result.ast.items[0]
    assert isinstance(item, VarDeclaration)
    assert item.type_ref.name == "array"
    assert item.type_ref.template_args[0].name == "float"
    assert isinstance(item.initializer.callee, GenericInstantiationExpr)
    assert callee_name(item.initializer.callee) == "array.new<float>"


def test_inline_function_comma_statement_body():
    src = """//@version=6
indicator("Inline")
f(x) => a = x + 1, b = a * 2, b
"""
    result = parse_code(src, ParseOptions(run_semantic=True))
    assert not [d for d in result.diagnostics if d.severity.value in {"FATAL", "ERROR"}], [
        d.to_dict() for d in result.diagnostics
    ]
    fn = result.ast.items[0]
    assert isinstance(fn, FunctionDeclaration)
    assert isinstance(fn.body, Block)
    assert len(fn.body.statements) == 3


def test_plot_forbidden_in_for_in_local_block():
    src = """//@version=6
indicator("Loop")
var array<float> values = array.new<float>()
for item in values
    plot(item)
"""
    result = parse_code(src)
    assert "P2A1503" in {d.code for d in result.diagnostics}


def test_second_declaration_statement_detected():
    src = """//@version=6
indicator("A")
strategy("B")
"""
    result = parse_code(src)
    assert "P2A1002" in {d.code for d in result.diagnostics}


def test_input_is_not_declaration_qualifier():
    src = """//@version=6
indicator("Bad")
input int len = input.int(14)
"""
    result = parse_code(src)
    assert "P2A0501" in {d.code for d in result.diagnostics}


def test_method_receiver_type_must_exist():
    src = """//@version=6
indicator("Bad")
method isOk(Pivot p) => true
"""
    result = parse_code(src)
    assert "P2A1603" in {d.code for d in result.diagnostics}


def test_extract_inputs_from_input_call():
    src = """//@version=6
indicator("Inputs")
int len = input.int(14, title = "Length", minval = 1, maxval = 100, step = 1)
"""
    result = parse_code(src)
    inputs = extract_inputs(result.ast, result.semantic_model)
    assert len(inputs) == 1
    assert inputs[0].input_function == "input.int"
    assert inputs[0].title == "Length"
    assert inputs[0].default_value == 14
    assert inputs[0].minval == 1
    assert inputs[0].maxval == 100
    assert inputs[0].step == 1
