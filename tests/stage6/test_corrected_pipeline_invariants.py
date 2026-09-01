from __future__ import annotations

import tomllib
from pathlib import Path

from pine2ast import ParseOptions, parse_code


def test_pyproject_is_valid_toml_and_has_one_package_data_key() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert payload["project"]["version"] == "5.0.0rc6"
    package_data = payload["tool"]["setuptools"]["package-data"]
    assert list(package_data) == ["pine2ast"]


def test_version_semantics_respects_max_diagnostics() -> None:
    source = '//@version=4\nindicator("bad", resolution="D")\nx=ta.sma(close,3)\n'
    result = parse_code(source, ParseOptions(max_diagnostics=1))
    assert len(result.diagnostics) == 1


def test_final_gate_metadata_matches_result() -> None:
    bad = parse_code('//@version=4\nindicator("bad")\nx=close\n')
    assert not bad.ok
    assert bad.ast is not None
    assert bad.ast.producer_metadata["frontend_gate"] == "fail"
    assert bad.ast.producer_metadata["semantic_gate"] == "fail"

    good = parse_code('//@version=4\nstudy("good")\nx=close\n')
    assert good.ok
    assert good.ast is not None
    assert good.ast.producer_metadata["frontend_gate"] == "pass"
    assert good.ast.producer_metadata["semantic_gate"] == "pass"


def test_version_metadata_describes_applicable_not_verified_rules() -> None:
    result = parse_code('//@version=6\nindicator("x")\nx=close\n')
    assert result.ok and result.ast is not None
    metadata = result.ast.producer_metadata["version_semantics"]
    assert metadata["applicable_rule_ids"]
    assert "verified_rule_ids" not in metadata
