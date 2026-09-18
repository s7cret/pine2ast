"""Type evidence for compiled request consumers and version-aware na()."""

import pytest
from pine2ast import parse_code


@pytest.mark.parametrize("version", range(1, 7))
def test_na_named_required_argument_all_versions(version):
    decl = "indicator" if version >= 5 else "study"
    result = parse_code(f'//@version={version}\n{decl}("na")\nx=na(close)\n')
    assert result.ok, result.diagnostics
    assert any(
        f.kind == "CallExpr" and f.resolved_type.base == "bool"
        for f in result.semantic_model.semantic_facts.facts
    )


@pytest.mark.parametrize("function", ["na", "nz", "fixnan"])
def test_v6_missing_value_functions_reject_bool(function):
    result = parse_code(f'//@version=6\nindicator("bool")\nx={function}(true)\n')
    assert not result.ok
    assert any(d.is_error and "bool" in d.message for d in result.diagnostics)


