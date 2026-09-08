"""Receiver evidence is reconstructed, never trusted merely because it joins."""

from copy import deepcopy

import pytest

from pine2ast.hardening import consumer_bundle as owner
from pine2ast.hardening.model import content_hash
from pine2ast.libraries import LibraryStore, link_libraries

CAP = "method_receiver_qualifiers_v1"
CHAINS = {
    "direct": "r=bar_index.add()",
    "global_alias": "int a=bar_index\nr=a.add()",
    "local_alias": "value()=>\n    int a=bar_index\n    int b=a\n    b.add()\nr=value()",
    "udf": "value()=>bar_index\nr=value().add()",
    "operation": "int a=bar_index*0+2\nr=a.add()",
}


def source(version=6, *, qualifier="series", body="a=2\nr=a.add()"):
    return f'//@version={version}\nindicator("Receiver admission")\nmethod add({qualifier + " " if qualifier else ""}int self)=>self+1\n{body}\nplot(r)\n'


def reseal(payload):
    payload["content_hash"] = content_hash(
        {k: v for k, v in payload.items() if k != "content_hash"}
    )


def reseal_facts(bundle):
    facts = bundle["semantic_facts"]
    reseal(facts)
    linked = bundle["linked_artifacts"]
    support = linked["support_profile"]
    support["semantic_facts_ref"] = facts["content_hash"]
    reseal(support)
    frontend = linked["frontend_artifact"]
    frontend["semantic_facts_ref"] = facts["content_hash"]
    frontend["frontend_support_ref"] = support["content_hash"]
    reseal(frontend)
    bundle["artifacts"]["semantic_facts_hash"] = content_hash(facts)
    for name, value in linked.items():
        bundle["artifacts"][f"{name}_hash"] = content_hash(value)
    reseal(bundle)


def poison_series(value):
    changed = 0
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"qualifier", "actual_qualifier"} and item == "series":
                value[key] = "simple"
                changed += 1
            else:
                changed += poison_series(item)
    elif isinstance(value, list):
        changed += sum(poison_series(item) for item in value)
    return changed


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("chain", list(CHAINS))
def test_all_colluding_receiver_chains_fail_after_complete_fact_reseal(monkeypatch, version, chain):
    clean = owner.build_consumer_bundle(source(version, body=CHAINS[chain]))
    tampered = deepcopy(clean)
    assert poison_series(tampered["semantic_facts"]) > 1
    reseal_facts(tampered)
    assert tampered["ast"] == clean["ast"]
    assert tampered["content_hash"] != clean["content_hash"]

    def forbidden(*args, **kwargs):
        raise AssertionError("AST2.1 source-free verification must not parse source")

    monkeypatch.setattr(owner, "parse_source", forbidden)
    owner.verify_consumer_bundle(clean)
    with pytest.raises(owner.ConsumerBundleError, match="fresh producer analysis"):
        owner.verify_consumer_bundle(tampered)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "part", ["resolved_type", "const_value", "call_return", "call_argument", "call_default"]
)
def test_replay_compares_all_facts_and_call_evidence(version, part):
    text = f'//@version={version}\nindicator("Whole evidence")\nmethod add(simple int self,int n=3)=>self+n\na=2\nx=a.add()\nr=a.add(4)\nplot(r)\n'
    bundle = owner.build_consumer_bundle(text)
    facts = bundle["semantic_facts"]
    methods = [c for c in facts["calls"] if c["call_form"] == "USER_METHOD"]
    if part == "resolved_type":
        next(f for f in facts["facts"] if f["node_id"] == methods[0]["node_id"])["resolved_type"][
            "qualifier"
        ] = "const"
    elif part == "const_value":
        literal = next(f for f in facts["facts"] if f.get("const_value") == 2)
        literal["const_value"] = 99
    elif part == "call_return":
        methods[0]["return_type"] = "float"
    elif part == "call_argument":
        methods[1]["arguments"][0]["actual_qualifier"] = "simple"
    else:
        methods[0]["defaults_applied"][0]["default_known"] = True
        methods[0]["defaults_applied"][0]["default_value"] = 99
    reseal_facts(bundle)
    with pytest.raises(owner.ConsumerBundleError):
        owner.verify_consumer_bundle(bundle)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "extra",
        "duplicate",
        "substitute",
        "wrong_consumer",
        "wrong_minimum",
        "null",
        "unknown_revision",
        "downgrade",
        "missing_field",
        "wrong_field",
        "unknown_field_value",
    ],
)
def test_exact_ast_revision_feature_and_consumer_capability(version, attack):
    bundle = owner.build_consumer_bundle(source(version))
    contract = bundle["consumer_contract"]
    caps = contract["required_capabilities"]
    method = next(n for n in bundle["ast"]["items"] if n["kind"] == "MethodDeclaration")
    if attack == "missing":
        caps.remove(CAP)
    elif attack == "extra":
        caps.append("unreviewed_receiver_v2")
    elif attack == "duplicate":
        caps.append(CAP)
    elif attack == "substitute":
        caps[caps.index(CAP)] = "method_receiver_qualifiers_v2"
    elif attack == "wrong_consumer":
        contract["consumer"] = "other"
    elif attack == "wrong_minimum":
        contract["minimum_consumer_version"] = "5.0.0rc7"
    elif attack == "null":
        method["receiver_explicit_qualifier"] = None
    elif attack == "unknown_revision":
        bundle["ast"]["schema_version"] = "2.2"
    elif attack == "downgrade":
        bundle["ast"]["schema_version"] = "2.0"
        caps.remove(CAP)
    elif attack == "missing_field":
        del method["receiver_explicit_qualifier"]
    elif attack == "wrong_field":
        bundle["ast"]["items"][-1]["receiver_explicit_qualifier"] = method.pop(
            "receiver_explicit_qualifier"
        )
    else:
        method["receiver_explicit_qualifier"] = "const"
    bundle["artifacts"]["ast_hash"] = content_hash(bundle["ast"])
    reseal(bundle)
    with pytest.raises(owner.ConsumerBundleError):
        owner.verify_consumer_bundle(bundle)


