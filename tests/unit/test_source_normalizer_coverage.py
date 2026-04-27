from __future__ import annotations

from pine2ast.diagnostics import codes
from pine2ast.source.normalizer import SourceNormalizer


def test_source_normalizer_handles_bom_newlines_and_long_line_warning():
    result = SourceNormalizer(line_too_long=3).normalize(
        "\ufeffabc\r\nlonger\r", source_name="x.pine"
    )
    assert result.source_name == "x.pine"
    assert result.text == "abc\nlonger\n"
    assert [d.code for d in result.diagnostics] == [codes.LINE_TOO_LONG]
    assert result.diagnostics[0].span.start_line == 2


def test_source_normalizer_handles_utf8_sig_bytes_and_invalid_bytes():
    ok = SourceNormalizer().normalize(b"\xef\xbb\xbf//@version=6\r\n")
    assert ok.text == "//@version=6\n"
    assert ok.diagnostics == []

    bad = SourceNormalizer().normalize(b"\xff")
    assert bad.text == ""
    assert bad.diagnostics[0].code == codes.INVALID_ENCODING
