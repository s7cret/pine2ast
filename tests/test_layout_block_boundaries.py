"""Synthetic layout tokens must not consume the following real token."""

import pytest


def library(body):
    return f'//@version=6\nlibrary("Lib")\n{body}\n'


@pytest.mark.parametrize(
    "tail", ["export f(float x)=>helper(x)", "f(float x)=>helper(x)", "plot(helper(close))"]
)
def test_dedent_is_zero_width_and_does_not_steal_a_sibling_token(tail):
    from pine2ast.api import ParseOptions, ParsePipeline
    from pine2ast.lexer.token import TokenKind

    source = library(body="helper(float x)=>\n    if x>0\n        x\n    else\n        0\n" + tail)
    result = ParsePipeline(ParseOptions(run_semantic=False, collect_tokens=True)).parse(source)
    assert result.ok
    fn = next(n for n in result.ast.items if n.kind == "FunctionDeclaration")
    assert tail not in source[fn.span.start_offset : fn.span.end_offset]
    assert "export" not in source[fn.span.start_offset : fn.span.end_offset]
    for token in result.tokens:
        if token.kind is TokenKind.DEDENT:
            assert token.span.start_offset == token.span.end_offset
