from pine2ast import ParseOptions, parse_code
from pine2ast.api import runtime_contract_v1_4_options
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.builtin_registry import load_builtin_registry, validate_builtin_registry

OFFICIAL_V6_REQUEST_FUNCTIONS = {
    "request.security": [
        "symbol",
        "timeframe",
        "expression",
        "gaps",
        "lookahead",
        "ignore_invalid_symbol",
        "currency",
        "calc_bars_count",
    ],
    "request.security_lower_tf": [
        "symbol",
        "timeframe",
        "expression",
        "ignore_invalid_symbol",
        "currency",
        "ignore_invalid_timeframe",
        "calc_bars_count",
    ],
    "request.currency_rate": ["from", "to", "ignore_invalid_currency"],
    "request.dividends": [
        "ticker",
        "field",
        "gaps",
        "lookahead",
        "ignore_invalid_symbol",
        "currency",
    ],
    "request.splits": [
        "ticker",
        "field",
        "gaps",
        "lookahead",
        "ignore_invalid_symbol",
        "currency",
    ],
    "request.earnings": [
        "ticker",
        "field",
        "gaps",
        "lookahead",
        "ignore_invalid_symbol",
        "currency",
    ],
    "request.financial": [
        "symbol",
        "financial_id",
        "period",
        "gaps",
        "ignore_invalid_symbol",
        "currency",
    ],
    "request.economic": ["country_code", "field", "gaps", "ignore_invalid_symbol"],
    "request.footprint": ["ticks_per_row", "va_percent", "imbalance_percent"],
    "request.seed": [
        "source",
        "symbol",
        "expression",
        "ignore_invalid_symbol",
        "calc_bars_count",
    ],
}


def _errors(src: str, *, strict: bool = True) -> list[str]:
    result = parse_code(src, ParseOptions(strict_builtin_namespaces=strict))
    return [
        diag.code
        for diag in result.diagnostics
        if diag.severity in {Severity.ERROR, Severity.FATAL}
    ]


def test_official_v6_request_namespace_entries_are_known_and_schema_valid():
    registry = load_builtin_registry()
    validate_builtin_registry(registry)

    for name, expected_params in OFFICIAL_V6_REQUEST_FUNCTIONS.items():
        entry = registry["functions"].get(name)
        assert entry is not None, name
        assert [param["name"] for param in entry["parameters"]] == expected_params
        assert entry["pine_version"] == "6"
        assert entry["scope"] == "any"

    assert registry["functions"]["request.economic"]["unsupported"] is True
    assert registry["functions"]["request.footprint"]["parameters"][1]["required"] is False
    assert registry["functions"]["request.footprint"]["parameters"][2]["required"] is False


def test_request_signatures_accept_official_series_and_optional_request_arguments():
    src = """//@version=6
indicator("request signatures")
fromCode = close > open ? "USD" : "EUR"
financialId = close > open ? "TOTAL_REVENUE" : "NET_INCOME"
period = close > open ? "FQ" : "FY"
rate = request.currency_rate(fromCode, "EUR", ignore_invalid_currency = close > open)
fin = request.financial(syminfo.tickerid, financialId, period)
fp = request.footprint(10)
plot(close)
"""
    errors = _errors(src)
    assert codes.ARGUMENT_QUALIFIER not in errors
    assert codes.UNKNOWN_PARAMETER not in errors
    assert codes.ARGUMENT_COUNT not in errors


def test_request_economic_is_known_but_runtime_unsupported():
    src = """//@version=6
indicator("econ")
x = request.economic("US", "GDP")
plot(close)
"""
    result = parse_code(src, runtime_contract_v1_4_options())
    assert any(
        diag.code == codes.UNSUPPORTED_FEATURE and diag.severity is Severity.ERROR
        for diag in result.diagnostics
    )
    assert not any(diag.code == codes.REQUEST_SIGNATURE for diag in result.diagnostics)
