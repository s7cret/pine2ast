from pine2ast import ParseOptions, parse_code
from pine2ast.diagnostics import codes
from pine2ast.diagnostics import Severity


def test_malformed_for_in_arity_diagnostic_is_deduplicated():
    result = parse_code('''//@version=6
indicator("bad-for-in")
values = array.from(1.0, 2.0)
for [i, v, extra] in values
    x = v
plot(close)
''')
    p2a1902 = [d for d in result.diagnostics if d.code == codes.FOR_IN_TARGET_ARITY]
    assert len(p2a1902) == 1
    assert result.ast is not None


def test_strict_builtin_namespace_promotes_unknown_member_to_error():
    source = '''//@version=6
indicator("strict-ns")
x = ta.future_unknown(close)
'''
    soft = parse_code(source)
    hard = parse_code(source, ParseOptions(strict_builtin_namespaces=True))
    assert any(d.code == codes.UNKNOWN_BUILTIN_MEMBER and d.severity is Severity.INFO for d in soft.diagnostics)
    assert any(d.code == codes.UNKNOWN_BUILTIN_MEMBER and d.severity is Severity.ERROR for d in hard.diagnostics)
    assert soft.ok
    assert not hard.ok


def test_forward_numeric_branch_return_shape_allows_float_assignment():
    result = parse_code('''//@version=6
indicator("return-shape")
float y = choose(true)
choose(bool flag) => flag ? 1 : 2.5
plot(y)
''')
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert result.semantic_model.symbols["choose"].type == "float"


def test_forward_tuple_branch_return_shape_preserves_merged_element_types():
    result = parse_code('''//@version=6
indicator("tuple-branch")
[a, b] = pair(true)
pair(bool flag) => flag ? [1, 2.0] : [3, 4.5]
plot(b)
''')
    assert result.ok, [d.to_dict() for d in result.diagnostics]
    assert result.semantic_model.symbols["a"].type == "int"
    assert result.semantic_model.symbols["b"].type == "float"
