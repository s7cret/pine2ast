from __future__ import annotations

from pine2ast.reference_catalog.official_reference import (
    OfficialReferenceIndex,
    _extract_reference_categories,
    official_reference_gate_payload,
    official_reference_diff_payload,
)


def test_extract_reference_categories_uses_top_level_doc_names_only() -> None:
    bundle = r"""
    const s={
      keywords:[{name:"if",syntax:["if condition"]}],
      types:[{name:"series"}],
      functions:[
        {name:"request.security",args:[{name:"symbol"},{name:"timeframe"}]},
        {name:"strategy.entry",args:[{name:"id"},{name:"direction"}]}
      ],
      variables:[{name:"bar_index"},{name:"close"}],
      methods:[{name:"copy",originalName:"box.copy",args:[{name:"id"}]}],
      constants:[{name:"strategy.long"}],
      annotations:[{name:"@version="}],
      operators:[{name:"+"}]
    };
    """

    categories = _extract_reference_categories(bundle)

    assert categories["functions"] == ["request.security", "strategy.entry"]
    assert "symbol" not in categories["functions"]
    assert categories["methods"] == ["box.copy"]
    assert categories["variables"] == ["bar_index", "close"]


def test_official_reference_diff_reports_missing_items(monkeypatch) -> None:
    index = OfficialReferenceIndex(
        pine_version=6,
        source_url="https://example.test/reference",
        bundle_url="https://example.test/bundle.js",
        categories={
            "functions": ["ta.ema", "request.security"],
            "variables": ["close", "bar_index"],
            "types": ["int", "chart.point"],
        },
    )

    def fake_registry():
        return {
            "functions": {"ta.ema": {}},
            "variables": {"close": {}},
            "types": {"int": {}},
            "namespaces": {},
        }

    monkeypatch.setattr(
        "pine2ast.reference_catalog.official_reference.load_builtin_registry",
        fake_registry,
    )

    payload = official_reference_diff_payload(index)

    assert payload["summary"]["official_comparable_count"] == 6
    assert payload["summary"]["missing_official_count"] == 3
    assert payload["missing_by_category"]["functions"] == ["request.security"]
    assert payload["missing_by_category"]["variables"] == ["bar_index"]
    assert payload["missing_by_category"]["types"] == ["chart.point"]


def test_official_reference_gate_fails_on_new_missing(monkeypatch, tmp_path) -> None:
    index = OfficialReferenceIndex(
        pine_version=6,
        source_url="https://example.test/reference",
        bundle_url="https://example.test/bundle.js",
        categories={
            "functions": ["ta.ema", "request.security"],
            "variables": ["close"],
            "types": ["int"],
        },
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        """{
          "schema_version": "pain.official_pine_reference_gap_baseline.v1",
          "pine_version": 6,
          "max_missing_official_count": 0,
          "min_coverage_ratio": 1.0,
          "missing_by_category": {"functions": [], "variables": [], "types": []}
        }""",
        encoding="utf-8",
    )

    def fake_registry():
        return {
            "functions": {"ta.ema": {}},
            "variables": {"close": {}},
            "types": {"int": {}},
            "namespaces": {},
        }

    monkeypatch.setattr(
        "pine2ast.reference_catalog.official_reference.load_builtin_registry",
        fake_registry,
    )

    payload = official_reference_gate_payload(index, str(baseline))

    assert payload["status"] == "fail"
    assert payload["new_missing_by_category"]["functions"] == ["request.security"]
