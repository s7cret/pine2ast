"""Stage 2.9 producer matrix: versioned builtin names, NA and qualifier forms."""

from __future__ import annotations

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle


def _src(body: str, version: int) -> str:
    header = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{header}("s29")\n{body}\n'


@pytest.mark.parametrize("version", range(1, 5))
def test_stage29_math_namespace_not_backported(version):
    result = parse_code(_src("plot(math.abs(-1))", version))
    assert not result.ok


@pytest.mark.parametrize("version", [5, 6])
def test_stage29_math_namespace_and_na_nz_parse(version):
    code = _src("plot(math.abs(-1))\nplot(nz(na, 2))\nplot(na(close[1]))", version)
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics
    build_consumer_bundle(code)


@pytest.mark.parametrize("version", [5, 6])
def test_stage29_collection_and_string_builtins_parse(version):
    code = _src(
        'plot(str.length("ab"))\n'
        "xs=array.new<int>(1, 2)\nplot(array.size(xs))\n"
        "m=map.new<string,int>()\nplot(map.size(m))\n"
        "plot(color.r(color.red))",
        version,
    )
    parsed = parse_code(code)
    assert parsed.ok, parsed.diagnostics


def test_stage29_unknown_builtin_is_not_accepted():
    result = parse_code(_src("plot(math.not_a_builtin(1))", 6))
    assert not result.ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(_src("plot(math.not_a_builtin(1))", 6))
