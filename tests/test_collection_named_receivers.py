"""Function-form receiver identity follows its name, not source argument order."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle

CASES = [
    (version, "a=array.new_int(1,1)", expression)
    for version in (4, 5, 6)
    for expression in (
        "array.push(value=2,id=a)",
        "x=array.get(index=0,id=a)",
        "array.set(value=2,index=0,id=a)",
    )
] + [
    (version, declaration, expression)
    for version in (5, 6)
    for declaration, expression in (
        ("m=map.new<string,int>()", 'map.put(value=2,key="b",id=m)'),
        ("m=matrix.new<int>(1,1,0)", "matrix.set(value=2,column=0,row=0,id=m)"),
    )
]


@pytest.mark.parametrize("version,declaration,expression", CASES)
def test_named_receiver_after_other_parameters_is_resolved(version, declaration, expression):
    annotation = "study" if version == 4 else "indicator"
    code = f'//@version={version}\n{annotation}("named receiver")\n{declaration}\n{expression}\n'
    result = parse_code(code)
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    assert build_consumer_bundle(code)["content_hash"]
