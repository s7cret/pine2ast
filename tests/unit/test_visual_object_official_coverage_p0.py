import json
from pathlib import Path

from pine2ast.api import ParseOptions, parse_code, runtime_contract_v1_4_options
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.builtin_registry import load_builtin_registry

OWNED_ROOT_IDS = {"box", "line", "label", "linefill", "chart.point", "color"}
OWNED_PREFIXES = ("box.", "line.", "label.", "linefill.", "chart.point.", "color.")


def _official_v6_categories() -> dict[str, list[str]]:
    return json.loads(
        Path("pine2ast/reference_catalog/official_pine_v6_reference_index.json").read_text(
            encoding="utf-8"
        )
    )["categories"]


def _owned(ids: list[str]) -> set[str]:
    return {item for item in ids if item in OWNED_ROOT_IDS or item.startswith(OWNED_PREFIXES)}


def _error_codes(source: str, *, runtime_contract: bool = False) -> list[str]:
    options = (
        runtime_contract_v1_4_options()
        if runtime_contract
        else ParseOptions(strict_builtin_namespaces=True)
    )
    result = parse_code(source, options)
    return [
        diag.code
        for diag in result.diagnostics
        if diag.severity in {Severity.ERROR, Severity.FATAL}
    ]


def test_owned_visual_object_official_v6_registry_ids_are_known_and_fail_closed():
    official = _official_v6_categories()
    registry = load_builtin_registry()

    assert registry["namespaces"]["linefill"] == {}
    assert _owned(official["functions"]) <= set(registry["functions"])
    assert _owned(official["variables"]) <= set(registry["variables"])
    assert _owned(official["types"]) <= set(registry["types"])

    for name in _owned(official["functions"]):
        assert registry["functions"][name]["runtime_contract_unsupported"] is True
        assert (
            registry["functions"][name]["unsupported_diagnostic_code"] == codes.UNSUPPORTED_FEATURE
        )


def test_owned_visual_object_catalog_and_matrix_track_official_v6_ids():
    official = _official_v6_categories()
    catalog = json.loads(
        Path("pine2ast/reference_catalog/pine_v6_reference_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    matrix = json.loads(
        Path("pine2ast/reference_catalog/parity_matrix.json").read_text(encoding="utf-8")
    )

    catalog_ids = {entry["id"] for entry in catalog["entries"]}
    matrix_ids = {(item["official_category"], item["id"]) for item in matrix["items"]}

    assert (
        _owned(official["functions"]) | _owned(official["variables"]) | _owned(official["types"])
    ) <= catalog_ids
    for category in ("functions", "methods", "variables", "types", "constants"):
        assert {(category, item_id) for item_id in _owned(official[category])} <= matrix_ids


def test_new_visual_object_registry_entries_parse_but_runtime_contract_fails_closed():
    source = """//@version=6
indicator("visual objects official")
p = chart.point.now(close)
ln = line.new(bar_index, close, bar_index + 1, open)
ln2 = line.copy(ln)
line.set_first_point(ln, p)
line.set_second_point(ln2, chart.point.copy(p))
lf = linefill.new(ln, ln2, color.new(color.blue, 80))
linefill.set_color(lf, color.rgb(color.r(color.blue), color.g(color.blue), color.b(color.blue), color.t(color.blue)))
b = box.new(bar_index, high, bar_index + 1, low)
left = box.get_left(b)
box.set_top_left_point(b, p)
lab = label.new(bar_index, close, "x")
label.set_point(lab, p)
label.set_text_font_family(lab, "monospace")
"""
    strict_errors = _error_codes(source)
    assert codes.UNKNOWN_BUILTIN_MEMBER not in strict_errors
    assert codes.UNKNOWN_PARAMETER not in strict_errors
    assert codes.UNSUPPORTED_FEATURE not in strict_errors

    runtime_errors = _error_codes(source, runtime_contract=True)
    assert codes.UNSUPPORTED_FEATURE in runtime_errors
    assert codes.UNKNOWN_BUILTIN_MEMBER not in runtime_errors
