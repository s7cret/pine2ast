from __future__ import annotations

import json
from importlib.resources import files

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.reference_catalog import load_catalog, load_parity_matrix
from pine2ast.semantic.builtin_registry import load_builtin_registry

FOOTPRINT_FUNCTIONS = {
    "footprint.get_row_by_price",
    "footprint.poc",
    "footprint.rows",
    "footprint.total_volume",
    "footprint.vah",
    "footprint.val",
}

VOLUME_ROW_FUNCTIONS = {
    "volume_row.buy_volume",
    "volume_row.delta",
    "volume_row.down_price",
    "volume_row.has_buy_imbalance",
    "volume_row.has_sell_imbalance",
    "volume_row.sell_volume",
    "volume_row.total_volume",
    "volume_row.up_price",
}

OFFICIAL_IDS = FOOTPRINT_FUNCTIONS | VOLUME_ROW_FUNCTIONS | {"volume_row"}


def test_footprint_volume_row_v6_ids_are_tracked_conservatively() -> None:
    registry = load_builtin_registry()
    catalog = {entry["id"]: entry for entry in load_catalog()["entries"]}
    matrix = {
        (item["official_category"], item["id"]): item for item in load_parity_matrix()["items"]
    }

    assert FOOTPRINT_FUNCTIONS | VOLUME_ROW_FUNCTIONS <= set(registry["functions"])
    assert "volume_row" in registry["types"]
    assert OFFICIAL_IDS <= set(catalog)

    for name in FOOTPRINT_FUNCTIONS | VOLUME_ROW_FUNCTIONS:
        assert ("functions", name) in matrix
        assert catalog[name]["runtime_status"] == "NOT_STARTED"
        assert matrix[("functions", name)]["runtime_status"] == "NOT_STARTED"

    assert ("types", "volume_row") in matrix
    assert catalog["volume_row"]["kind"] == "type"
    assert matrix[("types", "volume_row")]["runtime_status"] == "NOT_STARTED"


def test_footprint_volume_row_v6_ids_are_removed_from_gap_baseline() -> None:
    baseline = json.loads(
        files("pine2ast.reference_catalog")
        .joinpath("official_pine_v6_gap_baseline.json")
        .read_text(encoding="utf-8")
    )
    missing = {
        item
        for category_items in baseline["missing_by_category"].values()
        for item in category_items
    }

    assert OFFICIAL_IDS.isdisjoint(missing)


def test_footprint_volume_row_v6_names_do_not_trip_strict_builtin_checks() -> None:
    source = """//@version=6
indicator("footprint volume row official")
row = footprint.get_row_by_price(close)
rows = footprint.rows()
poc = footprint.poc()
vah = footprint.vah()
val = footprint.val()
ft_total = footprint.total_volume()
up = volume_row.up_price(row)
down = volume_row.down_price(row)
buy = volume_row.buy_volume(row)
sell = volume_row.sell_volume(row)
delta = volume_row.delta(row)
total = volume_row.total_volume(row)
has_buy = volume_row.has_buy_imbalance(row)
has_sell = volume_row.has_sell_imbalance(row)
plot(poc + vah + val + ft_total + up + down + buy + sell + delta + total)
plot(has_buy ? 1 : has_sell ? -1 : 0)
"""

    result = parse_code(source, ParseOptions(strict_builtin_namespaces=True))
    errors = [
        diagnostic.code
        for diagnostic in result.diagnostics
        if diagnostic.severity in {Severity.ERROR, Severity.FATAL}
    ]

    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNDECLARED_VARIABLE not in errors
