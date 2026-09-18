"""Stage 2.7 producer matrix: if/switch values, loops as values, once structure."""

from __future__ import annotations

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle


def _src(body: str, version: int = 6) -> str:
    header = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{header}("s27")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
def test_stage27_if_switch_for_while_for_in_parse_as_values(version):
    code = _src(
        "enum Side\n    buy\n    sell\n"
        "type Box\n    int n=0\n"
        "a=if close>1\n    2\nelse\n    3\n"
        "b=switch close>1\n    true => Side.sell\n    false => Side.buy\n"
        "c=for i=1 to 3\n    Box.new(i)\n"
        "d=while close<0\n    1\n"
        "xs=array.new<int>(2, 1)\n"
        "e=for x in xs\n    x\n"
        "plot(a)\nplot(c.n)\nplot(e)",
        version,
    )
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    build_consumer_bundle(code)


@pytest.mark.parametrize("version", [3, 4, 5, 6])
def test_stage27_break_continue_empty_and_nested_loops_parse(version):
    code = _src(
        "n=0\n"
        "for i=1 to 0\n    n:=n+1\n"
        "for i=1 to 3\n    if i==2\n        continue\n    if i==3\n        break\n    n:=n+i\n"
        "for i=1 to 2\n    for j=1 to 2\n        n:=n+1\n"
        "plot(n)",
        version,
    )
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics


@pytest.mark.parametrize("version", range(1, 6))
def test_stage27_once_structure_not_available_before_v6(version):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(_src("once\n    x=1\nplot(1)", version))


def test_stage27_once_is_statement_not_expression():
    parsed = parse_code(_src("x=once\n    1\nplot(x)"))
    assert not parsed.ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(_src("x=once\n    1\nplot(x)"))


@pytest.mark.parametrize(
    "body",
    [
        "for i=1 to 3\n    strategy(\"inner\")",
        "once na\n    x=1",
        "once\n    plot(close)",
    ],
)
def test_stage27_illegal_control_bodies_fail_closed(body):
    parsed = parse_code(_src(body))
    assert not parsed.ok
