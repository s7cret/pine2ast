"""Replay-only whole-bundle limits must not change genuine legacy admission."""

from copy import deepcopy
import json

import pytest

from pine2ast.ast.decode import ASTReplayLimits
from pine2ast.hardening.consumer_bundle import (
    ConsumerBundleError,
    build_consumer_bundle,
    verify_consumer_bundle,
)
from pine2ast.hardening.model import content_hash


def make_bundle(version, feature=False):
    annotation = "simple " if feature else ""
    return build_consumer_bundle(
        f'//@version={version}\nindicator("Legacy dispatch")\n'
        f"method add({annotation}int self,int n=2)=>self+n\na=2\nplot(a.add())\n"
    )


def seal(bundle):
    bundle["artifacts"]["ast_hash"] = content_hash(bundle["ast"])
    bundle["content_hash"] = content_hash({k: v for k, v in bundle.items() if k != "content_hash"})


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("feature", [False, True])
def test_full_bundle_byte_profile_applies_only_to_requested_replay(version, feature):
    bundle = make_bundle(version, feature)
    before = deepcopy(bundle)
    ast_bytes = len(
        json.dumps(bundle["ast"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    assert (
        len(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        > ast_bytes
    )
    limits = ASTReplayLimits(max_bytes=ast_bytes)
    if feature:
        with pytest.raises(ConsumerBundleError, match="byte limit"):
            verify_consumer_bundle(bundle, ast_replay_limits=limits)
    else:
        verify_consumer_bundle(bundle, ast_replay_limits=limits)
    assert bundle == before


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("location", ["method", "parameter", "metadata", "concealed"])
def test_legacy_revision_cannot_hide_or_misplace_receiver_fields(version, location):
    bundle = make_bundle(version)
    method = next(n for n in bundle["ast"]["items"] if n["kind"] == "MethodDeclaration")
    if location == "method":
        method["receiver_explicit_qualifier"] = "simple"
    elif location == "parameter":
        method["parameters"][0]["receiver_explicit_qualifier"] = "simple"
    elif location == "metadata":
        bundle["ast"]["producer_metadata"]["receiver_explicit_qualifier"] = "simple"
    else:
        bundle["ast"]["producer_metadata"]["nested"] = [
            {"kind": "MethodDeclaration", "receiver_explicit_qualifier": "simple"}
        ]
    seal(bundle)
    with pytest.raises(ConsumerBundleError, match="receiver|revision"):
        verify_consumer_bundle(bundle)
