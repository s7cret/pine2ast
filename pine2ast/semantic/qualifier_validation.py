"""Qualifier ranking and validation utilities."""

from __future__ import annotations


def qualifier_rank(qualifier: str | None) -> int:
    """Return a numeric rank for Pine qualifier string.

    Lower values = stronger (more constraining).  Used to enforce
    qualifier-assignment compatibility: a variable declared with a weaker
    qualifier may not be assigned a value with a stronger qualifier.
    """
    order = {"const": 0, "input": 1, "simple": 2, "series": 3, None: 3}
    return order.get(qualifier, 3)
