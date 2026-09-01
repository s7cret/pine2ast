from pine2ast import parse_code
from pine2ast.catalog import CatalogRepository
from pine2ast.diagnostics import codes


def test_v4_uses_study_and_pre_namespace_builtins():
    valid = parse_code("//@version=4\nstudy('v4')\nx = sma(close, 10)\n")
    invalid = parse_code("//@version=4\nstudy('v4')\nx = ta.sma(close, 10)\n")
    assert valid.ok
    assert not invalid.ok


def test_v4_supports_typed_var_varip_arrays_and_compound_assignment():
    source = """//@version=4
study('v4')
var float x = na
varip int ticks = 0
ticks += 1
var float[] values = array.new_float(0)
array.push(values, close)
"""
    result = parse_code(source)
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]


def test_v4_requires_explicit_type_for_na_declaration():
    invalid = parse_code("//@version=4\nstudy('v4')\nx = na\n")
    valid = parse_code("//@version=4\nstudy('v4')\nfloat x = na\n")
    assert not invalid.ok
    assert any(item.code == codes.NA_DECLARATION_TYPE_REQUIRED for item in invalid.diagnostics)
    assert valid.ok


def test_v4_retains_unified_input_iff_offset_and_legacy_rsi_overload():
    source = """//@version=4
study('v4')
length = input(14, title='Length', type=input.integer)
a = iff(close > open, close, open)
b = offset(a, 1)
r = rsi(close, length)
"""
    result = parse_code(source)
    assert result.ok, [(item.code, item.message) for item in result.diagnostics]
    catalog = CatalogRepository.default().view(4)
    for name in ("input", "iff", "offset", "rsi"):
        assert name in catalog["functions"]
    assert "input.int" not in catalog["functions"]


def test_v4_ternary_rule_is_lazy_and_logical_rule_remains_eager():
    result = parse_code("//@version=4\nstudy('v4')\nx = true and false\ny = true ? 1 : 2\n")
    assert result.ok
    rules = {
        rule
        for fact in result.semantic_model.semantic_facts.facts
        for rule in fact.semantic_rule_ids
    }
    assert "operator.logical_and.eager.v4" in rules
    assert "operator.ternary.lazy.v4" in rules
