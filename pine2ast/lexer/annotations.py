from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pine2ast.lexer.token import SourceSpan


class AnnotationKind(str, Enum):
    VERSION = "VERSION"
    DESCRIPTION = "DESCRIPTION"
    FUNCTION = "FUNCTION"
    PARAM = "PARAM"
    RETURNS = "RETURNS"
    TYPE = "TYPE"
    FIELD = "FIELD"
    ENUM = "ENUM"
    VARIABLE = "VARIABLE"
    STRATEGY_ALERT_MESSAGE = "STRATEGY_ALERT_MESSAGE"
    REGION_START = "REGION_START"
    REGION_END = "REGION_END"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class Annotation:
    kind: AnnotationKind
    raw: str
    name: str
    value: str | None
    span: SourceSpan

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "raw": self.raw,
            "name": self.name,
            "value": self.value,
            "span": self.span.to_dict(),
        }


def parse_annotation(raw: str, span: SourceSpan) -> Annotation:
    text = raw.strip()
    if text.startswith("//@"):
        body = text[3:].strip()
        if "=" in body:
            name, value = body.split("=", 1)
            name = name.strip()
            value = value.strip()
        else:
            parts = body.split(maxsplit=1)
            name = parts[0].strip() if parts else ""
            value = parts[1].strip() if len(parts) > 1 else None
        mapping = {
            "version": AnnotationKind.VERSION,
            "description": AnnotationKind.DESCRIPTION,
            "function": AnnotationKind.FUNCTION,
            "param": AnnotationKind.PARAM,
            "returns": AnnotationKind.RETURNS,
            "type": AnnotationKind.TYPE,
            "field": AnnotationKind.FIELD,
            "enum": AnnotationKind.ENUM,
            "variable": AnnotationKind.VARIABLE,
            "strategy_alert_message": AnnotationKind.STRATEGY_ALERT_MESSAGE,
        }
        return Annotation(mapping.get(name, AnnotationKind.UNKNOWN), raw, name, value, span)
    if text.startswith("//#region"):
        value = text[len("//#region") :].strip() or None
        return Annotation(AnnotationKind.REGION_START, raw, "region", value, span)
    if text.startswith("//#endregion"):
        value = text[len("//#endregion") :].strip() or None
        return Annotation(AnnotationKind.REGION_END, raw, "endregion", value, span)
    return Annotation(AnnotationKind.UNKNOWN, raw, "unknown", None, span)
