from pine2ast import ast_to_dict, parse_code


def test_basic_indicator_smoke():
    result = parse_code("""//@version=6
indicator("My script", overlay = true)
plot(close)
""")
    assert result.ast is not None
    assert result.ast.version == 6
    assert result.ast.declaration.script_type == "indicator"
    assert ast_to_dict(result.ast)["kind"] == "Program"
