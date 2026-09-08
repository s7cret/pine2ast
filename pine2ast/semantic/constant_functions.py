"""Resource and lexical state for the existing producer constant-value visitor.

This module does not evaluate source expressions or resolve callable identities.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

MAX_FUNCTION_DEPTH = 64
MAX_ROOT_WORK = 4096
MAX_BUILDER_WORK = 262144
MAX_CACHE_ENTRIES = 4096
MAX_EXPRESSION_DEPTH = 128
MAX_INTEGER_BITS = 4096


def supported_scalar(value: Any) -> bool:
    if type(value) is bool:
        return True
    if type(value) is int:
        return value.bit_length() <= MAX_INTEGER_BITS
    return type(value) is float and math.isfinite(value)


def numeric(value: Any) -> bool:
    return type(value) in (int, float) and supported_scalar(value)


@dataclass
class ConstantWork:
    spent: int = 0
    results: dict[tuple[Any, ...], tuple[bool, Any]] = field(default_factory=dict)
    purity: dict[str, bool] = field(default_factory=dict)

    def room(self) -> bool:
        return len(self.results) + len(self.purity) < MAX_CACHE_ENTRIES


@dataclass
class ConstantFrame:
    declaration_id: str
    # Names only select bindings established in this exact lexical frame.
    bindings: dict[str, tuple[str, Any]]
    proof: Any | None = None


@dataclass
class ConstantContext:
    work: ConstantWork
    spent: int = 0
    expression_depth: int = 0
    frames: list[ConstantFrame] = field(default_factory=list)
    purity_active: set[str] = field(default_factory=set)
    proof_stack: list[Any] = field(default_factory=list)
    scope_stack: list[str] = field(default_factory=list)
    global_active: set[str] = field(default_factory=set)

    def charge(self) -> bool:
        if self.spent >= MAX_ROOT_WORK or self.work.spent >= MAX_BUILDER_WORK:
            return False
        self.spent += 1
        self.work.spent += 1
        return True

    def enter_expression(self) -> bool:
        if self.expression_depth >= MAX_EXPRESSION_DEPTH or not self.charge():
            return False
        self.expression_depth += 1
        return True

    def lookup(self, name: str) -> tuple[bool, Any]:
        if not self.frames or name not in self.frames[-1].bindings:
            return False, None
        return True, self.frames[-1].bindings[name][1]
