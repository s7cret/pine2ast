from __future__ import annotations

import json
from pathlib import Path

from pine2ast.testing.compile_oracle import build_compile_oracle_report, report_to_dict


def test_compile_oracle_report_tracks_authenticated_external_checks_without_pending_or_blocked() -> (
    None
):
    report = build_compile_oracle_report("tests/fixtures/compile_oracle")

    assert report.metadata_count >= 6
    assert report.fixture_count >= 35
    assert report.invalid_count == 0
    assert report.ok_count >= 35
    assert report.pending_count == 0
    assert report.platform_blocked_count == 0
    assert report.ok

    payload = report_to_dict(report)
    assert payload["schema_version"] == 1
    assert payload["pending_count"] == report.pending_count
    assert payload["platform_blocked_count"] == report.platform_blocked_count
    assert all(entry["fixture"].endswith(".pine") for entry in payload["entries"])
    assert any(
        entry["metadata_file"] == "strategy_namespace/metadata.json" and entry["ok"]
        for entry in payload["entries"]
    )
    expansion_entries = [
        entry
        for entry in payload["entries"]
        if entry["metadata_file"] != "strategy_namespace/metadata.json"
    ]
    assert any(entry["tradingview_status"] == "ok" for entry in expansion_entries)
    assert all(
        entry["tradingview_status"] in {"ok", "pass", "fail_expected", "invalid_expected"}
        for entry in expansion_entries
    )
    assert not any(
        entry["tradingview_status"] in {"pending_external_oracle", "platform_blocked"}
        for entry in expansion_entries
    )
    assert all(entry["pine2ast_status"] == "pass" for entry in expansion_entries)


def test_compile_oracle_report_accepts_legacy_requested_but_fails_platform_blocked_statuses(
    tmp_path: Path,
) -> None:
    category = tmp_path / "oracle"
    category.mkdir()
    for name in ["pass.pine", "ok.pine", "fail.pine", "invalid.pine", "blocked.pine"]:
        (category / name).write_text('//@version=6\nindicator("x")\n', encoding="utf-8")
    (category / "metadata.json").write_text(
        json.dumps(
            {
                "checked_at": "2026-04-27",
                "policy": [
                    {"fixture": "pass.pine", "tradingview_status": "pass"},
                    {"fixture": "ok.pine", "tradingview_status": "ok"},
                    {"fixture": "fail.pine", "tradingview_status": "fail_expected"},
                    {"fixture": "invalid.pine", "tradingview_status": "invalid_expected"},
                    {"fixture": "blocked.pine", "tradingview_status": "platform_blocked"},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_compile_oracle_report(tmp_path)

    assert not report.ok
    assert report.ok_count == 4
    assert report.platform_blocked_count == 1
    assert report.pending_count == 0
    assert report.invalid_count == 1
