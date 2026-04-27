from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.semantic.builtin_registry import (
    builtin_registry_coverage_report,
    load_builtin_registry,
)


def _diagnostic_codes(src: str) -> list[str]:
    result = parse_code(src, ParseOptions(strict_builtin_namespaces=True))
    return [
        d.code
        for d in result.diagnostics
        if d.severity in {Severity.ERROR, Severity.FATAL, Severity.INFO}
    ]


def test_v31_box_and_label_copy_are_modeled_builtins():
    registry = load_builtin_registry()
    assert registry["functions"]["box.copy"]["returns"] == "box"
    assert registry["functions"]["label.copy"]["returns"] == "label"

    src = """//@version=6
indicator("copy")
b = box.new(bar_index, high, bar_index + 1, low)
l = label.new(bar_index, close, "x")
b2 = box.copy(b)
l2 = label.copy(l)
plot(close)
"""
    result = parse_code(src, ParseOptions(strict_builtin_namespaces=True))
    errors = [d.code for d in result.diagnostics if d.severity in {Severity.ERROR, Severity.FATAL}]
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.ARGUMENT_TYPE not in errors


def test_v31_official_gap_is_closed_without_claiming_deferred_surfaces():
    report = builtin_registry_coverage_report()
    assert report["official_unmapped_count"] == 0
    assert report["known_deferred_count"] > 0
    assert report["known_unsupported_count"] > 0
    assert "request.economic" in report["namespaces"]["request"]["known_deferred"]
    assert "runtime.error" in report["namespaces"]["runtime"]["known_unsupported"]


def test_v31_request_economic_has_explicit_deferred_contract():
    src = """//@version=6
indicator("econ")
x = request.economic("US", "GDP")
plot(close)
"""
    result = parse_code(src, ParseOptions(strict_builtin_namespaces=True))
    assert any(
        d.code == codes.UNSUPPORTED_FEATURE and d.severity is Severity.INFO
        for d in result.diagnostics
    )
    assert not any(d.code == codes.REQUEST_SIGNATURE for d in result.diagnostics)


def test_v31_runtime_error_has_explicit_unsupported_contract():
    src = """//@version=6
indicator("runtime")
runtime.error("stop")
plot(close)
"""
    result = parse_code(src, ParseOptions(strict_builtin_namespaces=True))
    assert any(
        d.code == codes.UNSUPPORTED_FEATURE and d.severity is Severity.ERROR
        for d in result.diagnostics
    )
    assert not any(d.code == codes.UNKNOWN_BUILTIN_MEMBER for d in result.diagnostics)
