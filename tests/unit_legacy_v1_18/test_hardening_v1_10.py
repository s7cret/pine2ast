from pine2ast.api import ParseOptions, parse_code


def _errors(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_unknown_type_in_variable_declaration_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
Foobar x = na
plot(close)
""")
    assert "P2A1604" in codes


def test_unknown_type_in_udt_field_is_rejected():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    Foobar x
plot(close)
""")
    assert "P2A1604" in codes


def test_unknown_type_in_function_parameter_is_rejected_once():
    codes = _errors("""//@version=6
indicator("T")
f(Foobar x) =>
    x
plot(close)
""")
    assert codes.count("P2A1604") == 1


def test_duplicate_udt_fields_are_rejected():
    codes = _errors("""//@version=6
indicator("T")
type Pivot
    int x
    float x
plot(close)
""")
    assert "P2A1102" in codes


def test_duplicate_enum_members_are_rejected():
    codes = _errors("""//@version=6
indicator("T")
enum Trend
    UP
    UP
plot(close)
""")
    assert "P2A1102" in codes


def test_valid_recursive_user_types_and_generics_validate_cleanly():
    assert _errors("""//@version=6
indicator("T")
type Pivot
    int x
    float y
var array<Pivot> pivots = array.new<Pivot>()
p = Pivot.new(bar_index, close)
array.push(pivots, p)
plot(p.y)
""") == []
