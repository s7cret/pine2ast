from pine2ast import parse_code
from pine2ast.diagnostics import codes


def diagnostic_codes(src: str) -> list[str]:
    return [d.code for d in parse_code(src).diagnostics]


def test_user_function_argument_type_mismatch_is_reported():
    src = '''//@version=6
indicator("T")
f(int x, string label="ok") => x
y = f("bad")
plot(close)
'''
    assert codes.TYPE_MISMATCH in diagnostic_codes(src)


def test_user_function_unknown_and_missing_named_arguments_are_reported():
    unknown = '''//@version=6
indicator("T")
f(int x, string label="ok") => x
y = f(1, bad=2)
plot(close)
'''
    missing = '''//@version=6
indicator("T")
f(int x, string label="ok") => x
y = f()
plot(close)
'''
    assert codes.UNKNOWN_PARAMETER in diagnostic_codes(unknown)
    assert codes.ARGUMENT_COUNT in diagnostic_codes(missing)


def test_user_function_positional_and_named_duplicate_parameter_is_reported():
    src = '''//@version=6
indicator("T")
f(int x, string label="ok") => x
y = f(1, x=2)
plot(close)
'''
    assert codes.DUPLICATE_NAMED_ARGUMENT in diagnostic_codes(src)


def test_udt_constructor_field_type_mismatch_is_reported():
    src = '''//@version=6
indicator("T")
type Pivot
    int x
    float y
p = Pivot.new(x="bad", y=close)
plot(close)
'''
    assert codes.TYPE_MISMATCH in diagnostic_codes(src)


def test_udt_method_argument_type_mismatch_is_reported():
    src = '''//@version=6
indicator("T")
type Pivot
    int x
    float y
method move(Pivot p, int dx, float dy=1.0) =>
    p.x + dx
p = Pivot.new(1, close)
z = p.move("bad")
plot(close)
'''
    assert codes.TYPE_MISMATCH in diagnostic_codes(src)


def test_valid_user_function_constructor_and_method_calls_stay_clean():
    src = '''//@version=6
indicator("T")
f(int x, string label="ok") => x
y = f(1, label="ok")
type Pivot
    int x
    float y
method move(Pivot p, int dx, float dy=1.0) =>
    p.x + dx
p = Pivot.new(x=1, y=close)
z = p.move(1, dy=2)
plot(close)
'''
    assert diagnostic_codes(src) == []
