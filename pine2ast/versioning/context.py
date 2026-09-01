from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from enum import Enum
from typing import Any, Final

from pine2ast.lexer.token import SourceSpan

SUPPORTED_PINE_VERSIONS: Final[frozenset[int]] = frozenset({1, 2, 3, 4, 5, 6})
PRODUCTION_FRONTEND_VERSIONS: Final[frozenset[int]] = SUPPORTED_PINE_VERSIONS


class VersionOrigin(str, Enum):
    COMPILER_ANNOTATION = "compiler_annotation"
    TRADINGVIEW_DEFAULT_V1 = "tradingview_default_v1"


@dataclass(frozen=True, slots=True)
class PineVersionContext:
    """The sole immutable Pine language-version identity for one source."""

    pine_version: int
    origin: VersionOrigin
    annotation_span: SourceSpan | None
    spec_snapshot_ref: str
    catalog_hash: str

    def __post_init__(self) -> None:
        if type(self.pine_version) is not int or self.pine_version not in SUPPORTED_PINE_VERSIONS:
            raise ValueError(f"unsupported Pine version identity: {self.pine_version!r}")
        if not self.spec_snapshot_ref:
            raise ValueError("spec_snapshot_ref is required")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.catalog_hash):
            raise ValueError("catalog_hash must be sha256:<64 lowercase hex>")
        if self.origin is VersionOrigin.COMPILER_ANNOTATION and self.annotation_span is None:
            raise ValueError("compiler annotation origin requires annotation_span")
        if self.origin is VersionOrigin.TRADINGVIEW_DEFAULT_V1:
            if self.pine_version != 1:
                raise ValueError("TradingView default origin is valid only for Pine v1")
            if self.annotation_span is not None:
                raise ValueError("default-v1 origin must not carry annotation_span")

    @property
    def production_frontend_supported(self) -> bool:
        return self.pine_version in PRODUCTION_FRONTEND_VERSIONS

    def _bound_policies(self):
        return _policy_bundle_for(self)

    @property
    def dynamic_requests_default(self) -> bool:
        return self._bound_policies().semantic.dynamic_requests_default

    @property
    def bool_allows_na(self) -> bool:
        return self._bound_policies().semantic.bool_allows_na

    @property
    def numeric_condition_allowed(self) -> bool:
        return self._bound_policies().semantic.numeric_condition_allowed

    @property
    def const_int_division_fractional(self) -> bool:
        return self._bound_policies().semantic.const_int_division_fractional

    @property
    def supports_multiline_strings(self) -> bool:
        return self._bound_policies().syntax.capability("multiline_strings")

    @property
    def supports_exported_const(self) -> bool:
        return self._bound_policies().syntax.capability("exported_const")

    @property
    def supports_bid_ask(self) -> bool:
        # Availability is represented by the active catalog spelling.
        from pine2ast.catalog import CatalogRepository

        return "bid" in CatalogRepository.default().readonly_view(self.pine_version).get(
            "variables", {}
        )

    @property
    def supports_current_contract(self) -> bool:
        from pine2ast.catalog import CatalogRepository

        view = CatalogRepository.default().readonly_view(self.pine_version)
        return any(
            name.startswith("syminfo.current_contract") for name in view.get("variables", {})
        )

    @property
    def uses_v6_bool_rules(self) -> bool:
        return self._bound_policies().semantic.uses_v6_bool_rules

    def to_dict(self) -> dict[str, Any]:
        return {
            "pine_version": self.pine_version,
            "origin": self.origin.value,
            "annotation_span": self.annotation_span.to_dict() if self.annotation_span else None,
            "spec_snapshot_ref": self.spec_snapshot_ref,
            "catalog_hash": self.catalog_hash,
        }


@lru_cache(maxsize=12)
def _policy_bundle_for(context: PineVersionContext):
    from pine2ast.catalog import CatalogRepository
    from pine2ast.policy import policy_bundle_from_catalog

    catalog = CatalogRepository.default().readonly_view(context.pine_version)
    return policy_bundle_from_catalog(context, catalog)


__all__ = [
    "PRODUCTION_FRONTEND_VERSIONS",
    "SUPPORTED_PINE_VERSIONS",
    "PineVersionContext",
    "VersionOrigin",
]
