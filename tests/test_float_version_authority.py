"""Explicit casting was introduced in Pine v4; this is a source-backed boundary.

https://www.tradingview.com/pine-script-docs/v4/language/type-system/#type-casting
The historical input-type constant and numeric language features are separate.
These tests do not use runtime results as their expected values.
"""

import pytest

from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.diagnostics import codes
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload
from pine2ast.semantic.signatures import SignatureResolver


def script(version, body):
    declaration = "study" if version <= 4 else "indicator"
    return f'//@version={version}\n{declaration}("float boundary")\n{body}\n'


def valid_facts(version, body):
    source = script(version, body)
    result = parse_code(source)
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    assert build_consumer_bundle(source)["content_hash"]
    return semantic_facts_payload(result)


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("argument", ["na", "-2", "1.25", "x=na"])
def test_explicit_float_callable_starts_at_v4(version, argument):
    source = script(version, f"x=float({argument})")
    result = parse_code(source)
    if version < 4:
        assert not result.ok
        assert any(d.code == codes.VERSION_CALL_UNAVAILABLE for d in result.diagnostics)
        fact = next(c for c in semantic_facts_payload(result)["calls"] if c["callee"] == "float")
        assert fact["resolution_status"] == "INVALID"
        assert fact["overload_id"] is None
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(source)
    else:
        facts = valid_facts(version, f"x=float({argument})")
        call = next(c for c in facts["calls"] if c["callee"] == "float")
        assert call["symbol_id"] == "pine:function:float"
        assert call["overload_id"] == "pine:function:float#canonical"
        assert call["call_form"] == "FUNCTION"
        assert call["return_type"] == "float"
        assert call["arguments"][0]["parameter_name"] == "x"


def test_implicit_v1_does_not_admit_a_modern_cast():
    source = 'study("default version")\nx=float(na)\n'
    result = parse_code(source)
    assert result.ast.version_context.pine_version == 1
    assert not result.ok
    assert any(d.code == codes.VERSION_CALL_UNAVAILABLE for d in result.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", range(1, 7))
def test_unavailable_float_signature_remains_in_the_catalog_denominator(version):
    result = parse_code(script(version, "x=0"))
    resolver = SignatureResolver(version_context=result.ast.version_context)
    row = CatalogRepository.default().readonly_view(version)["functions"]["float"]
    candidates = resolver.candidate_entries(row)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["symbol_id"] == "pine:function:float"
    assert candidate["__overload_id"] == "pine:function:float#canonical"
    assert candidate["added_in"] == 4
    assert resolver.candidate_is_active(candidate) is (version >= 4)
    assert candidate["parameters"][0]["name"] == "x"
    assert candidate["parameters"][0]["required"] is True
    candidate["added_in"] = 1
    assert resolver.candidate_entries(row)[0]["added_in"] == 4


@pytest.mark.parametrize("version", [1, 2, 3])
def test_historical_float_input_type_is_a_const_value(version):
    facts = valid_facts(version, "x=input(defval=1.5,type=float)")
    call = next(c for c in facts["calls"] if c["callee"] == "input")
    argument = next(a for a in call["arguments"] if a["parameter_name"] == "type")
    assert argument["actual_qualifier"] == "const"
    assert argument["actual_type"] == "string"
    assert not any(c["callee"] == "float" for c in facts["calls"])
    catalog = CatalogRepository.default().readonly_view(version)
    assert catalog["constants"]["float"]["symbol_id"] != catalog["functions"]["float"]["symbol_id"]


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("body", ["x=1.25", "x=1e-3", "x=1+0.5", "float=2\nx=float+0.5"])
def test_historical_float_literals_promotion_and_variable_names_remain_valid(version, body):
    facts = valid_facts(version, body)
    assert not any(c["callee"] == "float" for c in facts["calls"])
    value = next(
        f
        for f in facts["facts"]
        if f["classification"] == "EXPRESSION"
        and f["span"]["start_line"] == 2 + len(body.splitlines())
        and f["span"]["start_col"] == 3
    )
    assert value["resolved_type"]["base"] == "float"


@pytest.mark.parametrize("version", [2, 3])
def test_user_parameter_named_float_is_not_a_builtin_call(version):
    facts = valid_facts(version, "f(float)=>float+0.5\nx=f(2)")
    call = next(c for c in facts["calls"] if c["callee"] == "f")
    assert call["symbol_id"].startswith("user:function:f:")
    assert call["arguments"][0]["parameter_name"] == "float"
    assert call["return_type"] == "float"


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("argument", ['"1.25"', "true", "", "1,2", "number=1"])
def test_supported_float_versions_still_require_exact_numeric_signature(version, argument):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(script(version, f"x=float({argument})"))


@pytest.mark.parametrize("version", [1, 3, 4, 6])
def test_same_shape_candidates_with_disjoint_versions_are_not_deduplicated(version):
    result = parse_code(script(version, "x=0"))
    resolver = SignatureResolver(version_context=result.ast.version_context)
    # A synthetic catalog isolates version filtering from Pine runtime behavior.
    row = {
        "symbol_id": "pine:function:version_probe",
        "parameters": [],
        "returns": "float",
        "added_in": 4,
        "overloads": [{"added_in": 1, "removed_in": 4}],
    }
    assert len(resolver.candidate_entries(row)) == 2
    resolved = resolver.resolve_builtin("version_probe", row, [], None)
    assert resolved.ok, resolved.issues
    suffix = "overload:0" if version < 4 else "canonical"
    assert resolved.overload_id == "pine:function:version_probe#" + suffix


@pytest.mark.parametrize("version", [1, 3, 4, 6])
def test_no_active_candidate_never_selects_an_overload(version):
    result = parse_code(script(version, "x=0"))
    resolver = SignatureResolver(version_context=result.ast.version_context)
    row = {
        "symbol_id": "pine:function:version_probe",
        "parameters": [],
        "returns": "float",
        "added_in": 7,
    }
    resolved = resolver.resolve_builtin("version_probe", row, [], None)
    assert not resolved.ok
    assert resolved.overload_id is None
    assert any(issue.code == codes.VERSION_CALL_UNAVAILABLE for issue in resolved.issues)
