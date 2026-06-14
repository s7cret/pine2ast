"""Small AST traversal helpers shared by semantic and contract layers."""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Iterable

from pine2ast.ast.base import ASTNode

# Cached field tuples keyed by dataclass type. ``dataclasses.fields()`` is
# surprisingly expensive (~15us per call) and ``iter_child_nodes`` is on the
# hot path for the static validation walker (P1.5 perf gate). Cache once per
# class — instances of the same AST class share the same field tuple.
#
# We read ``__dataclass_fields__`` directly (the public dataclass storage) so
# the static type checker doesn't complain about passing a generic ``ASTNode``
# through ``dataclasses.fields()`` (the protocol narrows the type to
# ``DataclassInstance`` which ``ASTNode`` does not advertise statically).
_FIELDS_CACHE: dict[type, tuple[str, ...]] = {}


def _cached_field_names(node: ASTNode) -> tuple[str, ...]:
    """Return dataclass field names for ``node``'s class, cached by class."""
    cls = type(node)
    cached = _FIELDS_CACHE.get(cls)
    if cached is None:
        cached = tuple(node.__dataclass_fields__.keys())  # type: ignore[attr-defined]
        _FIELDS_CACHE[cls] = cached
    return cached


def iter_child_nodes(node: ASTNode) -> Iterable[ASTNode]:
    """Yield direct ASTNode children from dataclass fields.

    The AST uses dataclass nodes with nested node/list fields. Keeping traversal
    here avoids each semantic/reporting module reimplementing slightly different
    walkers.
    """

    if not is_dataclass(node):
        return
    _getattr = getattr
    for fname in _cached_field_names(node):
        value = _getattr(node, fname)
        if isinstance(value, ASTNode):
            yield value
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, ASTNode):
                    yield child


def iter_nodes(node: ASTNode) -> Iterable[ASTNode]:
    """Yield ``node`` and all descendants in source/dataclass order."""

    yield node
    for child in iter_child_nodes(node):
        yield from iter_nodes(child)
