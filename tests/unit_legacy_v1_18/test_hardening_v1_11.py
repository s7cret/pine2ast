from pine2ast.api import ParseOptions, parse_code


def _errors(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_unknown_enum_member_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
enum Trend
    UP
    DOWN
x = Trend.SIDEWAYS
plot(close)
""")
    assert "P2A1605" in codes


def test_known_enum_member_validates_cleanly():
    assert _errors("""//@version=6
indicator("T")
enum Trend
    UP
    DOWN
x = Trend.UP
plot(close)
""") == []


def test_unknown_udt_field_access_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    int x
    float y
p = Pivot.new(bar_index, close)
z = p.missing
plot(p.y)
""")
    assert "P2A1605" in codes


def test_unknown_udt_field_reassignment_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    int x
    float y
p = Pivot.new(bar_index, close)
p.missing := high
plot(p.y)
""")
    assert "P2A1605" in codes


def test_udt_constructor_missing_required_field_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    int x
    float y
p = Pivot.new(bar_index)
plot(close)
""")
    assert "P2A1404" in codes


def test_udt_constructor_named_fields_validate_cleanly():
    assert _errors("""//@version=6
indicator("T")
type Pivot
    int x
    float y
p = Pivot.new(y=close, x=bar_index)
plot(p.y)
""") == []


def test_duplicate_for_in_targets_are_rejected_but_underscore_is_ignored():
    codes = _errors("""//@version=6
indicator("T")
for [i, i, _] in array.from(1, 2, 3)
    x = i
plot(close)
""")
    assert "P2A1102" in codes


def test_for_in_underscore_target_does_not_leak_symbol():
    codes = _errors("""//@version=6
indicator("T")
for [_, v] in array.from(1, 2, 3)
    x = v
plot(_)
""")
    assert "P2A1101" in codes
