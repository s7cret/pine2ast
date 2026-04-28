from __future__ import annotations

from pine2ast.reference_catalog import catalog_markdown, validate_catalog, validate_matrix


def test_bundled_catalog_and_matrix_validate() -> None:
    validate_catalog()
    validate_matrix()


def test_catalog_markdown_exports_status_table() -> None:
    text = catalog_markdown()

    assert "# Pine v6 Reference Catalog" in text
    assert "`ta.ema`" in text
    assert "`strategy.entry`" in text
    assert "| ID | Kind | Owner | Parser | Semantic | Codegen | Runtime | Golden |" in text
    assert "full TradingView compatibility" in text
