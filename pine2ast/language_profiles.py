from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PineMajorVersion = Literal[5, 6]


@dataclass(frozen=True, slots=True)
class PineLanguageProfile:
    """Version-specific static language semantics for the frontend.

    The profile is intentionally limited to compile-time/frontend behavior. Runtime
    execution semantics (bar updates, request data fetching, broker emulator, etc.)
    remain the responsibility of downstream OpenPine packages.
    """

    version: PineMajorVersion
    strict: bool = True
    compatibility_mode: bool = False
    supports_dynamic_requests_default: bool = True
    bool_allows_na: bool = False
    numeric_condition_allowed: bool = False
    const_int_division_fractional: bool = True
    supports_multiline_strings: bool = True
    supports_exported_const: bool = True
    supports_bid_ask: bool = True
    supports_current_contract: bool = True

    @property
    def uses_v6_bool_rules(self) -> bool:
        return not self.bool_allows_na and not self.numeric_condition_allowed

    @property
    def dynamic_requests_default(self) -> bool:
        return self.supports_dynamic_requests_default


def pine_language_profile(
    version: int | None = 6,
    *,
    strict: bool = True,
    compatibility_mode: bool = False,
) -> PineLanguageProfile:
    """Return the normalized Pine v5/v6 frontend profile.

    Unknown future versions deliberately fall back to the v6 frontend shape. The
    parser still reports an unsupported-version diagnostic when it sees an
    unsupported source annotation; this helper only normalizes options used by
    static semantic passes.
    """

    normalized: PineMajorVersion = 5 if version == 5 else 6
    if normalized == 5:
        return PineLanguageProfile(
            version=5,
            strict=strict,
            compatibility_mode=compatibility_mode,
            supports_dynamic_requests_default=False,
            bool_allows_na=True,
            numeric_condition_allowed=True,
            const_int_division_fractional=False,
            supports_multiline_strings=False,
            supports_exported_const=False,
            supports_bid_ask=False,
            supports_current_contract=False,
        )
    return PineLanguageProfile(
        version=6,
        strict=strict,
        compatibility_mode=compatibility_mode,
    )
