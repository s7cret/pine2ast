from __future__ import annotations

import json
from pathlib import Path

from pine2ast.testing.oracle import (
    OracleCase,
    load_oracle_manifest,
    oracle_report_json,
    run_oracle_cases,
)


def test_oracle_runner_reports_valid_and_invalid_cases() -> None:
    cases = (
        OracleCase(
            id="valid",
            source='//@version=6\nindicator("ok")\nfloat x = close\n',
            expect_ok=True,
        ),
        OracleCase(
            id="invalid",
            source='//@version=6\nindicator("bad")\narray<float> xs = array.new<float>()\nfloat x = xs.get("bad")\n',
            expect_ok=False,
            expected_error_codes=("P2A1805",),
        ),
    )
    report = run_oracle_cases(cases)
    assert report.ok is True
    assert report.case_count == 2
    assert report.failure_count == 0


def test_oracle_manifest_can_be_loaded_from_json_fixture() -> None:
    manifest = Path("tests/oracle/frontend_oracle_manifest.json")
    cases = load_oracle_manifest(manifest)
    assert [case.id for case in cases] == [
        "v6-valid-map-enum-key",
        "v6-invalid-array-index",
        "v5-invalid-local-request-without-dynamic",
        "v5-valid-local-request-with-dynamic",
        "v6-invalid-strategy-exit-no-action",
        "v6-invalid-const-int-division-to-int",
        "v6-invalid-dynamic-request-disabled",
        "v6-valid-strategy-fixed",
        "v6-valid-strategy-direction-all",
        "v6-valid-strategy-direction-long",
        "v6-valid-strategy-direction-short",
    ]
    payload = json.loads(oracle_report_json(cases))
    assert payload["ok"] is True
    assert payload["case_count"] == 11