@pytest.mark.parametrize("version", [1, 2, 3, 4, True, 5.0])
def test_receiver_capability_never_backports_version(version):
    bundle = owner.build_consumer_bundle(source())
    bundle["version_context"]["pine_version"] = version
    reseal(bundle)
    with pytest.raises(owner.ConsumerBundleError, match="Pine v5/v6"):
        owner.verify_consumer_bundle(bundle)


@pytest.mark.parametrize("version", [5, 6])
def test_ast20_omission_preserves_existing_verification_route(monkeypatch, version):
    bundle = owner.build_consumer_bundle(source(version, qualifier=""))
    before = deepcopy(bundle)

    def forbidden(*args, **kwargs):
        raise AssertionError("AST2.0 must not call the new semantic replay")

    monkeypatch.setattr(owner, "verify_method_receiver_semantics", forbidden)
    owner.verify_consumer_bundle(bundle)
    assert bundle == before
    assert bundle["ast"]["schema_version"] == "2.0"
    assert all("receiver_explicit_qualifier" not in n for n in bundle["ast"]["items"])
    bundle["consumer_contract"]["required_capabilities"].append(CAP)
    reseal(bundle)
    with pytest.raises(owner.ConsumerBundleError, match="must match exactly"):
        owner.verify_consumer_bundle(bundle)


def linked_bundle(version):
    library = f'//@version={version}\nlibrary("Base")\nexport two()=>2\n'
    text = f'//@version={version}\nindicator("Linked receiver")\nimport qa/Base/1 as base\nmethod add(simple int self)=>self+1\na=base.two()\nplot(a.add())\n'
    linked = link_libraries(text, LibraryStore.create({"qa/Base/1": library}))
    return owner.build_consumer_bundle(linked.code, linked_source=linked)


