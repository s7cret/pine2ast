"""Context admission verifies provenance, rather than accepting resealed floors."""

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from pine2ast import ParseOptions, ParsePipeline, parse_code
from pine2ast.hardening.consumer_bundle import (
    ConsumerBundleError,
    build_consumer_bundle,
    verify_consumer_bundle,
)
from pine2ast.hardening.model import content_hash
from pine2ast.libraries import LibraryError, LibraryQualifierContext, LibraryStore, link_libraries
from pine2ast.libraries import LinkedSource
from pine2ast.libraries.store import canonical, source_hash


def projection(version=6):
    base = f'//@version={version}\nlibrary("Base")\nexport two()=>2\n'
    lib = f'//@version={version}\nlibrary("Lib")\nimport qa/Base/1 as base\nhelper()=>3\nexport value()=>base.two()+helper()\n'
    root = f'//@version={version}\nindicator("Caller")\nimport qa/Lib/1 as lib\nordinary()=>4\nplot(lib.value()+ordinary())\n'
    return link_libraries(root, LibraryStore.create({"qa/Base/1": base, "qa/Lib/1": lib}))


def reseal(payload):
    payload["content_hash"] = source_hash(
        canonical({k: v for k, v in payload.items() if k != "content_hash"})
    )


def reseal_facts_and_linkage(bundle):
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


@pytest.mark.parametrize("version", [5, 6])
def test_transitive_all_and_only_exported_declarations_with_immutable_copy(version):
    linked = projection(version)
    before = linked._receipt
    context = linked.qualifier_context()
    payload = context.to_dict()
    rows = payload["exported_functions"]
    assert [(r["source"], r["name"]) for r in rows] == [("qa/Base/1", "two"), ("qa/Lib/1", "value")]
    assert all(r["minimum_return_qualifier"] == "simple" for r in rows)
    assert LibraryQualifierContext.admit(payload).to_dict() == payload
    parsed = parse_code(linked.code, ParseOptions(library_context=context))
    assert parsed.ok
    symbols = parsed.semantic_model.symbols
    assert symbols["ordinary"].qualifier == "const"
    assert all(symbols[r["generated_name"]].qualifier == "simple" for r in rows)
    private = next(
        r["linked_name"] for r in linked.receipt()["declarations"] if r["name"] == "helper"
    )
    assert symbols[private].qualifier == "const"
    payload["exported_functions"].clear()
    assert len(context.to_dict()["exported_functions"]) == 2
    with pytest.raises(FrozenInstanceError):
        context.code = "different"
    assert linked._receipt == before


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "extra",
        "duplicate",
        "ref",
        "hash",
        "name",
        "span",
        "generated_name",
        "generated_span",
        "floor",
        "version",
        "schema",
        "receipt_projection",
        "original_export",
    ],
)
def test_resealed_provenance_cannot_grant_or_change_exported_floor(version, attack):
    payload = projection(version).qualifier_context().to_dict()
    rows = payload["exported_functions"]
    if attack == "missing":
        rows.pop()
    elif attack in {"extra", "duplicate"}:
        row = deepcopy(rows[0])
        if attack == "extra":
            row["generated_name"] = "ordinary"
        rows.append(row)
    elif attack in {"ref", "hash", "name", "generated_name", "floor"}:
        key, value = {
            "ref": ("source", "qa/Other/1"),
            "hash": ("source_hash", "sha256:" + "f" * 64),
            "name": ("name", "helper"),
            "generated_name": ("generated_name", "ordinary"),
            "floor": ("minimum_return_qualifier", "const"),
        }[attack]
        rows[0][key] = value
    elif attack in {"span", "generated_span"}:
        rows[0][attack]["start_offset"] += 1
    elif attack == "version":
        payload["pine_version"] = 11 - version
    elif attack == "schema":
        payload["schema_id"] += ".unknown"
    elif attack == "receipt_projection":
        payload["linkage_receipt"]["projection"][0]["source_start"] += 1
    elif attack == "original_export":
        receipt = payload["linkage_receipt"]
        receipt["sources"]["qa/Base/1"]["raw_text"] = receipt["sources"]["qa/Base/1"][
            "raw_text"
        ].replace("export ", "")
    reseal(payload["linkage_receipt"])
    payload["linkage_receipt_hash"] = payload["linkage_receipt"]["content_hash"]
    reseal(payload)
    with pytest.raises(LibraryError):
        LibraryQualifierContext.admit(payload)


