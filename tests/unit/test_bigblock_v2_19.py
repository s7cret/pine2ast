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
    else:  # pragma: no cover
        raise AssertionError("corrupt builtin registry was accepted")


def clean_registry_copy():
    registry = copy.deepcopy(load_builtin_registry())
    validate_builtin_registry(registry)
    return registry


def test_v219_builtin_registry_schema_rejects_missing_schema_version():
    registry = clean_registry_copy()
    del registry["schema_version"]
    assert_corrupt_registry_is_rejected(registry, "unsupported schema_version/pine_version")


def test_v219_builtin_registry_schema_rejects_bad_pine_version():
    registry = clean_registry_copy()
    # pine_version "7" is not yet supported; the schema validator must reject it.
    # (Pine v5 is now a valid value, see builtin_registry._REGISTRY_FILES.)
    registry["pine_version"] = "7"
    assert_corrupt_registry_is_rejected(registry, "unsupported schema_version/pine_version")


def test_v219_builtin_registry_schema_rejects_function_without_returns():
    registry = clean_registry_copy()
    del registry["functions"]["ta.sma"]["returns"]
    assert_corrupt_registry_is_rejected(registry, "$.functions.ta.sma.returns")


def test_v219_builtin_registry_schema_rejects_parameter_without_name():
    registry = clean_registry_copy()
    registry["functions"]["ta.sma"]["parameters"] = [{"type": "float", "required": True}]
    assert_corrupt_registry_is_rejected(registry, ".parameters[0].name")


def test_v219_builtin_registry_schema_rejects_invalid_removed_in():
    registry = clean_registry_copy()
    registry["functions"]["strategy.entry"]["parameters"][-1]["removed_in"] = "v6"
    assert_corrupt_registry_is_rejected(registry, ".removed_in")


def test_v219_builtin_registry_schema_rejects_duplicate_overload_and_parameter():
    registry = clean_registry_copy()
    registry["functions"]["ta.sma"]["overloads"] = [
        {
            "returns": "float",
            "parameters": [
                {"name": "source", "type": "float", "required": True},
                {"name": "source", "type": "int", "required": True},
            ],
        }
    ]
    assert_corrupt_registry_is_rejected(registry, "duplicate parameter")

    registry = clean_registry_copy()
    overload = {
        "returns": "float",
        "parameters": [{"name": "source", "type": "float", "required": True}],
    }
    registry["functions"]["ta.sma"]["overloads"] = [
        copy.deepcopy(overload),
        copy.deepcopy(overload),
    ]
    assert_corrupt_registry_is_rejected(registry, "duplicate overload signature")


def test_v219_builtin_registry_schema_rejects_unknown_qualifier_and_type():
    registry = clean_registry_copy()
    registry["functions"]["input.int"]["parameters"][0]["qualifier_max"] = "runtime"
    assert_corrupt_registry_is_rejected(registry, "unsupported qualifier")

    registry = clean_registry_copy()
    registry["functions"]["input.int"]["parameters"][0]["type"] = "future<object>"
    assert_corrupt_registry_is_rejected(registry, "unsupported generic base")


def error_codes(src: str, *, strict: bool = False):
    result = parse_code(src, ParseOptions(strict_builtin_namespaces=strict))
    return [d.code for d in result.diagnostics if d.severity.value in {"ERROR", "FATAL"}]


def test_v219_label_box_table_setter_metadata_accepts_named_and_typed_calls():
    src = """//@version=6
indicator("setters")
l = label.new(bar_index, close, "x")
label.set_style(l, label.style_label_down)
label.set_size(l, size.small)
label.set_tooltip(l, "tip")
b = box.new(bar_index, high, bar_index + 1, low)
box.set_border_style(b, line.style_dashed)
box.set_extend(b, extend.right)
box.set_text(b, "txt")
t = table.new(position.top_right, 2, 2)
table.cell(t, 0, 0, text = "a", bgcolor = color.green)
table.cell_set_text(t, 0, 0, "b")
table.merge_cells(table_id = t, start_column = 0, start_row = 0, end_column = 1, end_row = 1)
plot(close)
"""
    errors = error_codes(src, strict=True)
    assert codes.UNKNOWN_BUILTIN_MEMBER not in errors
    assert codes.UNKNOWN_PARAMETER not in errors
    assert codes.ARGUMENT_COUNT not in errors
    assert codes.ARGUMENT_TYPE not in errors


def test_v219_builtin_signature_validation_named_count_type_and_qualifier():
    src = """//@version=6
indicator("bad signatures")
l = label.new(bar_index, close, "x")
label.set_style(l, style = "bad")
table.cell_set_text(table.new(position.top_right, 1, 1), 0, 0, text = 42, extra = true)
len_title = str.tostring(close)
x = input.int(1, title = len_title)
plot(close)
"""
    errors = error_codes(src, strict=True)
    assert codes.ARGUMENT_TYPE in errors
    assert codes.UNKNOWN_PARAMETER in errors
    assert codes.ARGUMENT_QUALIFIER in errors


def test_v219_coverage_taxonomy_keeps_official_backlog_honest():
    report = builtin_registry_coverage_report()
    assert report["missing_internal_expected_count"] == 0
    assert report["official_unmapped_count"] == 0
    assert report["known_deferred_count"] == 0
    assert report["known_unsupported_count"] > 0
    assert report["taxonomy"]["official_unmapped"]
    assert "box.set_text" not in report["namespaces"]["box"]["official_unmapped"]
    assert "table.cell_set_text" not in report["namespaces"]["table"]["official_unmapped"]
