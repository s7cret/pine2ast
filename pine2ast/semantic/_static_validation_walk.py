"""AST walker for the static-validation pass.

Split out from ``static_validation.py`` so the main module stays under the
4.0 architecture budget (P0). The walker is purpose-built: it yields every
``(CallExpr, context)`` pair in a single pass so the four downstream
helpers (counts / dynamic-request / strategy.exit / sort_field) can
consume the same list without re-traversing the tree.
"""

from __future__ import annotations

from typing import Any, Iterator

from pine2ast.ast.nodes import Block, CallExpr
from pine2ast.ast.walk import iter_child_nodes
from pine2ast.semantic.facts import node_context_marker


def iter_calls_with_context_fast(node: Any) -> Iterator[tuple[Any, tuple]]:
    """Yield every ``(CallExpr, context)`` pair under ``node``.

    Equivalent to ``iter_calls_with_context`` but kept here so static
    validation can call it locally without paying for the public helper's
    per-node context-tuple allocation when the result will be consumed by
    three different passes back-to-back.
    """
    stack: list[tuple[Any, tuple]] = [(node, ())]
    _iter_children = iter_child_nodes
    while stack:
        cur, context = stack.pop()
        if isinstance(cur, CallExpr):
            yield cur, context
        marker = node_context_marker(cur)
        child_context = context + ((marker,) if marker else ())
        if isinstance(cur, Block):
            child_context = context
        for child in _iter_children(cur):
            stack.append((child, child_context))


__all__ = ["iter_calls_with_context_fast"]