@pytest.mark.parametrize("version", [5, 6])
def test_ast21_library11_keeps_real_reparse_and_both_exact_capabilities(monkeypatch, version):
    bundle = linked_bundle(version)
    original = owner.parse_source
    observations = []

    def observed(*args, **kwargs):
        observations.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, "parse_source", observed)
    owner.verify_consumer_bundle(bundle)
    assert len(observations) == 1
    assert observations[0][1]["library_context"] is not None
    assert bundle["schema_version"] == "1.1.0"
    assert bundle["ast"]["schema_version"] == "2.1"
    assert set(bundle["consumer_contract"]["required_capabilities"]) == {
        *owner._BASE_CONSUMER_CAPABILITIES,
        CAP,
        "library_qualifier_context_v1",
    }


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "attack", ["context", "library_cap", "receiver_cap", "version", "marker", "extra_cap"]
)
def test_library_and_receiver_proofs_cannot_be_independently_stripped(version, attack):
    bundle = linked_bundle(version)
    if attack == "context":
        del bundle["library_context"]
    elif attack in {"library_cap", "receiver_cap"}:
        bundle["consumer_contract"]["required_capabilities"].remove(
            "library_qualifier_context_v1" if attack == "library_cap" else CAP
        )
    elif attack == "version":
        bundle["schema_version"] = "1.0.0"
    elif attack == "marker":
        bundle["ast"]["producer_metadata"]["library_qualifier_context_ref"] = "sha256:" + "f" * 64
    else:
        bundle["consumer_contract"]["required_capabilities"].append("unreviewed_v1")
    bundle["artifacts"]["ast_hash"] = content_hash(bundle["ast"])
    reseal(bundle)
    with pytest.raises(owner.ConsumerBundleError):
        owner.verify_consumer_bundle(bundle)


def reseal_all_artifacts(bundle):
    """Preserve the complete lineage DAG while testing semantic tampering."""
    linked = bundle["linked_artifacts"]
    facts = bundle["semantic_facts"]
    reseal(facts)
    reseal(linked["source_manifest"])
    linked["ast_artifact"]["source_manifest_ref"] = linked["source_manifest"]["content_hash"]
    reseal(linked["ast_artifact"])
    refs = {
        "source_manifest_ref": linked["source_manifest"]["content_hash"],
        "ast_ref": linked["ast_artifact"]["content_hash"],
        "semantic_facts_ref": facts["content_hash"],
    }
    linked["support_profile"].update(refs)
    reseal(linked["support_profile"])
    linked["frontend_artifact"].update(refs)
    linked["frontend_artifact"]["frontend_support_ref"] = linked["support_profile"]["content_hash"]
    reseal(linked["frontend_artifact"])
    for name, payload in linked.items():
        bundle["artifacts"][f"{name}_hash"] = content_hash(payload)
    bundle["artifacts"]["ast_hash"] = content_hash(bundle["ast"])
    bundle["artifacts"]["semantic_facts_hash"] = content_hash(facts)
    reseal(bundle)


@pytest.mark.parametrize("version", [5, 6])
def test_actual_catalog_owner_rejects_fully_resealed_catalog_substitution(monkeypatch, version):
    bundle = owner.build_consumer_bundle(source(version))
    old = bundle["version_context"]["catalog_hash"]
    fake = "sha256:" + "0" * 64

    def replace(value, original=old, replacement=fake):
        if isinstance(value, dict):
            for key, item in value.items():
                if item == original:
                    value[key] = replacement
                else:
                    replace(item, original, replacement)
        elif isinstance(value, list):
            for item in value:
                replace(item, original, replacement)

    replace(bundle)
    context = bundle["version_context"]
    replace(
        bundle,
        context["context_hash"],
        content_hash({k: v for k, v in context.items() if k != "context_hash"}),
    )
    reseal_all_artifacts(bundle)

    def forbidden(*args, **kwargs):
        raise AssertionError("source-free catalog validation cannot parse source")

    monkeypatch.setattr(owner, "parse_source", forbidden)
    with pytest.raises(owner.ConsumerBundleError, match="catalog hash does not match"):
        owner.verify_consumer_bundle(bundle)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("chain", list(CHAINS))
def test_receiver_annotation_and_entire_qualifier_proof_cannot_collude(monkeypatch, version, chain):
    bundle = owner.build_consumer_bundle(source(version, body=CHAINS[chain]))
    method = next(n for n in bundle["ast"]["items"] if n["kind"] == "MethodDeclaration")
    method["receiver_explicit_qualifier"] = "simple"
    assert poison_series(bundle["semantic_facts"]) > 1
    reseal_all_artifacts(bundle)

    def forbidden(*args, **kwargs):
        raise AssertionError("source-free receiver proof cannot parse source")

    monkeypatch.setattr(owner, "parse_source", forbidden)
    with pytest.raises(
        owner.ConsumerBundleError, match="reconstructed method receiver semantics contain errors"
    ):
        owner.verify_consumer_bundle(bundle)
