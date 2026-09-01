from pine2ast import parse_code
from pine2ast.diagnostics import codes


def errors(source: str):
    return [item for item in parse_code(source).diagnostics if item.is_error]


def test_missing_annotation_executes_under_v1_identity():
    result = parse_code("study('v1')\nx = close\n")
    assert result.ok
    assert result.version_context.pine_version == 1
    assert any(item.code == codes.VERSION_DEFAULTED_TO_V1 for item in result.diagnostics)


def test_v1_supports_comma_separated_global_statements_and_self_reference():
    result = parse_code("study('v1'), x = nz(x[1]), y = x + 1\n")
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    assert result.semantic_model.symbols["x"].type in {"float", "int", "unknown"}
    assert result.semantic_model.symbols["y"].type in {"float", "int", "unknown"}


def test_v1_rejects_structures_added_in_v2_or_later():
    sources = (
        "study('v1')\nif true\n    x = 1\n",
        "study('v1')\nfor i = 0 to 2\n    x = i\n",
        "study('v1')\nf(x) => x\ny = f(1)\n",
        "study('v1')\nx = 1\nx := 2\n",
    )
    for source in sources:
        assert errors(source)


def test_v1_bool_to_number_and_security_lookahead_are_version_bound():
    result = parse_code("study('v1')\nx = true + 1\ny = security(tickerid, 'D', close)\n")
    assert result.ok
    facts = result.semantic_model.semantic_facts.facts
    binary = next(item for item in facts if item.kind == "BinaryExpr")
    security = next(
        item for item in facts if "request.security.lookahead.on.v1" in item.semantic_rule_ids
    )
    assert binary.resolved_type.base == "int"
    assert binary.coercions[0].reason == "coercion.bool_to_number.allow.v1"
    assert security.kind == "CallExpr"
