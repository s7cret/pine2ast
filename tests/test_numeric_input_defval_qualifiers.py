"""Numeric input defaults require const values, independently of runtime behavior.

Primary authority and scope: docs/STAGE2_INPUT_DEFVAL_QUALIFIERS.md.
The v5 split introduces callable input.int/float; the older input type constants
remain distinct values. Source inputs and v6 active parameters are controls.
"""

import pytest

from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload
from pine2ast.libraries import LibraryStore, link_libraries
from pine2ast.semantic.signatures import SignatureResolver


def script(version, body):
    declaration = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{declaration}("numeric input default")\n{body}\n'


def valid(source):
    result = parse_code(source)
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    assert build_consumer_bundle(source)["content_hash"]
    return semantic_facts_payload(result)


def invalid_qualifier(source, parameter):
    result = parse_code(source)
    assert not result.ok
    assert any(
        d.code == "P2A1405" and f"Argument {parameter} " in d.message for d in result.diagnostics
    ), [(d.code, d.message) for d in result.diagnostics]
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["int", "float"])
@pytest.mark.parametrize("binding", ["positional", "named"])
@pytest.mark.parametrize("expression", ["2", "-2", "1+2"])
def test_literal_and_constant_expression_defaults_have_exact_binding(
    version, kind, binding, expression
):
    argument = expression if binding == "positional" else f"defval={expression}"
    facts = valid(script(version, f"n=input.{kind}({argument})\nplot(n)"))
    call = next(c for c in facts["calls"] if c["callee"] == f"input.{kind}")
    assert call["symbol_id"] == f"pine:function:input.{kind}"
    assert call["overload_id"] == f"pine:function:input.{kind}#canonical"
    assert call["call_form"] == "NAMESPACE_FUNCTION"
    assert call["return_type"] == kind
    argument = call["arguments"][0]
    assert argument["parameter_name"] == "defval"
    assert argument["binding"] == binding
    assert argument["actual_qualifier"] == "const"
    assert argument["max_qualifier"] == "const"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind,value", [("int", "2"), ("float", "1.25")])
def test_declared_const_default_remains_valid(version, kind, value):
    # Qualifiers are inferred from literal initialization; an explicit const
    # declaration keyword is not needed to exercise this input contract.
    facts = valid(script(version, f"{kind} DEFAULT={value}\nn=input.{kind}(DEFAULT)\nplot(n)"))
    call = next(c for c in facts["calls"] if c["callee"] == f"input.{kind}")
    assert call["arguments"][0]["actual_qualifier"] == "const"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind,series", [("int", "bar_index"), ("float", "close")])
@pytest.mark.parametrize("binding", ["positional", "named"])
@pytest.mark.parametrize("origin", ["series", "input", "simple", "udf_result", "udf_parameter"])
def test_stronger_default_qualifier_is_rejected(version, kind, series, binding, origin):
    prefix, argument = {
        "series": ("", series),
        "input": (f"seed=input.{kind}(2)\n", "seed"),
        "simple": (f"simple {kind} seed=2\n", "seed"),
        "udf_result": ("get()=>2\n", "get()"),
        "udf_parameter": (f"get({kind} seed)=>\n    ", "seed"),
    }[origin]
    if binding == "named":
        argument = "defval=" + argument
    body = prefix + f"input.{kind}({argument})"
    if origin == "udf_parameter":
        body += "\nplot(get(2))"
    invalid_qualifier(script(version, body), "defval")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["int", "float"])
def test_imported_result_cannot_supply_numeric_input_default(version, kind):
    library = f'//@version={version}\nlibrary("Defaults")\nexport get()=>2\n'
    source = script(
        version, f"import qa/Defaults/1 as defaults\nn=input.{kind}(defaults.get())\nplot(n)"
    )
    linked = link_libraries(source, LibraryStore.create({"qa/Defaults/1": library}))
    invalid_qualifier(linked.code, "defval")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["int", "float"])
def test_const_requirement_of_title_is_an_independent_negative_control(version, kind):
    invalid_qualifier(
        script(version, f't=input.string("Title")\nn=input.{kind}(2,title=t)'), "title"
    )


@pytest.mark.parametrize("version", [5, 6])
def test_source_input_still_accepts_series_default(version):
    facts = valid(script(version, "n=input.source(close)\nplot(n)"))
    call = next(c for c in facts["calls"] if c["callee"] == "input.source")
    argument = call["arguments"][0]
    assert argument["parameter_name"] == "defval"
    assert argument["actual_qualifier"] == argument["max_qualifier"] == "series"


@pytest.mark.parametrize("kind", ["int", "float"])
def test_v6_active_still_accepts_input_bool(kind):
    facts = valid(script(6, f"enabled=input.bool(true)\nn=input.{kind}(2,active=enabled)\nplot(n)"))
    call = next(c for c in facts["calls"] if c["callee"] == f"input.{kind}")
    active = next(a for a in call["arguments"] if a["parameter_name"] == "active")
    assert active["actual_qualifier"] == active["max_qualifier"] == "input"


@pytest.mark.parametrize("version", [1, 2, 3, 4])
@pytest.mark.parametrize("kind", ["int", "float"])
def test_specialized_input_callable_is_not_backported(version, kind):
    source = script(version, f"n=input.{kind}(2)")
    assert f"input.{kind}" not in CatalogRepository.default().readonly_view(version)["functions"]
    result = parse_code(source)
    assert not result.ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize(
    "kind,constant,value", [("int", "input.integer", "2"), ("float", "input.float", "1.5")]
)
def test_v4_input_type_constant_keeps_its_original_role(kind, constant, value):
    facts = valid(script(4, f"n=input({value},type={constant})\nplot(n)"))
    call = next(c for c in facts["calls"] if c["callee"] == "input")
    assert call["return_type"] == kind
    assert (
        next(a for a in call["arguments"] if a["parameter_name"] == "type")["actual_qualifier"]
        == "const"
    )


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("kind", ["int", "float"])
def test_every_existing_numeric_input_candidate_requires_const_defval(version, kind):
    parsed = parse_code(script(version, "plot(1)"))
    resolver = SignatureResolver(version_context=parsed.ast.version_context)
    row = CatalogRepository.default().readonly_view(version)["functions"][f"input.{kind}"]
    candidates = resolver.candidate_entries(row)
    assert candidates
    for candidate in candidates:
        assert candidate["symbol_id"] == f"pine:function:input.{kind}"
        defval = next(p for p in candidate["parameters"] if p["name"] == "defval")
        assert defval["type"] == kind
        assert defval["required"] is True
        assert defval["qualifier_max"] == "const"
