from __future__ import annotations

import re
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from openpine_contracts import validate_payload, verify_content_hash

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity

ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE = ROOT / "tests" / "fixtures" / "frontend_conformance"
PRODUCER_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SUPPORT_AXES = {
    "parse",
    "bind_type",
    "lower",
    "runtime",
    "data_mtf",
    "simulation",
    "live_safe",
    "visual",
    "numeric_parity",
}
REQUIRED_CAPABILITIES = {
    "broker_projection_reads",
    "calc_on_order_fills",
    "mtf_requested_series",
    "visuals",
    "unsupported_features",
}


def _production_source() -> str:
    return (CONFORMANCE / "production_capabilities.pine").read_text(encoding="utf-8")


def _feature_map(result: Any) -> dict[str, dict[str, Any]]:
    assert result.support_profile is not None
    return {row["feature_id"]: row for row in result.support_profile["features"]}


def test_candidate_metadata_is_exact_rc3_and_has_no_vcs_dependency() -> None:
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject = tomllib.loads(pyproject_text)

    assert pyproject["project"]["version"] == "5.0.0rc3"
    assert pyproject["project"]["dependencies"] == ["openpine-contracts==5.0.0rc3"]
    assert "git+" not in pyproject_text

    from pine2ast import __version__

    assert __version__ == "5.0.0rc3"


def test_canonical_parse_returns_ast_artifact_and_support_as_one_immutable_result() -> None:
    result = parse_code(
        _production_source(),
        ParseOptions(source_name="production_capabilities.pine"),
    )

    assert result.ok
    assert result.ast is not None
    assert result.ast_artifact is not None
    assert result.frontend_artifact is not None
    assert result.support_profile is not None
    validate_payload("pine.ast.v1", result.ast_artifact)
    validate_payload("openpine.frontend.v2", result.frontend_artifact)
    validate_payload("openpine.support_profile.v2", result.support_profile)
    assert verify_content_hash(result.ast_artifact)
    assert verify_content_hash(result.frontend_artifact)
    assert verify_content_hash(result.support_profile)
    assert result.frontend_artifact["support_profile_ref"] == result.support_profile["content_hash"]

    with pytest.raises(FrozenInstanceError):
        result.frontend_artifact = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.ast_artifact["producer"] = "consumer"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.frontend_artifact["producer"] = "consumer"  # type: ignore[index]
    with pytest.raises(TypeError):
        result.support_profile["features"].append({})


def test_artifacts_have_exact_provenance_and_catalog_semver() -> None:
    result = parse_code(_production_source())
    assert result.frontend_artifact is not None
    assert result.support_profile is not None

    for payload in (result.frontend_artifact, result.support_profile):
        assert payload["producer"] == "pine2ast"
        assert payload["producer_version"] == "5.0.0-rc.3"
        assert PRODUCER_COMMIT_RE.fullmatch(payload["producer_commit"])
        assert payload["producer_commit"] != "unknown"


def test_invalid_producer_commit_override_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENPINE_PRODUCER_COMMIT", "unknown")

    with pytest.raises(ValueError, match="40 lowercase hexadecimal"):
        parse_code(_production_source())


def test_explicit_producer_commit_builds_artifacts_without_git_or_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pine2ast.frontend.artifact as artifact_module

    commit = "a" * 40
    monkeypatch.delenv("OPENPINE_PRODUCER_COMMIT", raising=False)
    monkeypatch.setattr(
        artifact_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("explicit provenance must not invoke Git"),
    )

    result = parse_code(
        _production_source(),
        ParseOptions(producer_commit=commit),
    )

    assert result.ast_artifact is not None
    assert result.frontend_artifact is not None
    assert result.support_profile is not None
    assert {
        result.ast_artifact["producer_commit"],
        result.frontend_artifact["producer_commit"],
        result.support_profile["producer_commit"],
    } == {commit}


def test_invalid_explicit_producer_commit_fails_closed() -> None:
    with pytest.raises(ValueError, match="40 lowercase hexadecimal"):
        parse_code(_production_source(), ParseOptions(producer_commit="unknown"))


def test_support_profile_is_complete_and_request_usage_is_capability_bound() -> None:
    result = parse_code(_production_source())
    assert result.frontend_artifact is not None
    features = _feature_map(result)

    assert REQUIRED_CAPABILITIES.issubset(features)
    assert len(features) == len(result.support_profile["features"])
    for feature in features.values():
        assert SUPPORT_AXES.issubset(feature)

    artifact = result.frontend_artifact
    assert artifact["request_usage"] == ["mtf_requested_series"]
    assert set(artifact["request_usage"]).issubset(features)
    assert artifact["strategy_settings"]["calc_on_order_fills"] == {
        "enabled": True,
        "capability": "calc_on_order_fills",
    }
    assert "broker_projection_reads" in artifact["referenced_builtins"]
    assert artifact["visual_requirements"] == ["visuals"]


def test_input_definitions_preserve_all_production_fields() -> None:
    result = parse_code(_production_source())
    assert result.frontend_artifact is not None

    assert result.frontend_artifact["inputs"] == [
        {
            "name": "length",
            "type": "int",
            "default": 14,
            "min": 1,
            "max": 100,
            "step": 1,
            "options": [1, 14, 50],
            "group": "Core",
        }
    ]


def test_same_source_options_and_profile_have_deterministic_content_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pine2ast.frontend.artifact as artifact_module

    created = iter((1000, 2000))
    monkeypatch.setattr(artifact_module, "_now_ms", lambda: next(created))
    options = ParseOptions(source_name="deterministic.pine")

    first = parse_code(_production_source(), options)
    second = parse_code(_production_source(), options)

    assert first.created_at_utc_ms == 1000
    assert second.created_at_utc_ms == 2000
    assert first.frontend_artifact is not None
    assert second.frontend_artifact is not None
    assert first.support_profile is not None
    assert second.support_profile is not None
    assert first.frontend_artifact["content_hash"] == second.frontend_artifact["content_hash"]
    assert first.support_profile["content_hash"] == second.support_profile["content_hash"]


def test_blocking_diagnostics_are_producer_owned_and_not_downgradeable() -> None:
    source = (CONFORMANCE / "unsupported_request.pine").read_text(encoding="utf-8")
    result = parse_code(source, ParseOptions(source_name="unsupported_request.pine"))

    assert not result.ok
    assert result.frontend_artifact is not None
    blocking = result.frontend_artifact["declarations"]["blocking_diagnostics"]
    assert [(row["code"], row["severity"]) for row in blocking] == [("P2A1507", "ERROR")]
    assert any(
        row["feature_id"] == "unsupported_features" for row in result.support_profile["features"]
    )

    diagnostic = next(item for item in result.diagnostics if item.code == "P2A1507")
    with pytest.raises(FrozenInstanceError):
        diagnostic.severity = Severity.WARNING  # type: ignore[misc]
    with pytest.raises(TypeError):
        blocking[0]["severity"] = "WARNING"


def test_parsing_does_not_rewrite_source() -> None:
    source = _production_source()
    original = source.encode("utf-8")

    parse_code(source)

    assert source.encode("utf-8") == original
