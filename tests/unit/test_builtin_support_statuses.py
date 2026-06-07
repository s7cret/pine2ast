"""Validate enriched builtins_v6.json support_statuses structure."""
from __future__ import annotations

import json
from pathlib import Path

PATH = Path("pine2ast/semantic/builtins_v6.json")
EXPECTED_AXES = {
    "official_known",
    "implemented",
    "lowerable",
    "runtime_supported",
    "oracle_verified",
}
EXPECTED_SECTIONS = {"functions", "variables", "constants", "methods", "types"}


def _load():
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_support_statuses_present():
    d = _load()
    assert "support_statuses" in d, "missing support_statuses block"


def test_support_statuses_schema():
    d = _load()["support_statuses"]
    assert d["schema_version"] == "openpine.support_statuses.v1"
    assert set(d["axes"]) == EXPECTED_AXES


def test_support_statuses_coverage_keys():
    d = _load()["support_statuses"]
    assert set(d["coverage"].keys()) == EXPECTED_SECTIONS


def test_each_status_has_all_axes():
    d = _load()["support_statuses"]["data"]
    for section in EXPECTED_SECTIONS:
        for name, status in d[section].items():
            assert set(status.keys()) >= EXPECTED_AXES, f"{section}.{name}"


def test_impl_count_matches_registry_count():
    d = _load()
    ss = d["support_statuses"]
    for section in EXPECTED_SECTIONS:
        registry_n = len(d.get(section, {}))
        ss_n = ss["coverage"][section]["total"]
        assert registry_n == ss_n, f"{section}: registry={registry_n} ss={ss_n}"


def test_oracle_verified_implies_implemented():
    d = _load()["support_statuses"]["data"]
    for section in EXPECTED_SECTIONS:
        for name, status in d[section].items():
            if status.get("oracle_verified"):
                assert status.get("implemented"), f"{name}: oracle without impl"
                assert status.get("lowerable"), f"{name}: oracle without lowerable"
                assert status.get("runtime_supported"), f"{name}: oracle without runtime"
