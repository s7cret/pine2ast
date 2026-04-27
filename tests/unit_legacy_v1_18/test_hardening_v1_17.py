from pine2ast.api import ParseOptions, parse_code
from pine2ast.ast.nodes import Block, MethodDeclaration


def _error_codes(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def _error_messages(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [(d.code, d.message) for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_multiline_method_body_is_preserved_as_block():
    result = parse_code("""//@version=6
indicator("T")
type Pivot
    float y
method get(Pivot p) =>
    p.y
var Pivot p = Pivot.new(close)
plot(p.get())
""", ParseOptions(run_semantic=True))
    method = next(item for item in result.ast.items if isinstance(item, MethodDeclaration))
    assert isinstance(method.body, Block)
    assert _error_codes("""//@version=6
indicator("T")
type Pivot
    float y
method get(Pivot p) =>
    p.y
var Pivot p = Pivot.new(close)
plot(p.get())
""") == []


def test_user_function_return_type_is_used_for_typed_assignment():
    codes = _error_codes("""//@version=6
indicator("T")
f() => "bad"
int x = f()
plot(close)
""")
    assert "P2A1210" in codes
    assert _error_codes("""//@version=6
indicator("T")
f() => 1.0
float x = f()
plot(x)
""") == []


def test_udt_method_return_type_is_used_for_typed_assignment():
    codes = _error_codes("""//@version=6
indicator("T")
type Pivot
    float y
method get(Pivot p) =>
    p.y
var Pivot p = Pivot.new(close)
int x = p.get()
plot(close)
""")
    assert "P2A1210" in codes
    assert _error_codes("""//@version=6
indicator("T")
type Pivot
    float y
method get(Pivot p) =>
    p.y
var Pivot p = Pivot.new(close)
float x = p.get()
plot(x)
""") == []


def test_udt_field_access_type_is_used_for_typed_assignment():
    codes = _error_codes("""//@version=6
indicator("T")
type Pivot
    float y
var Pivot p = Pivot.new(close)
int x = p.y
plot(close)
""")
    assert "P2A1210" in codes
    assert _error_codes("""//@version=6
indicator("T")
type Pivot
    float y
var Pivot p = Pivot.new(close)
float x = p.y
plot(x)
""") == []


def test_conditional_branch_type_mismatch_is_visible_to_typed_assignment():
    messages = _error_messages("""//@version=6
indicator("T")
int x = close > open ? 1 : "bad"
plot(close)
""")
    assert any(code == "P2A1210" and "union<int,string>" in message for code, message in messages)
    assert _error_codes("""//@version=6
indicator("T")
float x = close > open ? 1 : 2.5
plot(x)
""") == []


def test_mixed_numeric_array_literal_widens_to_array_float():
    assert _error_codes("""//@version=6
indicator("T")
array<float> xs = [1, 2.0]
plot(close)
""") == []


def test_mixed_non_numeric_array_literal_still_rejects_typed_array():
    codes = _error_codes("""//@version=6
indicator("T")
array<float> xs = [1, "bad"]
plot(close)
""")
    assert "P2A1210" in codes
