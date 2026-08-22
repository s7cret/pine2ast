"""Small JSON-compatible immutable container types for public artifacts."""

from __future__ import annotations

from typing import Any


class FrozenDict(dict[str, Any]):
    """A ``dict`` that remains JSON Schema compatible but rejects mutation."""

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen artifact mappings cannot be modified")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable  # type: ignore[assignment]
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable  # type: ignore[assignment]


class FrozenList(list[Any]):
    """A ``list`` that remains JSON Schema compatible but rejects mutation."""

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("frozen artifact sequences cannot be modified")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable  # type: ignore[assignment]
    __imul__ = _immutable  # type: ignore[assignment]
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def deep_freeze(value: Any) -> Any:
    """Recursively freeze JSON-compatible dictionaries and lists."""

    if isinstance(value, FrozenDict | FrozenList):
        return value
    if isinstance(value, dict):
        return FrozenDict({key: deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return FrozenList(deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(deep_freeze(item) for item in value)
    return value


__all__ = ["FrozenDict", "FrozenList", "deep_freeze"]
