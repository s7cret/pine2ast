from pine2ast import parse_code
from pine2ast.diagnostics import codes


def test_v3_removes_self_and_forward_reference_declarations():
    self_ref = parse_code("//@version=3\nstudy('v3')\na = nz(a[1])\n")
    forward = parse_code("//@version=3\nstudy('v3')\na = b\nb = 1\n")
    assert not self_ref.ok
    assert not forward.ok
    assert any(item.code == codes.UNDECLARED_VARIABLE for item in self_ref.diagnostics)
    assert any(item.code == codes.UNDECLARED_VARIABLE for item in forward.diagnostics)


def test_v3_forbids_bool_to_number_but_keeps_numeric_conditions():
    arithmetic = parse_code("//@version=3\nstudy('v3')\nx = true + 1\n")
    condition = parse_code("//@version=3\nstudy('v3')\nif 1\n    x = 2\n")
    assert not arithmetic.ok
    assert any(item.code == codes.BOOL_TO_NUMBER_FORBIDDEN for item in arithmetic.diagnostics)
    assert condition.ok, [(item.code, item.message) for item in condition.diagnostics]


def test_v3_security_lookahead_default_is_off_and_explicit_argument_exists():
    result = parse_code(
        "//@version=3\nstudy('v3')\nx = security(tickerid, 'D', close, lookahead=barmerge.lookahead_on)\n"
    )
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    call = next(
        item
        for item in result.semantic_model.semantic_facts.facts
        if "request.security.lookahead.off.v3" in item.semantic_rule_ids
    )
    assert call.kind == "CallExpr"


def test_v3_adds_tuple_declarations_but_not_v4_typed_declarations():
    tuple_result = parse_code("//@version=3\nstudy('v3')\n[a, b] = [1, 2]\n")
    typed_result = parse_code("//@version=3\nstudy('v3')\nfloat x = na\n")
    assert tuple_result.ok
    assert not typed_result.ok
