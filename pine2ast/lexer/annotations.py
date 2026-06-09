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


# Map: //@<token> → AnnotationKind
_KIND_BY_NAME = {
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

# Kinds whose annotation routes by target name (//@param x value, //@field x value).
# These take the form <kind> <target_name> [<value>...], where target_name is
# the first whitespace-separated token after the kind, and the rest is the value.
_ROUTED_KINDS = {"param", "field"}


def parse_annotation(raw: str, span: SourceSpan) -> Annotation:
    """Parse a single //@... or //#region... annotation line.

    Forms accepted:
        //@version=6               → name='version', value='6'
        //@description=...         → name='description', value='...'
        //@function <text>         → name='function', value='<text>'
        //@returns <text>          → name='returns', value='<text>'
        //@type <text>             → name='type', value='<text>'
        //@enum <text>             → name='enum', value='<text>'
        //@variable <text>         → name='variable', value='<text>'
        //@param <name> <text>     → name='<name>', value='<text>' (target is name)
        //@field <name> <text>     → name='<name>', value='<text>' (target is name)
        //@param=<name>=<text>     → same as //@param
        //@field=<name>=<text>     → same as //@field
        //#region <name>           → REGION_START
        //#endregion <name>        → REGION_END
        //@anything-else <text>    → kind=UNKNOWN, name='anything-else', value='<text>'
    """
    text = raw.strip()
    if text.startswith("//@"):
        body = text[3:].strip()
        if not body:
            return Annotation(AnnotationKind.UNKNOWN, raw, "", None, span)
        # Detect kind: first whitespace-delimited token, optionally =<name>
        first_token = body.split(maxsplit=1)[0]
        kind_token = first_token.split("=", 1)[0].strip()
        if kind_token in _ROUTED_KINDS:
            # //@param x value  → kind=PARAM, name='x', value='value'
            # //@param=x=value  → same (alternate form)
            after_kind = body[len(kind_token):].strip()
            if after_kind.startswith("="):
                _, _, after_eq = after_kind.partition("=")
                head, _, rest = after_eq.partition(" ")
                name = head.strip()
                value = rest.strip() or None
            else:
                head, _, rest = after_kind.partition(" ")
                name = head.strip()
                value = rest.strip() or None
            # Look up kind by kind_token, not by name
            kind = _KIND_BY_NAME.get(kind_token, AnnotationKind.UNKNOWN)
            return Annotation(kind, raw, name, value, span)
        if "=" in body:
            # //@<name>=<value>
            name_part, value_part = body.split("=", 1)
            name = name_part.strip()
            value = value_part.strip()
        else:
            # //@<name> <value...>
            parts = body.split(maxsplit=1)
            name = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else None
        return Annotation(_KIND_BY_NAME.get(name, AnnotationKind.UNKNOWN), raw, name, value, span)
    if text.startswith("//#region"):
        value = text[len("//#region") :].strip() or None
        return Annotation(AnnotationKind.REGION_START, raw, "region", value, span)
    if text.startswith("//#endregion"):
        value = text[len("//#endregion") :].strip() or None
        return Annotation(AnnotationKind.REGION_END, raw, "endregion", value, span)
    return Annotation(AnnotationKind.UNKNOWN, raw, "unknown", None, span)
