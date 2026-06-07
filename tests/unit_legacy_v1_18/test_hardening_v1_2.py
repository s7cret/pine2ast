import pytest

from pine2ast.api import ParseOptions, parse_code
from pine2ast.diagnostics import Severity
from pine2ast.diagnostics import codes


def error_codes(src: str):
    result = parse_code(src, ParseOptions(run_semantic=True, collect_tokens=True))
    return result, [d.code for d in result.diagnostics if d.severity is Severity.ERROR]


def test_named_arg_keyword_series_parses():
    result, errs = error_codes(
        '//@version=6\nindicator("T")\nplot(series=close, color=color.red)\n'
    )
    assert result.ast is not None
    assert codes.SYNTAX_ERROR not in errs


def test_unknown_call_is_reported():
    _, errs = error_codes('//@version=6\nindicator("T")\nfoo(close)\n')
    assert codes.UNDECLARED_VARIABLE in errs


def test_bad_indent_is_reported_by_layout():
    _, errs = error_codes('//@version=6\nindicator("T")\nif close > open\n   x = 1\nplot(close)\n')
    assert codes.SYNTAX_ERROR in errs


@pytest.mark.xfail(reason="Trivia collection not yet implemented in lexer")
def test_trivia_comments_are_preserved():
    result = parse_code(
        '//@version=6\n// lead\nindicator("T") // tail\nplot(close)\n',
        ParseOptions(run_semantic=False, collect_tokens=True),
    )
    toks = result.tokens or []
    indicator = next(t for t in toks if t.text == "indicator")
    assert any(tr.kind == "COMMENT" and "lead" in tr.text for tr in indicator.leading_trivia)
    assert any(
        any(tr.kind == "COMMENT" and "tail" in tr.text for tr in t.trailing_trivia) for t in toks
    )


def test_common_registry_calls_parse_without_unknowns():
    src = """//@version=6
indicator("T")
len = input.int(14, title="Len")
ma = ta.ema(close, len)
arr = array.new<float>()
array.push(arr, ma)
plot(series=ma, title="MA", color=color.green)
"""
    _, errs = error_codes(src)
    assert codes.UNDECLARED_VARIABLE not in errs
    assert codes.UNKNOWN_PARAMETER not in errs
