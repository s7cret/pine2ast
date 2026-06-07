from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import codes


def _error_codes(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_array_push_rejects_wrong_element_type():
    src = """//@version=6
indicator("T")
array<float> xs = array.new<float>()
xs.push("bad")
plot(close)
"""
    assert codes.COLLECTION_ELEMENT_TYPE in _error_codes(src)


def test_array_get_infers_element_type_for_typed_assignment():
    bad = """//@version=6
indicator("T")
array<float> xs = array.new<float>()
int y = xs.get(0)
plot(close)
"""
    ok = """//@version=6
indicator("T")
array<float> xs = array.new<float>()
float y = xs.get(0)
plot(close)
"""
    assert codes.TYPE_MISMATCH in _error_codes(bad)
    assert _error_codes(ok) == []


def test_map_put_key_and_value_types_are_checked():
    bad_value = """//@version=6
indicator("T")
map<string,float> m = map.new<string,float>()
m.put("a", "bad")
plot(close)
"""
    bad_key = """//@version=6
indicator("T")
map<string,float> m = map.new<string,float>()
m.get(1)
plot(close)
"""
    assert codes.COLLECTION_ELEMENT_TYPE in _error_codes(bad_value)
    assert codes.COLLECTION_ELEMENT_TYPE in _error_codes(bad_key)


def test_map_get_infers_value_type_for_typed_assignment():
    bad = """//@version=6
indicator("T")
map<string,float> m = map.new<string,float>()
int y = m.get("a")
plot(close)
"""
    ok = """//@version=6
indicator("T")
map<string,float> m = map.new<string,float>()
float y = m.get("a")
plot(close)
"""
    assert codes.TYPE_MISMATCH in _error_codes(bad)
    assert _error_codes(ok) == []


def test_matrix_set_and_get_use_element_type():
    bad_set = """//@version=6
indicator("T")
matrix<float> m = matrix.new<float>()
m.set(0, 0, "bad")
plot(close)
"""
    bad_get = """//@version=6
indicator("T")
matrix<float> m = matrix.new<float>()
int y = m.get(0, 0)
plot(close)
"""
    ok = """//@version=6
indicator("T")
matrix<float> m = matrix.new<float>()
m.set(0, 0, close)
float y = m.get(0, 0)
plot(close)
"""
    assert codes.COLLECTION_ELEMENT_TYPE in _error_codes(bad_set)
    assert codes.TYPE_MISMATCH in _error_codes(bad_get)
    assert _error_codes(ok) == []
