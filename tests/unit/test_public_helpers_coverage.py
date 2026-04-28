from __future__ import annotations

from pine2ast.diagnostics import Diagnostic, Severity, format_diagnostic
from pine2ast.lexer.annotations import AnnotationKind, parse_annotation
from pine2ast.lexer.token import SourceSpan


def span() -> SourceSpan:
    return SourceSpan(1, 1, 1, 8, 0, 7)


def test_diagnostic_to_dict_format_and_error_property_cover_optional_fields():
    diag = Diagnostic(
        Severity.ERROR,
        "E_TEST",
        "bad thing",
        span(),
        hint="fix it",
        doc_url="https://example.test/doc",
    )
    assert diag.is_error is True
    assert diag.to_dict()["hint"] == "fix it"
    rendered = format_diagnostic(diag, "sample.pine")
    assert "ERROR E_TEST at sample.pine:1:8" in rendered
    assert "Hint: fix it" in rendered
    assert "Docs: https://example.test/doc" in rendered

    info = Diagnostic(Severity.INFO, "I_TEST", "ok", span())
    assert info.is_error is False
    assert "hint" not in info.to_dict()
    assert "doc_url" not in info.to_dict()
    assert format_diagnostic(info) == "INFO I_TEST at <memory>:1:8\n  ok"


def test_parse_annotation_variants_and_dict_shape():
    s = span()
    version = parse_annotation("//@version=6", s)
    assert version.kind is AnnotationKind.VERSION
    assert version.name == "version"
    assert version.value == "6"
    assert version.to_dict()["span"] == s.to_dict()

    description = parse_annotation("//@description hello world", s)
    assert description.kind is AnnotationKind.DESCRIPTION
    assert description.value == "hello world"

    assert parse_annotation("//@does_not_exist value", s).kind is AnnotationKind.UNKNOWN
    assert parse_annotation("//#region inputs", s).kind is AnnotationKind.REGION_START
    assert parse_annotation("//#endregion inputs", s).kind is AnnotationKind.REGION_END
    assert parse_annotation("// normal comment", s).name == "unknown"
