from __future__ import annotations

import json
from importlib.resources import files

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.builtin_registry import load_builtin_registry

OFFICIAL_P0_IDS = {
    "ta.cog",
    "ta.max",
    "ta.min",
    "ta.median",
    "ta.mode",
    "ta.range",
    "ta.rci",
    "ta.percentile_linear_interpolation",
    "ta.percentile_nearest_rank",
    "ta.pivot_point_levels",
    "math.round_to_mintick",
    "str.format_time",
    "str.match",
    "str.pos",
    "str.repeat",
    "str.trim",
    "log.error",
    "log.info",
    "log.warning",
    "runtime.error",
}


def test_ta_math_string_log_runtime_official_p0_ids_are_registered() -> None:
    registry = load_builtin_registry()

    missing = sorted(OFFICIAL_P0_IDS - set(registry["functions"]))

    assert missing == []
    assert registry["functions"]["ta.pivot_point_levels"]["returns"] == "array<float>"
    assert registry["functions"]["math.round_to_mintick"]["returns"] == "series<float>"
    assert registry["functions"]["str.format_time"]["returns"] == "series<string>"
    # runtime.error and log.* are now pass-through (unsupported flag removed)
    assert "unsupported" not in registry["functions"]["runtime.error"]
    assert "unsupported" not in registry["functions"]["log.info"]


def test_official_p0_ids_are_tracked_in_catalog_matrix_and_removed_from_gaps() -> None:
    catalog = json.loads(
        files("pine2ast.reference_catalog")
        .joinpath("pine_v6_reference_catalog.json")
        .read_text(encoding="utf-8")
    )
    matrix = json.loads(
        files("pine2ast.reference_catalog")
        .joinpath("parity_matrix.json")
        .read_text(encoding="utf-8")
    )
    catalog_ids = {entry["id"] for entry in catalog["entries"]}
    matrix_ids = {item["id"] for item in matrix["items"]}

    assert OFFICIAL_P0_IDS <= catalog_ids
    assert OFFICIAL_P0_IDS <= matrix_ids

    for baseline_name in (
        "official_pine_v5_gap_baseline.json",
        "official_pine_v6_gap_baseline.json",
    ):
        baseline = json.loads(
            files("pine2ast.reference_catalog").joinpath(baseline_name).read_text(encoding="utf-8")
        )
        unresolved_functions = set(baseline["missing_by_category"]["functions"])

        assert not (OFFICIAL_P0_IDS & unresolved_functions)


def test_side_effect_functions_emit_explicit_unsupported_diagnostics() -> None:
    """log.info/warning/error and runtime.error are now pass-through (no errors)."""
    source = """//@version=6
indicator("side effects")
log.info("value {0}", close)
log.warning("warn")
log.error("err")
runtime.error("stop")
plot(close)
"""

    result = parse_code(source, ParseOptions(strict_builtin_namespaces=True))
    errors = [d for d in result.diagnostics if d.severity is Severity.ERROR]

    # log.* and runtime.error are now accepted as pass-through, no errors
    assert not errors, f"Expected no errors, got: {errors}"
    assert not any(d.code == codes.UNKNOWN_BUILTIN_MEMBER for d in errors)
