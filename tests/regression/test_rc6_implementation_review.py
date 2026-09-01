from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator
import pytest

from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import Severity, codes
from pine2ast.frontend import build_frontend_v3_payload
from pine2ast.hardening.consumer_bundle import (
    ConsumerBundleError,
    _release_axes,
    build_consumer_bundle,
    verify_consumer_bundle,
)
from pine2ast.hardening.model import canonical_json, content_hash, sha256_bytes


def test_diagnostic_limit_preserves_error_and_fail_closed_status() -> None:
    source = 'study("x")\nf(v) => v\n'

    result = parse_code(source, ParseOptions(max_diagnostics=1))

    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].severity in {Severity.ERROR, Severity.FATAL}
    assert result.ok is False
    assert result.frontend_artifact is not None
    frontend = result.frontend_artifact["frontend"]
    assert isinstance(frontend, dict)
    assert frontend["ok"] is False
    assert result.ast is not None
    assert result.ast.producer_metadata["frontend_gate"] == "fail"
    assert result.ast.producer_metadata["semantic_gate"] == "fail"


@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_diagnostic_limit_is_rejected(value: int) -> None:
    with pytest.raises(ValueError, match="max_diagnostics"):
        ParseOptions(max_diagnostics=value)


_VALID_V6 = '//@version=6\nindicator("x")\nx = close\n'


def _reseal_semantic_facts(bundle: dict[str, Any]) -> None:
    facts = bundle["semantic_facts"]
    if "content_hash" in facts:
        facts["content_hash"] = content_hash(
            {key: value for key, value in facts.items() if key != "content_hash"}
        )
    bundle["artifacts"]["semantic_facts_hash"] = content_hash(facts)


def _reseal_bundle(bundle: dict[str, Any]) -> None:
    bundle["content_hash"] = content_hash(
        {key: value for key, value in bundle.items() if key != "content_hash"}
    )


def test_frontend_builder_rejects_source_different_from_parse_result() -> None:
    result = parse_code(_VALID_V6)

    with pytest.raises(ValueError, match="source.*match"):
        build_frontend_v3_payload(
            result,
            source='//@version=6\nindicator("different")\ny = open\n',
        )


def test_consumer_bundle_canonical_roundtrip_matches_public_schema_and_verifier() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "pine2ast/hardening/schemas/pine2ast.consumer_bundle.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    bundle = json.loads(canonical_json(build_consumer_bundle(_VALID_V6)))

    Draft202012Validator(schema).validate(bundle)
    verify_consumer_bundle(bundle, source=_VALID_V6)


def test_release_axes_pass_for_complete_native_array_argument_contracts() -> None:
    source = """//@version=6
indicator("array bindings")
var array<float> xs = array.new<float>(1, 0.0)
x = array.get(xs, 0)
array.set(xs, 0, close)
"""
    bundle = build_consumer_bundle(source)
    arguments = [
        argument for call in bundle["semantic_facts"]["calls"] for argument in call["arguments"]
    ]

    assert all(argument["actual_type"] for argument in arguments)
    assert all(argument["expected_type"] for argument in arguments)
    assert bundle["release_axes"]["arguments_bound"] == {
        "status": "PASS",
        "verified": 8,
        "total": 8,
    }
    assert bundle["release_axes"]["qualifier_enforced"] == {
        "status": "PASS",
        "verified": 8,
        "total": 8,
    }


@pytest.mark.parametrize("missing_field", ["actual_type", "expected_type"])
def test_consumer_bundle_rejects_resealed_missing_call_argument_type_evidence(
    missing_field: str,
) -> None:
    forged = deepcopy(build_consumer_bundle(_VALID_V6))
    forged["semantic_facts"]["calls"][0]["arguments"][0][missing_field] = None
    _reseal_semantic_facts(forged)
    forged["release_axes"] = _release_axes(forged["semantic_facts"], forged["diagnostics"])
    _reseal_bundle(forged)

    assert forged["release_axes"]["arguments_bound"] == {
        "status": "FAIL",
        "verified": 0,
        "total": 1,
    }
    with pytest.raises(ConsumerBundleError, match="release axis arguments_bound failed"):
        verify_consumer_bundle(forged, source=_VALID_V6)


