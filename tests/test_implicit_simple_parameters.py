"""Independent v5/v6 library qualified-type rules; no runtime oracle involved."""

import pytest

from pine2ast import parse_code
from pine2ast.ast.nodes import FunctionDeclaration
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload
from pine2ast.libraries import LibraryError, LibraryStore, link_libraries


def library(body, version):
    return f'//@version={version}\nlibrary("Simple")\n{body}\n'


def script(body, version):
    declaration = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{declaration}("Simple")\n{body}\n'


def valid(source):
    parsed = parse_code(source)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    assert build_consumer_bundle(source)["content_hash"]
    return parsed, semantic_facts_payload(parsed)


def linked(body, usage, version):
    source = script("import qa/Simple/1 as lib\n" + usage, version)
    return link_libraries(source, LibraryStore.create({"qa/Simple/1": library(body, version)}))


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "export smooth(float value,int count=2)=>ta.ema(value,count)",
        "export smooth(float value,int count=2)=>ta.ema(length=count,source=value)",
        "export smooth(float value,int count=2)=>\n    length=count+1\n    ta.ema(value,length)",
        "inner(float value,int count)=>ta.ema(value,count)\nexport smooth(float value,int count=2)=>inner(value,count)",
        "inner(float value,int count)=>ta.ema(value,count)\nmiddle(float value,int count)=>inner(count=count,value=value)\nexport smooth(float value,int count=2)=>middle(value,count)",
        "export smooth(float value,int count=2)=>\n    ta.sma(value,count)\n    ta.ema(value,count)",
    ],
)
def test_body_constraints_bind_implicit_simple_without_mutating_source_qualifier(version, body):
    parsed, facts = valid(library(body, version))
    for declaration in parsed.ast.items:
        if isinstance(declaration, FunctionDeclaration):
            assert all(p.explicit_qualifier is None for p in declaration.parameters)
    ema = next(c for c in facts["calls"] if c["callee"] == "ta.ema")
    assert ema["symbol_id"] == "pine:function:ta.ema"
    assert ema["overload_id"] == "pine:function:ta.ema#canonical"
    assert ema["call_form"] == "NAMESPACE_FUNCTION"
    length = next(a for a in ema["arguments"] if a["parameter_name"] == "length")
    assert length["actual_qualifier"] == length["max_qualifier"] == "simple"
    assert length["actual_type"] == length["expected_type"] == "int"
    source = next(a for a in ema["arguments"] if a["parameter_name"] == "source")
    assert source["actual_qualifier"] == "series"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("argument", ["2", "input.int(2)", "count=2", "count=input.int(2)"])
def test_imported_parameter_accepts_const_input_and_named_arguments(version, argument):
    out = linked(
        "export smooth(int count)=>ta.ema(close,count)", f"plot(lib.smooth({argument}))", version
    )
    parsed, facts = valid(out.code)
    call = next(c for c in facts["calls"] if c["call_form"] == "USER_FUNCTION")
    assert call["overload_id"] == call["symbol_id"] + "#signature"
    assert call["arguments"][0]["max_qualifier"] == "simple"
    assert call["arguments"][0]["actual_qualifier"] in {"const", "input"}
    assert call["stateful"] is True
    out.verify()


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("expression", ["bar_index", "count=bar_index"])
def test_imported_parameter_rejects_series_callers(version, expression):
    out = linked(
        "export smooth(int count)=>ta.ema(close,count)", f"plot(lib.smooth({expression}))", version
    )
    parsed = parse_code(out.code)
    assert not parsed.ok
    assert any(d.code == "P2A1405" and "Argument count " in d.message for d in parsed.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(out.code)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body,code",
    [
        ("export smooth(series int count)=>ta.ema(close,count)", "P2A1405"),
        ("export smooth(int count)=>ta.ema(close,count+bar_index)", "P2A1405"),
        ("export smooth(float count)=>ta.ema(close,count)", "P2A1406"),
        ("export smooth(int count=bar_index)=>ta.ema(close,count)", "P2A1804"),
        ("export smooth(int count)=>input.int(count)", "P2A1405"),
    ],
)
def test_incompatible_body_constraints_cannot_be_silently_weakened(version, body, code):
    source = library(body, version)
    parsed = parse_code(source)
    assert not parsed.ok
    assert any(d.code == code for d in parsed.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)


