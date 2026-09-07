"""Independent reference contracts; no expected values are derived from runtime.

Sources and historical limitations: docs/STAGE2_SCALAR_SIGNATURE_REVIEW.md.
"""

import pytest

from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload
from pine2ast.semantic.signatures import SignatureResolver


def source(version, expression):
    declaration = "study" if version <= 4 else "indicator"
    return f'//@version={version}\n{declaration}("scalar contract")\nx={expression}\n'


def call(version, expression):
    text = source(version, expression)
    result = parse_code(text)
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    assert build_consumer_bundle(text)["content_hash"]
    return next(
        c
        for c in semantic_facts_payload(result)["calls"]
        if c["callee"] == expression.split("(", 1)[0]
    )


def math_name(version, name):
    return name if version <= 4 else "math." + name


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize(
    "name,args,expected,overload",
    [
        ("round", "1.2", "int", "canonical"),
        ("round", "na", "int", "canonical"),
        ("ceil", "1.2", "int", "canonical"),
        ("floor", "-1.2", "int", "canonical"),
        ("abs", "-2", "int", "overload:0"),
        ("abs", "-2.5", "float", "canonical"),
        ("exp", "0", "float", "canonical"),
        ("sqrt", "4", "float", "canonical"),
        ("pow", "2,3", "float", "canonical"),
    ],
)
def test_scalar_types_and_exact_call_identity(version, name, args, expected, overload):
    fact = call(version, f"{math_name(version, name)}({args})")
    assert fact["return_type"] == expected
    assert fact["symbol_id"] == f"pine:function:math.{name}"
    assert fact["overload_id"] == f"pine:function:math.{name}#{overload}"
    assert fact["stateful"] is False
    assert fact["call_form"] == ("FUNCTION" if version <= 4 else "NAMESPACE_FUNCTION")


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("precision", ["0", "1", "-1"])
def test_round_precision_is_separate_float_signature_since_v4(version, precision):
    expression = f"{math_name(version, 'round')}(1.25,{precision})"
    if version <= 3:
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(source(version, expression))
    else:
        fact = call(version, expression)
        assert fact["return_type"] == "float"
        assert fact["overload_id"] == "pine:function:math.round#overload:0"


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("name", ["round", "abs", "ceil", "floor", "exp", "sqrt"])
def test_scalar_named_parameter_is_version_exact(version, name):
    parameter = "x" if version <= 4 else "number"
    fact = call(version, f"{math_name(version, name)}({parameter}=1.25)")
    assert fact["arguments"][0]["parameter_name"] == parameter
    obsolete = "number" if version <= 4 else "x"
    for wrong in (obsolete, "value", "source"):
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(source(version, f"{math_name(version, name)}({wrong}=1.25)"))


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("name", ["round", "abs", "ceil", "floor", "exp", "sqrt"])
@pytest.mark.parametrize("args", ["", '"bad"', "1,2,3"])
def test_scalar_bad_arity_and_type_fail_closed(version, name, args):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source(version, f"{math_name(version, name)}({args})"))


@pytest.mark.parametrize("version", range(1, 7))
def test_rsi_simple_length_selects_conventional_overload(version):
    name = "rsi" if version <= 4 else "ta.rsi"
    names = "x=close,y=14" if version <= 4 else "source=close,length=14"
    fact = call(version, f"{name}({names})")
    assert fact["overload_id"] == "pine:function:ta.rsi#" + (
        "overload:0" if version <= 4 else "canonical"
    )
    assert fact["arguments"][1]["max_qualifier"] == "simple"
    assert fact["stateful"] is True


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("second", ["14.0", "close", "int(close)"])
def test_rsi_ratio_overload_is_removed_in_v5(version, second):
    name = "rsi" if version <= 4 else "ta.rsi"
    expression = f"{name}(close,{second})"
    if version >= 5:
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(source(version, expression))
    else:
        fact = call(version, expression)
        assert fact["overload_id"] == "pine:function:ta.rsi#overload:1"
        assert fact["stateful"] is False


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("args", ["", "close", '"bad",14'])
def test_rsi_has_no_phantom_zero_argument_canonical(version, args):
    name = "rsi" if version <= 4 else "ta.rsi"
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source(version, f"{name}({args})"))