@pytest.mark.parametrize(
    "missing_field",
    ["argument_node_id", "parameter_name", "parameter_index", "binding"],
)
def test_consumer_bundle_rejects_resealed_incomplete_argument_binding(
    missing_field: str,
) -> None:
    forged = deepcopy(build_consumer_bundle(_VALID_V6))
    forged["semantic_facts"]["calls"][0]["arguments"][0][missing_field] = None
    _reseal_semantic_facts(forged)
    forged["release_axes"] = _release_axes(forged["semantic_facts"], forged["diagnostics"])
    _reseal_bundle(forged)

    assert forged["release_axes"]["arguments_bound"]["status"] == "FAIL"
    with pytest.raises(ConsumerBundleError, match="release axis arguments_bound failed"):
        verify_consumer_bundle(forged, source=_VALID_V6)


def test_consumer_bundle_rejects_resealed_failed_qualifier_axis() -> None:
    forged = deepcopy(build_consumer_bundle(_VALID_V6))
    argument = forged["semantic_facts"]["calls"][0]["arguments"][0]
    argument["actual_qualifier"] = "series"
    argument["max_qualifier"] = "simple"
    _reseal_semantic_facts(forged)
    forged["release_axes"] = _release_axes(forged["semantic_facts"], forged["diagnostics"])
    _reseal_bundle(forged)

    assert forged["release_axes"]["qualifier_enforced"]["status"] == "FAIL"
    with pytest.raises(ConsumerBundleError, match="release axis qualifier_enforced failed"):
        verify_consumer_bundle(forged, source=_VALID_V6)


def test_consumer_bundle_rejects_resealed_forged_complete_argument_binding() -> None:
    forged = deepcopy(build_consumer_bundle(_VALID_V6))
    forged["semantic_facts"]["calls"][0]["arguments"][0]["parameter_name"] = "forged"
    _reseal_semantic_facts(forged)
    forged["release_axes"] = _release_axes(forged["semantic_facts"], forged["diagnostics"])
    _reseal_bundle(forged)

    assert forged["release_axes"]["arguments_bound"]["status"] == "PASS"
    with pytest.raises(ConsumerBundleError, match="linked artifact reference mismatch"):
        verify_consumer_bundle(forged, source=_VALID_V6)


def test_release_axes_execute_qualifier_lattice_check() -> None:
    facts = deepcopy(build_consumer_bundle(_VALID_V6)["semantic_facts"])
    argument = facts["calls"][0]["arguments"][0]
    argument["actual_qualifier"] = "series"
    argument["max_qualifier"] = "simple"

    axis = _release_axes(facts, [])["qualifier_enforced"]

    assert axis == {"status": "FAIL", "verified": 0, "total": 1}


def test_release_axes_do_not_pass_unexercised_method_receiver_axis() -> None:
    axis = build_consumer_bundle(_VALID_V6)["release_axes"]["method_receiver_typed"]

    assert axis == {"status": "NOT_APPLICABLE", "verified": 0, "total": 0}


def test_consumer_bundle_rejects_source_ast_mismatch_even_when_resealed() -> None:
    bundle = build_consumer_bundle(_VALID_V6)
    different_source = '//@version=5\nindicator("different")\ny = open\n'
    forged = deepcopy(bundle)
    forged["source"]["source_hash"] = sha256_bytes(different_source.encode("utf-8"))
    forged["source"]["byte_length"] = len(different_source.encode("utf-8"))
    _reseal_bundle(forged)

    with pytest.raises(ConsumerBundleError, match="linked artifact reference mismatch"):
        verify_consumer_bundle(forged, source=different_source)


