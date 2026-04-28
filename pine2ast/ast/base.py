from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, cast

from pine2ast.lexer.token import SourceSpan


class ASTNode:
    span: SourceSpan

    @property
    def kind(self) -> str:
        return self.__class__.__name__

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


class Statement(ASTNode):
    pass


class Expression(ASTNode):
    pass


class Declaration(Statement):
    pass


def _to_plain(value: Any) -> Any:
    if isinstance(value, ASTNode):
        result: dict[str, Any] = {"kind": value.kind}
        for f in fields(cast(Any, value)):
            result[f.name] = _to_plain(getattr(value, f.name))
        return result
    if isinstance(value, SourceSpan):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {f.name: _to_plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, tuple):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    return value
