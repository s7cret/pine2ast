"""Control-flow return typing follows completed value paths, not break/continue."""

import pytest
from pine2ast import parse_code


@pytest.mark.parametrize("version", [3, 4, 5, 6])
@pytest.mark.parametrize("kind", ["for", "nested", "udf", "break", "continue"])
def test_loop_values_receive_scalar_type_evidence(version, kind):
    body = {
        "for": "x=for i=1 to 3\n    i*2",
        "nested": "x=for i=1 to 2\n    for j=1 to 3\n        i+j",
        "udf": "f() =>\n    for i=1 to 3\n        i*2\nx=f()",
        "break": "x=for i=1 to 3\n    if i==2\n        break\n    else\n        i*2",
        "continue": "x=for i=1 to 3\n    if i==2\n        continue\n    else\n        i*2",
    }[kind]
    decl = "indicator" if version >= 5 else "study"
    result = parse_code(f'//@version={version}\n{decl}("loop")\n' + body + "\nplot(x)\n")
    assert result.ok, result.diagnostics
    facts = result.semantic_model.semantic_facts.facts
    assert any(f.kind == "Identifier" and f.resolved_type.base == "int" for f in facts)


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "body",
    [
        "[a,b]=for i=1 to 3\n    [i,i+1]\nx=a+b",
        "[a,b]=while false\n    [1,2]\nx=a+b",
        "a=for i=1 to 3\n    array.new_float(1,i)\nx=array.get(a,0)",
        "a=array.new_float(2,close)\nx=for v in a\n    v+1",
    ],
)
def test_tuple_and_reference_results_are_not_unknown(version, body):
    result = parse_code(f'//@version={version}\nindicator("loop")\n' + body + "\nplot(x)\n")
    assert result.ok, result.diagnostics


@pytest.mark.parametrize("version", [4, 5, 6])
@pytest.mark.parametrize("base", ["a", "f()"])
def test_array_instance_history_is_versioned_not_scalar_history(version, base):
    decl = "indicator" if version >= 5 else "study"
    src = f'//@version={version}\n{decl}("history")\na=array.new_float(1,close)\nf() =>\n    array.new_float(1,close)\nb={base}[1]\n'
    result = parse_code(src)
    assert result.ok == (version >= 5), result.diagnostics
    if version == 4:
        assert any("history" in d.message.lower() for d in result.diagnostics)
    result = parse_code(
        f'//@version={version}\n{decl}("scalar")\na=array.new_float(1,close)\nb=array.get(a,0)[1]\n'
    )
    assert result.ok, result.diagnostics


def test_true_void_arm_is_not_misclassified_as_abrupt_control():
    result = parse_code(
        '//@version=6\nindicator("void")\nx=for i=1 to 3\n    if i==2\n        array.push(array.new_float(),1)\n    else\n        i\n'
    )
    assert not result.ok
