from pine2ast.api import ParseOptions, parse_code


def _errors(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_generic_array_constructor_infers_type_for_member_validation():
    codes = _errors("""//@version=6
indicator("T")
xs = array.new<float>()
xs.nope(close)
plot(close)
""")
    assert "P2A1106" in codes


def test_generic_array_constructor_allows_known_method_after_inference():
    assert _errors("""//@version=6
indicator("T")
xs = array.new<float>()
xs.push(close)
plot(close)
""") == []


def test_array_from_infers_element_type_for_member_validation():
    codes = _errors("""//@version=6
indicator("T")
xs = array.from(1, 2, 3)
xs.nope(4)
plot(close)
""")
    assert "P2A1106" in codes


def test_explicit_scalar_type_mismatch_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
int x = "bad"
plot(close)
""")
    assert "P2A1210" in codes


def test_numeric_widening_int_to_float_is_allowed():
    assert _errors("""//@version=6
indicator("T")
float x = 1
plot(x)
""") == []


def test_explicit_generic_type_mismatch_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
array<float> xs = array.new<int>()
plot(close)
""")
    assert "P2A1210" in codes


def test_udt_field_default_type_mismatch_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    int x = "bad"
plot(close)
""")
    assert "P2A1210" in codes


def test_function_parameter_default_type_mismatch_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
f(int x = "bad") =>
    x
plot(close)
""")
    assert "P2A1210" in codes


def test_map_and_matrix_generic_constructor_inference():
    assert _errors("""//@version=6
indicator("T")
mx = matrix.new<float>(2, 2, 0.0)
kv = map.new<string, float>()
mx.set(0, 0, close)
kv.put("last", close)
plot(close)
""") == []