def test_consumer_bundle_rejects_semantic_facts_version_mismatch() -> None:
    forged = deepcopy(build_consumer_bundle(_VALID_V6))
    facts_context = forged["semantic_facts"]["version_context"]
    facts_context["pine_version"] = 5
    forged["semantic_facts"]["version_context_ref"] = content_hash(facts_context)
    _reseal_semantic_facts(forged)
    _reseal_bundle(forged)

    with pytest.raises(ConsumerBundleError, match="semantic facts.*version"):
        verify_consumer_bundle(forged, source=_VALID_V6)


def test_consumer_bundle_rejects_fact_for_unknown_ast_node() -> None:
    forged = deepcopy(build_consumer_bundle(_VALID_V6))
    forged["semantic_facts"]["facts"][0]["node_id"] = "n99999999"
    _reseal_semantic_facts(forged)
    _reseal_bundle(forged)

    with pytest.raises(ConsumerBundleError, match="node_id"):
        verify_consumer_bundle(forged, source=_VALID_V6)


def test_consumer_bundle_rejects_invalid_nested_semantic_hash() -> None:
    forged = deepcopy(build_consumer_bundle(_VALID_V6))
    forged["semantic_facts"]["content_hash"] = "sha256:" + "0" * 64
    forged["artifacts"]["semantic_facts_hash"] = content_hash(forged["semantic_facts"])
    _reseal_bundle(forged)

    with pytest.raises(ConsumerBundleError, match="semantic facts content hash"):
        verify_consumer_bundle(forged, source=_VALID_V6)


def test_consumer_bundle_requires_trusted_producer_commit() -> None:
    trusted_commit = "a" * 40
    bundle = build_consumer_bundle(_VALID_V6, producer_commit=trusted_commit)

    with pytest.raises(ConsumerBundleError, match="trusted producer commit"):
        verify_consumer_bundle(bundle, source=_VALID_V6)

    verify_consumer_bundle(bundle, source=_VALID_V6, expected_producer_commit=trusted_commit)
    forged = deepcopy(bundle)
    forged["producer"]["commit"] = "b" * 40
    _reseal_bundle(forged)
    with pytest.raises(ConsumerBundleError, match="producer commit mismatch"):
        verify_consumer_bundle(forged, source=_VALID_V6, expected_producer_commit=trusted_commit)


def test_consumer_bundle_propagates_producer_identity_to_every_linked_artifact() -> None:
    trusted_commit = "a" * 40
    bundle = build_consumer_bundle(_VALID_V6, producer_commit=trusted_commit)
    expected = {
        "name": "pine2ast",
        "version": bundle["producer"]["version"],
        "commit": trusted_commit,
        "source_state": "COMMIT_PINNED",
    }

    assert bundle["semantic_facts"]["producer"] == expected
    assert bundle["linked_artifacts"]
    assert all(
        artifact["producer"] == expected for artifact in bundle["linked_artifacts"].values()
    )
    verify_consumer_bundle(
        bundle,
        source=_VALID_V6,
        expected_producer_commit=trusted_commit,
    )


def test_consumer_bundle_rejects_resealed_linked_producer_forgery() -> None:
    trusted_commit = "a" * 40
    forged = deepcopy(build_consumer_bundle(_VALID_V6, producer_commit=trusted_commit))
    linked = forged["linked_artifacts"]["ast_artifact"]
    linked["producer"]["commit"] = "b" * 40
    linked["content_hash"] = content_hash(
        {key: value for key, value in linked.items() if key != "content_hash"}
    )
    forged["artifacts"]["ast_artifact_hash"] = content_hash(linked)
    _reseal_bundle(forged)

    with pytest.raises(ConsumerBundleError, match="linked artifact producer mismatch"):
        verify_consumer_bundle(
            forged,
            source=_VALID_V6,
            expected_producer_commit=trusted_commit,
        )


