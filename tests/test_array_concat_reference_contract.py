"""Array concatenation returns the first typed reference and uses id1/id2."""

import pytest

from pine2ast import parse_code
from pine2ast.hardening.consumer_bundle import build_consumer_bundle
from pine2ast.hardening.introspection import semantic_facts_payload
from pine2ast.semantic.collection_signatures import (
    collection_return_type,
    function_parameter_specs,
    method_parameter_specs,
)

FORMS = [
    (version, form, arguments)
    for version in (4, 5, 6)
    for form, arguments in [
        ("function", "a, b"),
        ("function", "id1=a, id2=b"),
        ("function", "id2=b, id1=a"),
    ]
] + [(version, "method", arguments) for version in (5, 6) for arguments in ("b", "id2=b")]
TYPES = [
    ("int", "1", "2"),
    ("float", "1.5", "2.5"),
    ("bool", "true", "false"),
    ("string", '"a"', '"b"'),
]


def source(version, dtype, first, second, expression):
    declaration = "study" if version == 4 else "indicator"
    return (
        f'//@version={version}\n{declaration}("concat")\n'
        f"a=array.new_{dtype}(1,{first})\nb=array.new_{dtype}(1,{second})\n"
        f"c={expression}\narray.push(c,{first})\nplot(array.size(a))\n"
    )


@pytest.mark.parametrize("version,form,arguments", FORMS)
@pytest.mark.parametrize("dtype,first,second", TYPES)
def test_concat_result_is_typed_reference_in_both_call_forms(
    version, form, arguments, dtype, first, second
):
    expression = f"array.concat({arguments})" if form == "function" else f"a.concat({arguments})"
    code = source(version, dtype, first, second, expression)
    result = parse_code(code)
    assert result.ok, [(d.code, d.message) for d in result.diagnostics]
    facts = semantic_facts_payload(result)
    call = next(row for row in facts["calls"] if row["callee"].endswith(".concat"))
    assert call["resolution_status"] == "RESOLVED"
    assert (
        call["symbol_id"] == f'pine:{"function" if form == "function" else "method"}:array.concat'
    )
    assert {row["parameter_name"] for row in call["arguments"]} == (
        {"id1", "id2"} if form == "function" else {"id2"}
    )
    assert build_consumer_bundle(code)["content_hash"]


@pytest.mark.parametrize("dtype", ["int", "float", "bool", "string"])
def test_specialized_signature_preserves_receiver_type_and_primary_names(dtype):
    receiver = f"array<{dtype}>"
    assert collection_return_type(receiver, "concat") == receiver
    assert [(p.name, p.type_name) for p in function_parameter_specs("array.concat", receiver)] == [
        ("id1", receiver),
        ("id2", receiver),
    ]
    assert [(p.name, p.type_name) for p in method_parameter_specs(receiver, "concat")] == [
        ("id2", receiver)
    ]


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize(
    "arguments", ["id=a,id2=b", "id1=a,array_id=b", "id1=a,id1=a,id2=b", "id1=a", "id1=1,id2=b"]
)
def test_concat_wrong_primary_binding_is_rejected(version, arguments):
    assert not parse_code(source(version, "int", "1", "2", f"array.concat({arguments})")).ok
