from __future__ import annotations

from pine2ast.compatibility.release_features import (
    load_v6_release_features,
    release_feature_summary,
    validate_release_feature_matrix,
)


def test_release4_release_matrix_has_no_not_started_items_after_static_hardening() -> None:
    payload = load_v6_release_features()
    assert validate_release_feature_matrix(payload) == ()
    assert "not_started" not in release_feature_summary(payload)


def test_release4_release_matrix_validator_catches_unknown_status_and_duplicates() -> None:
    payload = {
        "status_values": ["validated"],
        "features": [
            {"id": "feature.a", "status": "validated"},
            {"id": "feature.a", "status": "mystery"},
            {"id": "feature.b", "status": "not_started"},
        ],
    }
    errors = validate_release_feature_matrix(payload)
    assert "duplicate feature id: feature.a" in errors
    assert "feature.a has unknown status: mystery" in errors
    assert "feature.b has unknown status: not_started" in errors
