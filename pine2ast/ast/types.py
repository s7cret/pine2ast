from __future__ import annotations

from dataclasses import dataclass, field

from pine2ast.ast.base import ASTNode
from pine2ast.lexer.token import SourceSpan


@dataclass(slots=True)
class TypeRef(ASTNode):
    name: str
    template_args: list["TypeRef"] = field(default_factory=list)
    span: SourceSpan = field(default_factory=SourceSpan.zero)
