from __future__ import annotations

import json
from pathlib import Path

from pine2ast.testing.compile_oracle import build_compile_oracle_report, report_to_dict


def test_compile_oracle_report_tracks_pending_external_checks() -> None:
    report = build_compile_oracle_report("tests/fixtures/compile_oracle")

    assert report.metadata_count >= 1
    assert report.fixture_count >= 5
    assert report.invalid_count == 0
    assert report.pending_count >= 1
    assert not report.ok

    payload = report_to_dict(report)
    assert payload["schema_version"] == 1
    assert payload["pending_count"] == report.pending_count
    assert all(entry["fixture"].endswith(".pine") for entry in payload["entries"])


def test_compile_oracle_report_accepts_legacy_and_requested_verified_statuses(
    tmp_path: Path,
) -> None:
    category = tmp_path / "oracle"
    category.mkdir()
    for name in ["pass.pine", "ok.pine", "fail.pine", "invalid.pine"]:
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
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_compile_oracle_report(tmp_path)

    assert report.ok
    assert report.ok_count == 4
    assert report.pending_count == 0
    assert report.invalid_count == 0
