from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.semantic.extractors import extract_inputs


def diag_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics]


def test_forward_function_reference_is_resolved_by_global_predeclare():
    src = '''//@version=6
indicator("forward")
x = f(close)
f(float v) => v + 1
plot(x)
'''
    codes_seen = diag_codes(src)
    assert codes.UNDECLARED_VARIABLE not in codes_seen


def test_user_function_named_parameter_validation():
    src = '''//@version=6
indicator("user-fn")
f(float v) => v + 1
x = f(price = close)
'''
    codes_seen = diag_codes(src)
    assert codes.UNKNOWN_PARAMETER in codes_seen
    assert codes.ARGUMENT_COUNT in codes_seen


def test_import_alias_external_call_does_not_error_on_unresolved_member():
    src = '''//@version=6
indicator("imports")
import user/Lib/1 as lib
x = lib.someFunction(close)
plot(x)
'''
    result = parse_code(src)
    codes_seen = [d.code for d in result.diagnostics]
    assert codes.UNDECLARED_VARIABLE not in codes_seen
    assert result.semantic_model is not None
    assert "lib" in result.semantic_model.symbols


def test_type_field_defaults_are_semantically_visited():
    src = '''//@version=6
indicator("type-default")
type Pivot
    float y = missingValue
'''
    assert codes.UNDECLARED_VARIABLE in diag_codes(src)


def test_expanded_forbidden_builtin_in_local_block():
    src = '''//@version=6
indicator("local")
if close > open
    barcolor(color.red)
'''
    assert codes.BUILTIN_FORBIDDEN_LOCAL in diag_codes(src)


def test_input_options_extractor_from_tuple_expr():
    src = '''//@version=6
indicator("inputs")
mode = input.string("Both", title = "Mode", options = ["Long", "Short", "Both"])
'''
    result = parse_code(src)
    inputs = extract_inputs(result.ast, result.semantic_model)
    assert len(inputs) == 1
    assert inputs[0].name == "mode"
    assert inputs[0].options == ["Long", "Short", "Both"]


def test_ast_node_limit_returns_fatal():
    result = parse_code('''//@version=6
indicator("tiny")
plot(close)
''', ParseOptions(max_ast_nodes=1))
    assert result.ast is None
    assert any(d.code == codes.TOO_MANY_AST_NODES for d in result.diagnostics)
