import copy
import json
import subprocess
import sys
from pathlib import Path

from pine2ast.catalog import CatalogRepository, CatalogStatus, validate_catalog_pack

ROOT = Path(__file__).resolve().parents[2]


def test_all_six_packs_are_valid_and_hash_bound():
    repo = CatalogRepository.default()
    hashes = set()
    for version in range(1, 7):
        pack = repo.pack(version)
        validate_catalog_pack(pack)
        assert pack["pine_version"] == version
        assert repo.identity(version).catalog_hash == pack["catalog_hash"]
        hashes.add(pack["catalog_hash"])
    assert len(hashes) == 6


def test_historical_and_modern_statuses_are_honest():
    repo = CatalogRepository.default()
    for version in range(1, 5):
        identity = repo.identity(version)
        pack = repo.pack(version)
        assert identity.status is CatalogStatus.HISTORICAL_STATIC_SNAPSHOT
        assert "historical" in pack["coverage_basis"]
        assert pack["sections"]["functions"]
        assert pack["sections"]["variables"]
    for version in (5, 6):
        assert repo.identity(version).status is CatalogStatus.STATIC_COMPLETE
        assert repo.pack(version)["sections"]["functions"]


def test_cached_catalog_is_not_mutable_by_consumers():
    repo = CatalogRepository.default()
    first = repo.view(6)
    original = copy.deepcopy(first)
    first["functions"].clear()
    second = repo.view(6)
    assert second == original


def test_sequential_deltas_contain_only_declared_operations():
    for version in range(1, 7):
        rows = [
            json.loads(line)
            for line in (ROOT / f"catalog_source/deltas/v{version}.jsonl").read_text().splitlines()
            if line
        ]
        assert rows
        assert all(row["op"] in {"ADD", "PATCH", "REMOVE", "RENAME"} for row in rows)
    v6_rows = [
        json.loads(line)
        for line in (ROOT / "catalog_source/deltas/v6.jsonl").read_text().splitlines()
        if line
    ]
    view = CatalogRepository.default().view(6)
    assert len(v6_rows) < sum(
        len(view[name]) for name in ("functions", "variables", "methods", "types", "namespaces")
    )


def test_migration_report_is_lossless_for_v5_v6_and_clean_for_all_versions():
    report = json.loads((ROOT / "catalog_reports/migration_report.json").read_text())
    assert report["ok"] is True
    assert report["migration_loss_count"] == 0
    assert all(value == 0 for value in report["invariants"].values())
    assert set(report["pack_hashes"]) == {"1", "2", "3", "4", "5", "6"}


def test_generated_catalog_has_no_drift_from_any_working_directory(tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/catalog/build_catalog.py"),
            "--root",
            str(ROOT),
            "--check",
        ],
        cwd=tmp_path,
        check=True,
    )