@pytest.mark.parametrize("version", [5, 6])
def test_explicit_simple_parameter_remains_explicit_and_accepts_input(version):
    body = "export smooth(simple int count)=>ta.ema(close,count)"
    parsed, _ = valid(library(body, version))
    declaration = next(n for n in parsed.ast.items if isinstance(n, FunctionDeclaration))
    assert declaration.parameters[0].explicit_qualifier == "simple"
    valid(linked(body, "plot(lib.smooth(input.int(2)))", version).code)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "export value(int count)=>count+1",
        "export value(int count)=>ta.sma(close,count)",
        "export value(int count)=>\n    if true\n        int count=2\n        ta.ema(close,count)\n    count",
        "export value(int count)=>\n    for count=1 to 2\n        count\n    count",
    ],
)
def test_unconstrained_or_shadowed_parameter_stays_series(version, body):
    _, facts = valid(linked(body, "plot(lib.value(bar_index))", version).code)
    call = next(c for c in facts["calls"] if c["call_form"] == "USER_FUNCTION")
    assert call["arguments"][0]["max_qualifier"] == "series"
    assert call["arguments"][0]["actual_qualifier"] == "series"


@pytest.mark.parametrize("version", [5, 6])
def test_reference_parameter_does_not_inherit_simple_from_integer_projection(version):
    source = library("export smooth(array<int> values)=>ta.ema(close,array.size(values))", version)
    parsed = parse_code(source)
    assert not parsed.ok
    assert any(d.code == "P2A1405" for d in parsed.diagnostics)


@pytest.mark.parametrize("version", [5, 6])
def test_recursive_library_closure_remains_rejected(version):
    body = "a(int count)=>b(count)\nb(int count)=>\n    ta.ema(close,count)\n    a(count)\nexport smooth(int count)=>a(count)"
    with pytest.raises(LibraryError, match="RECURSION"):
        linked(body, "plot(lib.smooth(2))", version)


@pytest.mark.parametrize("version", [5, 6])
def test_defaulted_argument_retains_inferred_bound_in_consumer_facts(version):
    out = linked("export smooth(int count=2)=>ta.ema(close,count)", "plot(lib.smooth())", version)
    _, facts = valid(out.code)
    call = next(c for c in facts["calls"] if c["call_form"] == "USER_FUNCTION")
    default = next(d for d in call["defaults_applied"] if d["parameter_name"] == "count")
    assert default["max_qualifier"] == "simple"
    assert default["expected_type"] == "int"


@pytest.mark.parametrize("version", [5, 6])
def test_constraints_reach_beyond_the_old_sixteen_type_iterations(version):
    # Literal return types isolate qualifier propagation from return inference.
    body = "\n".join(f"f{i}(int count)=>\n    f{i+1}(count)\n    0.0" for i in range(24))
    body += "\nf24(int count)=>\n    ta.ema(close,count)\n    0.0"
    body += "\nexport smooth(int count)=>f0(count)"
    _, facts = valid(linked(body, "plot(lib.smooth(2))", version).code)
    calls = [c for c in facts["calls"] if c["call_form"] == "USER_FUNCTION"]
    assert len(calls) == 26
    assert all(c["arguments"][0]["max_qualifier"] == "simple" for c in calls)


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_older_version_behavior_is_not_changed_by_typed_parameter_inference(version):
    if version == 1:
        source = script("smooth(count)=>ema(close,count)\nplot(smooth(2))", version)
    else:
        source = script("smooth(int count)=>ema(close,count)\nplot(smooth(2))", version)
    parsed = parse_code(source)
    assert not parsed.ok
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(source)