@pytest.mark.parametrize("version", range(1, 7))
def test_nz_historical_names_and_numeric_promotion(version):
    names = "y=0,x=na" if version <= 4 else "replacement=0,source=na"
    assert call(version, "nz(" + names + ")")["return_type"] == "int"
    assert call(version, "nz(1,0.0)")["return_type"] == "float"


@pytest.mark.parametrize("version", range(1, 7))
def test_nz_boolean_na_overload_ends_at_v5(version):
    if version <= 5:
        assert call(version, "nz(na,false)")["return_type"] == "bool"
    else:
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(source(version, "nz(na,false)"))


@pytest.mark.parametrize("version", range(1, 7))
def test_public_signature_inventory_is_detached_and_has_no_phantom_rsi(version):
    result = parse_code(source(version, "0"))
    resolver = SignatureResolver(version_context=result.ast.version_context)
    entry = CatalogRepository.default().readonly_view(version)["functions"][
        "rsi" if version <= 4 else "ta.rsi"
    ]
    candidates = resolver.candidate_entries(entry)
    assert len(candidates) == (2 if version <= 4 else 1)
    assert all(len(c["parameters"]) == 2 for c in candidates)
    candidates[0]["parameters"][0]["name"] = "mutated"
    assert resolver.candidate_entries(entry)[0]["parameters"][0]["name"] != "mutated"


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("name", ["sma", "wma"])
def test_historical_moving_average_contract_and_state_identity(version, name):
    active = name if version <= 4 else "ta." + name
    fact = call(version, f"{active}(source=close,length=3)")
    assert fact["symbol_id"] == f"pine:function:ta.{name}"
    assert fact["overload_id"] == f"pine:function:ta.{name}#canonical"
    assert fact["return_type"] == "float"
    assert fact["stateful"] is True
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source(version, f"{active}(close,2.5)"))


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("round(1.2)", "const"),
        ("exp(0)", "const"),
        ("sqrt(close)", "series"),
        ("pow(2,3)", "const"),
        ("na(1)", "simple"),
        ("nz(1)", "simple"),
        ("nz(close)", "series"),
    ],
)
def test_scalar_qualifier_facts_follow_argument_lattice(version, expression, expected):
    if version >= 5 and not expression.startswith(("na(", "nz(")):
        expression = "math." + expression
    result = parse_code(source(version, expression))
    assert result.ok, result.diagnostics
    facts = semantic_facts_payload(result)
    call_fact = next(c for c in facts["calls"] if c["callee"] == expression.split("(", 1)[0])
    node = next(f for f in facts["facts"] if f["node_id"] == call_fact["node_id"])
    assert node["resolved_type"]["qualifier"] == expected


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("args", ["na", "1", "1.5", "x=na"])
def test_float_cast_has_complete_numeric_and_na_argument_evidence(version, args):
    # Reviewed correction to the old fixture: the official v4 type-system
    # manual explicitly dates casting functions to v4. Keep all nodeids;
    # pre-v4 successful bundling was an implementation assumption, not an oracle.
    if version < 4:
        text = source(version, f"float({args})")
        result = parse_code(text)
        assert not result.ok
        assert any(d.code == "P2A2102" for d in result.diagnostics)
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(text)
        return
    fact = call(version, f"float({args})")
    assert fact["return_type"] == "float"
    assert fact["overload_id"] == "pine:function:float#canonical"
    assert fact["arguments"][0]["parameter_name"] == "x"
    assert fact["arguments"][0]["expected_type"] == "float"


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("args", ["", '"bad"', "1,2"])
def test_float_cast_rejects_missing_extra_and_nonnumeric_arguments(version, args):
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source(version, f"float({args})"))
