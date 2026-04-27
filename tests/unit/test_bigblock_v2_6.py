from pine2ast import parse_code
from pine2ast.diagnostics import codes


def error_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_duplicate_enum_member_is_diagnosed():
    src = """//@version=6
indicator("enum duplicate")
enum Trend
    UP
    UP
"""
    assert codes.REDECLARATION in error_codes(src)


def test_unknown_enum_member_is_diagnosed():
    src = """//@version=6
indicator("enum unknown")
enum Trend
    UP
x = Trend.DOWN
"""
    assert codes.UNKNOWN_FIELD in error_codes(src)


def test_udt_field_call_is_not_callable():
    src = """//@version=6
indicator("field callable")
type Pivot
    float y
p = Pivot.new(close)
x = p.y()
"""
    assert codes.TYPE_MISMATCH in error_codes(src)


def test_unknown_scalar_method_is_diagnosed():
    src = """//@version=6
indicator("unknown scalar method")
x = close.foo()
"""
    assert codes.UNKNOWN_FIELD in error_codes(src)


def test_tuple_destructuring_rejects_non_tuple_initializer():
    src = """//@version=6
indicator("tuple non tuple")
[a, b] = close
"""
    assert codes.TYPE_MISMATCH in error_codes(src)


def test_tuple_destructuring_rejects_underflow_against_builtin_tuple_return():
    src = """//@version=6
indicator("tuple underflow")
[a, b] = ta.macd(close, 12, 26, 9)
"""
    assert codes.ARGUMENT_COUNT in error_codes(src)


def test_for_in_underscore_does_not_leak_symbol():
    src = """//@version=6
indicator("underscore")
values = array.from(1.0, 2.0)
for [_, item] in values
    x = item
plot(_)
"""
    assert codes.UNDECLARED_VARIABLE in error_codes(src)


def test_unary_not_requires_bool_operand():
    src = """//@version=6
indicator("not bool")
x = not close
"""
    assert codes.TYPE_MISMATCH in error_codes(src)


def test_map_get_validates_key_type_function_form():
    src = """//@version=6
indicator("map get key")
var map<string, float> weights = map.new<string, float>()
x = map.get(weights, 123)
"""
    assert codes.COLLECTION_ELEMENT_TYPE in error_codes(src)


def test_map_get_validates_key_type_method_form():
    src = """//@version=6
indicator("map method get key")
var map<string, float> weights = map.new<string, float>()
x = weights.get(123)
"""
    assert codes.COLLECTION_ELEMENT_TYPE in error_codes(src)


def test_array_from_mixed_nonnumeric_rejects_typed_assignment():
    src = """//@version=6
indicator("mixed array")
array<float> xs = array.from(1.0, "bad")
"""
    assert codes.TYPE_MISMATCH in error_codes(src)


def test_array_literal_alias_is_available_without_changing_json_kind():
    from pine2ast.ast.nodes import ArrayLiteralExpr, TupleExpr

    assert ArrayLiteralExpr is TupleExpr
