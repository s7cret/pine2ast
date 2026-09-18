"""Resolve a named/positional argument without confusing source order with binding."""

from __future__ import annotations
from collections.abc import Sequence
from pine2ast.ast.nodes import Argument, Expression


def argument_value(arguments: Sequence[Argument], name: str, position: int) -> Expression | None:
    for argument in arguments:
        if argument.name == name:
            return argument.value
    positional = [argument.value for argument in arguments if argument.name is None]
    return positional[position] if position < len(positional) else None
