from dataclasses import replace

import pytest

from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.policy import policy_bundle_from_catalog


def test_policy_refuses_catalog_hash_mismatch():
    repo = CatalogRepository.default()
    context = parse_code("//@version=6\nindicator('x')\n").version_context
    catalog = repo.view(6)
    tampered = replace(context, catalog_hash="sha256:" + "0" * 64)
    with pytest.raises(ValueError):
        policy_bundle_from_catalog(tampered, catalog)


def test_parser_analyzer_and_artifacts_share_one_context():
    result = parse_code("//@version=6\nindicator('x')\nx = 5 / 2\n")
    context = result.version_context.to_dict()
    assert result.ast.version_context.to_dict() == context
    assert result.semantic_model.version_context.to_dict() == context
    assert result.ast_artifact["version_context"] == context
    assert result.semantic_facts_artifact["version_context"] == context
    assert result.frontend_artifact["version_context"] == context
