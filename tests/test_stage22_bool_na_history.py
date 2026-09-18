from __future__ import annotations

from pine2ast import ParseOptions, parse_code


def diagnostics(source: str) -> set[str]:
    result = parse_code(source, ParseOptions(max_diagnostics=100))
    return {item.code for item in result.diagnostics}


def assert_ok(source: str) -> None:
    result = parse_code(source, ParseOptions(max_diagnostics=100))
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]


def test_v5_numeric_condition_remains_accepted() -> None:
    assert_ok('//@version=5\nindicator("v5")\nif bar_index\n    x = 1\n')


def test_v6_numeric_condition_requires_explicit_bool() -> None:
    codes = diagnostics('//@version=6\nindicator("v6")\nif bar_index\n    x = 1\n')
    assert "P2A1201" in codes
    assert_ok('//@version=6\nindicator("v6")\nif bool(bar_index)\n    x = 1\n')


def test_bool_and_int_cast_signatures_are_bound() -> None:
    for version in range(1, 7):
        declaration = 'indicator' if version >= 5 else 'study'
        assert_ok(f'//@version={version}\n{declaration}("casts")\nb = bool(1)\ni = int(1.5)\n')


def test_history_dynamic_int_offset_is_accepted() -> None:
    assert_ok('//@version=6\nindicator("hist")\nint n = bar_index % 3\nx = close[n]\n')


def test_history_non_int_offsets_fail_closed() -> None:
    for expr in ("1.0", "true", '"1"'):
        result = parse_code(
            f'//@version=6\nindicator("hist")\nx = close[{expr}]\n',
            ParseOptions(max_diagnostics=100),
        )
        assert not result.ok
        assert any("offset" in item.message.lower() or "integer" in item.message.lower() for item in result.diagnostics)


def test_bool_na_version_boundary_is_preserved() -> None:
    v5 = parse_code('//@version=5\nindicator("v5")\nbool x = na\n', ParseOptions(max_diagnostics=100))
    v6 = parse_code('//@version=6\nindicator("v6")\nbool x = na\n', ParseOptions(max_diagnostics=100))
    assert v5.ok
    assert not v6.ok
