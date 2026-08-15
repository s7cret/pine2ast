from pine2ast.api import parse_code
from pine2ast.openpine_contracts.frontend_v2 import (
    FRONTEND_V2,
    SUPPORT_PROFILE_V2,
    FrontendProfileError,
    build_frontend_v2_payload,
    resolve_semantic_profile,
)


def test_frontend_v2_defaults_to_strict_5x() -> None:
    result = parse_code("//@version=6\nindicator('t')\nplot(close)\n")
    payload = build_frontend_v2_payload(result, source_name="t.pine")
    assert payload["schema_id"] == FRONTEND_V2
    assert payload["semantic_profile"] == "strict_5x"
    assert payload["support_profile"]["schema_id"] == SUPPORT_PROFILE_V2
    assert payload["support_profile"]["features"][0]["feature_id"] == "request.security"


def test_unknown_semantic_profile_fail_closed() -> None:
    try:
        resolve_semantic_profile("maybe")
    except FrontendProfileError as exc:
        assert exc.code == "UNKNOWN_SEMANTIC_PROFILE"
    else:
        raise AssertionError("unknown profile must fail")
    assert resolve_semantic_profile("legacy_4x") == "legacy_4x"
    assert resolve_semantic_profile(None) == "strict_5x"


def test_support_profile_accepts_explicit_features() -> None:
    from pine2ast.openpine_contracts.frontend_v2 import build_support_profile_v2

    payload = build_support_profile_v2(
        semantic_profile="legacy_4x",
        features=[
            {
                "feature_id": "strategy.entry",
                "parse": "SUPPORTED",
                "bind_type": "SUPPORTED",
                "lower": "SUPPORTED",
                "runtime": "SUPPORTED",
                "data_mtf": "NOT_APPLICABLE",
                "simulation": "SUPPORTED",
                "live_safe": "CONDITIONAL",
                "visual": "NOT_APPLICABLE",
                "numeric_parity": "CONDITIONAL",
                "capability_predicate": "none",
                "limitation_code": "",
                "fixture_id": "entry",
            }
        ],
    )
    assert payload["semantic_profile"] == "legacy_4x"
    assert payload["features"][0]["feature_id"] == "strategy.entry"
