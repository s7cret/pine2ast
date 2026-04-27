from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes, Severity
from pine2ast.semantic.builtin_registry import builtin_registry_coverage_report


def error_codes(src: str):
    return [d.code for d in parse_code(src).diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_builtin_coverage_backlog_is_closed_for_v210_namespaces():
    report = builtin_registry_coverage_report()
    missing = {
        ns: ns_report["missing_expected"]
        for ns, ns_report in report["namespaces"].items()
        if ns_report["missing_expected"]
    }
    assert missing == {}
    assert report["function_count"] >= 275


def test_drawing_and_string_backlog_members_are_registered():
    src = """//@version=6
indicator("draw registry")
x = str.tonumber("12.5")
l = line.new(bar_index, close, bar_index + 1, close)
lx = line.get_x1(l)
lab = label.new(bar_index, close, "x")
t = label.get_text(lab)
b = box.new(bar_index, high, bar_index + 1, low)
box.set_bottom(b, low)
tb = table.new(position.top_right, 1, 1)
table.set_position(tb, position.bottom_left)
poly = polyline.new()
polyline.delete(poly)
plot(x)
"""
    assert codes.UNKNOWN_BUILTIN_MEMBER not in error_codes(src)


def test_strategy_trade_comment_accessors_are_registered_and_script_checked():
    strategy_src = """//@version=6
strategy("trade comments")
entry = strategy.closedtrades.entry_comment(0)
openEntry = strategy.opentrades.entry_comment(0)
plot(close)
"""
    assert codes.UNKNOWN_BUILTIN_MEMBER not in error_codes(strategy_src)
    assert codes.STRATEGY_STATE_WRONG_SCRIPT_TYPE not in error_codes(strategy_src)

    indicator_src = """//@version=6
indicator("bad trade comments")
entry = strategy.closedtrades.entry_comment(0)
"""
    assert codes.STRATEGY_STATE_WRONG_SCRIPT_TYPE in error_codes(indicator_src)


def test_strict_builtin_namespace_does_not_flag_closed_registry_members():
    result = parse_code(
        """//@version=6
indicator("strict known")
x = str.tonumber("42")
plot(x)
""",
        ParseOptions(strict_builtin_namespaces=True),
    )
    assert not any(
        d.code == codes.UNKNOWN_BUILTIN_MEMBER and d.severity is Severity.ERROR
        for d in result.diagnostics
    )


def test_na_narrowing_is_scope_local_semantic_metadata():
    result = parse_code("""//@version=6
indicator("na narrowing")
float x = na
if not na(x)
    y = x + 1
z = x + 2
plot(z)
""")
    narrowed = [
        scope.non_na_symbols
        for scope in result.semantic_model.scopes
        if "x" in scope.non_na_symbols
    ]
    assert narrowed == [{"x"}]
    global_scope = result.semantic_model.scopes[0]
    assert "x" not in global_scope.non_na_symbols
    assert result.semantic_model.non_na_scopes
