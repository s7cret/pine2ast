"""Stage 2.1 reconciliation of the useful CAT-01 coverage from Pine2AST PR #12.

This file intentionally keeps the high-value version-boundary assertions compact.
It does not merge the remote PR and does not turn historical uncertainty into an
unsupported completeness claim.
"""

from __future__ import annotations

import json
from pathlib import Path

from pine2ast.catalog import CatalogRepository, validate_catalog_pack

ROOT = Path(__file__).resolve().parents[2]
BARSTATE = {
    "barstate.isconfirmed",
    "barstate.isfirst",
    "barstate.ishistory",
    "barstate.islast",
    "barstate.islastconfirmedhistory",
    "barstate.isnew",
    "barstate.isrealtime",
}
LEGACY_INPUTS = {
    "input.bool",
    "input.color",
    "input.float",
    "input.integer",
    "input.source",
    "input.string",
}
MODERN_INPUTS = {
    "input.bool",
    "input.color",
    "input.float",
    "input.int",
    "input.source",
    "input.string",
    "input.timeframe",
}
SHORT = {
    "input.bool": "bool",
    "input.color": "color",
    "input.float": "float",
    "input.integer": "integer",
    "input.source": "source",
    "input.string": "string",
}


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_barstate_exact_inventory_is_stable_from_v1_through_v6():
    repo = CatalogRepository.default()
    ids = set()
    for version in range(1, 7):
        pack = repo.pack(version)
        validate_catalog_pack(pack)
        assert "barstate" in pack["sections"]["namespaces"]
        assert {
            name for name in pack["sections"]["variables"] if name.startswith("barstate.")
        } == BARSTATE
        ids.update(pack["sections"]["variables"][name]["symbol_id"] for name in BARSTATE)
    assert ids == {f"pine:variable:{name}" for name in BARSTATE}


def test_barstate_metadata_and_delta_origin_are_version_exact():
    symbols = _rows(ROOT / "catalog_source/symbols.jsonl")
    by_name = {row["canonical_name"]: row for row in symbols}
    for name in BARSTATE:
        row = by_name[name]
        assert row["kind"] == "variable"
        assert row["first_observed_version"] == 1
        assert row["last_observed_version"] == 6
    v1 = _rows(ROOT / "catalog_source/deltas/v1.jsonl")
    assert {
        r["name"] for r in v1 if r.get("op") == "ADD" and r.get("section") == "variables"
    } >= BARSTATE
    for version in range(1, 7):
        removes = [
            row
            for row in _rows(ROOT / f"catalog_source/deltas/v{version}.jsonl")
            if row.get("op") == "REMOVE" and ":barstate." in str(row.get("symbol_id", ""))
        ]
        assert removes == []


def test_legacy_and_modern_input_families_do_not_cross_version_boundary():
    repo = CatalogRepository.default()
    for version in range(1, 5):
        pack = repo.pack(version)
        assert not (MODERN_INPUTS & set(pack["sections"]["functions"]))
        assert LEGACY_INPUTS <= set(pack["sections"]["variables"])
        expected_constants = set(SHORT.values()) if version < 4 else LEGACY_INPUTS
        assert expected_constants <= set(pack["sections"]["constants"])
    for version in (5, 6):
        pack = repo.pack(version)
        assert MODERN_INPUTS <= set(pack["sections"]["functions"])
        assert not (LEGACY_INPUTS & set(pack["sections"]["variables"]))
        assert not (LEGACY_INPUTS & set(pack["sections"]["constants"]))


def test_input_integer_is_legacy_and_input_int_is_modern_only():
    symbols = _rows(ROOT / "catalog_source/symbols.jsonl")
    kinds = {}
    for row in symbols:
        kinds.setdefault(row["canonical_name"], set()).add(row["kind"])
    assert kinds["input.integer"] == {"constant", "variable"}
    assert kinds["input.int"] == {"function"}


def test_input_symbol_metadata_has_exact_observed_version_ranges():
    symbols = _rows(ROOT / "catalog_source/symbols.jsonl")
    rows = {(row["canonical_name"], row["kind"]): row for row in symbols}
    for name in LEGACY_INPUTS:
        for kind in ("constant", "variable"):
            row = rows[(name, kind)]
            assert (row["first_observed_version"], row["last_observed_version"]) == (1, 4)
    for name in MODERN_INPUTS:
        row = rows[(name, "function")]
        assert (row["first_observed_version"], row["last_observed_version"]) == (5, 6)


def test_v4_renames_legacy_input_constants_and_v5_performs_typed_input_migration():
    v4 = _rows(ROOT / "catalog_source/deltas/v4.jsonl")
    renamed = {row["symbol_id"] for row in v4 if row.get("op") == "RENAME"}
    assert {f"pine:constant:legacy.{name}" for name in LEGACY_INPUTS} <= renamed

    v5 = _rows(ROOT / "catalog_source/deltas/v5.jsonl")
    added = {
        row["name"] for row in v5 if row.get("op") == "ADD" and row.get("section") == "functions"
    }
    removed = {row.get("symbol_id") for row in v5 if row.get("op") == "REMOVE"}
    assert MODERN_INPUTS <= added
    for name in LEGACY_INPUTS:
        assert f"pine:constant:legacy.{name}" in removed
        assert f"pine:variable:legacy.{name}" in removed


def test_input_core_inventory_is_stable_within_historical_and_modern_ranges():
    repo = CatalogRepository.default()
    historical = [
        {name for name in repo.pack(v)["sections"]["variables"] if name in LEGACY_INPUTS}
        for v in range(1, 5)
    ]
    modern = [
        {name for name in repo.pack(v)["sections"]["functions"] if name in MODERN_INPUTS}
        for v in (5, 6)
    ]
    assert all(value == LEGACY_INPUTS for value in historical)
    assert all(value == MODERN_INPUTS for value in modern)
