from pine2ast.lexer import Lexer, TokenKind


def kinds_values(src):
    return [(t.kind, t.value) for t in Lexer(src).lex().tokens]


def test_number_literals():
    vals = kinds_values('1\n3.14\n.5\n3e8\n6.02e23\n1.6e-19\n')
    assert (TokenKind.INTEGER, 1) in vals
    assert (TokenKind.FLOAT, 3.14) in vals
    assert (TokenKind.FLOAT, 0.5) in vals
    assert (TokenKind.FLOAT, 3e8) in vals


def test_strings_and_color_and_annotation():
    res = Lexer('''//@version=6
#FF000080
"abc"
''' + "'''multi\nline'''" + "\n").lex()
    assert not res.diagnostics
    assert any(t.kind is TokenKind.VERSION_ANNOTATION for t in res.tokens)
    assert any(t.kind is TokenKind.COLOR and t.value == "#FF000080" for t in res.tokens)
    assert any(t.kind is TokenKind.STRING and t.value == "multi\nline" for t in res.tokens)
