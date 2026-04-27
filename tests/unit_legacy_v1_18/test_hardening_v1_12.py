from pine2ast.api import ParseOptions, parse_code


def _errors(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_udt_unknown_method_call_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    int x
Pivot p = Pivot.new(1)
p.nope()
plot(close)
""")
    assert "P2A1608" in codes


def test_udt_declared_method_call_validates_cleanly():
    assert _errors("""//@version=6
indicator("T")
type Pivot
    int x
method inc(Pivot p) =>
    p.x + 1
Pivot p = Pivot.new(1)
y = p.inc()
plot(y)
""") == []


def test_udt_field_is_not_callable():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    int x
Pivot p = Pivot.new(1)
y = p.x()
plot(close)
""")
    assert "P2A1106" in codes


def test_udt_constructor_defaults_allow_omitted_fields():
    assert _errors("""//@version=6
indicator("T")
type Pivot
    int x = 0
    float y
Pivot p = Pivot.new(y=close)
plot(p.y)
""") == []


def test_udt_constructor_duplicate_positional_and_named_field_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    int x
    float y
Pivot p = Pivot.new(1, x=2, y=close)
plot(close)
""")
    assert "P2A1401" in codes


def test_method_declaration_inside_block_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
if close > open
    method bad(float x) =>
        x
plot(close)
""")
    assert "P2A1601" in codes


def test_unknown_member_call_on_typed_scalar_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
float x = close
x.foo()
plot(close)
""")
    assert "P2A1106" in codes


def test_known_array_method_shorthand_validates_cleanly():
    assert _errors("""//@version=6
indicator("T")
var array<float> xs = array.new<float>()
xs.push(close)
plot(close)
""") == []


def test_unknown_array_method_shorthand_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
var array<float> xs = array.new<float>()
xs.nope(close)
plot(close)
""")
    assert "P2A1106" in codes
