from pine2ast import parse_code
from pine2ast.ast.nodes import FunctionDeclaration, TupleExpr, VarDeclaration
from pine2ast.diagnostics import codes
from pine2ast.semantic.extractors import (
    extract_inputs,
    extract_plots,
    extract_request_calls,
    extract_strategy_calls,
)


def diag_codes(src):
    return [d.code for d in parse_code(src).diagnostics]


def test_tuple_expression_function_return_is_ast_node():
    result = parse_code('''//@version=6
indicator("TupleExpr")
f(x) => [x, x + 1]
''')
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    fn = result.ast.items[0]
    assert isinstance(fn, FunctionDeclaration)
    assert isinstance(fn.body, TupleExpr)
    assert len(fn.body.elements) == 2


def test_switch_and_while_parse_and_break_is_allowed_in_loop():
    result = parse_code('''//@version=6
indicator("SwitchWhile")
trend = switch
    close > open => 1
    close < open => -1
    => 0
while close > open
    break
''')
    assert result.ok, [d.to_dict() for d in result.diagnostics]


def test_declaration_statement_in_local_block_is_semantic_error():
    codes_ = diag_codes('''//@version=6
indicator("Root")
if close > open
    indicator("Nested")
''')
    assert codes.DECLARATION_NOT_GLOBAL in codes_
    assert codes.MULTIPLE_DECLARATIONS in codes_


def test_unknown_declaration_named_argument_is_data_driven_error():
    codes_ = diag_codes('''//@version=6
indicator("X", invalid_name = true)
''')
    assert codes.UNKNOWN_PARAMETER in codes_


def test_history_reference_local_scope_warning_and_float_offset_error():
    codes_ = diag_codes('''//@version=6
indicator("History")
if close > open
    x = close
    y = x[1.5]
''')
    assert codes.HISTORY_LOCAL_SCOPE in codes_
    assert codes.HISTORY_OFFSET_NOT_INTEGER in codes_


def test_import_alias_member_call_is_external_not_undeclared():
    result = parse_code('''//@version=6
indicator("Import")
import user/Lib/1 as lib
x = lib.someFunction(close)
''')
    assert codes.UNDECLARED_VARIABLE not in [d.code for d in result.diagnostics]


def test_extractors_cover_optimizer_inputs_strategy_request_and_plots():
    result = parse_code('''//@version=6
strategy("S")
len = input.int(14, title = "Length", minval = 1, maxval = 100, step = 1)
sec = request.security(syminfo.tickerid, "D", close)
strategy.entry("L", strategy.long)
plot(sec)
''')
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    inputs = extract_inputs(result.ast, result.semantic_model)
    assert len(inputs) == 1
    assert inputs[0].title == "Length"
    assert inputs[0].default_value == 14
    assert inputs[0].minval == 1
    assert inputs[0].maxval == 100
    assert inputs[0].step == 1
    assert [c.name for c in extract_strategy_calls(result.ast)] == ["strategy.entry"]
    assert len(extract_request_calls(result.ast)) == 1
    assert len(extract_plots(result.ast)) == 1


def test_input_extractor_can_use_declared_variable_name_when_no_title():
    result = parse_code('''//@version=6
indicator("Inputs")
length = input.int(20)
''')
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    decl = result.ast.items[0]
    assert isinstance(decl, VarDeclaration)
    inputs = extract_inputs(result.ast, result.semantic_model)
    assert inputs[0].name == "length"
