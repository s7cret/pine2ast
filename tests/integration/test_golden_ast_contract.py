from __future__ import annotations

from pathlib import Path

from pine2ast.api import ParseOptions, parse_file
from pine2ast.testing.golden import compare_diagnostics, compare_golden

ROOT = Path(__file__).resolve().parents[1]
VALID_ROOT = ROOT / "fixtures" / "valid"
GOLDEN_ROOT = ROOT / "fixtures" / "golden_ast" / "valid"


def _valid_fixtures() -> list[Path]:
    return sorted(VALID_ROOT.rglob("*.pine"))


def _golden_paths(source: Path) -> tuple[Path, Path]:
    rel = source.relative_to(VALID_ROOT)
    return GOLDEN_ROOT / rel.with_suffix(".ast.json"), GOLDEN_ROOT / rel.with_suffix(".diagnostics.json")


def test_curated_valid_fixture_count_is_production_sized():
    fixtures = _valid_fixtures()
    assert len(fixtures) >= 40
    categories = {path.relative_to(VALID_ROOT).parts[0] for path in fixtures}
    assert {
        "declarations",
        "expressions",
        "layout",
        "semantic_ok",
        "imports",
        "optimizer_contract",
        "types",
        "loops",
    }.issubset(categories)


def test_all_curated_valid_fixtures_parse_ok():
    for source in _valid_fixtures():
        result = parse_file(str(source), ParseOptions(source_name=str(source)))
        assert result.ok, [diag.code for diag in result.diagnostics]


def test_curated_valid_golden_ast_matches_with_spans():
    for source in _valid_fixtures():
        ast_path, _ = _golden_paths(source)
        ok, message = compare_golden(source, ast_path=ast_path, ignore_spans=False)
        assert ok, message


def test_curated_valid_golden_ast_matches_ignore_spans():
    for source in _valid_fixtures():
        ast_path, _ = _golden_paths(source)
        ok, message = compare_golden(source, ast_path=ast_path, ignore_spans=True)
        assert ok, message


def test_curated_valid_golden_diagnostics_match():
    for source in _valid_fixtures():
        _, diagnostics_path = _golden_paths(source)
        ok, message = compare_diagnostics(source, diagnostics_path=diagnostics_path, ignore_spans=False)
        assert ok, message