@pytest.mark.parametrize("version", [5, 6])
def test_context_reconstructs_without_source_and_checks_exact_external_source(version):
    linked = projection(version)
    bundle = build_consumer_bundle(linked.code, linked_source=linked)
    verify_consumer_bundle(bundle)
    verify_consumer_bundle(bundle, source=linked.code)
    with pytest.raises(ConsumerBundleError, match="source differs"):
        verify_consumer_bundle(bundle, source=linked.code + "\n")
    with pytest.raises(ConsumerBundleError, match="source differs"):
        build_consumer_bundle(linked.code + "\n", linked_source=linked)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "attack", ["context", "capability", "downgrade", "schema", "marker", "missing_marker"]
)
def test_consumer_revision_context_capability_and_marker_cannot_be_stripped(version, attack):
    linked = projection(version)
    bundle = build_consumer_bundle(linked.code, linked_source=linked)
    if attack in {"context", "downgrade"}:
        del bundle["library_context"]
    if attack in {"capability", "downgrade"}:
        bundle["consumer_contract"]["required_capabilities"].remove("library_qualifier_context_v1")
    if attack == "downgrade":
        bundle["schema_version"] = "1.0.0"
    if attack == "schema":
        bundle["schema_version"] = "1.2.0"
    if attack == "marker":
        bundle["ast"]["producer_metadata"]["library_qualifier_context_ref"] = "sha256:" + "f" * 64
    if attack == "missing_marker":
        del bundle["ast"]["producer_metadata"]["library_qualifier_context_ref"]
    bundle["artifacts"]["ast_hash"] = content_hash(bundle["ast"])
    reseal(bundle)
    with pytest.raises(ConsumerBundleError, match="schema_version|must match exactly|provenance"):
        verify_consumer_bundle(bundle)


@pytest.mark.parametrize("attack", ["depth", "cycle", "source_count", "root_size"])
def test_untrusted_receipt_is_bounded_before_reconstruction(attack):
    payload = projection().qualifier_context().to_dict()
    if attack == "depth":
        deep = []
        payload["extra"] = deep
        for _ in range(18):
            child = []
            deep.append(child)
            deep = child
    elif attack == "cycle":
        payload["extra"] = payload
    elif attack == "source_count":
        payload["linkage_receipt"]["dependencies"] = {f"qa/L{i}/1": "x" for i in range(65)}
    else:
        receipt = payload["linkage_receipt"]
        receipt["sources"][receipt["root_source_name"]]["raw_text"] = "x" * 1_000_001
    with pytest.raises(LibraryError, match="limit|cyclic|count|size"):
        LibraryQualifierContext.admit(payload)


@pytest.mark.parametrize("version", [5, 6])
def test_semantic_only_does_not_accept_changed_body_with_same_declared_span(version):
    linked = projection(version)
    pipeline = ParsePipeline(ParseOptions(library_context=linked.qualifier_context()))
    tokens, diagnostics = pipeline.lex_only(linked.code)
    assert not any(d.is_error for d in diagnostics)
    context = pipeline.resolve_version(linked.code).context
    syntax = pipeline.parse_only(tokens, version_context=context).program
    syntax.items[-2].body.value = 9  # ordinary()=>4, identical declaration coordinates
    with pytest.raises(LibraryError, match="exact projected syntax"):
        pipeline.semantic_only(syntax)


@pytest.mark.parametrize("version", [1, 2, 3, 4, True, 5.0])
def test_context_never_backports_nominal_library_qualifier_rules(version):
    payload = projection().qualifier_context().to_dict()
    payload["pine_version"] = version
    reseal(payload)
    with pytest.raises(LibraryError, match="Pine v5 or v6"):
        LibraryQualifierContext.admit(payload)


@pytest.mark.parametrize("version", [5, 6])
def test_resealed_semantic_result_laundering_is_reparsed_without_source(version):
    linked = projection(version)
    bundle = build_consumer_bundle(linked.code, linked_source=linked)
    facts = bundle["semantic_facts"]
    changed = []
    for fact in facts["facts"]:
        dtype = fact.get("resolved_type")
        if dtype and dtype["qualifier"] == "simple":
            dtype["qualifier"] = "const"
            changed.append(fact["node_id"])
    for call in facts["calls"]:
        for argument in call["arguments"]:
            if argument["actual_qualifier"] == "simple":
                argument["actual_qualifier"] = "const"
    assert changed
    reseal_facts_and_linkage(bundle)
    with pytest.raises(ConsumerBundleError, match="source and semantic facts do not match"):
        verify_consumer_bundle(bundle)


@pytest.mark.parametrize(
    "data", [b"{", b"\xff", b"[[[]]]", b'{"x":' + b"[" * 1200 + b"0" + b"]" * 1200 + b"}"]
)
@pytest.mark.parametrize("entry", ["context", "linked"])
def test_manually_constructed_json_is_controlled_before_admission(data, entry):
    with pytest.raises(LibraryError, match="context.*JSON"):
        if entry == "context":
            LibraryQualifierContext(data, "").to_dict()
        else:
            LibraryQualifierContext.from_linked_source(LinkedSource("", data))


@pytest.mark.parametrize("version", [5, 6])
def test_zero_dependency_projection_keeps_existing_verified_linkage_boundary(version):
    code = f'//@version={version}\nindicator("No imports")\nplot(2)\n'
    store = LibraryStore.create(
        {"qa/Unused/1": f'//@version={version}\nlibrary("Unused")\nexport f()=>2\n'}
    )
    linked = link_libraries(code, store)
    assert linked.receipt()["dependencies"] == {}
    with pytest.raises(LibraryError, match="needs dependencies"):
        linked.verify()
    with pytest.raises(LibraryError, match="source count"):
        linked.qualifier_context()
    assert build_consumer_bundle(code)["schema_version"] == "1.0.0"
