"""Source-backed simple/series result propagation for typed v5/v6 functions."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload
from pine2ast.libraries import LibraryStore, link_libraries


def source(body, usage, version, *, imported=False):
    if imported:
        lib = f'//@version={version}\nlibrary("Length")\n{body}\n'
        root = f'//@version={version}\nindicator("Result")\nimport qa/Length/1 as lib\n{usage}\n'
        return link_libraries(root, LibraryStore.create({"qa/Length/1": lib})).code
    return f'//@version={version}\nindicator("Result")\n{body}\n{usage}\n'


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize(
    "body",
    [
        "length(simple int n)=>n",
        "length(simple int n)=>n+1",
        "length(simple int n)=>\n    result=n+1\n    result",
        "length(simple int n)=>math.abs(n)",
        "length(int n)=>identity(n)\nidentity(simple int n)=>n",
        "length(simple int n)=>\n    if n>1\n        chosen=n+1\n        chosen\n    else\n        n",
    ],
)
def test_simple_result_reaches_builtin_through_raw_or_linked_call(version, imported, body):
    if imported:
        body = "export " + body
    call = "lib.length" if imported else "length"
    code = source(body, f"plot(ta.ema(close,{call}(input.int(2))))", version, imported=imported)
    parsed = parse_code(code)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    assert build_consumer_bundle(code)["content_hash"]
    facts = semantic_facts_payload(parsed)
    ema = next(c for c in facts["calls"] if c["callee"] == "ta.ema")
    arg = next(a for a in ema["arguments"] if a["parameter_name"] == "length")
    assert arg["actual_qualifier"] == arg["max_qualifier"] == "simple"
    assert arg["actual_type"] == arg["expected_type"] == "int"


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "length(int n)=>n",
        "length(series int n)=>n",
        "length(simple int n)=>n+bar_index",
        "length(simple int n)=>bar_index>0?n:n+1",
        "length(simple int n)=>\n    if bar_index>0\n        n\n    else\n        n+1",
        "length(simple int n)=>int(ta.sma(close,n))",
        "length(simple int n)=>\n    array<int> values=array.new<int>(1,n)\n    array.get(values,0)",
    ],
)
def test_series_data_or_control_cannot_be_laundered_by_result_inference(version, body):
    code = source(body, "plot(ta.ema(close,length(2)))", version)
    parsed = parse_code(code)
    assert not parsed.ok
    assert any(d.code == "P2A1405" and "Argument length " in d.message for d in parsed.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(code)


@pytest.mark.parametrize("version", [5, 6])
def test_simple_result_does_not_bypass_const_required_control(version):
    code = source("length(simple int n)=>n", "value=input.int(length(2))\nplot(value)", version)
    parsed = parse_code(code)
    assert not parsed.ok
    assert any(d.code == "P2A1405" and "Argument defval " in d.message for d in parsed.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(code)


@pytest.mark.parametrize("version", [5, 6])
def test_simple_result_cannot_hide_series_argument_to_its_parameter(version):
    code = source("length(simple int n)=>n", "plot(length(bar_index))", version)
    parsed = parse_code(code)
    assert not parsed.ok
    assert any(d.code == "P2A1405" and "Argument n " in d.message for d in parsed.diagnostics)
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(code)


@pytest.mark.parametrize("version", [5, 6])
def test_simple_result_and_exact_type_cross_twenty_five_forward_helpers(version):
    body = "\n".join(f"f{i}(simple int n)=>f{i+1}(n)" for i in range(24))
    body += "\nf24(simple int n)=>n"
    code = source(body, "plot(ta.ema(close,f0(2)))", version)
    parsed = parse_code(code)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    assert build_consumer_bundle(code)["content_hash"]
    facts = semantic_facts_payload(parsed)
    calls = [c for c in facts["calls"] if c["call_form"] == "USER_FUNCTION"]
    assert len(calls) == 25
    assert all(c["return_type"] == "int" for c in calls)
    ema = next(c for c in facts["calls"] if c["callee"] == "ta.ema")
    length = next(a for a in ema["arguments"] if a["parameter_name"] == "length")
    assert length["actual_qualifier"] == "simple"
