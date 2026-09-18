"""Regression matrix for parameter identities and explicit numeric input overloads."""

import pytest
from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.hardening.introspection import semantic_facts_payload


@pytest.mark.parametrize("version", range(1, 7))
def test_named_default_inference_uses_defval(version):
    decl = "indicator" if version >= 5 else "study"
    result = parse_code(
        f'//@version={version}\n{decl}("x")\nx=input(title="Title",defval=2)\nplot(x)'
    )
    assert result.ok
    call = next(c for c in semantic_facts_payload(result)["calls"] if c["callee"] == "input")
    assert call["return_type"] == "int"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["int", "float"])
def test_numeric_catalog_separates_options_and_bounds(version, kind):
    row = CatalogRepository.default().readonly_view(version)["functions"][f"input.{kind}"]
    assert "options" not in [p["name"] for p in row["parameters"]]
    option = row["overloads"][0]
    assert "minval" not in [p["name"] for p in option["parameters"]]
    assert next(p for p in option["parameters"] if p["name"] == "options")["required"]
    result = parse_code(
        f'//@version={version}\nindicator("x")\nx=input.{kind}(2,"n",[1,2,3])\nplot(x)'
    )
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    call = next(
        c for c in semantic_facts_payload(result)["calls"] if c["callee"] == f"input.{kind}"
    )
    assert call["arguments"][2]["parameter_name"] == "options"
    assert call["overload_id"].endswith("#overload:0")


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_modern_source_overload_does_not_replace_legacy_type_signature(version):
    row = CatalogRepository.default().readonly_view(version)["functions"]["input"]
    assert "type" in [p["name"] for p in row["parameters"]]
    assert not row.get("overloads")
