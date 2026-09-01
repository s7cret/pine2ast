from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from pine2ast.catalog import CatalogRepository, CatalogSchemaError, validate_catalog_pack
from pine2ast.catalog.hashing import sha256_id
from pine2ast.catalog.schema import section_names
from pine2ast.lexer.token import SourceSpan
from pine2ast.versioning.context import PineVersionContext, VersionOrigin

SPAN = SourceSpan(0, 1, 1, 1, 1, 2)
ZERO_HASH = "sha256:" + "0" * 64


def _rehash_content(pack: dict[str, Any]) -> dict[str, Any]:
    pack["content_hash"] = sha256_id(
        {key: value for key, value in pack.items() if key != "content_hash"}
    )
    return pack


def _context(
    version: int, *, origin: VersionOrigin = VersionOrigin.COMPILER_ANNOTATION
) -> PineVersionContext:
    identity = CatalogRepository.default().identity(version)
    return PineVersionContext(
        version,
        origin,
        SPAN if origin is VersionOrigin.COMPILER_ANNOTATION else None,
        identity.spec_snapshot_ref,
        identity.catalog_hash,
    )


def test_catalog_schema_rejects_every_structural_invariant() -> None:
    base = CatalogRepository.default().pack(6)
    validate_catalog_pack(base)
    assert set(section_names()) == set(base["sections"])

    mutations: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
        ("schema_id", lambda row: row.__setitem__("schema_id", "bad"), "schema_id"),
        ("schema_version", lambda row: row.__setitem__("schema_version", "2"), "schema_version"),
        ("pine_version_bool", lambda row: row.__setitem__("pine_version", True), "pine_version"),
        ("pine_version_range", lambda row: row.__setitem__("pine_version", 7), "pine_version"),
        ("status", lambda row: row.__setitem__("status", "UNVERIFIED"), "status"),
        ("spec_ref", lambda row: row.__setitem__("spec_snapshot_ref", ""), "spec_snapshot_ref"),
        (
            "source_hash",
            lambda row: row.__setitem__("source_manifest_hash", "SHA256:bad"),
            "source_manifest_hash",
        ),
        (
            "catalog_hash_format",
            lambda row: row.__setitem__("catalog_hash", "sha256:ABC"),
            "catalog_hash",
        ),
        ("content_hash_format", lambda row: row.__setitem__("content_hash", "bad"), "content_hash"),
        ("rules", lambda row: row.__setitem__("rules", []), "rules"),
        ("section_set", lambda row: row["sections"].pop("annotations"), "complete section set"),
        (
            "section_type",
            lambda row: row["sections"].__setitem__("functions", []),
            "must be an object",
        ),
    ]
    for name, mutate, message in mutations:
        mutant = copy.deepcopy(base)
        mutate(mutant)
        with pytest.raises(CatalogSchemaError, match=message):
            validate_catalog_pack(mutant)

    valid_definition = copy.deepcopy(next(iter(base["sections"]["functions"].values())))
    invalid_nested: list[tuple[Callable[[dict[str, Any]], None], str]] = [
        (
            lambda row: row["sections"]["functions"].__setitem__("", valid_definition),
            "invalid name",
        ),
        (
            lambda row: row["sections"]["functions"].__setitem__("bad", []),
            "must be an object",
        ),
        (
            lambda row: row["sections"]["functions"].__setitem__(
                "bad", {**valid_definition, "name": "bad", "symbol_id": "bad"}
            ),
            "invalid symbol_id",
        ),
        (
            lambda row: row["sections"]["functions"].__setitem__(
                "bad", {**valid_definition, "name": "other", "symbol_id": "pine:function:bad"}
            ),
            "name mismatch",
        ),
    ]
    for mutate, message in invalid_nested:
        mutant = copy.deepcopy(base)
        mutate(mutant)
        with pytest.raises(CatalogSchemaError, match=message):
            validate_catalog_pack(mutant)

    bad_content = copy.deepcopy(base)
    bad_content["content_hash"] = ZERO_HASH
    with pytest.raises(CatalogSchemaError, match="content_hash is invalid"):
        validate_catalog_pack(bad_content)

    bad_catalog = copy.deepcopy(base)
    bad_catalog["catalog_hash"] = ZERO_HASH
    _rehash_content(bad_catalog)
    with pytest.raises(CatalogSchemaError, match="catalog_hash does not match"):
        validate_catalog_pack(bad_catalog)


def test_version_context_invariants_are_fail_closed() -> None:
    identity = CatalogRepository.default().identity(1)
    valid = {
        "pine_version": 1,
        "origin": VersionOrigin.COMPILER_ANNOTATION,
        "annotation_span": SPAN,
        "spec_snapshot_ref": identity.spec_snapshot_ref,
        "catalog_hash": identity.catalog_hash,
    }
    mutations = [
        ({"pine_version": True}, "unsupported Pine version"),
        ({"pine_version": 7}, "unsupported Pine version"),
        ({"spec_snapshot_ref": ""}, "spec_snapshot_ref"),
        ({"catalog_hash": "sha256:BAD"}, "catalog_hash"),
        ({"annotation_span": None}, "requires annotation_span"),
        (
            {
                "pine_version": 2,
                "origin": VersionOrigin.TRADINGVIEW_DEFAULT_V1,
                "annotation_span": None,
            },
            "valid only for Pine v1",
        ),
        (
            {
                "origin": VersionOrigin.TRADINGVIEW_DEFAULT_V1,
                "annotation_span": SPAN,
            },
            "must not carry annotation_span",
        ),
    ]
    for update, message in mutations:
        args = {**valid, **update}
        with pytest.raises(ValueError, match=message):
            PineVersionContext(**args)


