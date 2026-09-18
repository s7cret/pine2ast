"""Negative publication tests for audit S2-19/20; no execution receipts are fabricated."""
from copy import deepcopy
import json
import pytest
from pine2ast.hardening.language_publication import (
    LanguagePublicationError, PRIMARY_STAGE2_CRITERIA, MANDATORY_STAGE2_GATES,
    load_language_publication, observe_language_publication, verify_language_publication,
    file_sha256,
)


def complete_observation(lock):
    return {key: deepcopy(lock[key]) for key in (
        "packages", "catalog_hashes", "compiler_target_hash", "compiler_target_name",
        "compiler_target_version", "runtime_target_file_hash")}


def test_partial_observation_is_not_coordinated_publication():
    report = verify_language_publication()
    assert report["status"] == "verified_local"
    assert report["observation_complete"] is False
    assert "packages.pinelib" in report["missing_observations"]
    with pytest.raises(LanguagePublicationError, match="lacks observations"):
        verify_language_publication(mode="coordinated")


def test_complete_identity_observation_does_not_claim_full_stage():
    lock = load_language_publication()
    report = verify_language_publication(lock, complete_observation(lock), mode="coordinated")
    assert report["status"] == "published"
    assert report["observation_complete"] is True
    assert report["full_stage2_accepted"] is False


@pytest.mark.parametrize("field", ["ast2python", "pinelib"])
def test_missing_component_is_rejected(field):
    lock = load_language_publication(); observation = complete_observation(lock)
    del observation["packages"][field]
    with pytest.raises(LanguagePublicationError, match="lacks observations"):
        verify_language_publication(lock, observation, mode="coordinated")


@pytest.mark.parametrize("field", ["compiler_target_hash", "compiler_target_name", "compiler_target_version", "runtime_target_file_hash"])
def test_missing_identity_is_rejected(field):
    lock = load_language_publication(); observation = complete_observation(lock)
    del observation[field]
    with pytest.raises(LanguagePublicationError, match="lacks observations"):
        verify_language_publication(lock, observation, mode="coordinated")


@pytest.mark.parametrize("residuals", [["open issue"], [{"status":"open"}], [{"status":"resolved"}]])
def test_full_flag_with_unresolved_residuals_is_rejected(residuals):
    lock = load_language_publication(); lock["full_stage2_accepted"] = True
    lock["residuals"] = residuals
    with pytest.raises(LanguagePublicationError, match="unresolved residual"):
        verify_language_publication(lock, complete_observation(lock), mode="coordinated")


def test_truthy_acceptance_flags_without_receipts_are_rejected():
    lock = load_language_publication(); lock.update(full_stage2_accepted=True, residuals=[])
    lock["criteria"] = {name: "accepted" for name in PRIMARY_STAGE2_CRITERIA}
    lock["source_lock_hash"] = "sha256:" + "a" * 64
    with pytest.raises(LanguagePublicationError, match="receipt"):
        verify_language_publication(lock, complete_observation(lock), mode="coordinated")


def test_declared_receipt_hash_is_not_a_substitute_for_a_file(tmp_path):
    lock = load_language_publication(); lock.update(full_stage2_accepted=True, residuals=[])
    lock["criteria"] = {name: "accepted" for name in PRIMARY_STAGE2_CRITERIA}
    lock["source_lock_hash"] = "sha256:" + "a" * 64
    lock["mandatory_gate_receipts"] = {name: {
        "status":"passed", "source_lock_hash":lock["source_lock_hash"],
        "failures":0,"errors":0,"skipped":0,"artifact_hash":"sha256:"+"b"*64,
        "artifact_path":name+".json"} for name in MANDATORY_STAGE2_GATES}
    with pytest.raises(LanguagePublicationError, match="actual evidence directory"):
        verify_language_publication(lock, complete_observation(lock), mode="coordinated")
    with pytest.raises(LanguagePublicationError, match="missing or unsafe"):
        verify_language_publication(lock, complete_observation(lock), mode="coordinated", evidence_root=tmp_path)
