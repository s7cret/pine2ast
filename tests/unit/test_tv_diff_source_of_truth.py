from pathlib import Path

from tools.diff_source_of_truth import compare_snapshots, main, parse_snapshot, split_params

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "tv_snapshots" / "2026_04_28_baseline"
CURRENT = ROOT / "docs" / "tv_snapshots" / "2026_04_28_current"
CATALOG = ROOT / "pine2ast" / "semantic" / "builtins_v6.json"


def test_split_params_keeps_nested_commas():
    assert split_params("source, options=[1, 2, 3], title='a,b'") == [
        "source",
        "options=[1, 2, 3]",
        "title='a,b'",
    ]


def test_parse_snapshot_extracts_items_namespaces_and_ambiguous_lines():
    snapshot = parse_snapshot(BASELINE, {})

    assert "ta.sma" in snapshot.items
    assert "line.set_color" in snapshot.items
    assert snapshot.items["line.set_color"].kind == "method"
    assert snapshot.items["ta.sma"].param_names == ["source", "length"]
    assert "ta" in snapshot.namespaces
    assert any(entry["reason"] == "incomplete_signature" for entry in snapshot.ambiguous)


def test_compare_detects_expected_stage15_drift():
    baseline = parse_snapshot(BASELINE, {})
    current = parse_snapshot(CURRENT, {})
    report = compare_snapshots(baseline, current)

    assert "math" in report["new_namespaces"]
    assert {item["name"] for item in report["new_functions"]} >= {"ta.ema", "math.clamp"}
    assert {item["name"] for item in report["removed_functions"]} == {"ta.oldfunc"}
    assert any(change["name"] == "ta.sma" for change in report["changed_signatures"])
    assert any(change["name"] == "strategy.entry" for change in report["new_removed_named_args"])
    assert any(change["name"] == "strategy" for change in report["strategy_declaration_args"])
    assert any(
        change.get("current", {}).get("name") == "line.get_price"
        for change in report["method_changes"]
    )


def test_main_writes_markdown_and_json(tmp_path):
    md_out = tmp_path / "TV_DIFF_REPORT.md"
    json_out = tmp_path / "tv_diff_report.json"

    rc = main(
        [
            "--baseline",
            str(BASELINE),
            "--current",
            str(CURRENT),
            "--catalog",
            str(CATALOG),
            "--markdown-out",
            str(md_out),
            "--json-out",
            str(json_out),
        ]
    )

    assert rc == 0
    assert "TradingView Source-of-Truth Diff Report" in md_out.read_text(encoding="utf-8")
    data = json_out.read_text(encoding="utf-8")
    assert '"strategy_declaration_args"' in data
    assert '"catalog_id": "strategy.entry"' in data
