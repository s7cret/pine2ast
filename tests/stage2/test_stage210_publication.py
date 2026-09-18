"""Stage 2.10: catalog and pine2ast version stay bound to the published lock."""

from __future__ import annotations

import copy

import pytest

from pine2ast.hardening.language_publication import (
    LanguagePublicationError,
    load_language_publication,
    observe_language_publication,
    verify_language_publication,
)


def test_stage210_installed_catalog_matches_publication():
    report = verify_language_publication()
    assert report["status"] == "verified_local"
    lock = load_language_publication()
    assert lock["full_stage2_accepted"] is False
    assert lock.get("residuals")
    assert lock["packages"]["pine2ast"] == observe_language_publication()["packages"]["pine2ast"]


def test_stage210_version_drift_stops_publication():
    lock = load_language_publication()
    observed = observe_language_publication()
    observed["packages"] = dict(observed["packages"])
    observed["packages"]["pine2ast"] = "0.0.0-local"
    with pytest.raises(LanguagePublicationError, match="pine2ast version"):
        verify_language_publication(lock, observed)


def test_stage210_unpublished_catalog_change_stops_publication():
    lock = load_language_publication()
    observed = observe_language_publication()
    observed["catalog_hashes"] = dict(observed["catalog_hashes"])
    observed["catalog_hashes"]["6"] = "sha256:" + "0" * 64
    with pytest.raises(LanguagePublicationError, match="catalog hashes"):
        verify_language_publication(lock, observed)


def test_stage210_full_acceptance_requires_residual_register():
    lock = copy.deepcopy(load_language_publication())
    lock["full_stage2_accepted"] = True
    lock["residuals"] = []
    with pytest.raises(LanguagePublicationError, match="primary criteria"):
        verify_language_publication(lock, observe_language_publication())
