from pine2ast import ParseOptions, parse_code
from pine2ast.parser import Parser, ParserResult
from pine2ast.parser.base import BaseParser
from pine2ast.parser.declarations import DeclarationsMixin
from pine2ast.parser.expressions import ExpressionsMixin
from pine2ast.parser.parser import Parser as FacadeParser
from pine2ast.parser.statements import StatementsMixin


def test_public_parser_imports_remain_stable():
    assert Parser is FacadeParser
    assert ParserResult.__name__ == "ParserResult"
    assert issubclass(Parser, BaseParser)
    assert issubclass(Parser, DeclarationsMixin)
    assert issubclass(Parser, ExpressionsMixin)
    assert issubclass(Parser, StatementsMixin)


def test_parser_facade_contains_no_behavior_methods():
    behavior_methods = [
        name for name in FacadeParser.__dict__ if name.startswith("parse_") or name == "parse"
    ]
    assert behavior_methods == []


def test_modular_parser_preserves_history_reference_contract():
    src = """//@version=6
indicator("History")
prev = close[1]
"""
    res = parse_code(src, ParseOptions(run_semantic=False))
    assert res.ast is not None
    as_text = str(res.ast.to_dict())
    assert "HistoryRefExpr" in as_text
    assert "Array" not in as_text
