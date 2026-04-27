from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pine2ast.lexer.token import SourceSpan


class Severity(str, Enum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(slots=True)
class Diagnostic:
    severity: Severity
    code: str
    message: str
    span: SourceSpan
    hint: str | None = None
    doc_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "span": self.span.to_dict(),
        }
        if self.hint:
            data["hint"] = self.hint
        if self.doc_url:
            data["doc_url"] = self.doc_url
        return data

    @property
    def is_error(self) -> bool:
        return self.severity in {Severity.FATAL, Severity.ERROR}
