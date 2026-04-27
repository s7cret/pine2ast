from __future__ import annotations

from pathlib import Path

from pine2ast.testing.golden import validate_invalid_diagnostic_contract

ROOT = Path(__file__).resolve().parents[1]
INVALID_ROOT = ROOT / "fixtures" / "invalid"


def _invalid_fixtures() -> list[Path]:
    return sorted(INVALID_ROOT.rglob("*.pine"))


def test_invalid_fixture_count_is_production_sized():
    fixtures = _invalid_fixtures()
    assert len(fixtures) >= 20
    categories = {path.relative_to(INVALID_ROOT).parts[0] for path in fixtures if len(path.relative_to(INVALID_ROOT).parts) > 1}
    assert {"syntax", "semantic", "v6_migration", "layout"}.issubset(categories)


def test_invalid_fixtures_have_diagnostic_contracts():
    for source in _invalid_fixtures():
        contract_path = source.with_suffix(".diagnostics.json")
        assert contract_path.exists()


def test_invalid_fixtures_emit_expected_diagnostic_codes():
    for source in _invalid_fixtures():
        ok, message = validate_invalid_diagnostic_contract(source)
        assert ok, message
