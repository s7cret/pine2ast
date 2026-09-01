from pine2ast import parse_code
from pine2ast.diagnostics import codes


def test_v2_adds_if_for_break_continue_udf_and_reassignment():
    source = """//@version=2
study('v2')
f(x) => x + 1
x = 0
for i = 0 to 3
    if i > 1
        x := f(i)
        break
    else
        continue
"""
    result = parse_code(source)
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]


def test_v2_preserves_self_and_forward_reference_declarations():
    source = """//@version=2
study('v2')
a = nz(a[1]) + b
b = 1
"""
    result = parse_code(source)
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]


def test_v2_allows_bool_to_number_but_records_explicit_coercion():
    result = parse_code("//@version=2\nstudy('v2')\nx = true + 1\n")
    assert result.ok
    fact = next(
        item for item in result.semantic_model.semantic_facts.facts if item.kind == "BinaryExpr"
    )
    assert fact.resolved_type.base == "int"
    assert [item.reason for item in fact.coercions] == ["coercion.bool_to_number.allow.v2"]


def test_v2_security_default_is_lookahead_on_and_mutable_expression_is_forbidden():
    clean = parse_code("//@version=2\nstudy('v2')\ny = security(tickerid, 'D', close)\n")
    assert clean.ok
    assert any(
        "request.security.lookahead.on.v2" in fact.semantic_rule_ids
        for fact in clean.semantic_model.semantic_facts.facts
    )

    mutable = parse_code(
        "//@version=2\nstudy('v2')\nx = 1\nx := x + 1\ny = security(tickerid, 'D', x)\n"
    )
    assert not mutable.ok
    assert any(item.code == codes.MUTABLE_SECURITY_ARGUMENT for item in mutable.diagnostics)
