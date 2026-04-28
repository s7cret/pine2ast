from __future__ import annotations

from dataclasses import dataclass

from pine2ast.diagnostics import Diagnostic, Severity
from pine2ast.diagnostics import codes
from pine2ast.lexer.token import SourceSpan


@dataclass(slots=True)
class NormalizedSource:
    text: str
    diagnostics: list[Diagnostic]
    source_name: str = "<memory>"


class SourceNormalizer:
    def __init__(self, *, line_too_long: int = 20_000) -> None:
        self.line_too_long = line_too_long

    def normalize(self, source: str | bytes, *, source_name: str = "<memory>") -> NormalizedSource:
        diagnostics: list[Diagnostic] = []
        if isinstance(source, bytes):
            try:
                text = source.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                diagnostics.append(
                    Diagnostic(
                        Severity.FATAL,
                        codes.INVALID_ENCODING,
                        f"Input is not valid UTF-8: {exc}",
                        SourceSpan.zero(),
                    )
                )
                return NormalizedSource("", diagnostics, source_name)
        else:
            text = source
            if text.startswith("\ufeff"):
                text = text[1:]

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        offset = 0
        for line_no, line in enumerate(text.split("\n"), start=1):
            if len(line) > self.line_too_long:
                diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        codes.LINE_TOO_LONG,
                        f"Line is longer than {self.line_too_long} characters.",
                        SourceSpan(offset, offset + len(line), line_no, 1, line_no, len(line) + 1),
                    )
                )
            offset += len(line) + 1
        return NormalizedSource(text, diagnostics, source_name)
