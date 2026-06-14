from __future__ import annotations

import json

from pine2ast.semantic.signature_coverage import (
    build_signature_coverage_report,
    signature_coverage_json,
)


def test_signature_coverage_report_is_version_aware_for_v5_and_v6() -> None:
    v5 = build_signature_coverage_report(5)
    v6 = build_signature_coverage_report(6)

    assert v5.pine_version == 5
    assert v6.pine_version == 6
    assert v5.ok is True
    assert v6.ok is True
    assert v6.to_dict()["categories"]["functions"]["missing_count"] == 0
    assert v6.to_dict()["categories"]["methods"]["official_count"] >= 1


def test_signature_coverage_reports_signature_ready_and_pending_counts() -> None:
    payload = json.loads(signature_coverage_json(6))

    assert payload["schema_version"] == "pine2ast.signature_coverage.v1"
    assert payload["summary"]["implemented_count"] == payload["summary"]["signature_ready_count"]
    assert payload["summary"]["signature_ready_ratio"] == 1.0
    assert payload["categories"]["methods"]["signature_pending_count"] == 0
    assert payload["categories"]["constants"]["signature_pending_count"] == 0
