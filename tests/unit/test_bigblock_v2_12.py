import json
from pathlib import Path

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes, Severity
from pine2ast.semantic.builtin_registry import (
    builtin_registry_coverage_report,
    load_builtin_registry,
)


def diagnostics(src: str, *, strict: bool = False):
    result = parse_code(src, ParseOptions(strict_builtin_namespaces=strict))
    return result, result.diagnostics


def error_codes(src: str):
    result, diags = diagnostics(src)
    return [d.code for d in diags if d.severity.value in {"ERROR", "FATAL"}]


def test_v212_nested_and_records_all_stable_non_na_facts():
    result, _ = diagnostics("""//@version=6
indicator("nested and")
float x = na
float y = na
if not na(x) and (not na(y) and (x > 0 and y > 0))
    z = x + y
plot(close)
""")
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert any({"x", "y"}.issubset(paths) for paths in result.semantic_model.non_na_paths.values())


def test_v212_or_guard_does_not_record_unsound_non_na_fact():
    result, _ = diagnostics("""//@version=6
indicator("or no narrowing")
float x = na
if not na(x) or close > open
    z = close
plot(close)
""")
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert not any("x" in paths for paths in result.semantic_model.non_na_paths.values())


def test_v212_else_if_narrowing_is_branch_local_only():
    result, _ = diagnostics("""//@version=6
indicator("branch local")
float x = na
float y = na
if not na(x)
    a = x + 1
else if not na(y)
    b = y + 1
else
    c = close
plot(close)
""")
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    path_sets = list(result.semantic_model.non_na_paths.values())
    assert any(paths == {"x"} for paths in path_sets)
    assert any(paths == {"y"} for paths in path_sets)
    assert not any({"x", "y"}.issubset(paths) for paths in path_sets)


def test_v212_unstable_na_guard_emits_info_not_error():
    result, diags = diagnostics("""//@version=6
indicator("unstable na")
if not na(close + open)
    z = close
plot(close)
""")
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert any(d.code == codes.UNSTABLE_NA_NARROWING and d.severity is Severity.INFO for d in diags)


def test_v212_drawing_registry_named_parameters_are_accepted():
    src = """//@version=6
indicator("drawing params")
l = line.new(x1 = bar_index, y1 = close, x2 = bar_index + 1, y2 = close, width = 2, force_overlay = true)
lab = label.new(x = bar_index, y = close, text = "x", tooltip = "tip", force_overlay = true)
b = box.new(left = bar_index, top = high, right = bar_index + 1, bottom = low, text = "box")
t = table.new(position = position.top_right, columns = 2, rows = 1, frame_width = 1)
p = polyline.new(curved = false, closed = false, line_width = 1)
plot(close)
"""
    assert codes.UNKNOWN_PARAMETER not in error_codes(src)
    assert codes.ARGUMENT_COUNT not in error_codes(src)


def test_v212_strategy_and_request_optional_metadata_are_accepted():
    src = """//@version=6
strategy("strategy params")
remote = request.security(syminfo.tickerid, "D", close, gaps = barmerge.gaps_off, lookahead = barmerge.lookahead_off, calc_bars_count = 100)
strategy.entry("L", strategy.long, qty = 1.0, comment = "go", alert_message = "msg", disable_alert = false)
strategy.exit("XL", from_entry = "L", limit = remote, stop = remote - 1, comment_profit = "tp", alert_loss = "sl")
strategy.order("S", strategy.short, qty = 1.0, oca_name = "grp", comment = "ord")
plot(remote)
"""
    assert codes.UNKNOWN_PARAMETER not in error_codes(src)
    assert codes.ARGUMENT_COUNT not in error_codes(src)


def test_v212_strategy_when_is_still_removed_after_metadata_expansion():
    assert codes.STRATEGY_WHEN_REMOVED in error_codes("""//@version=6
strategy("when removed")
strategy.order("L", strategy.long, when = close > open)
""")


def test_v212_input_metadata_accepts_ui_options_and_typed_options():
    src = """//@version=6
indicator("input params")
len = input.int(14, title = "Len", minval = 1, maxval = 200, step = 1, options = [10, 14, 20], group = "G", inline = "L", tooltip = "tip", confirm = false, display = display.all)
mode = input.string("A", title = "Mode", options = ["A", "B"], active = true)
useIt = input.bool(true, title = "Use", group = "G")
plot(close)
"""
    assert codes.UNKNOWN_PARAMETER not in error_codes(src)
    assert codes.ARGUMENT_TYPE not in error_codes(src)


def test_v212_registry_backlog_has_parameter_metadata_for_priority_entries():
    registry = load_builtin_registry()
    required = [
        "line.new",
        "label.new",
        "box.new",
        "table.new",
        "polyline.new",
        "strategy.entry",
        "strategy.exit",
        "strategy.order",
        "request.security",
        "input.int",
        "input.float",
        "input.bool",
        "input.string",
        "input.timeframe",
    ]
    missing = [
        name for name in required if not registry["functions"].get(name, {}).get("parameters")
    ]
    assert missing == []
    assert len(registry["functions"]["strategy.exit"]["parameters"]) >= 15
    assert len(registry["functions"]["request.security"]["parameters"]) >= 8


def test_v212_builtin_coverage_stays_closed_after_registry_expansion():
    report = builtin_registry_coverage_report()
    missing = {
        ns: ns_report["missing_expected"]
        for ns, ns_report in report["namespaces"].items()
        if ns_report["missing_expected"]
    }
    assert missing == {}
    assert report["function_count"] >= 275


def test_v212_compile_oracle_metadata_is_schema_v2_internal_checked():
    payload = json.loads(
        Path("tests/fixtures/compile_oracle/strategy_namespace/metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["schema_version"] == 2
    assert all(item["pine2ast_status"] == "pass" for item in payload["policy"])
    assert all(
        item["tradingview_status"] == "pending_external_oracle" for item in payload["policy"]
    )
