from pine2ast import parse_code


def _errors(source: str):
    return [item for item in parse_code(source).diagnostics if item.is_error]


def _facts(source: str):
    result = parse_code(source)
    assert result.ast is not None
    return result, result.semantic_model.semantic_facts.facts


def test_multiline_string_is_version_bound():
    body = 'indicator("x")\ns = """a\nb"""\n'
    assert _errors("//@version=5\n" + body)
    assert not _errors("//@version=6\n" + body)


def test_numeric_condition_is_v5_only():
    body = "indicator('x')\nif 1\n    x = 2\n"
    assert not _errors("//@version=5\n" + body)
    errors = _errors("//@version=6\n" + body)
    assert any(item.code == "P2A1201" for item in errors)


def test_const_integer_division_type_and_rule_differ():
    body = "indicator('x')\nx = 5 / 2\n"
    _, v5 = _facts("//@version=5\n" + body)
    _, v6 = _facts("//@version=6\n" + body)
    f5 = next(item for item in v5 if item.kind == "BinaryExpr")
    f6 = next(item for item in v6 if item.kind == "BinaryExpr")
    assert f5.resolved_type.base == "int"
    assert f6.resolved_type.base == "float"
    assert "operator.division.const_int.v5" in f5.semantic_rule_ids
    assert "operator.division.const_int.v6" in f6.semantic_rule_ids


def test_logical_evaluation_rule_is_eager_in_v5_and_lazy_in_v6():
    body = "indicator('x')\nx = true and false\n"
    _, v5 = _facts("//@version=5\n" + body)
    _, v6 = _facts("//@version=6\n" + body)
    f5 = next(item for item in v5 if item.kind == "BinaryExpr")
    f6 = next(item for item in v6 if item.kind == "BinaryExpr")
    assert "operator.logical_and.eager.v5" in f5.semantic_rule_ids
    assert "operator.logical_and.lazy.v6" in f6.semantic_rule_ids


def test_request_default_rule_is_versioned():
    body = "indicator('x')\nx = request.security('A', 'D', close)\n"
    _, v5 = _facts("//@version=5\n" + body)
    _, v6 = _facts("//@version=6\n" + body)
    r5 = next(item for item in v5 if "request.default.static.v5" in item.semantic_rule_ids)
    r6 = next(item for item in v6 if "request.default.dynamic.v6" in item.semantic_rule_ids)
    assert r5.kind == r6.kind == "CallExpr"


def test_for_endpoint_rule_is_versioned():
    body = "indicator('x')\nfor i = 0 to 2\n    x = i\n"
    _, v5 = _facts("//@version=5\n" + body)
    _, v6 = _facts("//@version=6\n" + body)
    f5 = next(item for item in v5 if item.kind == "ForRangeStructure")
    f6 = next(item for item in v6 if item.kind == "ForRangeStructure")
    assert f5.semantic_rule_ids == ("control.for_range.fixed_end.v5",)
    assert f6.semantic_rule_ids == ("control.for_range.dynamic_end.v6",)
