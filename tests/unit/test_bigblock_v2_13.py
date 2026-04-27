from pathlib import Path
import json

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes, Severity
from pine2ast.semantic.builtin_registry import builtin_registry_coverage_report, load_builtin_registry


def diags(src: str, *, strict: bool = False):
    return parse_code(src, ParseOptions(strict_builtin_namespaces=strict)).diagnostics


def error_codes(src: str, *, strict: bool = False):
    return [d.code for d in diags(src, strict=strict) if d.severity.value in {"ERROR", "FATAL"}]


def test_v213_request_metadata_pack_accepts_named_parameters_and_typed_constants():
    src = '''//@version=6
indicator("request pack")
f = request.financial(syminfo.tickerid, "TOTAL_REVENUE", "FQ", gaps = barmerge.gaps_off, ignore_invalid_symbol = true, currency = "USD")
d = request.dividends(syminfo.tickerid, dividends.gross, gaps = barmerge.gaps_on, lookahead = barmerge.lookahead_off)
e = request.earnings(syminfo.tickerid, earnings.actual, ignore_invalid_symbol = true)
s = request.splits(syminfo.tickerid, splits.numerator)
r = request.currency_rate("USD", "EUR", ignore_invalid_currency = true)
seed = request.seed("seed", "SYM", close, calc_bars_count = 10)
plot(close)
'''
    errors = error_codes(src)
    assert codes.UNKNOWN_PARAMETER not in errors
    assert codes.ARGUMENT_TYPE not in errors
    assert codes.ARGUMENT_QUALIFIER not in errors


def test_v213_request_metadata_rejects_wrong_typed_field_constant():
    src = '''//@version=6
indicator("bad request field")
d = request.dividends(syminfo.tickerid, earnings.actual)
plot(close)
'''
    assert codes.ARGUMENT_TYPE in error_codes(src)


def test_v213_style_and_display_constants_are_registered_and_strict_clean():
    src = '''//@version=6
indicator("style constants")
len = input.int(14, display = display.status_line)
l = line.new(bar_index, close, bar_index + 1, close, style = line.style_dashed)
lab = label.new(bar_index, close, "x", style = label.style_label_up)
t = table.new(position.middle_center, 2, 2)
table.set_position(t, position.middle_right)
plot(close)
'''
    errors = error_codes(src, strict=True)
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.ARGUMENT_TYPE not in errors


def test_v213_input_display_is_typed_and_rejects_plain_string():
    src = '''//@version=6
indicator("display bad")
len = input.int(14, display = "status")
plot(close)
'''
    assert codes.ARGUMENT_TYPE in error_codes(src)


def test_v213_strategy_risk_metadata_pack_and_script_policy():
    ok_src = '''//@version=6
strategy("risk pack")
strategy.risk.allow_entry_in(strategy.long)
strategy.risk.max_drawdown(25, strategy.percent_of_equity, alert_message = "dd")
strategy.risk.max_intraday_loss(1000, strategy.cash)
strategy.risk.max_cons_loss_days(3)
strategy.risk.max_intraday_filled_orders(10)
plot(close)
'''
    assert codes.UNKNOWN_PARAMETER not in error_codes(ok_src)
    assert codes.ARGUMENT_COUNT not in error_codes(ok_src)
    bad_src = '''//@version=6
indicator("risk wrong script")
strategy.risk.max_cons_loss_days(3)
'''
    assert codes.STRATEGY_CALL_WRONG_SCRIPT_TYPE in error_codes(bad_src)


def test_v213_registry_coverage_tracks_typed_constants_pack():
    report = builtin_registry_coverage_report()
    assert report["function_count"] >= 278
    assert report["variable_count"] >= 95
    for namespace in ["line", "label", "display", "position", "barmerge", "request"]:
        assert namespace in report["namespaces"]
    missing = {
        ns: ns_report["missing_expected"]
        for ns, ns_report in report["namespaces"].items()
        if ns_report["missing_expected"]
    }
    assert missing == {}


def test_v213_registry_entries_have_metadata_v2_for_next_pack():
    registry = load_builtin_registry()
    for name in [
        "request.financial", "request.dividends", "request.earnings", "request.splits", "request.currency_rate", "request.seed",
        "strategy.risk.allow_entry_in", "strategy.risk.max_drawdown", "strategy.risk.max_intraday_loss", "strategy.risk.max_cons_loss_days", "strategy.risk.max_intraday_filled_orders",
    ]:
        entry = registry["functions"].get(name)
        assert entry and entry.get("parameters"), name
        assert entry.get("metadata_version") == 2, name
    assert registry["variables"]["line.style_dashed"]["type"] == "line.style"
    assert registry["variables"]["display.status_line"]["type"] == "display"


def test_v213_baseline_reports_are_committed():
    base = Path("tests/fixtures/baselines/v2_13")
    for name in ["diagnostics_01_ma_indicator.json", "builtin_coverage.json", "semantic_01_ma_indicator.json"]:
        payload = json.loads((base / name).read_text(encoding="utf-8"))
        assert payload.get("schema_version") or payload.get("summary") or payload.get("semantic")
