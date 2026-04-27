from pine2ast import ParseOptions, parse_code
from pine2ast.ast.nodes import BinaryExpr, ConditionalExpr, HistoryRefExpr, VarDeclaration


def first_item_expr(src):
    res = parse_code('//@version=6\nindicator("x")\n' + src, ParseOptions(run_semantic=False))
    assert res.ast is not None, res.diagnostics
    item = res.ast.items[0]
    return item.initializer if isinstance(item, VarDeclaration) else item.expression


def test_precedence():
    expr = first_item_expr("x = 1 + 2 * 3\n")
    assert isinstance(expr, BinaryExpr)
    assert expr.op == "+"
    assert isinstance(expr.right, BinaryExpr)


def test_ternary_and_history():
    expr = first_item_expr("x = close > open ? close[1] : open\n")
    assert isinstance(expr, ConditionalExpr)
    assert isinstance(expr.if_true, HistoryRefExpr)
