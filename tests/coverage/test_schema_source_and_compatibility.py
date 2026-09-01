from __future__ import annotations

from pine2ast import parse_code
from pine2ast.ast.schema import SchemaIssue, SchemaReport, validate_ast_schema
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan
from pine2ast.semantic import type_system, types, validators
from pine2ast.source.normalizer import SourceNormalizer
from pine2ast.source.source_map import SourceMap
from pine2ast.versioning.resolver import PineVersionResolver, _scan_version_annotations


def test_source_normalizer_handles_bom_invalid_utf8_line_endings_and_limits() -> None:
    normalizer = SourceNormalizer(line_too_long=3)
    decoded = normalizer.normalize(b"\xef\xbb\xbfabc\r\ndef\rghi", source_name="bytes.pine")
    assert decoded.text == "abc\ndef\nghi"
    assert decoded.source_name == "bytes.pine"
    assert decoded.diagnostics == []

    text_bom = normalizer.normalize("\ufeffabcd\r\n")
    assert text_bom.text == "abcd\n"
    assert [diagnostic.code for diagnostic in text_bom.diagnostics] == [codes.LINE_TOO_LONG]
    assert text_bom.diagnostics[0].span.start_line == 1

    invalid = normalizer.normalize(b"\xff")
    assert invalid.text == ""
    assert [diagnostic.code for diagnostic in invalid.diagnostics] == [codes.INVALID_ENCODING]
    assert invalid.diagnostics[0].is_error


def test_small_compatibility_surfaces_are_importable_and_alias_canonical_types() -> None:
    assert SourceMap().source_name == "<memory>"
    assert SourceMap("script.pine").source_name == "script.pine"
    assert types.Qualifier is types.PineQualifier
    assert types.is_reference_type is types.is_reference_type_name
    assert types.type_to_string(types.parse_type_string("array<float>")) == "array<float>"
    assert type_system.PineType is types.PineType
    assert "plot" in validators.FORBIDDEN_IN_LOCAL_BLOCKS
    assert "library" in validators.FORBIDDEN_IN_LOCAL_BLOCKS


def test_ast_schema_reports_corrupt_headers_shared_nodes_spans_and_function_body() -> None:
    result = parse_code('//@version=6\nindicator("schema")\nf(float x) => x\ny = f(close)\n')
    assert result.ast is not None
    program = result.ast
    clean = validate_ast_schema(program)
    assert clean.ok
    assert clean.pine_version == 6
    assert clean.node_count > 0
    assert clean.to_dict()["kind_counts"] == dict(sorted(clean.kind_counts.items()))

    program.schema_version = "1.0"
    program.language = "other"
    program.version_context = object()  # type: ignore[assignment]
    function = next(item for item in program.items if type(item).__name__ == "FunctionDeclaration")
    function.body = object()  # type: ignore[assignment]
    first = program.items[0]
    first.span = SourceSpan(2, 1, 0, 0, 0, 0)
    program.items.append(first)

    report = validate_ast_schema(program)
    assert report.ok is False
    assert report.pine_version is None
    assert report.version_context is None
    codes_seen = {issue.code for issue in report.issues}
    assert {
        "AST_SCHEMA_VERSION_INVALID",
        "AST_LANGUAGE_INVALID",
        "AST_VERSION_CONTEXT_INVALID",
        "AST_SHARED_NODE",
        "AST_SPAN_INVALID",
        "AST_DECLARATION_BODY_INVALID",
    } <= codes_seen
    payload = report.to_dict()
    assert payload["issues"]
    assert any(row["span"] is not None for row in payload["issues"])

    issue = SchemaIssue("X", "message")
    empty = SchemaReport(True, None, None, None, None, 0, issues=[issue])
    assert empty.to_dict()["issues"] == [
        {"code": "X", "message": "message", "node_kind": None, "span": None}
    ]


def test_ast_schema_reports_non_source_span_without_crashing() -> None:
    result = parse_code('//@version=6\nindicator("schema")\nx = 1\n')
    assert result.ast is not None
    result.ast.items[0].span = object()  # type: ignore[assignment]
    report = validate_ast_schema(result.ast)
    assert "AST_SPAN_MISSING" in {issue.code for issue in report.issues}


def test_version_resolver_rejects_boolean_and_out_of_range_expectations() -> None:
    resolver = PineVersionResolver(
        lambda version: (f"snapshot-v{version}", "sha256:" + f"{version:064x}")
    )
    bool_expected = resolver.resolve('//@version=6\nindicator("x")\n', expected_pine_version=True)
    assert not bool_expected.ok
    assert [item.code for item in bool_expected.diagnostics] == [codes.INVALID_EXPECTED_VERSION]

    out_of_range = resolver.resolve('//@version=6\nindicator("x")\n', expected_pine_version=7)
    assert not out_of_range.ok
    assert [item.code for item in out_of_range.diagnostics] == [codes.INVALID_EXPECTED_VERSION]


def test_version_scanner_ignores_escaped_and_multiline_string_contents() -> None:
    source = '''text = "escaped \\\" //@version=2"
triple = """//@version=3
still text"""
'//@version=4'
//@version=6
indicator("ok")
'''
    candidates = _scan_version_annotations(source)
    assert [candidate.raw for candidate in candidates] == ["//@version=6"]

    resolver = PineVersionResolver(
        lambda version: (f"snapshot-v{version}", "sha256:" + f"{version:064x}")
    )
    resolution = resolver.resolve(source)
    assert resolution.ok
    assert resolution.context is not None
    assert resolution.context.pine_version == 6
