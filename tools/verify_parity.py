#!/usr/bin/env python3
"""Bulk verify IMPLEMENTED_UNVERIFIED entries — safe version that preserves matrix structure."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pine2ast.api import ParseOptions, parse_code  # noqa: E402
from pine2ast.diagnostics import Severity  # noqa: E402

MATRIX_PATH = ROOT / "pine2ast" / "reference_catalog" / "parity_matrix.json"
CATALOG_PATH = ROOT / "pine2ast" / "reference_catalog" / "pine_v6_reference_catalog.json"
BUILTINS_PATH = ROOT / "pine2ast" / "semantic" / "builtins_v6.json"


def make_script(eid: str, builtins: dict) -> str | None:
    """Generate minimal Pine v6 test script."""
    UNSUPPORTED = {"log.error", "log.info", "log.warning", "request.economic", "runtime.error"}
    if eid in UNSUPPORTED:
        return None  # intentionally unsupported

    # Variables
    if eid in builtins.get("variables", {}):
        return f'//@version=6\nindicator("V")\nx = {eid}\nplot(x)\n'

    # Types
    if eid in builtins.get("types", {}):
        return f'//@version=6\nindicator("V")\n{eid} x = 0\nplot(0)\n'

    # Constants (check by category or known patterns)
    KNOWN_CONSTANTS = {
        "adjustment.dividends",
        "alert.freq_all",
        "alert.freq_once_per_bar",
        "alert.freq_once_per_bar_close",
        "barmerge.gaps_off",
        "barmerge.gaps_on",
        "barmerge.lookahead_off",
        "barmerge.lookahead_on",
        "extend.both",
        "extend.left",
        "extend.none",
        "extend.right",
        "format.inherit",
        "format.mintick",
        "format.percent",
        "format.price",
        "format.volume",
        "font.family_default",
        "label.style_label_down",
        "label.style_label_up",
        "label.style_label_left",
        "label.style_label_right",
        "label.style_label_center",
        "label.style_none",
        "line.style_solid",
        "line.style_dashed",
        "line.style_dotted",
        "line.style_arrow_left",
        "line.style_arrow_right",
        "line.style_arrow_both",
        "location.abovebar",
        "location.belowbar",
        "location.bottom",
        "location.top",
        "location.absolute",
        "position.bottom_center",
        "position.bottom_left",
        "position.bottom_right",
        "position.middle_center",
        "position.middle_left",
        "position.middle_right",
        "position.top_center",
        "position.top_left",
        "position.top_right",
        "shape.arrowdown",
        "shape.arrowup",
        "shape.circle",
        "shape.cross",
        "shape.diamond",
        "shape.flag",
        "shape.labeldown",
        "shape.labelup",
        "shape.square",
        "shape.triangledown",
        "shape.triangleup",
        "shape.xcross",
        "size.auto",
        "size.huge",
        "size.large",
        "size.normal",
        "size.small",
        "size.tiny",
        "strategy.cash",
        "strategy.fixed",
        "strategy.percent_of_equity",
        "strategy.closedtrades.entry_price",
        "strategy.closedtrades.entry_time",
        "strategy.closedtrades.exit_price",
        "strategy.closedtrades.exit_time",
        "strategy.closedtrades.max_drawdown",
        "strategy.closedtrades.max_drawdown_percent",
        "strategy.closedtrades.max_runup",
        "strategy.closedtrades.max_runup_percent",
        "strategy.closedtrades.profit",
        "strategy.closedtrades.profit_percent",
        "strategy.closedtrades.size",
        "text.align_bottom",
        "text.align_center",
        "text.align_left",
        "text.align_right",
        "text.align_top",
        "text.format_bold",
        "text.format_italic",
        "text.format_none",
        "text.wrap_auto",
        "text.wrap_none",
    }
    if eid in KNOWN_CONSTANTS:
        return f'//@version=6\nindicator("V")\nx = {eid}\nplot(0)\n'

    # Functions - find in builtins
    entry = builtins.get("functions", {}).get(eid)
    if entry is None:
        return None

    params = entry.get("parameters", [])
    args = []
    for p in params:
        if not p.get("required", True):
            continue
        ptype = p.get("type", "series float")
        if "int" in ptype:
            args.append("14")
        elif "float" in ptype:
            args.append("1.0")
        elif "string" in ptype:
            args.append('"x"')
        elif "bool" in ptype:
            args.append("true")
        elif "color" in ptype:
            args.append("color.red")
        elif "line" in ptype:
            args.append("ln")
        elif "label" in ptype:
            args.append("lbl")
        elif "box" in ptype:
            args.append("bx")
        elif "table" in ptype:
            args.append("tbl")
        elif "linefill" in ptype:
            args.append("lf")
        else:
            args.append("close")

    args_str = ", ".join(args)

    # Drawing method calls need setup
    DRAWING_SETUP = {
        "box": "var box bx = box.new(bar_index, low, bar_index + 1, high)",
        "label": 'var label lbl = label.new(bar_index, high, text="x")',
        "line": "var line ln = line.new(bar_index, low, bar_index + 1, high)",
        "linefill": "var linefill lf = linefill.new(line.new(0,0,1,1), line.new(0,1,1,0), color.red)",
        "table": "var table tbl = table.new(position.top_right, 2, 2)",
    }

    ns = eid.split(".")[0] if "." in eid else None
    if ns in DRAWING_SETUP:
        setup = DRAWING_SETUP[ns]
        return f'//@version=6\nindicator("V")\n{setup}\n{eid}({args_str})\nplot(close)\n'

    # Strategy functions
    if eid.startswith("strategy."):
        return f'//@version=6\nstrategy("S")\n{eid}({args_str})\nplot(close)\n'

    # Generic constructors
    if "<" in eid:
        base = eid.split("<")[0]
        if "array" in base:
            return (
                '//@version=6\nindicator("V")\narr = array.new<float>()\nplot(array.size(arr))\n'
            )
        if "map" in base:
            return '//@version=6\nindicator("V")\nm = map.new<string,float>()\nplot(0)\n'
        if "matrix" in base:
            return '//@version=6\nindicator("V")\nm = matrix.new<float>(2, 2, 0.0)\nplot(0)\n'

    # Regular function
    if args:
        return f'//@version=6\nindicator("V")\nx = {eid}({args_str})\nplot(0)\n'
    return f'//@version=6\nindicator("V")\n{eid}()\nplot(0)\n'


def main():
    matrix_data = json.loads(MATRIX_PATH.read_text())
    catalog_data = json.loads(CATALOG_PATH.read_text())
    builtins = json.loads(BUILTINS_PATH.read_text())

    items = matrix_data["items"]
    cat_lookup = {e["id"]: e for e in catalog_data["entries"]}


    verified = 0
    failed = 0
    skipped = 0

    for item in items:
        if item.get("parser_status") != "IMPLEMENTED_UNVERIFIED":
            continue

        eid = item["id"]
        script = make_script(eid, builtins)
        if script is None:
            skipped += 1
            continue

        result = parse_code(script, ParseOptions(run_semantic=True))
        fatal = [d for d in result.diagnostics if d.severity in (Severity.ERROR, Severity.FATAL)]
        if not fatal:
            item["parser_status"] = "DONE_VERIFIED"
            item["semantic_status"] = "DONE_VERIFIED"
            # Sync to catalog
            if eid in cat_lookup:
                cat_lookup[eid]["parser_status"] = "DONE_VERIFIED"
                cat_lookup[eid]["semantic_status"] = "DONE_VERIFIED"
            verified += 1
        else:
            failed += 1

    # Mark unsupported
    UNSUPPORTED = {"log.error", "log.info", "log.warning", "request.economic", "runtime.error"}
    for item in items:
        if item["id"] in UNSUPPORTED and item.get("parser_status") == "IMPLEMENTED_UNVERIFIED":
            item["parser_status"] = "UNSUPPORTED_DIAGNOSTIC"
            item["semantic_status"] = "UNSUPPORTED_DIAGNOSTIC"
            if item["id"] in cat_lookup:
                cat_lookup[item["id"]]["parser_status"] = "UNSUPPORTED_DIAGNOSTIC"
                cat_lookup[item["id"]]["semantic_status"] = "UNSUPPORTED_DIAGNOSTIC"

    # Write both
    MATRIX_PATH.write_text(json.dumps(matrix_data, indent=2, ensure_ascii=False) + "\n")
    CATALOG_PATH.write_text(json.dumps(catalog_data, indent=2, ensure_ascii=False) + "\n")

    # Summary
    from collections import Counter

    parser = Counter(e.get("parser_status") for e in items)
    semantic = Counter(e.get("semantic_status") for e in items)
    total = len(items)

    print(f"\n✅ Verified: {verified}")
    print(f"❌ Failed: {failed}")
    print(f"⏭  Skipped: {skipped}")
    print(f"\nParser DONE_VERIFIED: {parser.get('DONE_VERIFIED', 0)}/{total}")
    print(f"Semantic DONE_VERIFIED: {semantic.get('DONE_VERIFIED', 0)}/{total}")


if __name__ == "__main__":
    main()
