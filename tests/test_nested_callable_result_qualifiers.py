"""Independent nested-control counterexamples for the callable-result P1."""

from textwrap import indent

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import ConsumerBundleError, build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload
from pine2ast.libraries import LibraryStore, link_libraries


def nested_source(inner, version, imported):
    body = "length(simple int n)=>\n    if n>0\n" + indent(inner, "        ")
    body += "\n    else\n        n+9\n"
    prefix = "lib." if imported else ""
    usage = f"plot(ta.ema(close,{prefix}length(2)))\n"
    if not imported:
        return f'//@version={version}\nindicator("Nested qualifiers")\n{body}{usage}'
    lib = f'//@version={version}\nlibrary("Nested")\nexport {body}'
    root = (
        f'//@version={version}\nindicator("Nested qualifiers")\nimport qa/Nested/1 as lib\n{usage}'
    )
    return link_libraries(root, LibraryStore.create({"qa/Nested/1": lib})).code


def length_argument(parsed):
    calls = semantic_facts_payload(parsed)["calls"]
    ema = next(c for c in calls if c["callee"] == "ta.ema")
    return next(a for a in ema["arguments"] if a["parameter_name"] == "length")


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize(
    "inner",
    [
        "if bar_index>0\n    n\nelse\n    n+1",
        "switch bar_index\n    0=>n\n    =>n+1",
        "switch\n    bar_index>0=>n\n    =>n+1",
        "if n>1\n    n\nelse if bar_index>0\n    n+1\nelse\n    n+2",
        "if n>1\n    if bar_index>0\n        n\n    else\n        n+1\nelse\n    n+2",
        "choose=bar_index>0\nif choose\n    n\nelse\n    n+1",
        "for i=0 to bar_index\n    n",
        "for value in array.new<int>(1,bar_index)\n    n",
        "while bar_index<0\n    n",
    ],
)
def test_nested_series_control_and_loops_do_not_become_simple(version, imported, inner):
    code = nested_source(inner, version, imported)
    parsed = parse_code(code)
    assert not parsed.ok
    assert any(d.code == "P2A1405" and "Argument length " in d.message for d in parsed.diagnostics)
    assert all(d.code in {"P2A1405", "P2A2008"} for d in parsed.diagnostics if d.is_error)
    argument = length_argument(parsed)
    assert argument["actual_type"] == argument["expected_type"] == "int"
    assert argument["actual_qualifier"] == "series"
    assert argument["max_qualifier"] == "simple"
    with pytest.raises(ConsumerBundleError):
        build_consumer_bundle(code)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("imported", [False, True])
@pytest.mark.parametrize(
    "inner",
    [
        "if n>1\n    n\nelse\n    n+1",
        "switch n\n    0=>n\n    =>n+1",
        "switch\n    n>1=>n\n    =>n+1",
        "if n>1\n    if n>2\n        value=n+1\n        value\n    else\n        n+2\nelse\n    n+3",
    ],
)
def test_nested_simple_control_retains_simple_value_and_exact_type(version, imported, inner):
    code = nested_source(inner, version, imported)
    parsed = parse_code(code)
    assert parsed.ok, [(d.code, d.message) for d in parsed.diagnostics]
    argument = length_argument(parsed)
    assert argument["actual_qualifier"] == argument["max_qualifier"] == "simple"
    assert argument["actual_type"] == argument["expected_type"] == "int"
    assert build_consumer_bundle(code)["content_hash"]


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("argument,accepted", [("input.bool(true)", True), ("bar_index>0", False)])
def test_nested_guard_dependency_reaches_inferred_parameter_bound(version, argument, accepted):
    code = f"""//@version={version}
indicator("Nested bound")
smooth(int n,bool choose)=>
    length=if n>0
        if choose
            n
        else
            n+1
    else
        n+2
    ta.ema(close,length)
plot(smooth(2,{argument}))
"""
    parsed = parse_code(code)
    assert parsed.ok is accepted, [(d.code, d.message) for d in parsed.diagnostics]
    call = next(c for c in semantic_facts_payload(parsed)["calls"] if c["callee"] == "smooth")
    choose = next(a for a in call["arguments"] if a["parameter_name"] == "choose")
    assert choose["max_qualifier"] == "simple"
    if accepted:
        assert choose["actual_qualifier"] == "input"
        assert build_consumer_bundle(code)["content_hash"]
    else:
        assert any(
            d.code == "P2A1405" and "Argument choose " in d.message for d in parsed.diagnostics
        )
        with pytest.raises(ConsumerBundleError):
            build_consumer_bundle(code)
