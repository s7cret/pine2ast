import json
from pathlib import Path

from pine2ast.api import ParseOptions, parse_code, runtime_contract_v1_4_options
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.builtin_registry import load_builtin_registry

VISUAL_FUNCTIONS = {
    "plot",
    "plotshape",
    "plotchar",
    "plotarrow",
    "plotbar",
    "plotcandle",
    "hline",
    "fill",
    "bgcolor",
    "barcolor",
}

VISUAL_CONSTANT_PREFIXES = ("display.", "hline.", "location.", "plot.", "shape.", "size.")


def _errors(source: str, *, runtime_contract: bool = False) -> list[str]:
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


def test_visual_p0_functions_and_constants_match_official_v6_index_subset():
    registry = load_builtin_registry()
    official = json.loads(
        Path("pine2ast/reference_catalog/official_pine_v6_reference_index.json").read_text(
            encoding="utf-8"
        )
    )["categories"]

    missing_functions = sorted(VISUAL_FUNCTIONS - set(registry["functions"]))
    assert missing_functions == []
    assert VISUAL_FUNCTIONS <= set(official["functions"])

    official_visual_constants = {
        name for name in official["constants"] if name.startswith(VISUAL_CONSTANT_PREFIXES)
    }
    missing_constants = sorted(official_visual_constants - set(registry["variables"]))
    assert missing_constants == []


def test_visual_signatures_accept_known_v6_parameters_without_unknown_builtin_gaps():
    source = """//@version=6
indicator("visual signatures")
p1 = plot(close, "Close", color.blue, 2, plot.style_stepline, false, 0.0, 1, false, true, 10, display.all, format.price, 2, true, plot.linestyle_dashed)
p2 = plot(open, style = plot.style_areabr, display = display.pine_screener)
plotshape(close > open, "shape", shape.arrowup, location.belowbar, color.green, offset = 1, text = "S", textcolor = color.white, size = size.large, force_overlay = true)
plotchar(close > open, "char", "x", location.top, color.yellow, size = size.auto)
plotarrow(close - open, colorup = color.lime, colordown = color.red, display = display.status_line)
plotbar(open, high, low, close, display = display.all, force_overlay = true)
plotcandle(open, high, low, close, wickcolor = color.gray, bordercolor = color.black, display = display.all)
h1 = hline(1.0, "H1", color.blue, hline.style_dotted, 2, true, display.all)
h2 = hline(2.0)
fill(p1, p2, color.new(color.blue, 80), "fill", true, 10, true, display.all)
bgcolor(color.new(color.green, 90), force_overlay = true)
barcolor(color.red, display = display.all)
"""
    errors = _errors(source)
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNKNOWN_PARAMETER not in errors
    assert codes.ARGUMENT_COUNT not in errors


def test_visual_runtime_contract_profile_marks_known_visual_calls_unsupported():
    source = """//@version=6
indicator("visual runtime")
p1 = plot(close)
p2 = plot(open)
fill(p1, p2, color.new(color.blue, 80))
bgcolor(color.new(color.green, 90))
barcolor(color.red)
"""
    errors = _errors(source, runtime_contract=True)
    assert codes.UNSUPPORTED_FEATURE in errors
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors


def test_visual_unknown_parameter_is_specific_signature_error_not_unknown_builtin():
    source = """//@version=6
indicator("visual bad param")
bgcolor(color.red, transp = 90)
"""
    errors = _errors(source)
    assert codes.UNKNOWN_PARAMETER in errors
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors


def test_hline_series_price_still_fails_closed_on_qualifier():
    source = """//@version=6
indicator("hline bad price")
hline(close)
"""
    errors = _errors(source)
    assert codes.ARGUMENT_QUALIFIER in errors
    assert codes.UNKNOWN_PARAMETER not in errors
