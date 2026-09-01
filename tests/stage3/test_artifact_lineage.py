from pine2ast import ParseOptions, parse_code
from pine2ast.catalog.hashing import sha256_id, verify_hash


def test_artifacts_are_hash_linked_and_producer_is_honest():
    source = "//@version=6\nindicator('x')\nx = 5 / 2\n"
    result = parse_code(source, ParseOptions(producer_commit="b" * 40))
    for artifact in (
        result.source_manifest,
        result.ast_artifact,
        result.semantic_facts_artifact,
        result.support_profile,
        result.frontend_artifact,
    ):
        assert artifact is not None
        assert verify_hash(artifact)
    frontend = result.frontend_artifact
    assert frontend["source_manifest_ref"] == result.source_manifest["content_hash"]
    assert frontend["ast_ref"] == result.ast_artifact["content_hash"]
    assert frontend["semantic_facts_ref"] == result.semantic_facts_artifact["content_hash"]
    assert frontend["frontend_support_ref"] == result.support_profile["content_hash"]
    assert frontend["version_context_ref"] == sha256_id(result.version_context.to_dict())
    assert frontend["producer"]["commit"] == "b" * 40
    assert frontend["producer"]["source_state"] == "COMMIT_PINNED"


def test_unpinned_local_build_never_invents_commit():
    result = parse_code("//@version=6\nindicator('x')\n")
    assert result.frontend_artifact["producer"]["commit"] is None
    assert result.frontend_artifact["producer"]["source_state"] == "UNCOMMITTED_LOCAL_BUILD"
