from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib.resources import files
from typing import Any, Mapping, NoReturn

from pine2ast.catalog.model import CatalogIdentity, CatalogIntegrityError, CatalogStatus
from pine2ast.catalog.schema import validate_catalog_pack

_PACK_NAMES = {version: f"pine_v{version}.pack.json" for version in range(1, 7)}


class FrozenDict(dict):
    """JSON-compatible immutable mapping used by internal catalog views."""

    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> NoReturn:
        raise TypeError("catalog view is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable

    # The single variadic blocker deliberately covers every dict mutation
    # signature.  The targeted ignores document the two operators whose
    # typeshed overloads cannot be represented by one shared implementation.
    popitem = _immutable  # type: ignore[assignment]

    setdefault = _immutable
    update = _immutable

    __ior__ = _immutable  # type: ignore[assignment]


class FrozenList(list):
    """JSON-compatible immutable sequence used by internal catalog views."""

    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> NoReturn:
        raise TypeError("catalog view is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    __iadd__ = _immutable  # type: ignore[assignment]
    __imul__ = _immutable  # type: ignore[assignment]


class CatalogRepository:
    _default: "CatalogRepository | None" = None

    @classmethod
    def default(cls) -> "CatalogRepository":
        if cls._default is None:
            cls._default = cls()
        return cls._default

    @staticmethod
    @lru_cache(maxsize=6)
    def _load_frozen(version: int) -> Mapping[str, Any]:
        if version not in _PACK_NAMES:
            raise CatalogIntegrityError(f"catalog version must be one of 1..6, got {version!r}")
        path = files("pine2ast.catalog_data.packs").joinpath(_PACK_NAMES[version])
        pack = json.loads(path.read_text(encoding="utf-8"))
        validate_catalog_pack(pack)
        return _deep_freeze(pack)

    def identity(self, version: int) -> CatalogIdentity:
        pack = self._load_frozen(version)
        return CatalogIdentity(
            pine_version=version,
            status=CatalogStatus(str(pack["status"])),
            spec_snapshot_ref=str(pack["spec_snapshot_ref"]),
            catalog_hash=str(pack["catalog_hash"]),
        )

    def identity_tuple(self, version: int) -> tuple[str, str]:
        identity = self.identity(version)
        return identity.spec_snapshot_ref, identity.catalog_hash

    @staticmethod
    @lru_cache(maxsize=6)
    def _load_readonly_view(version: int) -> Mapping[str, Any]:
        """Return the canonical immutable semantic view for internal frontend use.

        The materialized pack is validated and frozen exactly once.  Internal parser,
        binder, inference, and artifact passes share this read-only projection instead
        of recursively copying thousands of catalog entries for every parse.
        """
        pack = CatalogRepository._load_frozen(version)
        sections = pack["sections"]
        result: dict[str, Any] = {
            "schema_version": 2,
            "pine_version": str(version),
            "catalog_hash": pack["catalog_hash"],
            "catalog_status": pack["status"],
            "rules": pack["rules"],
        }
        result.update(sections)
        for required in ("functions", "namespaces", "types", "variables"):
            result.setdefault(required, FrozenDict())
        return FrozenDict(result)

    def pack(self, version: int) -> dict[str, Any]:
        """Return an isolated mutable copy for public inspection/export callers."""
        return _deep_thaw(self._load_frozen(version))

    def readonly_view(self, version: int) -> Mapping[str, Any]:
        """Return a cached immutable view for trusted read-only frontend consumers."""
        return self._load_readonly_view(version)

    def view(self, version: int) -> dict[str, Any]:
        pack = self.pack(version)
        sections = pack["sections"]
        result: dict[str, Any] = {
            "schema_version": 2,
            "pine_version": str(version),
            "catalog_hash": pack["catalog_hash"],
            "catalog_status": pack["status"],
            "rules": copy.deepcopy(pack["rules"]),
        }
        result.update(copy.deepcopy(sections))
        # Consumers historically expect these four mandatory maps.  They are not
        # a legacy data source: this is the sole materialized projection of the
        # canonical pack.
        for required in ("functions", "namespaces", "types", "variables"):
            result.setdefault(required, {})
        return result

    def rule(self, version: int, name: str) -> Any:
        pack = self._load_frozen(version)
        rules = pack["rules"]
        if name not in rules:
            raise CatalogIntegrityError(f"catalog v{version} has no semantic rule {name!r}")
        return _deep_thaw(rules[name])


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenDict({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return FrozenList(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_thaw(item) for item in value]
    return copy.deepcopy(value)


def clear_catalog_cache() -> None:
    CatalogRepository._load_frozen.cache_clear()
    CatalogRepository._load_readonly_view.cache_clear()
    CatalogRepository._default = None


__all__ = ["CatalogRepository", "clear_catalog_cache"]
