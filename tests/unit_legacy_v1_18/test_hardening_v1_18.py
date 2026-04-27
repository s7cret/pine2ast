from pine2ast.api import ParseOptions, parse_code


def _errors(source: str):
    result = parse_code(source, ParseOptions(run_semantic=True))
    return [(d.code, d.message) for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def _codes(source: str):
    return [code for code, _ in _errors(source)]


def test_tuple_builtins_define_typed_targets():
    assert _codes("""//@version=6
indicator("T")
[macdLine, signalLine, histLine] = ta.macd(close, 12, 26, 9)
float x = macdLine
plot(x)
""") == []
    assert "P2A1210" in _codes("""//@version=6
indicator("T")
[middle, upper, lower] = ta.bb(close, 20, 2)
int x = upper
plot(close)
""")


def test_tuple_destructuring_rejects_non_tuple_and_wrong_arity():
    codes = _codes("""//@version=6
indicator("T")
[a, b] = close
plot(close)
""")
    assert "P2A1411" in codes
    codes = _codes("""//@version=6
indicator("T")
[a, b] = ta.macd(close, 12, 26, 9)
plot(a)
""")
    assert "P2A1410" in codes


def test_user_function_tuple_return_drives_destructuring_types():
    assert _codes("""//@version=6
indicator("T")
f() => [1, 2.5]
[a, b] = f()
float x = b
plot(x)
""") == []
    codes = _codes("""//@version=6
indicator("T")
f() => [1, 2.5]
[a, b] = f()
int x = b
plot(close)
""")
    assert "P2A1210" in codes


def test_request_security_tuple_expression_preserves_element_types():
    assert _codes("""//@version=6
indicator("T")
[h, l] = request.security(syminfo.tickerid, timeframe.period, [high, low])
float spread = h - l
plot(spread)
""") == []
    codes = _codes("""//@version=6
indicator("T")
[h, l] = request.security(syminfo.tickerid, timeframe.period, [high, low])
int x = h
plot(close)
""")
    assert "P2A1210" in codes
