"""Smoke test for compatibility matrix generator and JSON shape."""
from __future__ import annotations

import json
from pathlib import Path

JSON_PATH = Path("pine2ast/compatibility/compatibility_matrix.json")
MD_PATH = Path("pine2ast/compatibility/compatibility_matrix.md")

ALLOWED_STATUSES = {
    "DONE_VERIFIED",
    "IMPLEMENTED_UNVERIFIED",
    "UNSUPPORTED_DIAGNOSTIC",
    "PARTIAL",
    "NOT_STARTED",
}
ALLOWED_AXES = ["parser", "semantic", "codegen", "runtime", "golden"]


def test_compatibility_matrix_files_exist():
    assert JSON_PATH.exists(), f"missing {JSON_PATH}"
    assert MD_PATH.exists(), f"missing {MD_PATH}"


def test_compatibility_matrix_schema():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert data["schema_version"] == "openpine.compatibility_matrix.v1"
    assert data["axes"] == ALLOWED_AXES
    for s in data["status_values"]:
        assert s in ALLOWED_STATUSES


def test_compatibility_matrix_summary_matches_items():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    total = len(data["items"])
    for ax in ALLOWED_AXES:
        s = sum(data["summary"][ax].values())
        assert s == total, f"{ax}: summary={s} != items={total}"


def test_compatibility_matrix_items_have_valid_statuses():
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    for it in data["items"]:
        for ax in ALLOWED_AXES:
            # Items use "oracle" as the canonical key (parity matrix field is
            # golden_status, generator maps it to oracle in the compat record).
            key = "oracle" if ax == "golden" else ax
            assert it[key] in ALLOWED_STATUSES, f"{it['id']} {ax}={it[key]}"
        assert it["id"]


def test_compatibility_matrix_md_has_sections():
    md = MD_PATH.read_text(encoding="utf-8")
    assert "OpenPine Compatibility Matrix" in md
    assert "Summary by axis" in md
    assert "Coverage by category" in md
    assert "Overall readiness" in md
