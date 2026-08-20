from pine2ast.lexer import Lexer, TokenKind
from pine2ast.layout import LayoutProcessor


def layout_kinds(src):
    return [t.kind for t in LayoutProcessor().process(Lexer(src).lex().tokens).tokens]


def test_indent_dedent():
    kinds = layout_kinds("""if close > open
    x = 1
    y = 2
z = 3
""")
    assert TokenKind.INDENT in kinds
    assert TokenKind.DEDENT in kinds


def test_line_wrapping_after_operator_no_indent():
    kinds = layout_kinds("""x = open + high +
  low + close
""")
    assert TokenKind.INDENT not in kinds
