"""Static exit action validation uses catalog-bound positions, not only keywords."""

import pytest
from pine2ast import parse_code


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize(
    "arguments",
    [
        '"X", "A", na, na, 5',
        '"X", "A", na, na, na, 105',
        '"X", "A", na, na, na, na, 5',
        '"X", "A", na, na, na, na, na, 95',
        '"X", "A", na, na, na, na, na, na, 105, na, 2',
    ],
)
def test_positional_exit_actions_follow_the_version_catalog(version, arguments):
    result = parse_code(f'//@version={version}\nstrategy("binding")\nstrategy.exit({arguments})\n')
    assert result.ok, result.diagnostics


@pytest.mark.parametrize("arguments", ['"X"', '"X", "A", 2', '"X", "A", 2, 50'])
def test_quantities_alone_do_not_turn_an_exit_into_an_action(arguments):
    result = parse_code(f'//@version=6\nstrategy("binding")\nstrategy.exit({arguments})\n')
    assert not result.ok
    assert any(d.code == "P2A1404" for d in result.diagnostics)
