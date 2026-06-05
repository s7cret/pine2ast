"""Tests for strategy trades/equity compile oracle fixtures."""

import pytest
from pathlib import Path
from pine2ast import parse_code, ParseOptions

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "compile_oracle" / "strategy_trades"


def load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "fixture_name",
    [
        "strategy_entry_exit_allowed.pine",
        "strategy_equity_allowed.pine",
        "strategy_netprofit_allowed.pine",
        "strategy_opentrades_allowed.pine",
        "strategy_position_size_allowed.pine",
        "strategy_risk_allowed.pine",
        "strategy_commission_allowed.pine",
    ],
)
def test_strategy_allowed_fixtures(fixture_name: str) -> None:
    """Strategy fixtures should compile without errors."""
    src = load_fixture(fixture_name)
    tree = parse_code(src, ParseOptions(run_semantic=True))
    errors = [d for d in tree.diagnostics if d.severity.value in {"FATAL", "ERROR"}]
    assert not errors, [d.to_dict() for d in errors]


@pytest.mark.parametrize(
    "fixture_name",
    [
        "indicator_strategy_entry_forbidden.pine",
        "indicator_strategy_exit_forbidden.pine",
        "indicator_strategy_equity_forbidden.pine",
    ],
)
def test_indicator_strategy_forbidden_fixtures(fixture_name: str) -> None:
    """Indicator fixtures using strategy functions should produce errors."""
    src = load_fixture(fixture_name)
    tree = parse_code(src, ParseOptions(run_semantic=True))
    errors = [d for d in tree.diagnostics if d.severity.value in {"FATAL", "ERROR"}]
    assert errors, f"Expected errors for {fixture_name}"
    assert any(
        "strategy" in d.message.lower() for d in errors
    ), f"Expected strategy-related error for {fixture_name}"
