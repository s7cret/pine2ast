"""Modern statistical estimate flags are optional, typed and per-call series."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload


def script(version, body):
    declaration = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{declaration}("estimate mode")\n{body}\n'


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("family", ["variance", "stdev"])
@pytest.mark.parametrize("binding", ["positional", "named"])
@pytest.mark.parametrize("expression", ["true", "false", "bar_index % 2 == 0"])
def test_biased_flag_admits_literal_and_series_bool(version, family, binding, expression):
    argument = expression if binding == "positional" else f"biased={expression}"
    source = script(version, f"plot(ta.{family}(close, 3, {argument}))")
    result = parse_code(source)
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    facts = semantic_facts_payload(result)
    call = next(row for row in facts["calls"] if row["callee"] == f"ta.{family}")
    assert call["symbol_id"] == f"pine:function:ta.{family}"
    assert call["overload_id"] == f"pine:function:ta.{family}#canonical"
    argument_fact = call["arguments"][2]
    assert argument_fact["parameter_name"] == "biased"
    assert argument_fact["actual_type"] == "bool"
    assert argument_fact["max_qualifier"] == "series"
    assert argument_fact["binding"] == binding
    assert build_consumer_bundle(source)["content_hash"]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("family", ["variance", "stdev"])
def test_omitted_biased_retains_defaulted_parameter_and_catalog_true(version, family):
    source = script(version, f"plot(ta.{family}(close, 3))")
    result = parse_code(source)
    assert result.ok
    assert build_consumer_bundle(source)["content_hash"]
    from pine2ast.catalog import load_catalog_view

    parameter = load_catalog_view(pine_version=version)["functions"][f"ta.{family}"]["parameters"][
        2
    ]
    assert parameter == {
        "name": "biased",
        "type": "bool",
        "required": False,
        "qualifier_max": "series",
        "default": True,
    }


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("family", ["variance", "stdev"])
@pytest.mark.parametrize("argument", ['"false"', "biased=true, biased=false", "bias=true"])
def test_wrong_type_duplicate_and_unknown_flag_are_rejected(version, family, argument):
    source = script(version, f"plot(ta.{family}(close, 3, {argument}))")
    assert not parse_code(source).ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("family", ["variance", "stdev"])
def test_modern_parameter_does_not_silently_change_historical_catalog(version, family):
    from pine2ast.catalog import load_catalog_view

    parameters = load_catalog_view(pine_version=version)["functions"][family]["parameters"]
    assert [parameter["name"] for parameter in parameters] == ["source", "length"]
    # This preserves the previously supported historical signature; it does not
    # assert that an undocumented server version rejected the optional parameter.
    assert not parse_code(script(version, f"plot({family}(close,3,true))")).ok
