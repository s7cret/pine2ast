from pine2ast import parse_code
from pine2ast.ast.nodes import TupleDeclaration, VarDeclaration


def assert_ok(src):
    result = parse_code(src)
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    return result


def test_nested_function_call_line_wrapping_fixture():
    result = assert_ok('''//@version=6
indicator("Nested")
x = ta.sma(
    request.security(
        syminfo.tickerid,
        "D",
        close
    ),
    20
)
''')
    assert isinstance(result.ast.items[0], VarDeclaration)


def test_multiline_tuple_declaration_line_wrapping_fixture():
    result = assert_ok('''//@version=6
indicator("Tuple")
[basis,
 upper,
 lower] = ta.bb(
    close,
    20,
    2
)
''')
    assert isinstance(result.ast.items[0], TupleDeclaration)


def test_ternary_line_wrapping_fixture():
    result = assert_ok('''//@version=6
indicator("Ternary")
c = close > open ?
  color.green :
  color.red
''')
    assert isinstance(result.ast.items[0], VarDeclaration)


def test_comments_only_inside_wrapped_call_do_not_break_layout():
    result = assert_ok('''//@version=6
indicator("Comments")
x = ta.sma(
    close,
    // length comment
    20
)
''')
    assert isinstance(result.ast.items[0], VarDeclaration)
