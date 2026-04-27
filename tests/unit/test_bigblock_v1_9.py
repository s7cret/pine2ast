from pathlib import Path

from pine2ast import parse_code
from pine2ast.diagnostics import codes
from pine2ast.corpus import validate_corpus


def diag_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics]


def error_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_explicit_var_initializer_type_mismatch_errors():
    src = '''//@version=6
indicator("typed var")
int x = "bad"
'''
    assert codes.TYPE_MISMATCH in diag_codes(src)


def test_explicit_var_initializer_allows_int_to_float_widening():
    src = '''//@version=6
indicator("typed var")
float x = 1
plot(x)
'''
    assert codes.TYPE_MISMATCH not in error_codes(src)


def test_reassignment_type_mismatch_errors():
    src = '''//@version=6
indicator("reassign")
int x = 1
x := "bad"
'''
    assert codes.TYPE_MISMATCH in diag_codes(src)


def test_compound_assignment_requires_numeric_target():
    src = '''//@version=6
indicator("compound")
string x = "a"
x += "b"
'''
    assert codes.TYPE_MISMATCH in diag_codes(src)


def test_function_param_default_type_mismatch_errors():
    src = '''//@version=6
indicator("param default")
f(int x = "bad") => x
plot(close)
'''
    assert codes.TYPE_MISMATCH in diag_codes(src)


def test_method_param_default_type_mismatch_errors():
    src = '''//@version=6
indicator("method param default")
type Pivot
    float y
method score(Pivot p, int weight = "bad") => p.y
p = Pivot.new(close)
plot(p.score())
'''
    assert codes.TYPE_MISMATCH in diag_codes(src)


def test_udt_field_default_type_mismatch_errors():
    src = '''//@version=6
indicator("field default")
type Pivot
    float y = "bad"
p = Pivot.new(close)
'''
    assert codes.TYPE_MISMATCH in diag_codes(src)


def test_for_range_requires_int_like_bounds():
    src = '''//@version=6
indicator("loop bounds")
for i = 0.5 to 10
    x = i
'''
    assert codes.LOOP_RANGE_TYPE in diag_codes(src)


def test_switch_without_expression_requires_bool_cases():
    src = '''//@version=6
indicator("switch bool")
switch
    close => 1
    => 0
'''
    assert codes.NON_BOOL_CONDITION in diag_codes(src)


def test_switch_expression_case_type_mismatch_errors():
    src = '''//@version=6
indicator("switch type")
switch close
    "bad" => 1
    => 0
'''
    assert codes.SWITCH_CASE_TYPE in diag_codes(src)


def test_switch_expression_case_type_match_is_clean():
    src = '''//@version=6
indicator("switch ok")
mode = input.string("fast", options = ["fast", "slow"])
value = switch mode
    "fast" => close
    "slow" => open
    => hl2
plot(value)
'''
    assert codes.SWITCH_CASE_TYPE not in error_codes(src)


def test_v19_real_world_corpus_still_clean():
    result = validate_corpus(Path(__file__).absolute().parents[1] / "fixtures" / "real_world" / "81_v19_switch_request_tuple.pine")
    assert result["file_count"] == 1
    assert result["ok_count"] == result["file_count"]
    assert result["error_count"] == 0


def test_request_security_propagates_expression_type_to_assignment():
    src = '''//@version=6
indicator("security type")
float higher = request.security(syminfo.tickerid, "D", close)
plot(higher)
'''
    assert codes.TYPE_MISMATCH not in error_codes(src)


def test_request_security_tuple_type_unpacks():
    src = '''//@version=6
indicator("security tuple")
[o, h] = request.security(syminfo.tickerid, "D", [open, high])
float x = o + h
plot(x)
'''
    assert codes.TYPE_MISMATCH not in error_codes(src)


def test_map_get_infers_value_type_for_typed_map():
    src = '''//@version=6
indicator("map get")
var map<string, float> weights = map.new<string, float>()
w = weights.get("risk")
float x = w
plot(x)
'''
    assert codes.TYPE_MISMATCH not in error_codes(src)


def test_matrix_get_infers_element_type_for_typed_matrix():
    src = '''//@version=6
indicator("matrix get")
var matrix<float> m = matrix.new<float>(2, 2, 0.0)
x = matrix.get(m, 0, 0)
float y = x
plot(y)
'''
    assert codes.TYPE_MISMATCH not in error_codes(src)


def test_package_module_entrypoint_exists():
    import pine2ast.__main__ as main_mod
    assert callable(main_mod.main)
