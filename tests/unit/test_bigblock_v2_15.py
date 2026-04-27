import copy

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.semantic.builtin_registry import (
    BuiltinRegistrySchemaError,
    builtin_registry_coverage_report,
    load_builtin_registry,
    validate_builtin_registry,
)


def assert_corrupt_registry_is_rejected(registry, needle: str):
    try:
        validate_builtin_registry(registry)
    except BuiltinRegistrySchemaError as exc:
        assert needle in str(exc), str(exc)
    else:  # pragma: no cover - stdlib runner has no pytest.raises helper
        raise AssertionError("corrupt builtin registry was accepted")


def clean_registry_copy():
    registry = copy.deepcopy(load_builtin_registry())
    validate_builtin_registry(registry)
    return registry


def test_v215_builtin_registry_schema_rejects_missing_required_sections():
    registry = clean_registry_copy()
    del registry["variables"]
    assert_corrupt_registry_is_rejected(registry, "$.variables")


def test_v215_builtin_registry_schema_rejects_function_name_mismatch():
    registry = clean_registry_copy()
    registry["functions"]["ta.sma"]["name"] = "ta.ema"
    assert_corrupt_registry_is_rejected(registry, "$.functions.ta.sma.name")


def test_v215_builtin_registry_schema_rejects_malformed_parameters():
    registry = clean_registry_copy()
    registry["functions"]["ta.sma"]["parameters"] = {"source": "series float"}
    assert_corrupt_registry_is_rejected(registry, "$.functions.ta.sma.parameters")


def test_v215_builtin_registry_schema_rejects_duplicate_parameters():
    registry = clean_registry_copy()
    registry["functions"]["ta.sma"]["parameters"] = [
        {"name": "source", "type": "series float", "required": True},
        {"name": "source", "type": "simple int", "required": True},
    ]
    assert_corrupt_registry_is_rejected(registry, "duplicate parameter")


def test_v215_builtin_registry_schema_rejects_bad_variable_qualifier():
    registry = clean_registry_copy()
    registry["variables"]["bar_index"]["qualifier"] = "sometimes"
    assert_corrupt_registry_is_rejected(registry, "$.variables.bar_index.qualifier")


def test_v215_builtin_coverage_taxonomy_separates_internal_official_and_deferred():
    report = builtin_registry_coverage_report()
    assert report["coverage_basis"] == "internal_expected_snapshot_not_official_complete"
    assert report["missing_internal_expected_count"] == 0
    assert report["official_unmapped_count"] == 0
    assert report["known_deferred_count"] > 0
    assert report["known_unsupported_count"] > 0
    assert "official_unmapped" in report["taxonomy"]
    line = report["namespaces"]["line"]
    assert line["missing_expected"] == []  # legacy alias remains internal-only.
    assert line["missing_internal_expected"] == []
    assert line["official_unmapped"] == []  # safe v3 line setters are now modeled.
    assert line["coverage_basis"] == "internal_expected_snapshot_not_official_complete"
    assert "box.copy" not in report["namespaces"]["box"]["official_unmapped"]


def test_v215_line_setter_registry_expansion_accepts_named_parameters_and_types():
    ok_src = """//@version=6
indicator("line setters")
l = line.new(bar_index, close, bar_index + 1, close)
line.set_style(l, line.style_dashed)
line.set_width(l, 2)
line.set_extend(l, extend.right)
line.set_x1(l, bar_index)
line.set_y2(l, close)
plot(close)
"""
    ok = parse_code(ok_src, ParseOptions(strict_builtin_namespaces=True))
    ok_errors = [d.code for d in ok.diagnostics if d.severity.value in {"ERROR", "FATAL"}]
    assert codes.UNKNOWN_BUILTIN_MEMBER not in ok_errors
    assert codes.UNKNOWN_PARAMETER not in ok_errors
    assert codes.ARGUMENT_TYPE not in ok_errors

    bad_src = """//@version=6
indicator("bad line setter")
l = line.new(bar_index, close, bar_index + 1, close)
line.set_width(l, "wide")
"""
    bad = parse_code(bad_src, ParseOptions(strict_builtin_namespaces=True))
    bad_errors = [d.code for d in bad.diagnostics if d.severity.value in {"ERROR", "FATAL"}]
    assert codes.ARGUMENT_TYPE in bad_errors
