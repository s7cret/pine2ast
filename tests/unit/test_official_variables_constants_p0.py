from __future__ import annotations

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.reference_catalog import load_catalog, load_parity_matrix
from pine2ast.semantic.builtin_registry import load_builtin_registry

P0_VARIABLES = {
    "ask": ("float", "series"),
    "bid": ("float", "series"),
    "chart.bg_color": ("color", "input"),
    "chart.is_standard": ("bool", "simple"),
    "dayofmonth": ("int", "series"),
    "dayofweek": ("int", "series"),
    "dividends.future_amount": ("float", "series"),
    "earnings.future_time": ("int", "series"),
    "hlcc4": ("float", "series"),
    "hour": ("int", "series"),
    "last_bar_time": ("int", "series"),
    "minute": ("int", "series"),
    "month": ("int", "series"),
    "na": ("unknown", "const"),
    "second": ("int", "series"),
    "session.ismarket": ("bool", "series"),
    "syminfo.current_contract": ("string", "simple"),
    "syminfo.isin": ("string", "simple"),
    "syminfo.mincontract": ("int", "simple"),
    "syminfo.target_price_average": ("float", "simple"),
    "ta.accdist": ("float", "series"),
    "ta.tr": ("float", "series"),
    "ta.vwap": ("float", "series"),
    "time_close": ("int", "series"),
    "time_tradingday": ("int", "series"),
    "timeframe.main_period": ("string", "simple"),
    "weekofyear": ("int", "series"),
    "year": ("int", "series"),
}

P0_CONSTANTS = {
    "adjustment.dividends",
    "backadjustment.on",
    "color.fuchsia",
    "currency.AED",
    "dayofweek.monday",
    "font.family_monospace",
    "math.phi",
    "order.descending",
    "scale.right",
    "session.extended",
    "settlement_as_close.inherit",
    "text.format_bold",
    "xloc.bar_time",
    "yloc.abovebar",
}

P0_FAIL_CLOSED_CONSTANTS = {
    "color.fuchsia",
}


def _error_codes(source: str) -> list[str]:
    result = parse_code(source, ParseOptions(strict_builtin_namespaces=True))
    return [
        diagnostic.code
        for diagnostic in result.diagnostics
        if diagnostic.severity in {Severity.ERROR, Severity.FATAL}
    ]


def test_official_p0_variables_are_known_with_conservative_types() -> None:
    registry = load_builtin_registry()

    for name, (typ, qualifier) in P0_VARIABLES.items():
        assert registry["variables"][name] == {"type": typ, "qualifier": qualifier}


def test_official_p0_variables_do_not_trip_strict_namespace_checks() -> None:
    source = """//@version=6
indicator("official vars")
float quote = ask + bid + hlcc4 + dividends.future_amount + ta.accdist
bool market = session.ismarket and chart.is_standard
string meta = syminfo.current_contract + syminfo.isin + timeframe.main_period
int dates = earnings.future_time + last_bar_time + time_close + time_tradingday + weekofyear
int calendar = year + month + dayofmonth + dayofweek + hour + minute + second
float taVars = ta.tr + ta.vwap
plot(quote + dates + syminfo.mincontract + syminfo.target_price_average)
"""

    errors = _error_codes(source)

    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNDECLARED_VARIABLE not in errors


def test_official_p0_constants_are_known_but_not_runtime_verified() -> None:
    registry = load_builtin_registry()
    catalog = {entry["id"]: entry for entry in load_catalog()["entries"]}
    matrix = {
        (item["official_category"], item["id"]): item for item in load_parity_matrix()["items"]
    }

    for name in P0_CONSTANTS:
        expected_status = (
            "UNSUPPORTED_DIAGNOSTIC" if name in P0_FAIL_CLOSED_CONSTANTS else "NOT_STARTED"
        )
        assert registry["variables"][name]["qualifier"] == "const"
        assert catalog[name]["kind"] == "constant"
        assert catalog[name]["codegen_status"] == expected_status
        assert catalog[name]["runtime_status"] == expected_status
        assert matrix[("constants", name)]["semantic_status"] == "IMPLEMENTED_UNVERIFIED"


def test_official_p0_constants_do_not_trip_strict_namespace_checks() -> None:
    source = """//@version=6
indicator("official constants")
color c = color.fuchsia
float m = math.phi
string ids = currency.AED + font.family_monospace + text.format_bold
string modes = adjustment.dividends + backadjustment.on + settlement_as_close.inherit
string locs = xloc.bar_time + yloc.abovebar + order.descending + scale.right
plot(m, color = c)
"""

    errors = _error_codes(source)

    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNDECLARED_VARIABLE not in errors
