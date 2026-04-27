from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Iterator

from pine2ast.ast.base import ASTNode


def walk(node: ASTNode) -> Iterator[ASTNode]:
    yield node
    if not is_dataclass(node):
        return
    for f in fields(node):
        value = getattr(node, f.name)
        if isinstance(value, ASTNode):
            yield from walk(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, ASTNode):
                    yield from walk(item)