def test_consumer_bundle_rejects_resealed_broken_linked_reference() -> None:
    forged = deepcopy(build_consumer_bundle(_VALID_V6))
    linked = forged["linked_artifacts"]["frontend_artifact"]
    linked["source_manifest_ref"] = "sha256:" + "0" * 64
    linked["content_hash"] = content_hash(
        {key: value for key, value in linked.items() if key != "content_hash"}
    )
    forged["artifacts"]["frontend_artifact_hash"] = content_hash(linked)
    _reseal_bundle(forged)

    with pytest.raises(ConsumerBundleError, match="linked artifact reference mismatch"):
        verify_consumer_bundle(forged, source=_VALID_V6)


def test_user_methods_with_same_name_are_dispatched_by_receiver_type() -> None:
    source = """//@version=6
indicator("methods")
type Foo
    float x
type Bar
    float y
method ping(Foo this) => this.x
method ping(Bar this, float scale) => this.y * scale
foo = Foo.new(1.0)
bar = Bar.new(2.0)
a = foo.ping()
b = bar.ping(3.0)
"""

    result = parse_code(source)

    assert result.ok, [(item.code, item.message) for item in result.diagnostics]


def test_user_method_name_does_not_shadow_builtin_collection_method() -> None:
    source = """//@version=6
indicator("method shadow")
type Foo
    float value
method get(Foo this) => this.value
array<int> xs = array.new<int>(1, 0)
value = xs.get(0)
"""

    result = parse_code(source)

    assert result.ok, [(item.code, item.message) for item in result.diagnostics]


def test_collection_type_references_enforce_generic_arity() -> None:
    source = """//@version=6
indicator("generic arity")
array<int, float> bad_array = na
map<string> bad_map = na
matrix<float, int> bad_matrix = na
"""

    result = parse_code(source)

    messages = [item.message for item in result.diagnostics if item.is_error]
    assert len(messages) == 3
    assert any("array<...> expects 1" in message for message in messages)
    assert any("map<...> expects 2" in message for message in messages)
    assert any("matrix<...> expects 1" in message for message in messages)


def test_mutable_collection_assignments_are_invariant() -> None:
    source = """//@version=6
indicator("collection invariance")
array<int> ints = array.new<int>(1, 0)
array<float> floats = ints
map<string, int> int_map = map.new<string, int>()
map<string, float> float_map = int_map
"""

    result = parse_code(source)

    errors = [item for item in result.diagnostics if item.is_error]
    assert len(errors) == 2
    assert all(item.code == "P2A1801" for item in errors)


def test_v6_version_rules_do_not_reject_user_callable_names_or_parameters() -> None:
    source = """//@version=6
indicator("user callables")
sma(float value) => value
with_transparency(float transp) => transp
x = sma(close)
y = with_transparency(transp = 1.0)
"""

    result = parse_code(source)

    assert result.ok, [(item.code, item.message) for item in result.diagnostics]


@pytest.mark.parametrize("name", ["barssince", "valuewhen"])
def test_v6_rejects_removed_bare_global_builtin_names(name: str) -> None:
    arguments = "close > open" if name == "barssince" else "close > open, close, 0"
    source = f'//@version=6\nindicator("legacy")\nx = {name}({arguments})\n'

    result = parse_code(source)

    assert any(
        item.code == codes.LEGACY_SPELLING_UNAVAILABLE and name in item.message
        for item in result.diagnostics
        if item.is_error
    )


def test_receiver_diagnostic_is_stable_across_hash_seeds() -> None:
    root = Path(__file__).resolve().parents[2]
    probe = """
from pine2ast import parse_code
source = '//@version=6\\nindicator("stable diagnostics")\\nx = 1\\ny = x.delete()\\n'
result = parse_code(source)
print(next(item.message for item in result.diagnostics if 'expects receiver' in item.message))
"""
    outputs: list[str] = []
    for seed in ("1", "2", "3", "4", "5"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(root))
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        outputs.append(completed.stdout.strip())

    assert len(set(outputs)) == 1
