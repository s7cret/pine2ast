from __future__ import annotations

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