def test_version_context_properties_bind_to_the_canonical_catalog() -> None:
    contexts = [_context(version) for version in range(1, 7)]
    for context in contexts:
        assert context.production_frontend_supported
        assert isinstance(context.dynamic_requests_default, bool)
        assert isinstance(context.bool_allows_na, bool)
        assert isinstance(context.numeric_condition_allowed, bool)
        assert isinstance(context.const_int_division_fractional, bool)
        assert isinstance(context.supports_multiline_strings, bool)
        assert isinstance(context.supports_exported_const, bool)
        assert isinstance(context.supports_bid_ask, bool)
        assert isinstance(context.supports_current_contract, bool)
        assert isinstance(context.uses_v6_bool_rules, bool)
        payload = context.to_dict()
        assert payload["pine_version"] == context.pine_version
        assert payload["annotation_span"] == SPAN.to_dict()

    default = _context(1, origin=VersionOrigin.TRADINGVIEW_DEFAULT_V1)
    assert default.to_dict()["annotation_span"] is None
    assert contexts[0].bool_allows_na is True
    assert contexts[-1].uses_v6_bool_rules is True


def test_catalog_repository_mutation_guards_rules_hash_and_cache() -> None:
    from pine2ast.catalog import CatalogIntegrityError, clear_catalog_cache
    from pine2ast.catalog.hashing import verify_hash
    from pine2ast.catalog.repository import FrozenDict, FrozenList

    frozen_dict = FrozenDict({"x": 1})
    frozen_list = FrozenList([1])
    with pytest.raises(TypeError, match="immutable"):
        frozen_dict["x"] = 2
    with pytest.raises(TypeError, match="immutable"):
        frozen_list.append(2)

    repo = CatalogRepository.default()
    with pytest.raises(CatalogIntegrityError, match="one of 1..6"):
        repo.pack(0)
    rule_name = next(iter(repo.pack(6)["rules"]))
    assert repo.rule(6, rule_name) == repo.pack(6)["rules"][rule_name]
    with pytest.raises(CatalogIntegrityError, match="no semantic rule"):
        repo.rule(6, "definitely_missing")

    assert verify_hash({"content_hash": 123}) is False
    clear_catalog_cache()
    assert CatalogRepository.default().identity(6).pine_version == 6


def test_version_resolver_rejects_invalid_expectations_and_scans_strings_exactly() -> None:
    from pine2ast.diagnostics import Diagnostic, Severity, codes
    from pine2ast.versioning.resolver import (
        PineVersionResolver,
        VersionResolution,
        _scan_version_annotations,
    )

    resolver = PineVersionResolver(CatalogRepository.default().identity_tuple)
    valid = resolver.resolve("//@version=6")
    assert valid.ok
    assert VersionResolution(valid.context, ()).ok
    assert not VersionResolution(
        None,
        (Diagnostic(Severity.ERROR, "P2ATEST", "error", SPAN),),
    ).ok

    invalid_expected = resolver.resolve("//@version=6", expected_pine_version=True)
    assert invalid_expected.context is None
    assert {row.code for row in invalid_expected.diagnostics} == {codes.INVALID_EXPECTED_VERSION}

    mismatch = resolver.resolve("//@version=6", expected_pine_version=5)
    assert mismatch.context is None
    assert {row.code for row in mismatch.diagnostics} == {codes.VERSION_EXPECTATION_MISMATCH}

    unsupported = resolver.resolve("//@version=7")
    assert unsupported.context is None
    assert {row.code for row in unsupported.diagnostics} == {codes.UNSUPPORTED_VERSION}

    invalid = resolver.resolve("//@version=not-a-number")
    assert invalid.context is None
    assert {row.code for row in invalid.diagnostics} == {codes.INVALID_VERSION_ANNOTATION}

    duplicate = resolver.resolve("//@version=5\n//@version=6\n")
    assert duplicate.context is None
    assert {row.code for row in duplicate.diagnostics} == {codes.DUPLICATE_VERSION_ANNOTATION}

    defaulted = resolver.resolve('indicator("no annotation")\n')
    assert defaulted.ok and defaulted.context.pine_version == 1
    assert defaulted.diagnostics[0].code == codes.VERSION_DEFAULTED_TO_V1

    source = '''"escaped \\\" //@version=2"\ncode // @version=3\n"""multi\n//@version=4\n"""\n//@version=6'''
    candidates = _scan_version_annotations(source)
    assert [row.raw for row in candidates] == ["//@version=6"]
    assert candidates[0].span.end_offset == len(source)
