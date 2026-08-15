"""OpenPine 5.0 frontend and support-profile artifacts."""

from __future__ import annotations

from typing import Any, Mapping

from pine2ast._version import __version__
from pine2ast.openpine_contracts.payload import build_openpine_contract_payload
from pine2ast.openpine_contracts.schema import FRONTEND_CONTRACT

FRONTEND_V2 = "openpine.frontend.v2"
SUPPORT_PROFILE_V2 = "openpine.support_profile.v2"
SUPPORT_STATUSES = (
    "SUPPORTED",
    "CONDITIONAL",
    "VISUAL_ONLY",
    "UNSUPPORTED",
    "NOT_APPLICABLE",
)
SUPPORT_DIMENSIONS = (
    "parse",
    "bind_type",
    "lower",
    "runtime",
    "data_mtf",
    "simulation",
    "live_safe",
    "visual",
    "numeric_parity",
)


class FrontendProfileError(ValueError):
    code = "UNKNOWN_SEMANTIC_PROFILE"


def resolve_semantic_profile(value: str | None) -> str:
    if value is None:
        return "strict_5x"
    if value in {"strict_5x", "legacy_4x"}:
        return value
    raise FrontendProfileError(f"unknown semantic profile: {value}")


def build_support_profile_v2(
    *,
    semantic_profile: str | None = None,
    features: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = resolve_semantic_profile(semantic_profile)
    rows = list(features or [])
    if not rows:
        rows = [
            {
                "feature_id": "request.security",
                "parse": "SUPPORTED",
                "bind_type": "SUPPORTED",
                "lower": "CONDITIONAL",
                "runtime": "CONDITIONAL",
                "data_mtf": "CONDITIONAL",
                "simulation": "CONDITIONAL",
                "live_safe": "CONDITIONAL",
                "visual": "NOT_APPLICABLE",
                "numeric_parity": "CONDITIONAL",
                "capability_predicate": "semantic_profile",
                "limitation_code": "MTF_PROFILE_REQUIRED",
                "fixture_id": "request_security_profile",
            }
        ]
    return {
        "schema_id": SUPPORT_PROFILE_V2,
        "schema_version": "2.0.0",
        "producer": "pine2ast",
        "producer_version": __version__,
        "semantic_profile": profile,
        "features": rows,
    }


def build_frontend_v2_payload(
    result: Any,
    *,
    source_path: str = "<memory>",
    source_name: str | None = None,
    semantic_profile: str | None = None,
) -> dict[str, Any]:
    profile = resolve_semantic_profile(semantic_profile)
    v1 = build_openpine_contract_payload(result, source_path=source_path, source_name=source_name)
    support = build_support_profile_v2(semantic_profile=profile)
    return {
        "schema_id": FRONTEND_V2,
        "schema_version": "2.0.0",
        "producer": "pine2ast",
        "producer_version": __version__,
        "semantic_profile": profile,
        "legacy_frontend_contract": FRONTEND_CONTRACT,
        "ok": v1.get("ok"),
        "source": v1.get("source"),
        "diagnostics": v1.get("diagnostics"),
        "support_profile": support,
        "legacy": v1,
    }
